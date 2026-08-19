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

    def test_validate_flags_cross_site_fabnet_network(self, client):
        create_resp = client.post("/api/slices?name=validate-cross-site-fabnet")
        sid = create_resp.json()["id"]
        for name, site in [("vm1", "DALL"), ("vm2", "WASH")]:
            client.post(
                f"/api/slices/{sid}/nodes",
                json={
                    "name": name,
                    "site": site,
                    "components": [{"name": "nic1", "model": "NIC_Basic"}],
                },
            )

        resp = client.get(f"/api/slices/{sid}")
        ifaces = [
            iface["name"]
            for node in resp.json()["nodes"]
            for comp in node["components"]
            for iface in comp["interfaces"]
        ]
        client.post(
            f"/api/slices/{sid}/networks",
            json={"name": "fabnet", "type": "FABNetv4", "interfaces": ifaces},
        )

        validate = client.get(f"/api/slices/{sid}/validate")
        assert validate.status_code == 200
        data = validate.json()
        assert data["valid"] is False
        error_text = "\n".join(
            f"{issue['message']} {issue['remedy']}"
            for issue in data["issues"]
            if issue["severity"] == "error"
        )
        assert "fabnet" in error_text
        assert "DALL" in error_text
        assert "WASH" in error_text
        assert "one FABNet service per site" in error_text
        assert "add_fabnet" in error_text

    def test_validate_flags_l2ptp_wrong_interface_count(self, client):
        create_resp = client.post("/api/slices?name=validate-l2ptp-count")
        sid = create_resp.json()["id"]
        client.post(
            f"/api/slices/{sid}/nodes",
            json={
                "name": "vm1",
                "site": "DALL",
                "components": [{"name": "nic1", "model": "NIC_Basic"}],
            },
        )
        resp = client.get(f"/api/slices/{sid}")
        iface = resp.json()["nodes"][0]["components"][0]["interfaces"][0]["name"]
        client.post(
            f"/api/slices/{sid}/networks",
            json={"name": "ptp", "type": "L2PTP", "interfaces": [iface]},
        )

        validate = client.get(f"/api/slices/{sid}/validate")
        assert validate.status_code == 200
        data = validate.json()
        assert data["valid"] is False
        assert any(
            "ptp" in issue["message"] and "needs exactly 2" in issue["message"]
            for issue in data["issues"]
            if issue["severity"] == "error"
        )
