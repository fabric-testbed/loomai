"""FABRIC specialized hardware and network provisioning E2E tests.

These tests provision real FABRIC slices with specific hardware (GPUs, NVMe,
FPGAs, SmartNICs) and network types (FABNetv4, L2STS, L2PTP) across multiple
sites.  They are very slow (10-30 min each) and require a valid FABRIC token
plus availability of the specific hardware at the target sites.

Gate: ``@pytest.mark.fabric`` — excluded from default runs.
Run all::

    pytest tests/fabric/test_fabric_hardware_e2e.py -v -s -m fabric --timeout=1800

Run one::

    pytest tests/fabric/test_fabric_hardware_e2e.py -v -s -m fabric -k gpu --timeout=1800
    pytest tests/fabric/test_fabric_hardware_e2e.py -v -s -m fabric -k l2sts --timeout=1200
"""

import os
import time

import httpx
import pytest

pytestmark = pytest.mark.fabric

BASE_URL = os.environ.get("LOOMAI_BASE_URL", "http://localhost:8000")

# Timeouts — these tests involve specialized hardware that may take longer
SUBMIT_TIMEOUT = 180        # 3 min for submit call
STABLE_TIMEOUT = 900        # 15 min for StableOK (specialized hardware is slower)
POLL_INTERVAL = 15          # seconds between state polls
EXEC_TIMEOUT = 120          # 2 min for command execution
SSH_WAIT_TIMEOUT = 300      # 5 min for SSH readiness
GPU_SETUP_TIMEOUT = 600     # 10 min for GPU driver + Ollama setup

# Site pairs for multi-site tests (pick 2 sites known to have good connectivity)
SITE_A = os.environ.get("FABRIC_SITE_A", "TACC")
SITE_B = os.environ.get("FABRIC_SITE_B", "STAR")

# Sites known to have specific hardware (overridable via env)
GPU_SITE = os.environ.get("FABRIC_GPU_SITE", "UCSD")
NVME_SITE = os.environ.get("FABRIC_NVME_SITE", "TACC")
FPGA_SITE = os.environ.get("FABRIC_FPGA_SITE", "UCSD")
CX5_SITE = os.environ.get("FABRIC_CX5_SITE", "TACC")
CX6_SITE = os.environ.get("FABRIC_CX6_SITE", "TACC")
CX7_SITE = os.environ.get("FABRIC_CX7_SITE", "STAR")


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
    """Execute a command on a FABRIC VM node."""
    resp = api.post(
        f"/api/files/vm/{slice_name}/{node_name}/execute",
        json={"command": command},
        timeout=float(timeout),
    )
    assert resp.status_code == 200, f"Execute failed ({resp.status_code}): {resp.text}"
    return resp.json()


def _wait_ssh_ready(api: httpx.Client, slice_name: str, node_name: str,
                    timeout: int = SSH_WAIT_TIMEOUT) -> bool:
    """Poll until SSH is reachable on a node."""
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


def _get_interface_names(api: httpx.Client, slice_name: str) -> list[str]:
    """Get all interface names from a slice's nodes."""
    resp = api.get(f"/slices/{slice_name}")
    assert resp.status_code == 200
    ifaces = []
    for node in resp.json().get("nodes", []):
        for comp in node.get("components", []):
            for iface in comp.get("interfaces", []):
                if iface.get("name"):
                    ifaces.append(iface["name"])
    return ifaces


def _get_dataplane_ip(api: httpx.Client, slice_name: str, node_name: str) -> str:
    """Get a node's data-plane IP (non-loopback, non-management)."""
    # Try FABNetv4 range first (10.x.x.x)
    result = _exec_on_node(api, slice_name, node_name,
        "ip -4 addr show | grep 'inet 10\\.' | awk '{print $2}' | cut -d/ -f1 | head -1")
    ip = result.get("stdout", "").strip()
    if ip:
        return ip

    # Fallback: any non-localhost, non-management IP
    result = _exec_on_node(api, slice_name, node_name,
        "ip -4 addr show | grep 'inet ' | grep -v '127.0.0' | "
        "awk '{print $2}' | cut -d/ -f1 | tail -1")
    return result.get("stdout", "").strip()


