"""End-to-end Chameleon SSH test — create server, assign floating IP, verify SSH.

This test investigates the full SSH chain on Chameleon Cloud:
  1. Create lease + instance with keypair
  2. Create security group (SSH + ICMP)
  3. Allocate + associate floating IP
  4. Wait for SSH reachability
  5. SSH via paramiko and run a command

Run with: pytest tests/chameleon/test_chameleon_ssh.py -v -s -m chameleon --timeout=900

Requires Chameleon credentials in .env:
  CHAMELEON_TACC_KVM_APP_CREDENTIAL_ID  (or CHAMELEON_TACC_APP_CREDENTIAL_ID)
  CHAMELEON_TACC_KVM_APP_CREDENTIAL_SECRET
  CHAMELEON_TACC_PROJECT_ID

WARNING: Creates real resources. All cleaned up in teardown.
"""

import json
import os
import socket
import tempfile
import time
import pytest

# Load .env if present
_search_dirs = [os.getcwd()] + [os.path.join(os.getcwd(), *([".."]*i)) for i in range(1, 4)]
_search_dirs += [os.path.dirname(__file__)] + [os.path.join(os.path.dirname(__file__), *([".."]*i)) for i in range(1, 6)]
for _parent in _search_dirs:
    _env_candidate = os.path.join(_parent, ".env")
    if os.path.isfile(_env_candidate):
        with open(_env_candidate) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip().strip('"')
        break


def _configure_chameleon():
    from app.chameleon_manager import _ChameleonSession, _sessions
    sites = {
        "KVM@TACC": {
            "auth_url": "https://kvm.tacc.chameleoncloud.org:5000/v3",
            "cred_id": os.environ.get("CHAMELEON_TACC_KVM_APP_CREDENTIAL_ID",
                                      os.environ.get("CHAMELEON_TACC_APP_CREDENTIAL_ID", "")),
            "cred_secret": os.environ.get("CHAMELEON_TACC_KVM_APP_CREDENTIAL_SECRET",
                                          os.environ.get("CHAMELEON_TACC_APP_CREDENTIAL_SECRET", "")),
            "project_id": os.environ.get("CHAMELEON_TACC_PROJECT_ID", ""),
        },
        "CHI@UC": {
            "auth_url": "https://chi.uc.chameleoncloud.org:5000/v3",
            "cred_id": os.environ.get("CHAMELEON_UC_APP_CREDENTIAL_ID", ""),
            "cred_secret": os.environ.get("CHAMELEON_UC_APP_CREDENTIAL_SECRET", ""),
            "project_id": os.environ.get("CHAMELEON_UC_PROJECT_ID", ""),
        },
    }
    for site_name, cfg in sites.items():
        if cfg["cred_id"] and cfg["cred_secret"]:
            _sessions[site_name] = _ChameleonSession(
                site=site_name, auth_url=cfg["auth_url"],
                cred_id=cfg["cred_id"], cred_secret=cfg["cred_secret"],
                project_id=cfg["project_id"],
            )


def _is_configured():
    return bool(os.environ.get("CHAMELEON_TACC_KVM_APP_CREDENTIAL_ID",
                               os.environ.get("CHAMELEON_TACC_APP_CREDENTIAL_ID", "")))


pytestmark = pytest.mark.chameleon
TEST_SITE = os.environ.get("TEST_SITE", "KVM@TACC")
TEST_PREFIX = "loomai-e2e-ssh"

# Track resources for cleanup
_created_leases: list[tuple[str, str]] = []
_created_instances: list[tuple[str, str]] = []
_created_fips: list[tuple[str, str]] = []  # (fip_id, site)
_created_keypairs: list[tuple[str, str]] = []  # (name, site)
_private_key_path: str = ""


