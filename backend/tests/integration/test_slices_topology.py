"""Tests for topology manipulation: nodes, components, networks."""


class TestAddNode:
    def test_add_node(self, client):
        create_resp = client.post("/api/slices?name=topo-test")
        sid = create_resp.json()["id"]
        resp = client.post(f"/api/slices/{sid}/nodes",
                           json={"name": "node1", "site": "RENC",
                                 "cores": 4, "ram": 16, "disk": 50})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["nodes"]) == 1
        assert data["nodes"][0]["name"] == "node1"
        assert data["nodes"][0]["cores"] == 4

    def test_add_node_with_components(self, client):
        create_resp = client.post("/api/slices?name=comp-test")
        sid = create_resp.json()["id"]
        resp = client.post(f"/api/slices/{sid}/nodes",
                           json={"name": "gpu-node", "site": "UCSD",
                                 "cores": 8, "ram": 32, "disk": 100,
                                 "components": [
                                     {"name": "gpu1", "model": "GPU_RTX6000"},
                                     {"name": "nic1", "model": "NIC_Basic"},
                                 ]})
        assert resp.status_code == 200
        node = resp.json()["nodes"][0]
        assert len(node["components"]) == 2

    def test_add_multiple_nodes(self, client):
        create_resp = client.post("/api/slices?name=multi-node")
        sid = create_resp.json()["id"]
        client.post(f"/api/slices/{sid}/nodes",
                    json={"name": "n1", "site": "RENC"})
        resp = client.post(f"/api/slices/{sid}/nodes",
                           json={"name": "n2", "site": "UCSD"})
        assert resp.status_code == 200
        assert len(resp.json()["nodes"]) == 2

    def test_graph_updates_with_node(self, client):
        create_resp = client.post("/api/slices?name=graph-node")
        sid = create_resp.json()["id"]
        resp = client.post(f"/api/slices/{sid}/nodes",
                           json={"name": "n1", "site": "RENC"})
        graph = resp.json()["graph"]
        vm_nodes = [n for n in graph["nodes"] if n["classes"] == "vm"]
        assert len(vm_nodes) == 1


class TestUpdateNode:
    def test_update_site(self, client):
        create_resp = client.post("/api/slices?name=update-test")
        sid = create_resp.json()["id"]
        client.post(f"/api/slices/{sid}/nodes",
                    json={"name": "n1", "site": "RENC"})
        resp = client.put(f"/api/slices/{sid}/nodes/n1",
                          json={"site": "UCSD"})
        assert resp.status_code == 200

    def test_update_resources(self, client):
        create_resp = client.post("/api/slices?name=res-update")
        sid = create_resp.json()["id"]
        client.post(f"/api/slices/{sid}/nodes",
                    json={"name": "n1", "site": "RENC", "cores": 2, "ram": 8, "disk": 10})
        resp = client.put(f"/api/slices/{sid}/nodes/n1",
                          json={"cores": 8, "ram": 32, "disk": 100})
        assert resp.status_code == 200


class TestRemoveNode:
    def test_remove_node(self, client):
        create_resp = client.post("/api/slices?name=remove-node")
        sid = create_resp.json()["id"]
        client.post(f"/api/slices/{sid}/nodes",
                    json={"name": "n1", "site": "RENC"})
        resp = client.delete(f"/api/slices/{sid}/nodes/n1")
        assert resp.status_code == 200


class TestAddComponent:
    def test_add_component_to_node(self, client):
        create_resp = client.post("/api/slices?name=add-comp")
        sid = create_resp.json()["id"]
        client.post(f"/api/slices/{sid}/nodes",
                    json={"name": "n1", "site": "RENC"})
        resp = client.post(f"/api/slices/{sid}/nodes/n1/components",
                           json={"name": "nic1", "model": "NIC_Basic"})
        assert resp.status_code == 200


class TestAddNetwork:
    def test_add_l2_network(self, client):
        create_resp = client.post("/api/slices?name=net-test")
        sid = create_resp.json()["id"]
        # Add two nodes with NICs first
        client.post(f"/api/slices/{sid}/nodes",
                    json={"name": "n1", "site": "RENC",
                          "components": [{"name": "nic1", "model": "NIC_Basic"}]})
        client.post(f"/api/slices/{sid}/nodes",
                    json={"name": "n2", "site": "RENC",
                          "components": [{"name": "nic1", "model": "NIC_Basic"}]})
        # Create network connecting the NICs
        resp = client.post(f"/api/slices/{sid}/networks",
                           json={"name": "lan", "type": "L2Bridge",
                                 "interfaces": ["n1-nic1-p1", "n2-nic1-p1"]})
        assert resp.status_code == 200
        nets = resp.json()["networks"]
        assert len(nets) == 1
        assert nets[0]["name"] == "lan"