def _ping_test(api: httpx.Client, slice_name: str, from_node: str, target_ip: str,
               count: int = 3, wait: int = 5) -> bool:
    """Ping from one node to target IP. Returns True if at least 1 packet received."""
    result = _exec_on_node(api, slice_name, from_node,
        f"ping -c {count} -W {wait} {target_ip}")
    stdout = result.get("stdout", "")
    return "bytes from" in stdout and "0 received" not in stdout


# ---------------------------------------------------------------------------
# Network Tests — Multi-site connectivity
# ---------------------------------------------------------------------------

class TestMultiSiteNetworks:
    """Multi-site network provisioning with connectivity verification."""

    def test_multisite_fabnetv4_ping(self, api, fabric_ok):
        """Two VMs on different sites connected via FABNetv4 — ping test.

        Creates node1 at SITE_A and node2 at SITE_B, both with NIC_Basic
        on a shared FABNetv4 network.  Verifies L3 ping connectivity.
        """
        name = f"e2e-fab-ms-l3-{int(time.time())}"

        try:
            resp = api.post(f"/slices?name={name}")
            assert resp.status_code == 200

            # Node at site A
            resp = api.post(f"/slices/{name}/nodes", json={
                "name": "node1", "site": SITE_A,
                "cores": 2, "ram": 8, "disk": 10,
                "image": "default_ubuntu_22",
                "components": [{"model": "NIC_Basic", "name": "nic1"}],
            })
            assert resp.status_code == 200, f"Add node1 at {SITE_A} failed: {resp.text}"

            # Node at site B
            resp = api.post(f"/slices/{name}/nodes", json={
                "name": "node2", "site": SITE_B,
                "cores": 2, "ram": 8, "disk": 10,
                "image": "default_ubuntu_22",
                "components": [{"model": "NIC_Basic", "name": "nic1"}],
            })
            assert resp.status_code == 200, f"Add node2 at {SITE_B} failed: {resp.text}"

            # Get interface names
            ifaces = _get_interface_names(api, name)
            assert len(ifaces) >= 2, f"Expected 2+ interfaces, got: {ifaces}"

            # FABNetv4 network connecting both
            resp = api.post(f"/slices/{name}/networks", json={
                "name": "fabnet",
                "type": "FABNetv4",
                "interfaces": ifaces[:2],
            })
            assert resp.status_code == 200

            # Submit and wait
            resp = api.post(f"/slices/{name}/submit", timeout=SUBMIT_TIMEOUT)
            assert resp.status_code == 200
            data = _wait_stable_ok(api, name)

            # SSH wait
            for n in ["node1", "node2"]:
                assert _wait_ssh_ready(api, name, n), f"SSH not ready on {n}"

            # Get node2 data-plane IP and ping from node1
            node2_ip = _get_dataplane_ip(api, name, "node2")
            assert node2_ip, "Could not get node2 data-plane IP"
            assert _ping_test(api, name, "node1", node2_ip), \
                f"node1@{SITE_A} cannot ping node2@{SITE_B} at {node2_ip}"

        finally:
            _cleanup_slice(api, name)

    def test_multisite_l2sts_ping(self, api, fabric_ok):
        """Two VMs on different sites connected via L2 Site-to-Site — ping test.

        Creates an L2STS link between SITE_A and SITE_B with static IP
        configuration.  Verifies L2 + L3 connectivity.
        """
        name = f"e2e-fab-l2sts-{int(time.time())}"

        try:
            resp = api.post(f"/slices?name={name}")
            assert resp.status_code == 200

            for i, site in enumerate([SITE_A, SITE_B], 1):
                resp = api.post(f"/slices/{name}/nodes", json={
                    "name": f"node{i}", "site": site,
                    "cores": 2, "ram": 8, "disk": 10,
                    "image": "default_ubuntu_22",
                    "components": [{"model": "NIC_Basic", "name": f"nic{i}"}],
                })
                assert resp.status_code == 200, f"Add node{i} at {site} failed: {resp.text}"

            ifaces = _get_interface_names(api, name)
            assert len(ifaces) >= 2

            # L2STS network with static IPs
            resp = api.post(f"/slices/{name}/networks", json={
                "name": "l2sts-link",
                "type": "L2STS",
                "interfaces": ifaces[:2],
                "subnet": "192.168.100.0/24",
                "ip_mode": "config",
                "interface_ips": {
                    ifaces[0]: "192.168.100.10",
                    ifaces[1]: "192.168.100.20",
                },
            })
            assert resp.status_code == 200, f"Add L2STS network failed: {resp.text}"

            resp = api.post(f"/slices/{name}/submit", timeout=SUBMIT_TIMEOUT)
            assert resp.status_code == 200
            data = _wait_stable_ok(api, name)

            for n in ["node1", "node2"]:
                assert _wait_ssh_ready(api, name, n), f"SSH not ready on {n}"

            # Configure IPs on the data-plane interfaces (L2 may need manual config)
            # Find the data-plane interface name on each node
            for node_name, ip in [("node1", "192.168.100.10"), ("node2", "192.168.100.20")]:
                # Find the non-management, non-loopback interface
                result = _exec_on_node(api, name, node_name,
                    "ip -o link show | grep -v lo | grep -v 'ens\\|eth0\\|management' | "
                    "awk -F': ' '{print $2}' | head -1")
                data_iface = result.get("stdout", "").strip()
                if data_iface:
                    _exec_on_node(api, name, node_name,
                        f"sudo ip addr add {ip}/24 dev {data_iface} 2>/dev/null; "
                        f"sudo ip link set {data_iface} up")

            # Give interfaces time to come up
            time.sleep(5)

            # Ping test
            assert _ping_test(api, name, "node1", "192.168.100.20"), \
                f"node1@{SITE_A} cannot ping node2@{SITE_B} over L2STS at 192.168.100.20"

        finally:
            _cleanup_slice(api, name)

    def test_multisite_l2ptp_ping(self, api, fabric_ok):
        """Two VMs on different sites connected via L2 Point-to-Point — ping test.

        L2PTP is a dedicated point-to-point link between exactly 2 interfaces.
        """
        name = f"e2e-fab-l2ptp-{int(time.time())}"

        try:
            resp = api.post(f"/slices?name={name}")
            assert resp.status_code == 200

            for i, site in enumerate([SITE_A, SITE_B], 1):
                resp = api.post(f"/slices/{name}/nodes", json={
                    "name": f"node{i}", "site": site,
                    "cores": 2, "ram": 8, "disk": 10,
                    "image": "default_ubuntu_22",
                    "components": [{"model": "NIC_Basic", "name": f"nic{i}"}],
                })
                assert resp.status_code == 200, f"Add node{i} at {site} failed: {resp.text}"

            ifaces = _get_interface_names(api, name)
            assert len(ifaces) >= 2

            # L2PTP — exactly 2 interfaces, static IPs
            resp = api.post(f"/slices/{name}/networks", json={
                "name": "p2p-link",
                "type": "L2PTP",
                "interfaces": ifaces[:2],
                "subnet": "10.10.10.0/30",
                "ip_mode": "config",
                "interface_ips": {
                    ifaces[0]: "10.10.10.1",
                    ifaces[1]: "10.10.10.2",
                },
            })
            assert resp.status_code == 200, f"Add L2PTP network failed: {resp.text}"

            resp = api.post(f"/slices/{name}/submit", timeout=SUBMIT_TIMEOUT)
            assert resp.status_code == 200
            data = _wait_stable_ok(api, name)

            for n in ["node1", "node2"]:
                assert _wait_ssh_ready(api, name, n), f"SSH not ready on {n}"

            # Configure IPs on data-plane interfaces
            for node_name, ip in [("node1", "10.10.10.1"), ("node2", "10.10.10.2")]:
                result = _exec_on_node(api, name, node_name,
                    "ip -o link show | grep -v lo | grep -v 'ens\\|eth0\\|management' | "
                    "awk -F': ' '{print $2}' | head -1")
                data_iface = result.get("stdout", "").strip()
                if data_iface:
                    _exec_on_node(api, name, node_name,
                        f"sudo ip addr add {ip}/30 dev {data_iface} 2>/dev/null; "
                        f"sudo ip link set {data_iface} up")

            time.sleep(5)

            assert _ping_test(api, name, "node1", "10.10.10.2"), \
                f"node1@{SITE_A} cannot ping node2@{SITE_B} over L2PTP at 10.10.10.2"

        finally:
            _cleanup_slice(api, name)