@pytest.fixture(scope="module", autouse=True)
def setup_and_cleanup():
    if not _is_configured():
        pytest.skip("Chameleon credentials not configured")
    from app.chameleon_manager import reset_sessions
    reset_sessions()
    try:
        _configure_chameleon()
    except Exception as e:
        pytest.skip(f"Chameleon configuration failed: {e}")

    yield

    # Cleanup in reverse order
    from app.chameleon_manager import _sessions
    for inst_id, site in reversed(_created_instances):
        try:
            s = _sessions.get(site)
            if s:
                s.api_delete("compute", f"/servers/{inst_id}")
                print(f"  Cleaned up instance {inst_id}")
        except Exception as e:
            print(f"  Instance cleanup failed: {e}")

    if _created_instances:
        time.sleep(5)

    for fip_id, site in reversed(_created_fips):
        try:
            s = _sessions.get(site)
            if s:
                s.api_delete("network", f"/v2.0/floatingips/{fip_id}")
                print(f"  Released floating IP {fip_id}")
        except Exception as e:
            print(f"  FIP cleanup failed: {e}")

    for lease_id, site in reversed(_created_leases):
        try:
            s = _sessions.get(site)
            if s:
                s.api_delete("reservation", f"/leases/{lease_id}")
                print(f"  Cleaned up lease {lease_id}")
        except Exception as e:
            print(f"  Lease cleanup failed: {e}")

    # Don't delete keypairs — reuse across test runs
    if _private_key_path and os.path.isfile(_private_key_path):
        print(f"  Private key saved at: {_private_key_path}")

    reset_sessions()


def _get_session():
    from app.chameleon_manager import _sessions
    session = _sessions.get(TEST_SITE)
    if not session:
        pytest.skip(f"No session for {TEST_SITE}")
    return session


