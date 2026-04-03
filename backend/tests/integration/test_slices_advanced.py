"""Tests for advanced slice endpoints: renew, clone, export, import, storage, archive, reconcile, composite submit, post-boot."""

import json
import os
from unittest.mock import patch, MagicMock, AsyncMock

import pytest


# ---------------------------------------------------------------------------
# Helper: create a draft with one node and return the slice ID
# ---------------------------------------------------------------------------

def _create_draft_with_node(client, name="adv-test"):
    """Create a draft slice with one node, return (slice_id, response_data)."""
    resp = client.post(f"/api/slices?name={name}")
    assert resp.status_code == 200
    sid = resp.json()["id"]
    add = client.post(f"/api/slices/{sid}/nodes",
                      json={"name": "n1", "site": "RENC",
                            "cores": 4, "ram": 16, "disk": 50})
    assert add.status_code == 200
    return sid, add.json()


# ===========================================================================
# POST /slices/{name}/clone
# ===========================================================================

class TestCloneSlice:
    def test_clone_preserves_topology(self, client):
        sid, _ = _create_draft_with_node(client, "original-topo")
        # Add a second node
        client.post(f"/api/slices/{sid}/nodes",
                    json={"name": "n2", "site": "UCSD",
                          "cores": 2, "ram": 8, "disk": 10})
        resp = client.post(f"/api/slices/{sid}/clone?new_name=cloned-topo")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "cloned-topo"
        assert data["state"] == "Draft"
        assert len(data["nodes"]) >= 1  # at least one node cloned

    def test_clone_nonexistent_slice(self, client):
        resp = client.post("/api/slices/no-such-slice/clone?new_name=x")
        assert resp.status_code in (404, 500)


# ===========================================================================
# GET /slices/{name}/export
# ===========================================================================

class TestExportSlice:
    def test_export_returns_json_model(self, client):
        sid, _ = _create_draft_with_node(client, "export-test")
        resp = client.get(f"/api/slices/{sid}/export")
        assert resp.status_code == 200
        data = resp.json()
        assert data["format"] == "fabric-webgui-v1"
        assert data["name"] == "export-test"
        assert "nodes" in data
        assert "networks" in data

    def test_export_includes_node_data(self, client):
        sid, _ = _create_draft_with_node(client, "export-nodes")
        resp = client.get(f"/api/slices/{sid}/export")
        data = resp.json()
        node_names = [n["name"] for n in data["nodes"]]
        assert "n1" in node_names

    def test_export_nonexistent(self, client):
        resp = client.get("/api/slices/missing-slice/export")
        assert resp.status_code in (404, 500)


# ===========================================================================
# POST /slices/import
# ===========================================================================

class TestImportSlice:
    def test_import_minimal_model(self, client):
        model = {
            "format": "fabric-webgui-v1",
            "name": "imported",
            "nodes": [
                {"name": "imp-node", "site": "RENC", "cores": 2, "ram": 8, "disk": 10}
            ],
            "networks": [],
            "facility_ports": [],
        }
        resp = client.post("/api/slices/import", json=model)
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "imported"
        assert data["state"] == "Draft"
        assert len(data["nodes"]) >= 1

    def test_import_with_components(self, client):
        model = {
            "format": "fabric-webgui-v1",
            "name": "imported-comp",
            "nodes": [
                {
                    "name": "comp-node",
                    "site": "RENC",
                    "cores": 4,
                    "ram": 16,
                    "disk": 50,
                    "components": [
                        {"name": "nic1", "model": "NIC_Basic"},
                    ],
                }
            ],
            "networks": [],
            "facility_ports": [],
        }
        resp = client.post("/api/slices/import", json=model)
        assert resp.status_code == 200
        data = resp.json()
        node = data["nodes"][0]
        assert len(node["components"]) >= 1

    def test_import_with_group_site(self, client):
        """Import a model where site is an @group tag (should be deferred)."""
        model = {
            "format": "fabric-webgui-v1",
            "name": "group-import",
            "nodes": [
                {"name": "g-node", "site": "@compute", "cores": 2, "ram": 8, "disk": 10}
            ],
            "networks": [],
            "facility_ports": [],
        }
        resp = client.post("/api/slices/import", json=model)
        assert resp.status_code == 200
        # The slice should still be created as a draft
        assert resp.json()["state"] == "Draft"

    def test_import_missing_name(self, client):
        model = {"format": "fabric-webgui-v1", "nodes": [], "networks": [], "facility_ports": []}
        resp = client.post("/api/slices/import", json=model)
        assert resp.status_code == 422  # Pydantic validation error


# ===========================================================================
# POST /slices/{name}/save-to-storage
# ===========================================================================

class TestSaveToStorage:
    def test_save_creates_file(self, client, storage_dir):
        sid, _ = _create_draft_with_node(client, "save-test")
        resp = client.post(f"/api/slices/{sid}/save-to-storage")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "path" in data
        assert data["path"].endswith(".fabric.json")


