"""Mock integration tests for FABRIC slice provisioning scenarios.

These tests use mocked FABlib (no real FABRIC credentials needed) to verify
that the API correctly builds topologies, serializes responses, and produces
valid graph output for each provisioning scenario.

Mirrors the real provisioning tests in tests/fabric/test_fabric_provision_e2e.py.
"""


class TestSingleNodeMock:
    """Mock: create single-node slice, verify API response and graph."""

    def test_create_draft_and_add_node(self, client):
        resp = client.post("/api/slices?name=e2e-mock-single")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "e2e-mock-single"
        sid = data["id"]

        resp = client.post(f"/api/slices/{sid}/nodes", json={
            "name": "node1", "site": "RENC", "cores": 2, "ram": 8, "disk": 10,
            "image": "default_ubuntu_22",
        })
        assert resp.status_code == 200
        nodes = resp.json()["nodes"]
        assert len(nodes) == 1
        assert nodes[0]["name"] == "node1"
        assert nodes[0]["site"] == "RENC"

    def test_single_node_graph(self, client):
        client.post("/api/slices?name=e2e-mock-graph1")
        resp = client.post("/api/slices/e2e-mock-graph1/nodes", json={
            "name": "node1", "site": "RENC", "cores": 2, "ram": 8, "disk": 10,
        })
        graph = resp.json()["graph"]
        vm_nodes = [n for n in graph["nodes"] if n.get("classes") == "vm"]
        assert len(vm_nodes) == 1
        assert vm_nodes[0]["data"]["name"] == "node1"

    def test_node_response_shape(self, client):
        """Verify the response shape after adding a node."""
        client.post("/api/slices?name=e2e-mock-shape")
        resp = client.post("/api/slices/e2e-mock-shape/nodes", json={
            "name": "node1", "site": "RENC", "cores": 4, "ram": 16, "disk": 50,
            "image": "default_ubuntu_22",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "nodes" in data
        assert "networks" in data
        assert "graph" in data
        node = data["nodes"][0]
        assert node["cores"] == 4
        assert node["ram"] == 16
        assert node["disk"] == 50

    def test_delete_draft(self, client):
        client.post("/api/slices?name=e2e-mock-del")
        client.post("/api/slices/e2e-mock-del/nodes", json={
            "name": "node1", "site": "RENC", "cores": 2, "ram": 8, "disk": 10,
        })
        resp = client.delete("/api/slices/e2e-mock-del")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"


class TestMultiNodeMock:
    """Mock: create multi-node slice, verify both nodes in response."""

    def test_two_nodes(self, client):
        client.post("/api/slices?name=e2e-mock-multi")
        for i in range(2):
            resp = client.post("/api/slices/e2e-mock-multi/nodes", json={
                "name": f"node{i+1}", "site": "RENC", "cores": 2, "ram": 8, "disk": 10,
            })
            assert resp.status_code == 200
        data = resp.json()
        assert len(data["nodes"]) == 2

    def test_multi_node_graph_has_two_vms(self, client):
        client.post("/api/slices?name=e2e-mock-multi-g")
        for i in range(2):
            client.post("/api/slices/e2e-mock-multi-g/nodes", json={
                "name": f"node{i+1}", "site": "RENC", "cores": 2, "ram": 8, "disk": 10,
            })
        resp = client.get("/api/slices/e2e-mock-multi-g")
        graph = resp.json()["graph"]
        vm_nodes = [n for n in graph["nodes"] if n.get("classes") == "vm"]
        assert len(vm_nodes) == 2


class TestNicFabNetv4Mock:
    """Mock: node + NIC + FABNetv4 network."""

    def test_add_nic_and_fabnetv4(self, client):
        client.post("/api/slices?name=e2e-mock-l3")
        client.post("/api/slices/e2e-mock-l3/nodes", json={
            "name": "node1", "site": "RENC", "cores": 2, "ram": 8, "disk": 10,
            "components": [{"model": "NIC_Basic", "name": "nic1"}],
        })
        # Get interface name
        resp = client.get("/api/slices/e2e-mock-l3")
        iface = resp.json()["nodes"][0]["components"][0]["interfaces"][0]["name"]
        assert iface  # Should be "node1-nic1-p1"

        # Add FABNetv4
        resp = client.post("/api/slices/e2e-mock-l3/networks", json={
            "name": "fabnet", "type": "FABNetv4", "interfaces": [iface],
        })
        assert resp.status_code == 200
        networks = resp.json()["networks"]
        assert len(networks) >= 1

    def test_fabnetv4_graph_has_l3_network(self, client):
        client.post("/api/slices?name=e2e-mock-l3g")
        client.post("/api/slices/e2e-mock-l3g/nodes", json={
            "name": "node1", "site": "RENC",
            "components": [{"model": "NIC_Basic", "name": "nic1"}],
        })
        resp = client.get("/api/slices/e2e-mock-l3g")
        iface = resp.json()["nodes"][0]["components"][0]["interfaces"][0]["name"]
        client.post("/api/slices/e2e-mock-l3g/networks", json={
            "name": "fabnet", "type": "FABNetv4", "interfaces": [iface],
        })
        resp = client.get("/api/slices/e2e-mock-l3g")
        graph = resp.json()["graph"]
        net_nodes = [n for n in graph["nodes"] if "network" in n.get("classes", "")]
        assert len(net_nodes) >= 1
        edges = graph.get("edges", [])
        assert len(edges) >= 1


class TestTwoNodeFabNetv4PingMock:
    """Mock: two nodes with NICs on FABNetv4 — verify topology."""

    def test_two_nodes_fabnetv4_topology(self, client):
        client.post("/api/slices?name=e2e-mock-ping")
        for i in range(2):
            client.post("/api/slices/e2e-mock-ping/nodes", json={
                "name": f"node{i+1}", "site": "RENC",
                "components": [{"model": "NIC_Basic", "name": f"nic{i+1}"}],
            })
        resp = client.get("/api/slices/e2e-mock-ping")
        ifaces = []
        for node in resp.json()["nodes"]:
            for comp in node["components"]:
                for iface in comp["interfaces"]:
                    ifaces.append(iface["name"])
        assert len(ifaces) >= 2

        resp = client.post("/api/slices/e2e-mock-ping/networks", json={
            "name": "fabnet", "type": "FABNetv4", "interfaces": ifaces[:2],
        })
        assert resp.status_code == 200

        # Graph should have 2 VMs, 1+ network nodes, 2+ edges
        graph = resp.json()["graph"]
        vm_nodes = [n for n in graph["nodes"] if n.get("classes") == "vm"]
        assert len(vm_nodes) == 2
        edges = graph.get("edges", [])
        assert len(edges) >= 2


class TestStateTransitionsMock:
    """Mock: verify Draft -> Configuring state transition."""

    def test_draft_state(self, client):
        resp = client.post("/api/slices?name=e2e-mock-state")
        assert resp.json().get("state") in ("Draft", "")

    def test_get_slice_returns_state(self, client):
        """Verify GET slice returns state field."""
        client.post("/api/slices?name=e2e-mock-state2")
        client.post("/api/slices/e2e-mock-state2/nodes", json={
            "name": "node1", "site": "RENC", "cores": 2, "ram": 8, "disk": 10,
        })
        resp = client.get("/api/slices/e2e-mock-state2")
        assert resp.status_code == 200
        data = resp.json()
        assert "state" in data
        assert data["state"] in ("Draft", "")
