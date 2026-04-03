"""Mock integration tests for FABRIC specialized hardware and network scenarios.

These tests use mocked FABlib (no real FABRIC credentials needed) to verify
that the API correctly builds topologies with GPUs, NVMe, FPGAs, SmartNICs,
and specialized network types (L2STS, L2PTP, FABNetv4).

Mirrors the real provisioning tests in tests/fabric/test_fabric_hardware_e2e.py.
Each test verifies: correct API response, component serialization, graph output.
"""


# ---------------------------------------------------------------------------
# Multi-site network topology tests
# ---------------------------------------------------------------------------

class TestMultiSiteFabNetv4Mock:
    """Mock: two nodes on different sites with FABNetv4."""

    def test_create_topology(self, client):
        client.post("/api/slices?name=mock-ms-l3")
        # Node at TACC
        resp = client.post("/api/slices/mock-ms-l3/nodes", json={
            "name": "node1", "site": "TACC", "cores": 2, "ram": 8, "disk": 10,
            "components": [{"model": "NIC_Basic", "name": "nic1"}],
        })
        assert resp.status_code == 200
        # Node at STAR (different site)
        resp = client.post("/api/slices/mock-ms-l3/nodes", json={
            "name": "node2", "site": "STAR", "cores": 2, "ram": 8, "disk": 10,
            "components": [{"model": "NIC_Basic", "name": "nic1"}],
        })
        assert resp.status_code == 200
        nodes = resp.json()["nodes"]
        assert nodes[0]["site"] != nodes[1]["site"]

    def test_fabnetv4_network(self, client):
        client.post("/api/slices?name=mock-ms-l3-net")
        for site, i in [("TACC", 1), ("STAR", 2)]:
            client.post("/api/slices/mock-ms-l3-net/nodes", json={
                "name": f"node{i}", "site": site,
                "components": [{"model": "NIC_Basic", "name": f"nic{i}"}],
            })
        resp = client.get("/api/slices/mock-ms-l3-net")
        ifaces = [iface["name"]
                  for n in resp.json()["nodes"]
                  for c in n["components"]
                  for iface in c["interfaces"]]
        resp = client.post("/api/slices/mock-ms-l3-net/networks", json={
            "name": "fabnet", "type": "FABNetv4", "interfaces": ifaces[:2],
        })
        assert resp.status_code == 200
        nets = resp.json()["networks"]
        assert any(n["name"] == "fabnet" for n in nets)

    def test_graph_shows_cross_site(self, client):
        client.post("/api/slices?name=mock-ms-l3-g")
        for site, i in [("TACC", 1), ("UCSD", 2)]:
            client.post("/api/slices/mock-ms-l3-g/nodes", json={
                "name": f"node{i}", "site": site,
                "components": [{"model": "NIC_Basic", "name": f"nic{i}"}],
            })
        resp = client.get("/api/slices/mock-ms-l3-g")
        ifaces = [iface["name"]
                  for n in resp.json()["nodes"]
                  for c in n["components"]
                  for iface in c["interfaces"]]
        client.post("/api/slices/mock-ms-l3-g/networks", json={
            "name": "fabnet", "type": "FABNetv4", "interfaces": ifaces[:2],
        })
        resp = client.get("/api/slices/mock-ms-l3-g")
        graph = resp.json()["graph"]
        vm_nodes = [n for n in graph["nodes"] if n.get("classes") == "vm"]
        assert len(vm_nodes) == 2
        # Nodes should be at different sites
        sites = {n["data"]["site"] for n in vm_nodes}
        assert len(sites) == 2