# ---------------------------------------------------------------------------
# Specialized Hardware Tests
# ---------------------------------------------------------------------------

class TestSpecializedHardware:
    """Tests for GPU, NVMe, FPGA, and SmartNIC hardware."""

    def test_gpu_ollama_llm(self, api, fabric_ok):
        """VM with GPU — install Ollama, pull a small model, query for a joke.

        Provisions a node with GPU_RTX6000 (or GPU_A30/A40), installs Ollama,
        pulls the tinyllama model, and queries it for a joke.
        This test is very slow (~15-30 min for setup + model pull).
        """
        name = f"e2e-fab-gpu-{int(time.time())}"

        try:
            resp = api.post(f"/slices?name={name}")
            assert resp.status_code == 200

            resp = api.post(f"/slices/{name}/nodes", json={
                "name": "gpu-node",
                "site": GPU_SITE,
                "cores": 8,
                "ram": 32,
                "disk": 100,
                "image": "default_ubuntu_22",
                "components": [{"model": "GPU_RTX6000", "name": "gpu1"}],
            })
            assert resp.status_code == 200, f"Add GPU node failed: {resp.text}"

            resp = api.post(f"/slices/{name}/submit", timeout=SUBMIT_TIMEOUT)
            assert resp.status_code == 200
            _wait_stable_ok(api, name)

            assert _wait_ssh_ready(api, name, "gpu-node"), "SSH not ready on gpu-node"

            # Verify GPU is visible
            result = _exec_on_node(api, name, "gpu-node", "lspci | grep -i nvidia")
            stdout = result.get("stdout", "")
            assert "NVIDIA" in stdout.upper(), f"No NVIDIA GPU detected: {stdout}"

            # Install Ollama
            _exec_on_node(api, name, "gpu-node",
                "curl -fsSL https://ollama.com/install.sh | sh",
                timeout=GPU_SETUP_TIMEOUT)

            # Start Ollama server in background
            _exec_on_node(api, name, "gpu-node",
                "nohup ollama serve > /tmp/ollama.log 2>&1 &")
            time.sleep(5)

            # Pull a tiny model (tinyllama is ~1.1GB, fastest option)
            result = _exec_on_node(api, name, "gpu-node",
                "ollama pull tinyllama",
                timeout=GPU_SETUP_TIMEOUT)
            stdout = result.get("stdout", "") + result.get("stderr", "")
            assert "error" not in stdout.lower() or "success" in stdout.lower(), \
                f"Ollama pull failed: {stdout}"

            # Query the model for a joke
            result = _exec_on_node(api, name, "gpu-node",
                'ollama run tinyllama "Tell me a short joke" --nowordwrap 2>/dev/null | head -20',
                timeout=120)
            stdout = result.get("stdout", "").strip()
            assert len(stdout) > 10, f"LLM response too short or empty: {stdout}"

        finally:
            _cleanup_slice(api, name)

    def test_nvme_format_readwrite(self, api, fabric_ok):
        """VM with NVMe drive — format, mount, test read/write capabilities.

        Provisions a node with NVME_P4510, partitions and formats the NVMe,
        mounts it, and verifies read/write operations.
        """
        name = f"e2e-fab-nvme-{int(time.time())}"

        try:
            resp = api.post(f"/slices?name={name}")
            assert resp.status_code == 200

            resp = api.post(f"/slices/{name}/nodes", json={
                "name": "nvme-node",
                "site": NVME_SITE,
                "cores": 4,
                "ram": 16,
                "disk": 10,
                "image": "default_ubuntu_22",
                "components": [{"model": "NVME_P4510", "name": "nvme1"}],
            })
            assert resp.status_code == 200, f"Add NVMe node failed: {resp.text}"

            resp = api.post(f"/slices/{name}/submit", timeout=SUBMIT_TIMEOUT)
            assert resp.status_code == 200
            _wait_stable_ok(api, name)

            assert _wait_ssh_ready(api, name, "nvme-node"), "SSH not ready on nvme-node"

            # Find the NVMe device
            result = _exec_on_node(api, name, "nvme-node", "lsblk -d -o NAME,SIZE,TYPE | grep nvme")
            stdout = result.get("stdout", "")
            assert "nvme" in stdout, f"No NVMe device found: {stdout}"

            # Get the NVMe device path (e.g., /dev/nvme0n1)
            result = _exec_on_node(api, name, "nvme-node",
                "lsblk -d -o NAME | grep nvme | head -1")
            nvme_dev = result.get("stdout", "").strip()
            assert nvme_dev, "Could not determine NVMe device name"
            nvme_path = f"/dev/{nvme_dev}"

            # Format with ext4
            result = _exec_on_node(api, name, "nvme-node",
                f"sudo mkfs.ext4 -F {nvme_path}", timeout=120)
            stdout = result.get("stdout", "") + result.get("stderr", "")
            assert "error" not in stdout.lower() or "Writing superblocks" in stdout, \
                f"mkfs.ext4 failed: {stdout}"

            # Mount
            _exec_on_node(api, name, "nvme-node",
                f"sudo mkdir -p /mnt/nvme && sudo mount {nvme_path} /mnt/nvme")

            # Write test
            _exec_on_node(api, name, "nvme-node",
                "sudo dd if=/dev/urandom of=/mnt/nvme/testfile bs=1M count=100 2>/dev/null")

            # Verify file exists and has correct size
            result = _exec_on_node(api, name, "nvme-node",
                "ls -la /mnt/nvme/testfile | awk '{print $5}'")
            file_size = result.get("stdout", "").strip()
            assert int(file_size) >= 100_000_000, f"Written file too small: {file_size} bytes"

            # Read test — compute checksum
            result = _exec_on_node(api, name, "nvme-node",
                "md5sum /mnt/nvme/testfile | awk '{print $1}'")
            checksum1 = result.get("stdout", "").strip()
            assert len(checksum1) == 32, f"Invalid checksum: {checksum1}"

            # Copy and verify (read + write integrity)
            _exec_on_node(api, name, "nvme-node",
                "sudo cp /mnt/nvme/testfile /mnt/nvme/testfile_copy")
            result = _exec_on_node(api, name, "nvme-node",
                "md5sum /mnt/nvme/testfile_copy | awk '{print $1}'")
            checksum2 = result.get("stdout", "").strip()
            assert checksum1 == checksum2, f"Checksum mismatch: {checksum1} vs {checksum2}"

            # Cleanup mount
            _exec_on_node(api, name, "nvme-node", "sudo umount /mnt/nvme")

        finally:
            _cleanup_slice(api, name)

    def test_fpga_xilinx_pci(self, api, fabric_ok):
        """VM with Xilinx FPGA — verify the Xilinx PCIe device exists.

        Provisions a node with FPGA_Xilinx_U280 and checks that the Xilinx
        PCIe device is visible via lspci.
        """
        name = f"e2e-fab-fpga-{int(time.time())}"

        try:
            resp = api.post(f"/slices?name={name}")
            assert resp.status_code == 200

            resp = api.post(f"/slices/{name}/nodes", json={
                "name": "fpga-node",
                "site": FPGA_SITE,
                "cores": 4,
                "ram": 16,
                "disk": 10,
                "image": "default_ubuntu_22",
                "components": [{"model": "FPGA_Xilinx_U280", "name": "fpga1"}],
            })
            assert resp.status_code == 200, f"Add FPGA node failed: {resp.text}"

            resp = api.post(f"/slices/{name}/submit", timeout=SUBMIT_TIMEOUT)
            assert resp.status_code == 200
            _wait_stable_ok(api, name)

            assert _wait_ssh_ready(api, name, "fpga-node"), "SSH not ready on fpga-node"

            # Check for Xilinx PCIe device
            result = _exec_on_node(api, name, "fpga-node", "lspci | grep -i xilinx")
            stdout = result.get("stdout", "")
            assert "xilinx" in stdout.lower(), f"No Xilinx FPGA PCI device found: {stdout}"

            # Also check /dev for any xclmgmt or xocl devices
            result = _exec_on_node(api, name, "fpga-node",
                "lspci -d 10ee: -v 2>/dev/null | head -20")
            stdout = result.get("stdout", "")
            # Xilinx vendor ID is 10ee — at least one device should match
            assert stdout.strip(), f"No Xilinx vendor (10ee) PCI devices found"

        finally:
            _cleanup_slice(api, name)


