"""Tests for slice import/export round-trip."""

import json


class TestExportSlice:
    def test_export_returns_model(self, client):
        create_resp = client.post("/api/slices?name=export-test")
        sid = create_resp.json()["id"]
        client.post(f"/api/slices/{sid}/nodes",
                    json={"name": "n1", "site": "RENC", "cores": 4, "ram": 16, "disk": 50})
        resp = client.get(f"/api/slices/{sid}/export")
        assert resp.status_code == 200
        model = resp.json()
        assert model["format"] == "fabric-webgui-v1"
        assert model["name"] == "export-test"
        assert len(model["nodes"]) == 1

    def test_export_includes_components(self, client):
        create_resp = client.post("/api/slices?name=comp-export")
        sid = create_resp.json()["id"]
        client.post(f"/api/slices/{sid}/nodes",
                    json={"name": "n1", "site": "RENC",
                          "components": [{"name": "nic1", "model": "NIC_Basic"}]})
        resp = client.get(f"/api/slices/{sid}/export")
        model = resp.json()
        assert len(model["nodes"][0]["components"]) == 1


class TestImportSlice:
    def test_import_creates_draft(self, client):
        model = {
            "format": "fabric-webgui-v1",
            "name": "imported-slice",
            "nodes": [
                {
                    "name": "node1",
                    "site": "RENC",
                    "cores": 2,
                    "ram": 8,
                    "disk": 10,
                    "image": "default_ubuntu_22",
                    "components": [],
                }
            ],
            "networks": [],
        }
        resp = client.post("/api/slices/import", json=model)
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "imported-slice"
        assert data["state"] == "Draft"
        assert len(data["nodes"]) == 1

    def test_import_with_group_tags(self, client):
        model = {
            "format": "fabric-webgui-v1",
            "name": "grouped-import",
            "nodes": [
                {
                    "name": "n1",
                    "site": "@compute",
                    "cores": 2,
                    "ram": 8,
                    "disk": 10,
                    "components": [{"name": "nic1", "model": "NIC_Basic"}],
                },
                {
                    "name": "n2",
                    "site": "@compute",
                    "cores": 2,
                    "ram": 8,
                    "disk": 10,
                    "components": [{"name": "nic1", "model": "NIC_Basic"}],
                },
            ],
            "networks": [
                {
                    "name": "lan",
                    "type": "L2Bridge",
                    "interfaces": ["n1-nic1-p1", "n2-nic1-p1"],
                }
            ],
        }
        resp = client.post("/api/slices/import", json=model)
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "grouped-import"


class TestImportExportRoundTrip:
    def test_round_trip_preserves_structure(self, client):
        # Create a slice with a node
        create_resp = client.post("/api/slices?name=round-trip")
        sid = create_resp.json()["id"]
        client.post(f"/api/slices/{sid}/nodes",
                    json={"name": "n1", "site": "RENC", "cores": 4, "ram": 16, "disk": 50,
                          "image": "default_ubuntu_22"})

        # Export
        export_resp = client.get(f"/api/slices/{sid}/export")
        model = export_resp.json()

        # Import as new slice
        model["name"] = "round-trip-copy"
        import_resp = client.post("/api/slices/import", json=model)
        assert import_resp.status_code == 200
        imported = import_resp.json()
        assert imported["name"] == "round-trip-copy"
        assert len(imported["nodes"]) == 1
        assert imported["nodes"][0]["name"] == "n1"