class TestMultiSiteL2STSMock:
    """Mock: two nodes on different sites with L2STS + static IPs."""

    def test_l2sts_topology(self, client):
        client.post("/api/slices?name=mock-l2sts")
        for site, i in [("TACC", 1), ("STAR", 2)]:
            client.post("/api/slices/mock-l2sts/nodes", json={
                "name": f"node{i}", "site": site,
                "components": [{"model": "NIC_Basic", "name": f"nic{i}"}],
            })
        resp = client.get("/api/slices/mock-l2sts")
        ifaces = [iface["name"]
                  for n in resp.json()["nodes"]
                  for c in n["components"]
                  for iface in c["interfaces"]]
        resp = client.post("/api/slices/mock-l2sts/networks", json={
            "name": "l2sts-link", "type": "L2STS",
            "interfaces": ifaces[:2],
            "subnet": "192.168.100.0/24",
            "ip_mode": "config",
            "interface_ips": {ifaces[0]: "192.168.100.10", ifaces[1]: "192.168.100.20"},
        })
        assert resp.status_code == 200
        nets = resp.json()["networks"]
        l2sts = [n for n in nets if n["name"] == "l2sts-link"]
        assert len(l2sts) == 1
        assert l2sts[0]["type"] == "L2STS"

    def test_l2sts_graph_has_l2_network(self, client):
        client.post("/api/slices?name=mock-l2sts-g")
        for site, i in [("RENC", 1), ("DALL", 2)]:
            client.post("/api/slices/mock-l2sts-g/nodes", json={
                "name": f"node{i}", "site": site,
                "components": [{"model": "NIC_Basic", "name": f"nic{i}"}],
            })
        resp = client.get("/api/slices/mock-l2sts-g")
        ifaces = [iface["name"]
                  for n in resp.json()["nodes"]
                  for c in n["components"]
                  for iface in c["interfaces"]]
        client.post("/api/slices/mock-l2sts-g/networks", json={
            "name": "s2s", "type": "L2STS", "interfaces": ifaces[:2],
        })
        resp = client.get("/api/slices/mock-l2sts-g")
        graph = resp.json()["graph"]
        net_nodes = [n for n in graph["nodes"] if "network" in n.get("classes", "")]
        assert len(net_nodes) >= 1
        assert any("l2" in n.get("classes", "") for n in net_nodes)


class TestMultiSiteL2PTPMock:
    """Mock: two nodes with L2 Point-to-Point link."""

    def test_l2ptp_topology(self, client):
        client.post("/api/slices?name=mock-l2ptp")
        for site, i in [("TACC", 1), ("STAR", 2)]:
            client.post("/api/slices/mock-l2ptp/nodes", json={
                "name": f"node{i}", "site": site,
                "components": [{"model": "NIC_Basic", "name": f"nic{i}"}],
            })
        resp = client.get("/api/slices/mock-l2ptp")
        ifaces = [iface["name"]
                  for n in resp.json()["nodes"]
                  for c in n["components"]
                  for iface in c["interfaces"]]
        resp = client.post("/api/slices/mock-l2ptp/networks", json={
            "name": "p2p-link", "type": "L2PTP",
            "interfaces": ifaces[:2],
            "subnet": "10.10.10.0/30",
            "ip_mode": "config",
            "interface_ips": {ifaces[0]: "10.10.10.1", ifaces[1]: "10.10.10.2"},
        })
        assert resp.status_code == 200
        nets = resp.json()["networks"]
        ptp = [n for n in nets if n["name"] == "p2p-link"]
        assert len(ptp) == 1
        assert ptp[0]["type"] == "L2PTP"


# ---------------------------------------------------------------------------
# Specialized hardware component tests
# ---------------------------------------------------------------------------

class TestGPUMock:
    """Mock: node with GPU component."""

    def test_add_gpu_node(self, client):
        client.post("/api/slices?name=mock-gpu")
        resp = client.post("/api/slices/mock-gpu/nodes", json={
            "name": "gpu-node", "site": "UCSD", "cores": 8, "ram": 32, "disk": 100,
            "components": [{"model": "GPU_RTX6000", "name": "gpu1"}],
        })
        assert resp.status_code == 200
        node = resp.json()["nodes"][0]
        assert node["name"] == "gpu-node"
        comps = node["components"]
        assert len(comps) == 1
        assert comps[0]["model"] == "GPU_RTX6000"
        assert comps[0]["name"] == "gpu1"

    def test_gpu_graph_badge(self, client):
        client.post("/api/slices?name=mock-gpu-g")
        client.post("/api/slices/mock-gpu-g/nodes", json={
            "name": "gpu-node", "site": "UCSD", "cores": 8, "ram": 32, "disk": 100,
            "components": [{"model": "GPU_RTX6000", "name": "gpu1"}],
        })
        resp = client.get("/api/slices/mock-gpu-g")
        graph = resp.json()["graph"]
        # Component badge node should exist for the GPU
        comp_nodes = [n for n in graph["nodes"] if "component" in n.get("classes", "")]
        assert len(comp_nodes) >= 1
        assert any(n["data"].get("model") == "GPU_RTX6000" for n in comp_nodes)

    def test_gpu_with_nic(self, client):
        """GPU node with both GPU and NIC components."""
        client.post("/api/slices?name=mock-gpu-nic")
        resp = client.post("/api/slices/mock-gpu-nic/nodes", json={
            "name": "gpu-node", "site": "UCSD", "cores": 8, "ram": 32, "disk": 100,
            "components": [
                {"model": "GPU_RTX6000", "name": "gpu1"},
                {"model": "NIC_Basic", "name": "nic1"},
            ],
        })
        assert resp.status_code == 200
        comps = resp.json()["nodes"][0]["components"]
        models = {c["model"] for c in comps}
        assert "GPU_RTX6000" in models
        assert "NIC_Basic" in models


