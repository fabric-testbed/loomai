"""FABRIC real-provisioning end-to-end tests.

These tests create actual FABRIC slices, submit them, wait for StableOK,
execute commands on nodes, and verify network connectivity.  They are slow
(5-15 min) and require a valid FABRIC token.

Gate: ``@pytest.mark.fabric`` — excluded from default runs.
Run::

    pytest tests/fabric/test_fabric_provision_e2e.py -v -s -m fabric --timeout=900
"""

import os
import time

import httpx
import pytest

pytestmark = pytest.mark.fabric

BASE_URL = os.environ.get("LOOMAI_BASE_URL", "http://localhost:8000")

# Timeouts
SUBMIT_TIMEOUT = 120       # 2 min for submit call itself
STABLE_TIMEOUT = 600       # 10 min for slice to reach StableOK
POLL_INTERVAL = 15         # seconds between state polls
EXEC_TIMEOUT = 60          # 1 min for command execution
SSH_WAIT_TIMEOUT = 180     # 3 min for SSH to become reachable after StableOK


@pytest.fixture(scope="session")
def api():
    return httpx.Client(base_url=f"{BASE_URL}/api", timeout=60.0)


@pytest.fixture(scope="session")
def fabric_ok(api):
    """Ensure FABRIC is configured with a valid token."""
    try:
        resp = api.get("/config")
        if resp.status_code != 200:
            pytest.skip("Backend not running")
        data = resp.json()
        exp = data.get("token_info", {}).get("exp", 0)
        if exp * 1000 < time.time() * 1000:
            pytest.skip("FABRIC token expired — re-login required")
        return data
    except Exception:
        pytest.skip("Backend not running or unreachable")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wait_stable_ok(api: httpx.Client, name: str, timeout: int = STABLE_TIMEOUT) -> dict:
    """Poll until slice reaches StableOK. Fails on StableError/Dead."""
    start = time.time()
    while time.time() - start < timeout:
        resp = api.get(f"/slices/{name}")
        if resp.status_code == 200:
            data = resp.json()
            state = data.get("state", "")
            if state == "StableOK":
                return data
            if state in ("StableError", "Dead"):
                errors = data.get("error_messages", [])
                pytest.fail(f"Slice '{name}' entered {state}: {errors}")
        time.sleep(POLL_INTERVAL)
    pytest.fail(f"Slice '{name}' did not reach StableOK within {timeout}s")


def _cleanup_slice(api: httpx.Client, name: str):
    """Best-effort delete a FABRIC slice."""
    try:
        api.delete(f"/slices/{name}", timeout=120.0)
    except Exception:
        pass


def _exec_on_node(api: httpx.Client, slice_name: str, node_name: str, command: str,
                   timeout: int = EXEC_TIMEOUT) -> dict:
    """Execute a command on a FABRIC VM node via the files/execute API."""
    resp = api.post(
        f"/api/files/vm/{slice_name}/{node_name}/execute",
        json={"command": command},
        timeout=float(timeout),
    )
    assert resp.status_code == 200, f"Execute failed ({resp.status_code}): {resp.text}"
    return resp.json()


