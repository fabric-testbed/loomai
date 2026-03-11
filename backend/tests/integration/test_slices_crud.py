"""Tests for slice CRUD: create, list, get, delete, clone."""


class TestCreateSlice:
    def test_create_returns_slice_data(self, client):
        resp = client.post("/api/slices?name=test-slice")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "test-slice"
        assert data["state"] == "Draft"
        assert "id" in data
        assert data["id"].startswith("draft-")
        assert "graph" in data

    def test_create_includes_graph(self, client):
        resp = client.post("/api/slices?name=graphed")
        data = resp.json()
        graph = data["graph"]
        assert "nodes" in graph
        assert "edges" in graph
        # Empty slice has only the slice container node
        assert len(graph["nodes"]) == 1

    def test_create_two_slices(self, client):
        r1 = client.post("/api/slices?name=slice-a")
        r2 = client.post("/api/slices?name=slice-b")
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["id"] != r2.json()["id"]


class TestGetSlice:
    def test_get_draft_by_id(self, client):
        """A newly created draft can be fetched by its ID."""
        create_resp = client.post("/api/slices?name=get-test")
        assert create_resp.status_code == 200
        slice_id = create_resp.json()["id"]
        # The draft is in _draft_slices, so get should work
        resp = client.get(f"/api/slices/{slice_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "get-test"
        assert "graph" in data

    def test_get_nonexistent(self, client):
        resp = client.get("/api/slices/nonexistent-uuid")
        assert resp.status_code == 404


class TestDeleteSlice:
    def test_delete_draft(self, client):
        create_resp = client.post("/api/slices?name=to-delete")
        slice_id = create_resp.json()["id"]
        resp = client.delete(f"/api/slices/{slice_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

    def test_delete_then_get_fails(self, client):
        """After deleting a draft, GET returns 404."""
        create_resp = client.post("/api/slices?name=gone")
        slice_id = create_resp.json()["id"]
        client.delete(f"/api/slices/{slice_id}")
        resp = client.get(f"/api/slices/{slice_id}")
        assert resp.status_code == 404


class TestCloneSlice:
    def test_clone_creates_new_draft(self, client):
        create_resp = client.post("/api/slices?name=original")
        assert create_resp.status_code == 200
        slice_id = create_resp.json()["id"]
        # Add a node first
        add_resp = client.post(f"/api/slices/{slice_id}/nodes",
                               json={"name": "node1", "site": "RENC",
                                     "cores": 4, "ram": 16, "disk": 50})
        assert add_resp.status_code == 200
        resp = client.post(f"/api/slices/{slice_id}/clone?new_name=cloned")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "cloned"
        assert data["state"] == "Draft"