class TestNVMeMock:
    """Mock: node with NVMe storage component."""

    def test_add_nvme_node(self, client):
        client.post("/api/slices?name=mock-nvme")
        resp = client.post("/api/slices/mock-nvme/nodes", json={
            "name": "nvme-node", "site": "TACC", "cores": 4, "ram": 16, "disk": 10,
            "components": [{"model": "NVME_P4510", "name": "nvme1"}],
        })
        assert resp.status_code == 200
        comps = resp.json()["nodes"][0]["components"]
        assert comps[0]["model"] == "NVME_P4510"

    def test_nvme_graph_badge(self, client):
        client.post("/api/slices?name=mock-nvme-g")
        client.post("/api/slices/mock-nvme-g/nodes", json={
            "name": "nvme-node", "site": "TACC",
            "components": [{"model": "NVME_P4510", "name": "nvme1"}],
        })
        resp = client.get("/api/slices/mock-nvme-g")
        graph = resp.json()["graph"]
        comp_nodes = [n for n in graph["nodes"] if "component" in n.get("classes", "")]
        assert len(comp_nodes) >= 1
        assert any(n["data"].get("model") == "NVME_P4510" for n in comp_nodes)


class TestFPGAMock:
    """Mock: node with Xilinx FPGA component."""

    def test_add_fpga_node(self, client):
        client.post("/api/slices?name=mock-fpga")
        resp = client.post("/api/slices/mock-fpga/nodes", json={
            "name": "fpga-node", "site": "UCSD", "cores": 4, "ram": 16, "disk": 10,
            "components": [{"model": "FPGA_Xilinx_U280", "name": "fpga1"}],
        })
        assert resp.status_code == 200
        comps = resp.json()["nodes"][0]["components"]
        assert comps[0]["model"] == "FPGA_Xilinx_U280"

    def test_fpga_graph_badge(self, client):
        client.post("/api/slices?name=mock-fpga-g")
        client.post("/api/slices/mock-fpga-g/nodes", json={
            "name": "fpga-node", "site": "UCSD",
            "components": [{"model": "FPGA_Xilinx_U280", "name": "fpga1"}],
        })
        resp = client.get("/api/slices/mock-fpga-g")
        graph = resp.json()["graph"]
        comp_nodes = [n for n in graph["nodes"] if "component" in n.get("classes", "")]
        assert len(comp_nodes) >= 1
        assert any(n["data"].get("model") == "FPGA_Xilinx_U280" for n in comp_nodes)


# ---------------------------------------------------------------------------
# SmartNIC tests — ConnectX-5, ConnectX-6, ConnectX-7
# ---------------------------------------------------------------------------

class TestConnectX5Mock:
    """Mock: node with ConnectX-5 on FABNetv4."""

    def test_cx5_node_with_fabnet(self, client):
        client.post("/api/slices?name=mock-cx5")
        # SmartNIC node
        client.post("/api/slices/mock-cx5/nodes", json={
            "name": "smartnic-node", "site": "TACC", "cores": 4, "ram": 16, "disk": 10,
            "components": [{"model": "NIC_ConnectX_5", "name": "nic1"}],
        })
        # Gateway node at different site
        client.post("/api/slices/mock-cx5/nodes", json={
            "name": "gw-node", "site": "STAR", "cores": 2, "ram": 8, "disk": 10,
            "components": [{"model": "NIC_Basic", "name": "nic1"}],
        })
        resp = client.get("/api/slices/mock-cx5")
        ifaces = [iface["name"]
                  for n in resp.json()["nodes"]
                  for c in n["components"]
                  for iface in c["interfaces"]]
        resp = client.post("/api/slices/mock-cx5/networks", json={
            "name": "fabnet", "type": "FABNetv4", "interfaces": ifaces[:2],
        })
        assert resp.status_code == 200
        # Verify CX5 model in response
        nodes = resp.json()["nodes"]
        sn = [n for n in nodes if n["name"] == "smartnic-node"][0]
        assert sn["components"][0]["model"] == "NIC_ConnectX_5"

    def test_cx5_graph_badge(self, client):
        client.post("/api/slices?name=mock-cx5-g")
        client.post("/api/slices/mock-cx5-g/nodes", json={
            "name": "smartnic-node", "site": "TACC",
            "components": [{"model": "NIC_ConnectX_5", "name": "nic1"}],
        })
        resp = client.get("/api/slices/mock-cx5-g")
        graph = resp.json()["graph"]
        comp_nodes = [n for n in graph["nodes"] if "component" in n.get("classes", "")]
        assert len(comp_nodes) >= 1
        assert any(n["data"].get("model") == "NIC_ConnectX_5" for n in comp_nodes)