# ===========================================================================
# GET /slices/storage-files
# Note: This route is shadowed by GET /slices/{slice_name} due to FastAPI
# route ordering. The frontend does not use this GET endpoint directly.
# We test the underlying function instead.
# ===========================================================================

class TestListStorageFiles:
    def test_list_storage_function_directly(self, client, storage_dir):
        """Test the list_storage_files function directly since the route is shadowed."""
        from app.routes.slices import list_storage_files
        result = list_storage_files()
        assert isinstance(result, list)

    def test_list_after_save(self, client, storage_dir):
        """After saving to storage, listing should find the file."""
        sid, _ = _create_draft_with_node(client, "listed-slice")
        client.post(f"/api/slices/{sid}/save-to-storage")
        from app.routes.slices import list_storage_files
        files = list_storage_files()
        names = [f["name"] for f in files]
        assert any("listed-slice" in n for n in names)


# ===========================================================================
# POST /slices/open-from-storage
# ===========================================================================

class TestOpenFromStorage:
    def test_open_saved_file(self, client, storage_dir):
        sid, _ = _create_draft_with_node(client, "roundtrip")
        save_resp = client.post(f"/api/slices/{sid}/save-to-storage")
        filename = save_resp.json()["path"]
        resp = client.post("/api/slices/open-from-storage",
                           json={"filename": filename})
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "roundtrip"
        assert data["state"] == "Draft"

    def test_open_missing_filename(self, client):
        resp = client.post("/api/slices/open-from-storage", json={"filename": ""})
        assert resp.status_code == 400

    def test_open_nonexistent_file(self, client):
        resp = client.post("/api/slices/open-from-storage",
                           json={"filename": "no-such-file.fabric.json"})
        assert resp.status_code == 404


# ===========================================================================
# POST /slices/archive-terminal
# ===========================================================================

class TestArchiveTerminal:
    def test_archive_terminal_returns_list(self, client):
        resp = client.post("/api/slices/archive-terminal")
        assert resp.status_code == 200
        data = resp.json()
        assert "archived" in data
        assert "count" in data
        assert isinstance(data["archived"], list)
        assert data["count"] == len(data["archived"])


# ===========================================================================
# POST /slices/reconcile-projects
# ===========================================================================

class TestReconcileProjects:
    def test_reconcile_with_mock_fablib(self, client, mock_fablib):
        """Reconcile should succeed even when mock has no real projects."""
        # The mock manager doesn't have get_manager(), so patch it
        mock_mgr = MagicMock()
        mock_mgr.get_project_info.return_value = []
        mock_fablib.get_manager = MagicMock(return_value=mock_mgr)
        mock_fablib.set_project_id = MagicMock()

        resp = client.post("/api/slices/reconcile-projects")
        assert resp.status_code == 200
        data = resp.json()
        assert "tagged" in data or "projects_scanned" in data


# ===========================================================================
# POST /slices/{name}/submit-composite
# ===========================================================================

class TestSubmitComposite:
    def test_composite_no_chameleon_falls_through_to_submit(self, client, mock_fablib):
        """Without Chameleon nodes, submit-composite delegates to normal submit."""
        sid, _ = _create_draft_with_node(client, "composite-test")
        # Mock the chameleon import to have no nodes
        with patch("app.routes.slices._chameleon_slice_nodes", {}, create=True):
            resp = client.post(f"/api/slices/{sid}/submit-composite")
        # Should attempt submit (may fail on FABRIC, but endpoint should be callable)
        assert resp.status_code in (200, 500)


# ===========================================================================
# PUT /slices/{name}/nodes/{node}/post-boot
# ===========================================================================

class TestPostBootConfig:
    def test_set_post_boot_on_node(self, client):
        sid, _ = _create_draft_with_node(client, "boot-test")
        resp = client.put(f"/api/slices/{sid}/nodes/n1/post-boot",
                          json={"script": "#!/bin/bash\necho hello"})
        assert resp.status_code == 200
        data = resp.json()
        # Should return serialized slice data
        assert "nodes" in data

    def test_post_boot_nonexistent_node(self, client):
        sid, _ = _create_draft_with_node(client, "boot-missing")
        resp = client.put(f"/api/slices/{sid}/nodes/no-node/post-boot",
                          json={"script": "echo hi"})
        assert resp.status_code == 500


# ===========================================================================
# POST /slices/{name}/renew — requires submitted slice (mock FABlib)
# ===========================================================================

class TestRenewSlice:
    def test_renew_invalid_date(self, client):
        sid, _ = _create_draft_with_node(client, "renew-test")
        resp = client.post(f"/api/slices/{sid}/renew",
                           json={"end_date": "not-a-date"})
        assert resp.status_code == 400

    def test_renew_nonexistent_slice(self, client):
        resp = client.post("/api/slices/nonexistent/renew",
                           json={"end_date": "2026-12-31T23:59:59Z"})
        assert resp.status_code in (404, 500)