def _wait_lease_active(session, lease_id, timeout=300):
    for _ in range(timeout // 5):
        resp = session.api_get("reservation", f"/leases/{lease_id}")
        lease = resp if "id" in resp else resp.get("lease", resp)
        status = lease.get("status", "")
        if status == "ACTIVE":
            return lease
        if status == "ERROR":
            raise RuntimeError(f"Lease ERROR: {lease}")
        time.sleep(5)
    raise TimeoutError(f"Lease {lease_id} not ACTIVE within {timeout}s")


def _wait_instance_active(session, instance_id, timeout=600):
    for _ in range(timeout // 10):
        resp = session.api_get("compute", f"/servers/{instance_id}")
        server = resp.get("server", resp)
        status = server.get("status", "")
        if status == "ACTIVE":
            return server
        if status == "ERROR":
            raise RuntimeError(f"Instance ERROR: {server.get('fault', {})}")
        time.sleep(10)
    raise TimeoutError(f"Instance {instance_id} not ACTIVE within {timeout}s")


def _check_port(ip, port=22, timeout=5):
    """Check if a TCP port is reachable."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, port))
        sock.close()
        return result == 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Shared state across ordered tests
# ---------------------------------------------------------------------------
_state: dict = {}


class TestChameleonSSH:
    """Full SSH lifecycle test: lease → instance → keypair → FIP → SSH."""

    def test_01_authenticate(self):
        """Verify authentication works."""
        session = _get_session()
        token = session.get_token()
        assert token and len(token) > 20
        print(f"  ✓ Authenticated to {TEST_SITE}")

    def test_02_ensure_keypair(self):
        """Ensure loomai-key keypair exists; create if not."""
        global _private_key_path
        session = _get_session()

        # Check if keypair already exists
        resp = session.api_get("compute", "/os-keypairs")
        keypairs = resp.get("keypairs", [])
        existing = None
        for kp in keypairs:
            kp_data = kp.get("keypair", kp)
            if kp_data.get("name") == "loomai-key":
                existing = kp_data
                break

        if existing:
            print(f"  ✓ Keypair 'loomai-key' already exists (fingerprint: {existing.get('fingerprint', '?')})")
            # We need the private key — check if we have it saved
            key_candidates = [
                os.path.expanduser("~/.ssh/chameleon_key"),
                "/home/fabric/work/fabric_config/chameleon_key",
                os.path.join(os.path.dirname(__file__), "chameleon_key"),
            ]
            for kc in key_candidates:
                if os.path.isfile(kc):
                    _private_key_path = kc
                    print(f"  ✓ Found private key at: {kc}")
                    break
            if not _private_key_path:
                # Delete and recreate so we have the private key
                print("  ⚠ No private key found — deleting and recreating keypair")
                session.api_delete("compute", f"/os-keypairs/loomai-key")
                existing = None

        if not existing:
            # Create new keypair (Nova generates the key pair)
            resp = session.api_post("compute", "/os-keypairs", {
                "keypair": {"name": "loomai-key"}
            })
            kp_data = resp.get("keypair", resp)
            private_key = kp_data.get("private_key", "")
            assert private_key, f"Nova did not return private key: {json.dumps(kp_data, indent=2)}"

            # Save private key
            key_dir = os.path.join(os.path.dirname(__file__))
            _private_key_path = os.path.join(key_dir, "chameleon_key")
            with open(_private_key_path, "w") as f:
                f.write(private_key)
            os.chmod(_private_key_path, 0o600)
            _created_keypairs.append(("loomai-key", TEST_SITE))
            print(f"  ✓ Created keypair 'loomai-key', saved to {_private_key_path}")
            print(f"    Fingerprint: {kp_data.get('fingerprint', '?')}")

        _state["key_path"] = _private_key_path

    def test_03_create_lease(self):
        """Create a short lease for testing, or reuse an existing ACTIVE one."""
        session = _get_session()

        # First check for existing ACTIVE leases we can reuse
        leases_resp = session.api_get("reservation", "/leases")
        for lease in leases_resp.get("leases", []):
            if lease.get("status") == "ACTIVE":
                reservations = lease.get("reservations", [])
                for r in reservations:
                    if r.get("status") == "active":
                        _state["lease_id"] = lease["id"]
                        _state["reservation_id"] = r["id"]
                        print(f"  ✓ Reusing existing ACTIVE lease: {lease['id']} ({lease.get('name')})")
                        print(f"    Reservation: {r['id']}")
                        return
                # ACTIVE lease but no active reservation — try anyway
                if reservations:
                    _state["lease_id"] = lease["id"]
                    _state["reservation_id"] = reservations[0]["id"]
                    print(f"  ✓ Reusing existing ACTIVE lease: {lease['id']} ({lease.get('name')})")
                    return

        print("  No existing ACTIVE leases found, creating a new one...")

        # Find available node type
        hosts_resp = session.api_get("reservation", "/os-hosts")
        hosts = hosts_resp.get("hosts", [])
        assert hosts, "No hosts available"

        type_counts: dict[str, int] = {}
        for h in hosts:
            nt = ""
            if isinstance(h, dict):
                extra = h.get("extra_capabilities", h.get("host_extra_capability", {}))
                if isinstance(extra, dict) and extra.get("node_type"):
                    nt = extra["node_type"]
                if not nt:
                    for key in ["node_type", "hypervisor_hostname"]:
                        if key in h:
                            nt = h[key]
                            break
            if nt:
                type_counts[nt] = type_counts.get(nt, 0) + 1

        print(f"  Node types: {type_counts}")

        # Try each node type from most to least available
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        start = (now + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M")
        end = (now + timedelta(hours=4)).strftime("%Y-%m-%d %H:%M")

        sorted_types = sorted(type_counts.keys(), key=lambda k: type_counts[k], reverse=True)
        last_error = None
        for node_type in sorted_types:
            print(f"  Trying node_type={node_type} ({type_counts[node_type]} hosts)...")
            lease_body = {
                "name": f"{TEST_PREFIX}-{int(time.time())}",
                "start_date": start,
                "end_date": end,
                "reservations": [{
                    "resource_type": "physical:host",
                    "resource_properties": json.dumps(["==", "$node_type", node_type]),
                    "min": 1, "max": 1,
                    "hypervisor_properties": "",
                }],
                "events": [],
            }
            try:
                result = session.api_post("reservation", "/leases", lease_body)
                lease = result if "id" in result else result.get("lease", result)
                lease_id = lease["id"]
                _created_leases.append((lease_id, TEST_SITE))
                print(f"  ✓ Created lease: {lease_id} ({lease.get('name')})")
                for r in lease.get("reservations", []):
                    _state["reservation_id"] = r["id"]
                    print(f"    Reservation: {r['id']} (status: {r.get('status')})")
                    break
                _state["lease_id"] = lease_id
                return
            except RuntimeError as e:
                last_error = e
                print(f"    ✗ {e}")
                continue

        pytest.skip(f"No available resources at {TEST_SITE}. Last error: {last_error}")

    def test_04_wait_lease_active(self):
        """Wait for lease to become ACTIVE."""
        session = _get_session()
        lease_id = _state.get("lease_id")
        assert lease_id, "No lease created"

        print(f"  Waiting for lease {lease_id} to become ACTIVE...")
        lease = _wait_lease_active(session, lease_id, timeout=300)
        print(f"  ✓ Lease ACTIVE")

        # Re-read reservation ID (may change after activation)
        for r in lease.get("reservations", []):
            _state["reservation_id"] = r["id"]
            print(f"    Reservation: {r['id']} (status: {r.get('status')})")

    def test_05_find_network(self):
        """Find a shared network for the instance."""
        session = _get_session()
        result = session.api_get("network", "/v2.0/networks")
        networks = result.get("networks", [])

        # Prefer sharednet1
        shared = [n for n in networks if n.get("shared")]
        target = None
        for n in shared:
            if "sharednet" in n.get("name", "").lower():
                target = n
                break
        if not target and shared:
            target = shared[0]
        assert target, f"No shared network found. Networks: {[n['name'] for n in networks]}"

        _state["network_id"] = target["id"]
        print(f"  ✓ Using network: {target['name']} ({target['id'][:8]}...)")

    def test_06_ensure_security_group(self):
        """Ensure loomai-ssh security group exists with SSH + ICMP rules."""
        session = _get_session()

        result = session.api_get("network", "/v2.0/security-groups")
        sgs = result.get("security_groups", [])
        existing = next((sg for sg in sgs if sg.get("name") == "loomai-ssh"), None)

        if existing:
            print(f"  ✓ Security group 'loomai-ssh' already exists ({existing['id'][:8]}...)")
            _state["sg_id"] = existing["id"]
            return

        # Create security group
        sg_resp = session.api_post("network", "/v2.0/security-groups", {
            "security_group": {
                "name": "loomai-ssh",
                "description": "LoomAI SSH + ICMP access",
            }
        })
        sg = sg_resp.get("security_group", sg_resp)
        sg_id = sg["id"]
        _state["sg_id"] = sg_id
        print(f"  ✓ Created security group: {sg_id[:8]}...")

        # Add SSH rule
        session.api_post("network", "/v2.0/security-group-rules", {
            "security_group_rule": {
                "security_group_id": sg_id,
                "direction": "ingress",
                "protocol": "tcp",
                "port_range_min": 22,
                "port_range_max": 22,
                "remote_ip_prefix": "0.0.0.0/0",
                "ethertype": "IPv4",
            }
        })
        print(f"    + SSH (TCP 22) rule added")

        # Add ICMP rule
        session.api_post("network", "/v2.0/security-group-rules", {
            "security_group_rule": {
                "security_group_id": sg_id,
                "direction": "ingress",
                "protocol": "icmp",
                "remote_ip_prefix": "0.0.0.0/0",
                "ethertype": "IPv4",
            }
        })
        print(f"    + ICMP rule added")

    def test_07_create_instance(self):
        """Create instance with keypair, network, and reservation hint."""
        session = _get_session()
        reservation_id = _state.get("reservation_id")
        network_id = _state.get("network_id")
        assert reservation_id, "No reservation ID"
        assert network_id, "No network ID"

        # Find an image
        images_resp = session.api_get("image", "/v2/images")
        images = images_resp.get("images", [])
        # Prefer CC-Ubuntu22.04 or similar
        target_image = None
        for img in images:
            name = img.get("name", "").lower()
            if "ubuntu" in name and "22" in name:
                target_image = img
                break
        if not target_image:
            for img in images:
                if "ubuntu" in img.get("name", "").lower():
                    target_image = img
                    break
        if not target_image and images:
            target_image = images[0]
        assert target_image, "No images available"
        print(f"  Using image: {target_image['name']} ({target_image['id'][:8]}...)")

        # Find flavor
        is_kvm = "KVM" in TEST_SITE.upper()
        if is_kvm:
            flavor_ref = "m1.small"
            # Try to resolve UUID
            try:
                flavors_resp = session.api_get("compute", "/flavors/detail")
                for f in flavors_resp.get("flavors", []):
                    if f.get("name") == flavor_ref:
                        flavor_ref = f["id"]
                        break
            except Exception:
                pass
        else:
            flavor_ref = "baremetal"
            try:
                flavors_resp = session.api_get("compute", "/flavors/detail")
                for f in flavors_resp.get("flavors", []):
                    if f.get("name") == "baremetal":
                        flavor_ref = f["id"]
                        break
            except Exception:
                pass

        server_body = {
            "server": {
                "name": f"{TEST_PREFIX}-{int(time.time())}",
                "imageRef": target_image["id"],
                "flavorRef": flavor_ref,
                "key_name": "loomai-key",
                "networks": [{"uuid": network_id}],
                "security_groups": [{"name": "loomai-ssh"}],
            },
            # Scheduler hints at TOP LEVEL (sibling of "server")
            "os:scheduler_hints": {"reservation": reservation_id},
        }

        print(f"  Creating instance with key_name=loomai-key, network={network_id[:8]}...")
        print(f"    scheduler_hints: reservation={reservation_id}")
        result = session.api_post("compute", "/servers", server_body)
        server = result.get("server", result)
        instance_id = server["id"]
        _created_instances.append((instance_id, TEST_SITE))
        _state["instance_id"] = instance_id
        print(f"  ✓ Created instance: {instance_id} ({server.get('name')})")

    def test_08_wait_instance_active(self):
        """Wait for instance to become ACTIVE."""
        session = _get_session()
        instance_id = _state.get("instance_id")
        assert instance_id, "No instance created"

        print(f"  Waiting for instance {instance_id} to become ACTIVE...")
        server = _wait_instance_active(session, instance_id, timeout=600)
        print(f"  ✓ Instance ACTIVE")

        # Report IPs
        for net_name, addrs in server.get("addresses", {}).items():
            for addr in addrs:
                ip_type = addr.get("OS-EXT-IPS:type", "unknown")
                print(f"    IP: {addr['addr']} ({ip_type}) on {net_name}")

    def test_09_allocate_floating_ip(self):
        """Allocate a floating IP via Neutron and associate it."""
        session = _get_session()
        instance_id = _state.get("instance_id")
        assert instance_id, "No instance"

        # Find external (public) network
        nets_resp = session.api_get("network", "/v2.0/networks")
        ext_net = None
        for n in nets_resp.get("networks", []):
            if n.get("router:external") or n.get("name", "").lower() == "public":
                ext_net = n
                break
        assert ext_net, f"No external network found. Names: {[n['name'] for n in nets_resp.get('networks', [])]}"
        print(f"  External network: {ext_net['name']} ({ext_net['id'][:8]}...)")

        # Find instance port
        ports_resp = session.api_get("network", f"/v2.0/ports?device_id={instance_id}")
        ports = ports_resp.get("ports", [])
        assert ports, "Instance has no ports"
        port_id = ports[0]["id"]
        print(f"  Instance port: {port_id[:8]}...")

        # Allocate floating IP
        fip_resp = session.api_post("network", "/v2.0/floatingips", {
            "floatingip": {
                "floating_network_id": ext_net["id"],
                "port_id": port_id,
            }
        })
        fip = fip_resp.get("floatingip", fip_resp)
        fip_id = fip["id"]
        fip_addr = fip.get("floating_ip_address", "")
        _created_fips.append((fip_id, TEST_SITE))
        _state["floating_ip"] = fip_addr
        _state["fip_id"] = fip_id
        print(f"  ✓ Floating IP allocated and associated: {fip_addr}")

    def test_10_wait_ssh_reachable(self):
        """Poll until SSH port 22 is reachable on the floating IP."""
        fip = _state.get("floating_ip")
        assert fip, "No floating IP"

        print(f"  Waiting for SSH on {fip}:22...")
        reachable = False
        for attempt in range(30):  # 5 min max
            if _check_port(fip, 22, timeout=5):
                reachable = True
                print(f"  ✓ SSH port reachable after {(attempt + 1) * 10}s")
                break
            time.sleep(10)
            if attempt % 3 == 0:
                print(f"    Attempt {attempt + 1}/30...")

        assert reachable, f"SSH port 22 not reachable on {fip} after 5 minutes"

    def test_11_ssh_connect(self):
        """SSH to the instance via paramiko and run a command."""
        import paramiko

        fip = _state.get("floating_ip")
        key_path = _state.get("key_path", _private_key_path)
        assert fip, "No floating IP"
        assert key_path and os.path.isfile(key_path), f"No private key at {key_path}"

        print(f"  Connecting SSH to {fip} as cc with key {key_path}")

        # Load private key
        pkey = None
        for key_class in [paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey]:
            try:
                pkey = key_class.from_private_key_file(key_path)
                print(f"    Key type: {key_class.__name__}")
                break
            except Exception:
                continue
        assert pkey, f"Could not load private key from {key_path}"

        # Connect
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=fip,
                port=22,
                username="cc",
                pkey=pkey,
                timeout=30,
                allow_agent=False,
                look_for_keys=False,
            )
            print(f"  ✓ SSH connected!")

            # Run a command
            stdin, stdout, stderr = client.exec_command("hostname && whoami && uname -a")
            output = stdout.read().decode().strip()
            err = stderr.read().decode().strip()
            exit_code = stdout.channel.recv_exit_status()

            print(f"  ✓ Command output:")
            print(f"    {output}")
            if err:
                print(f"    stderr: {err}")
            print(f"    exit code: {exit_code}")
            assert exit_code == 0, f"Command failed with exit code {exit_code}: {err}"

            # Test interactive shell (like the terminal handler does)
            chan = client.invoke_shell(term="xterm-256color", width=120, height=30)
            time.sleep(1)
            if chan.recv_ready():
                banner = chan.recv(4096).decode(errors="replace")
                print(f"  ✓ Interactive shell banner: {banner[:200]}...")
            chan.send("echo LOOMAI_SSH_TEST_OK\n")
            time.sleep(1)
            if chan.recv_ready():
                shell_out = chan.recv(4096).decode(errors="replace")
                assert "LOOMAI_SSH_TEST_OK" in shell_out, f"Shell echo not found in: {shell_out}"
                print(f"  ✓ Interactive shell works!")
            chan.close()

        except paramiko.AuthenticationException as e:
            print(f"  ✗ SSH Authentication FAILED: {e}")
            print(f"    This means the key doesn't match what's on the server.")
            print(f"    Check: was key_name='loomai-key' passed during instance creation?")
            raise
        except paramiko.SSHException as e:
            print(f"  ✗ SSH Connection FAILED: {e}")
            raise
        except Exception as e:
            print(f"  ✗ SSH FAILED: {type(e).__name__}: {e}")
            raise
        finally:
            client.close()

    def test_12_report_findings(self):
        """Summary of what worked and what didn't."""
        print("\n" + "="*60)
        print("CHAMELEON SSH INVESTIGATION RESULTS")
        print("="*60)
        print(f"  Site:           {TEST_SITE}")
        print(f"  Lease:          {_state.get('lease_id', 'N/A')}")
        print(f"  Instance:       {_state.get('instance_id', 'N/A')}")
        print(f"  Floating IP:    {_state.get('floating_ip', 'N/A')}")
        print(f"  Key Path:       {_state.get('key_path', 'N/A')}")
        print(f"  Reservation:    {_state.get('reservation_id', 'N/A')}")
        print(f"  Security Group: {_state.get('sg_id', 'N/A')}")
        print("="*60)
        print("  If all tests passed, SSH via floating IP works correctly.")
        print("  The LoomAI terminal handler should work if:")
        print("    1. key_name='loomai-key' is passed during instance creation")
        print("    2. Private key is saved and discoverable")
        print("    3. Security group allows SSH (port 22)")
        print("    4. Floating IP is allocated and associated")
        print("="*60)