class TestConnectX6Mock:
    """Mock: node with dedicated ConnectX-6 on FABNetv4."""

    def test_cx6_node_with_fabnet(self, client):
        client.post("/api/slices?name=mock-cx6")
        client.post("/api/slices/mock-cx6/nodes", json={
            "name": "smartnic-node", "site": "TACC",
            "components": [{"model": "NIC_ConnectX_6", "name": "nic1"}],
        })
        client.post("/api/slices/mock-cx6/nodes", json={
            "name": "gw-node", "site": "STAR",
            "components": [{"model": "NIC_Basic", "name": "nic1"}],
        })
        resp = client.get("/api/slices/mock-cx6")
        ifaces = [iface["name"]
                  for n in resp.json()["nodes"]
                  for c in n["components"]
                  for iface in c["interfaces"]]
        resp = client.post("/api/slices/mock-cx6/networks", json={
            "name": "fabnet", "type": "FABNetv4", "interfaces": ifaces[:2],
        })
        assert resp.status_code == 200
        nodes = resp.json()["nodes"]
        sn = [n for n in nodes if n["name"] == "smartnic-node"][0]
        assert sn["components"][0]["model"] == "NIC_ConnectX_6"

    def test_cx6_graph_badge(self, client):
        client.post("/api/slices?name=mock-cx6-g")
        client.post("/api/slices/mock-cx6-g/nodes", json={
            "name": "smartnic-node", "site": "TACC",
            "components": [{"model": "NIC_ConnectX_6", "name": "nic1"}],
        })
        resp = client.get("/api/slices/mock-cx6-g")
        graph = resp.json()["graph"]
        comp_nodes = [n for n in graph["nodes"] if "component" in n.get("classes", "")]
        assert len(comp_nodes) >= 1
        assert any(n["data"].get("model") == "NIC_ConnectX_6" for n in comp_nodes)


class TestConnectX7Mock:
    """Mock: node with ConnectX-7 (BlueField) on FABNetv4."""

    def test_cx7_node_with_fabnet(self, client):
        client.post("/api/slices?name=mock-cx7")
        client.post("/api/slices/mock-cx7/nodes", json={
            "name": "smartnic-node", "site": "STAR",
            "components": [{"model": "NIC_ConnectX_7", "name": "nic1"}],
        })
        client.post("/api/slices/mock-cx7/nodes", json={
            "name": "gw-node", "site": "TACC",
            "components": [{"model": "NIC_Basic", "name": "nic1"}],
        })
        resp = client.get("/api/slices/mock-cx7")
        ifaces = [iface["name"]
                  for n in resp.json()["nodes"]
                  for c in n["components"]
                  for iface in c["interfaces"]]
        resp = client.post("/api/slices/mock-cx7/networks", json={
            "name": "fabnet", "type": "FABNetv4", "interfaces": ifaces[:2],
        })
        assert resp.status_code == 200
        nodes = resp.json()["nodes"]
        sn = [n for n in nodes if n["name"] == "smartnic-node"][0]
        assert sn["components"][0]["model"] == "NIC_ConnectX_7"

    def test_cx7_graph_badge(self, client):
        client.post("/api/slices?name=mock-cx7-g")
        client.post("/api/slices/mock-cx7-g/nodes", json={
            "name": "smartnic-node", "site": "STAR",
            "components": [{"model": "NIC_ConnectX_7", "name": "nic1"}],
        })
        resp = client.get("/api/slices/mock-cx7-g")
        graph = resp.json()["graph"]
        comp_nodes = [n for n in graph["nodes"] if "component" in n.get("classes", "")]
        assert len(comp_nodes) >= 1
        assert any(n["data"].get("model") == "NIC_ConnectX_7" for n in comp_nodes)