def _wait_ssh_ready(api: httpx.Client, slice_name: str, node_name: str,
                    timeout: int = SSH_WAIT_TIMEOUT) -> bool:
    """Poll until SSH is reachable on a node (execute 'echo ok')."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            result = _exec_on_node(api, slice_name, node_name, "echo ok", timeout=15)
            if "ok" in result.get("stdout", ""):
                return True
        except Exception:
            pass
        time.sleep(10)
    return False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFabricProvision:
    """Real FABRIC slice provisioning tests."""

    def test_create_submit_single_node(self, api, fabric_ok):
        """Create a slice with one node, submit, wait for StableOK, cleanup."""
        name = f"e2e-fab-single-{int(time.time())}"

        try:
            # Create draft
            resp = api.post(f"/slices?name={name}")
            assert resp.status_code == 200, f"Create draft failed: {resp.text}"

            # Add a node
            resp = api.post(f"/slices/{name}/nodes", json={
                "name": "node1",
                "site": "auto",
                "cores": 2,
                "ram": 8,
                "disk": 10,
                "image": "default_ubuntu_22",
            })
            assert resp.status_code == 200, f"Add node failed: {resp.text}"

            # Submit
            resp = api.post(f"/slices/{name}/submit", timeout=SUBMIT_TIMEOUT)
            assert resp.status_code == 200, f"Submit failed: {resp.text}"
            submit_data = resp.json()
            assert submit_data.get("state") in ("Configuring", "Nascent", "StableOK"), \
                f"Unexpected post-submit state: {submit_data.get('state')}"

            # Wait for StableOK
            data = _wait_stable_ok(api, name)
            assert data["state"] == "StableOK"
            assert len(data.get("nodes", [])) >= 1

        finally:
            _cleanup_slice(api, name)

    def test_submit_multi_node(self, api, fabric_ok):
        """Create a slice with 2 nodes, submit, verify both provision."""
        name = f"e2e-fab-multi-{int(time.time())}"

        try:
            resp = api.post(f"/slices?name={name}")
            assert resp.status_code == 200

            # Add two nodes
            for i in range(2):
                resp = api.post(f"/slices/{name}/nodes", json={
                    "name": f"node{i+1}",
                    "site": "auto",
                    "cores": 2,
                    "ram": 8,
                    "disk": 10,
                    "image": "default_ubuntu_22",
                })
                assert resp.status_code == 200

            # Submit
            resp = api.post(f"/slices/{name}/submit", timeout=SUBMIT_TIMEOUT)
            assert resp.status_code == 200

            # Wait for StableOK
            data = _wait_stable_ok(api, name)
            assert len(data.get("nodes", [])) >= 2

            # Both nodes should have management IPs
            for node in data["nodes"]:
                mgmt_ip = node.get("management_ip", "")
                assert mgmt_ip, f"Node '{node['name']}' has no management_ip"

        finally:
            _cleanup_slice(api, name)

    def test_node_with_nic_and_fabnetv4(self, api, fabric_ok):
        """Create a slice with a node + NIC + FABNetv4 network, verify L3 connectivity."""
        name = f"e2e-fab-l3-{int(time.time())}"

        try:
            resp = api.post(f"/slices?name={name}")
            assert resp.status_code == 200

            # Add a node with a NIC
            resp = api.post(f"/slices/{name}/nodes", json={
                "name": "node1",
                "site": "auto",
                "cores": 2,
                "ram": 8,
                "disk": 10,
                "image": "default_ubuntu_22",
                "components": [{"model": "NIC_Basic", "name": "nic1"}],
            })
            assert resp.status_code == 200

            # Get the interface name from the slice data
            resp = api.get(f"/slices/{name}")
            assert resp.status_code == 200
            slice_data = resp.json()

            iface_name = None
            for node in slice_data.get("nodes", []):
                for comp in node.get("components", []):
                    for iface in comp.get("interfaces", []):
                        iface_name = iface.get("name")
                        if iface_name:
                            break
                    if iface_name:
                        break
            assert iface_name, "No interface found on NIC component"

            # Add FABNetv4 network
            resp = api.post(f"/slices/{name}/networks", json={
                "name": "fabnet",
                "type": "FABNetv4",
                "interfaces": [iface_name],
            })
            assert resp.status_code == 200, f"Add FABNetv4 failed: {resp.text}"

            # Submit
            resp = api.post(f"/slices/{name}/submit", timeout=SUBMIT_TIMEOUT)
            assert resp.status_code == 200

            # Wait for StableOK
            data = _wait_stable_ok(api, name)

            # Verify the network was created
            networks = data.get("networks", [])
            assert len(networks) >= 1
            fabnet = [n for n in networks if "fabnet" in n.get("name", "").lower()
                      or n.get("type", "") in ("IPv4", "FABNetv4")]
            assert len(fabnet) >= 1, f"FABNetv4 network not found in: {networks}"

        finally:
            _cleanup_slice(api, name)

    def test_execute_command_on_node(self, api, fabric_ok):
        """Submit a slice, wait for StableOK, then execute commands via SSH."""
        name = f"e2e-fab-exec-{int(time.time())}"

        try:
            resp = api.post(f"/slices?name={name}")
            assert resp.status_code == 200

            resp = api.post(f"/slices/{name}/nodes", json={
                "name": "node1",
                "site": "auto",
                "cores": 2,
                "ram": 8,
                "disk": 10,
                "image": "default_ubuntu_22",
            })
            assert resp.status_code == 200

            resp = api.post(f"/slices/{name}/submit", timeout=SUBMIT_TIMEOUT)
            assert resp.status_code == 200

            data = _wait_stable_ok(api, name)

            # Wait for SSH to be reachable
            ssh_ok = _wait_ssh_ready(api, name, "node1")
            assert ssh_ok, "SSH not reachable on node1 after StableOK"

            # Execute hostname
            result = _exec_on_node(api, name, "node1", "hostname")
            assert result.get("stdout", "").strip(), "hostname returned empty output"

            # Execute uname
            result = _exec_on_node(api, name, "node1", "uname -a")
            stdout = result.get("stdout", "")
            assert "Linux" in stdout, f"Expected 'Linux' in uname output: {stdout}"

            # Execute ip addr (verify networking)
            result = _exec_on_node(api, name, "node1", "ip addr show")
            stdout = result.get("stdout", "")
            assert "inet" in stdout, f"Expected 'inet' in ip addr output: {stdout}"

        finally:
            _cleanup_slice(api, name)

    def test_two_nodes_fabnetv4_ping(self, api, fabric_ok):
        """Two FABRIC nodes on FABNetv4 can ping each other."""
        name = f"e2e-fab-ping-{int(time.time())}"

        try:
            resp = api.post(f"/slices?name={name}")
            assert resp.status_code == 200

            # Add two nodes with NICs
            for i in range(2):
                resp = api.post(f"/slices/{name}/nodes", json={
                    "name": f"node{i+1}",
                    "site": "auto",
                    "cores": 2,
                    "ram": 8,
                    "disk": 10,
                    "image": "default_ubuntu_22",
                    "components": [{"model": "NIC_Basic", "name": f"nic{i+1}"}],
                })
                assert resp.status_code == 200

            # Get interface names
            resp = api.get(f"/slices/{name}")
            assert resp.status_code == 200
            slice_data = resp.json()

            iface_names = []
            for node in slice_data.get("nodes", []):
                for comp in node.get("components", []):
                    for iface in comp.get("interfaces", []):
                        if iface.get("name"):
                            iface_names.append(iface["name"])
            assert len(iface_names) >= 2, f"Expected 2+ interfaces, found: {iface_names}"

            # Add FABNetv4 network connecting both NICs
            resp = api.post(f"/slices/{name}/networks", json={
                "name": "fabnet",
                "type": "FABNetv4",
                "interfaces": iface_names[:2],
            })
            assert resp.status_code == 200

            # Submit
            resp = api.post(f"/slices/{name}/submit", timeout=SUBMIT_TIMEOUT)
            assert resp.status_code == 200

            # Wait for StableOK
            data = _wait_stable_ok(api, name)

            # Wait for SSH on both nodes
            for node_name in ["node1", "node2"]:
                ssh_ok = _wait_ssh_ready(api, name, node_name)
                assert ssh_ok, f"SSH not reachable on {node_name}"

            # Get node2's data-plane IP (from the FABNetv4 interface)
            # Execute `ip addr` on node2 to find the data-plane IP
            result = _exec_on_node(api, name, "node2", "ip -4 addr show | grep 'inet 10\\.' | awk '{print $2}' | cut -d/ -f1 | head -1")
            node2_ip = result.get("stdout", "").strip()

            if not node2_ip:
                # Fallback: try getting any non-management IP
                result = _exec_on_node(api, name, "node2",
                    "ip -4 addr show | grep 'inet ' | grep -v '127.0.0' | grep -v 'management' | awk '{print $2}' | cut -d/ -f1 | head -1")
                node2_ip = result.get("stdout", "").strip()

            assert node2_ip, "Could not determine node2 data-plane IP"

            # Ping from node1 to node2
            result = _exec_on_node(api, name, "node1", f"ping -c 3 -W 5 {node2_ip}")
            stdout = result.get("stdout", "")
            assert "bytes from" in stdout, f"Ping failed — no response from {node2_ip}: {stdout}"
            # Allow some packet loss on first ping but at least 1 must succeed
            assert "0 received" not in stdout, f"All packets lost pinging {node2_ip}: {stdout}"

        finally:
            _cleanup_slice(api, name)

    def test_slice_delete_after_active(self, api, fabric_ok):
        """Submit a slice, wait for StableOK, then delete it and verify deletion."""
        name = f"e2e-fab-del-{int(time.time())}"

        try:
            resp = api.post(f"/slices?name={name}")
            assert resp.status_code == 200

            resp = api.post(f"/slices/{name}/nodes", json={
                "name": "node1",
                "site": "auto",
                "cores": 2,
                "ram": 8,
                "disk": 10,
                "image": "default_ubuntu_22",
            })
            assert resp.status_code == 200

            resp = api.post(f"/slices/{name}/submit", timeout=SUBMIT_TIMEOUT)
            assert resp.status_code == 200

            _wait_stable_ok(api, name)

            # Delete the active slice
            resp = api.delete(f"/slices/{name}", timeout=120.0)
            assert resp.status_code == 200
            del_data = resp.json()
            assert del_data.get("status") == "deleted"

            # Verify it's gone or Dead
            time.sleep(5)
            resp = api.get(f"/slices/{name}")
            if resp.status_code == 200:
                data = resp.json()
                assert data.get("state") in ("Dead", "Closing"), \
                    f"Expected Dead/Closing after delete, got {data.get('state')}"

        except Exception:
            # If test fails, still try cleanup
            _cleanup_slice(api, name)
            raise

    def test_slice_state_transitions(self, api, fabric_ok):
        """Verify state progression: Draft -> Configuring -> StableOK."""
        name = f"e2e-fab-state-{int(time.time())}"

        try:
            # Create draft
            resp = api.post(f"/slices?name={name}")
            assert resp.status_code == 200
            data = resp.json()
            # New draft should be Draft or have no state
            initial_state = data.get("state", "Draft")
            assert initial_state in ("Draft", "Nascent", ""), \
                f"Expected Draft state, got {initial_state}"

            # Add node
            api.post(f"/slices/{name}/nodes", json={
                "name": "node1", "site": "auto", "cores": 2, "ram": 8, "disk": 10,
                "image": "default_ubuntu_22",
            })

            # Submit
            resp = api.post(f"/slices/{name}/submit", timeout=SUBMIT_TIMEOUT)
            assert resp.status_code == 200
            submit_data = resp.json()
            post_submit_state = submit_data.get("state", "")
            # After submit, should be Configuring or already StableOK
            assert post_submit_state in ("Configuring", "Nascent", "StableOK"), \
                f"Expected Configuring/Nascent/StableOK after submit, got {post_submit_state}"

            # Wait for StableOK
            data = _wait_stable_ok(api, name)
            assert data["state"] == "StableOK"

        finally:
            _cleanup_slice(api, name)
