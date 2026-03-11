"""Tests for slice validation endpoint."""


class TestValidateSlice:
    def test_empty_slice_has_errors(self, client):
        create_resp = client.post("/api/slices?name=empty-validate")
        sid = create_resp.json()["id"]
        resp = client.get(f"/api/slices/{sid}/validate")
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        # Should have at least the "no nodes" error
        error_msgs = [i["message"] for i in data["issues"]
                      if i["severity"] == "error"]
        assert any("no nodes" in m.lower() for m in error_msgs)

    def test_valid_single_node(self, client):
        create_resp = client.post("/api/slices?name=valid-test")
        sid = create_resp.json()["id"]
        client.post(f"/api/slices/{sid}/nodes",
                    json={"name": "n1", "site": "RENC",
                          "cores": 2, "ram": 8, "disk": 10})
        resp = client.get(f"/api/slices/{sid}/validate")
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True

    def test_issues_have_severity_and_remedy(self, client):
        create_resp = client.post("/api/slices?name=issue-fields")
        sid = create_resp.json()["id"]
        resp = client.get(f"/api/slices/{sid}/validate")
        for issue in resp.json()["issues"]:
            assert "severity" in issue
            assert "message" in issue
            assert "remedy" in issue