# ---------------------------------------------------------------------------
# SmartNIC Tests — ConnectX-5, ConnectX-6, ConnectX-7 (BlueField)
# ---------------------------------------------------------------------------

class TestSmartNICFabNet:
    """SmartNIC tests with FABNetv4 connectivity verification."""

    def _run_smartnic_fabnet_test(self, api, fabric_ok, nic_model: str, nic_site: str,
                                  gateway_site: str, test_label: str):
        """Shared implementation: VM with SmartNIC on FABNetv4, ping a gateway node.

        Creates two nodes:
        - smartnic-node at nic_site with the specified NIC model on FABNetv4
        - gw-node at gateway_site with NIC_Basic on FABNetv4
        Verifies ping between them over the FABNet.
        """
        name = f"e2e-fab-{test_label}-{int(time.time())}"

        try:
            resp = api.post(f"/slices?name={name}")
            assert resp.status_code == 200

            # SmartNIC node
            resp = api.post(f"/slices/{name}/nodes", json={
                "name": "smartnic-node",
                "site": nic_site,
                "cores": 4,
                "ram": 16,
                "disk": 10,
                "image": "default_ubuntu_22",
                "components": [{"model": nic_model, "name": "nic1"}],
            })
            assert resp.status_code == 200, f"Add {nic_model} node at {nic_site} failed: {resp.text}"

            # Gateway node on a different site
            resp = api.post(f"/slices/{name}/nodes", json={
                "name": "gw-node",
                "site": gateway_site,
                "cores": 2,
                "ram": 8,
                "disk": 10,
                "image": "default_ubuntu_22",
                "components": [{"model": "NIC_Basic", "name": "nic1"}],
            })
            assert resp.status_code == 200, f"Add gw-node at {gateway_site} failed: {resp.text}"

            # Get interface names
            ifaces = _get_interface_names(api, name)
            assert len(ifaces) >= 2, f"Expected 2+ interfaces, got: {ifaces}"

            # FABNetv4 network connecting both
            resp = api.post(f"/slices/{name}/networks", json={
                "name": "fabnet",
                "type": "FABNetv4",
                "interfaces": ifaces[:2],
            })
            assert resp.status_code == 200, f"Add FABNetv4 failed: {resp.text}"

            resp = api.post(f"/slices/{name}/submit", timeout=SUBMIT_TIMEOUT)
            assert resp.status_code == 200
            _wait_stable_ok(api, name)

            for n in ["smartnic-node", "gw-node"]:
                assert _wait_ssh_ready(api, name, n), f"SSH not ready on {n}"

            # Verify the SmartNIC is visible via lspci
            result = _exec_on_node(api, name, "smartnic-node", "lspci | grep -i mellanox")
            stdout = result.get("stdout", "")
            assert "mellanox" in stdout.lower() or "connectx" in stdout.lower(), \
                f"No Mellanox/ConnectX device found: {stdout}"

            # Get gateway node's FABNet IP and ping
            gw_ip = _get_dataplane_ip(api, name, "gw-node")
            assert gw_ip, "Could not get gw-node data-plane IP"
            assert _ping_test(api, name, "smartnic-node", gw_ip), \
                f"smartnic-node@{nic_site} ({nic_model}) cannot ping gw-node@{gateway_site} at {gw_ip}"

        finally:
            _cleanup_slice(api, name)

    def test_connectx5_fabnet_ping(self, api, fabric_ok):
        """VM with ConnectX-5 on FABNetv4 — ping gateway on different site."""
        self._run_smartnic_fabnet_test(
            api, fabric_ok,
            nic_model="NIC_ConnectX_5",
            nic_site=CX5_SITE,
            gateway_site=SITE_B if CX5_SITE != SITE_B else SITE_A,
            test_label="cx5",
        )

    def test_connectx6_fabnet_ping(self, api, fabric_ok):
        """VM with dedicated ConnectX-6 on FABNetv4 — ping gateway on different site."""
        self._run_smartnic_fabnet_test(
            api, fabric_ok,
            nic_model="NIC_ConnectX_6",
            nic_site=CX6_SITE,
            gateway_site=SITE_B if CX6_SITE != SITE_B else SITE_A,
            test_label="cx6",
        )

    def test_connectx7_bluefield_fabnet_ping(self, api, fabric_ok):
        """VM with ConnectX-7 (BlueField) on FABNetv4 — ping gateway on different site."""
        self._run_smartnic_fabnet_test(
            api, fabric_ok,
            nic_model="NIC_ConnectX_7",
            nic_site=CX7_SITE,
            gateway_site=SITE_B if CX7_SITE != SITE_B else SITE_A,
            test_label="cx7",
        )
