"""Tests for advanced slice endpoints: renew, clone, export, import, storage, archive, reconcile, composite submit, post-boot."""

import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock, AsyncMock

import pytest
from tests.fixtures.fablib_mocks import MockSlice


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


def _create_cross_site_fabnet_draft(client, name="cross-site-fabnet"):
    resp = client.post(f"/api/slices?name={name}")
    assert resp.status_code == 200
    sid = resp.json()["id"]
    for node_name, site in [("vm1", "DALL"), ("vm2", "WASH")]:
        add = client.post(
            f"/api/slices/{sid}/nodes",
            json={
                "name": node_name,
                "site": site,
                "components": [{"name": "nic1", "model": "NIC_Basic"}],
            },
        )
        assert add.status_code == 200
    resp = client.get(f"/api/slices/{sid}")
    ifaces = [
        iface["name"]
        for node in resp.json()["nodes"]
        for comp in node["components"]
        for iface in comp["interfaces"]
    ]
    add_net = client.post(
        f"/api/slices/{sid}/networks",
        json={"name": "fabnet", "type": "FABNetv4", "interfaces": ifaces},
    )
    assert add_net.status_code == 200
    return sid


def _set_max_lease_hours(hours: int):
    from app import settings_manager
    settings = settings_manager.load_settings()
    settings.setdefault("fabric", {}).setdefault("slice_policy", {})["max_lease_hours"] = hours
    settings_manager.save_settings(settings)


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
        assert resp.status_code in (200, 500, 502)
        if resp.status_code == 502:
            assert resp.json()["detail"]["code"] == "FABRIC_SUBMIT_FAILED"


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
# POST /slices/{name}/submit — lease handling
# ===========================================================================

class TestSubmitLease:
    def test_submit_background_returns_job_id(self, client):
        sid, _ = _create_draft_with_node(client, "lease-submit-bg")
        captured = {}

        async def fake_start_job(kind, work, metadata=None):
            captured["kind"] = kind
            captured["metadata"] = metadata
            return "job-test-submit"

        with patch("app.assistant_jobs.start_job", new_callable=AsyncMock, side_effect=fake_start_job), \
             patch("app.routes.slices.get_fresh_sites", return_value=[]), \
             patch("app.routes.slices.resolve_sites", side_effect=lambda nodes, sites: (nodes, {})):
            submit = client.post(
                f"/api/slices/{sid}/submit",
                json={
                    "lease_hours": 6,
                    "wait_for_stableok": True,
                    "background": True,
                },
            )

        assert submit.status_code == 200
        payload = submit.json()
        assert payload["status"] == "queued"
        assert payload["job_id"] == "job-test-submit"
        assert payload["slice_name"] == "lease-submit-bg"
        assert payload["wait_for_stableok"] is True
        assert payload["background"] is True
        assert captured["kind"] == "submit_slice"
        assert captured["metadata"]["lease_hours"] == 6
        assert captured["metadata"]["wait_for_stableok"] is True

    def test_submit_uses_lease_hours_from_create(self, client, mock_fablib):
        resp = client.post("/api/slices?name=lease-submit&lease_hours=6")
        assert resp.status_code == 200
        sid = resp.json()["id"]
        add = client.post(f"/api/slices/{sid}/nodes",
                          json={"name": "n1", "site": "RENC"})
        assert add.status_code == 200

        with patch("app.routes.slices.get_fresh_sites", return_value=[]), \
             patch("app.routes.slices.resolve_sites", side_effect=lambda nodes, sites: (nodes, {})):
            submit = client.post(f"/api/slices/{sid}/submit")

        assert submit.status_code == 200
        slice_obj = mock_fablib.get_slice(name="lease-submit")
        assert slice_obj.submitted_kwargs["lease_in_hours"] == 6

    def test_submit_uses_lease_hours_from_create_body(self, client, mock_fablib):
        resp = client.post("/api/slices", json={"name": "lease-submit-body-create", "lease_hours": 6})
        assert resp.status_code == 200
        sid = resp.json()["id"]
        add = client.post(f"/api/slices/{sid}/nodes",
                          json={"name": "n1", "site": "RENC"})
        assert add.status_code == 200

        with patch("app.routes.slices.get_fresh_sites", return_value=[]), \
             patch("app.routes.slices.resolve_sites", side_effect=lambda nodes, sites: (nodes, {})):
            submit = client.post(f"/api/slices/{sid}/submit")

        assert submit.status_code == 200
        slice_obj = mock_fablib.get_slice(name="lease-submit-body-create")
        assert slice_obj.submitted_kwargs["lease_in_hours"] == 6

    def test_submit_uses_explicit_lease_hours_body(self, client, mock_fablib):
        sid, _ = _create_draft_with_node(client, "lease-submit-body")

        with patch("app.routes.slices.get_fresh_sites", return_value=[]), \
             patch("app.routes.slices.resolve_sites", side_effect=lambda nodes, sites: (nodes, {})):
            submit = client.post(f"/api/slices/{sid}/submit",
                                 json={"lease_hours": 6})

        assert submit.status_code == 200
        slice_obj = mock_fablib.get_slice(name="lease-submit-body")
        assert slice_obj.submitted_kwargs["lease_in_hours"] == 6

    def test_submit_prefers_lease_hours_over_end_date(self, client, mock_fablib):
        sid, _ = _create_draft_with_node(client, "lease-submit-cap")

        with patch("app.routes.slices.get_fresh_sites", return_value=[]), \
             patch("app.routes.slices.resolve_sites", side_effect=lambda nodes, sites: (nodes, {})):
            submit = client.post(f"/api/slices/{sid}/submit",
                                 json={
                                     "lease_hours": 6,
                                     "end_date": "2099-01-01T00:00:00Z",
                                 })

        assert submit.status_code == 200
        slice_obj = mock_fablib.get_slice(name="lease-submit-cap")
        assert slice_obj.submitted_kwargs["lease_in_hours"] == 6
        assert "lease_end_time" not in slice_obj.submitted_kwargs

    def test_submit_applies_max_lease_policy_default(self, client, mock_fablib):
        _set_max_lease_hours(6)
        sid, _ = _create_draft_with_node(client, "lease-policy-default")

        with patch("app.routes.slices.get_fresh_sites", return_value=[]), \
             patch("app.routes.slices.resolve_sites", side_effect=lambda nodes, sites: (nodes, {})):
            submit = client.post(f"/api/slices/{sid}/submit")

        assert submit.status_code == 200
        slice_obj = mock_fablib.get_slice(name="lease-policy-default")
        assert slice_obj.submitted_kwargs["lease_in_hours"] == 6
        warning = submit.json()["warnings"][0]
        assert warning["code"] == "LEASE_CLAMPED_TO_POLICY"
        assert warning["requested_lease_hours"] is None
        assert warning["effective_lease_hours"] == 6
        assert warning["source"] == "policy_default"

    def test_submit_background_reports_policy_default_lease_warning(self, client):
        _set_max_lease_hours(6)
        sid, _ = _create_draft_with_node(client, "lease-policy-bg-default")
        captured = {}

        async def fake_start_job(kind, work, metadata=None):
            captured["kind"] = kind
            captured["metadata"] = metadata
            return "job-policy-default"

        with patch("app.assistant_jobs.start_job", new_callable=AsyncMock, side_effect=fake_start_job), \
             patch("app.routes.slices.get_fresh_sites", return_value=[]), \
             patch("app.routes.slices.resolve_sites", side_effect=lambda nodes, sites: (nodes, {})):
            submit = client.post(
                f"/api/slices/{sid}/submit",
                json={"wait_for_stableok": True, "background": True},
            )

        assert submit.status_code == 200
        payload = submit.json()
        assert payload["status"] == "queued"
        assert payload["lease_hours"] == 6
        warning = payload["warnings"][0]
        assert warning["code"] == "LEASE_CLAMPED_TO_POLICY"
        assert warning["source"] == "policy_default"
        assert captured["metadata"]["lease_hours"] == 6
        assert captured["metadata"]["warnings"][0]["code"] == "LEASE_CLAMPED_TO_POLICY"

    def test_submit_caps_requested_lease_hours_to_policy(self, client, mock_fablib):
        _set_max_lease_hours(6)
        resp = client.post("/api/slices?name=lease-policy-cap&lease_hours=24")
        assert resp.status_code == 200
        sid = resp.json()["id"]
        add = client.post(f"/api/slices/{sid}/nodes",
                          json={"name": "n1", "site": "RENC"})
        assert add.status_code == 200

        with patch("app.routes.slices.get_fresh_sites", return_value=[]), \
             patch("app.routes.slices.resolve_sites", side_effect=lambda nodes, sites: (nodes, {})):
            submit = client.post(f"/api/slices/{sid}/submit")

        assert submit.status_code == 200
        slice_obj = mock_fablib.get_slice(name="lease-policy-cap")
        assert slice_obj.submitted_kwargs["lease_in_hours"] == 6

    def test_submit_clamps_explicit_over_cap_lease_with_warning(self, client, mock_fablib):
        _set_max_lease_hours(6)
        sid, _ = _create_draft_with_node(client, "lease-policy-warning")

        with patch("app.routes.slices.get_fresh_sites", return_value=[]), \
             patch("app.routes.slices.resolve_sites", side_effect=lambda nodes, sites: (nodes, {})):
            submit = client.post(
                f"/api/slices/{sid}/submit",
                json={"lease_hours": 30},
            )

        assert submit.status_code == 200
        slice_obj = mock_fablib.get_slice(name="lease-policy-warning")
        assert slice_obj.submitted_kwargs["lease_in_hours"] == 6
        warning = submit.json()["warnings"][0]
        assert warning["code"] == "LEASE_CLAMPED_TO_POLICY"
        assert warning["requested_lease_hours"] == 30
        assert warning["effective_lease_hours"] == 6

    def test_submit_honors_explicit_under_cap_lease(self, client, mock_fablib):
        _set_max_lease_hours(6)
        sid, _ = _create_draft_with_node(client, "lease-policy-under")

        with patch("app.routes.slices.get_fresh_sites", return_value=[]), \
             patch("app.routes.slices.resolve_sites", side_effect=lambda nodes, sites: (nodes, {})):
            submit = client.post(
                f"/api/slices/{sid}/submit",
                json={"lease_hours": 4},
            )

        assert submit.status_code == 200
        slice_obj = mock_fablib.get_slice(name="lease-policy-under")
        assert slice_obj.submitted_kwargs["lease_in_hours"] == 4
        assert "warnings" not in submit.json()

    def test_submit_explicit_end_date_is_not_replaced_by_policy_default_hours(self, client, mock_fablib):
        _set_max_lease_hours(6)
        sid, _ = _create_draft_with_node(client, "lease-policy-end-date")

        with patch("app.routes.slices.get_fresh_sites", return_value=[]), \
             patch("app.routes.slices.resolve_sites", side_effect=lambda nodes, sites: (nodes, {})):
            submit = client.post(
                f"/api/slices/{sid}/submit",
                json={"end_date": "2099-01-01T00:00:00Z"},
            )

        assert submit.status_code == 200
        slice_obj = mock_fablib.get_slice(name="lease-policy-end-date")
        assert "lease_in_hours" not in slice_obj.submitted_kwargs
        assert "lease_end_time" in slice_obj.submitted_kwargs
        assert "warnings" not in submit.json()


class TestSliceRegistryResolution:
    def test_refresh_falls_back_to_name_when_registry_uuid_returns_incomplete_object(self, client, mock_fablib):
        from app.slice_registry import get_slice_uuid, register_slice

        live = MockSlice(name="stale-refresh", slice_id="fresh-refresh-uuid", state="StableOK")
        mock_fablib._slices[live.get_name()] = live
        register_slice("stale-refresh", uuid="stale-refresh-uuid", state="StableOK")
        original_get_slice = mock_fablib.get_slice

        broken = MagicMock()
        broken.get_name.return_value = None
        broken.get_slice_id.return_value = None
        broken.get_state.return_value = None

        def stale_get_slice(name=None, slice_id=None):
            if slice_id == "stale-refresh-uuid":
                return broken
            return original_get_slice(name=name, slice_id=slice_id)

        mock_fablib.get_slice = stale_get_slice

        resp = client.post("/api/slices/stale-refresh/refresh")

        assert resp.status_code == 200
        assert resp.json()["name"] == "stale-refresh"
        assert get_slice_uuid("stale-refresh") == "fresh-refresh-uuid"

    def test_delete_falls_back_to_name_when_registry_uuid_is_stale(self, client, mock_fablib):
        from app.slice_registry import get_all_entries, get_slice_uuid, register_slice

        live = MockSlice(name="stale-delete", slice_id="fresh-delete-uuid", state="StableOK")
        mock_fablib._slices[live.get_name()] = live
        register_slice("stale-delete", uuid="stale-delete-uuid", state="StableOK")
        original_get_slice = mock_fablib.get_slice

        broken = MagicMock()
        broken.get_name.return_value = None
        broken.get_slice_id.return_value = None
        broken.get_state.return_value = None

        def stale_get_slice(name=None, slice_id=None):
            if slice_id == "stale-delete-uuid":
                return broken
            return original_get_slice(name=name, slice_id=slice_id)

        mock_fablib.get_slice = stale_get_slice

        resp = client.delete("/api/slices/stale-delete")

        assert resp.status_code == 200
        assert resp.json() == {"status": "deleted", "name": "stale-delete"}
        assert live.get_state() == "Dead"
        assert get_slice_uuid("stale-delete") == "fresh-delete-uuid"
        assert get_all_entries(include_archived=True)["stale-delete"]["state"] == "Dead"

    def test_refresh_resolution_failure_surfaces_uuid_and_name_errors(self, client, mock_fablib):
        from app.slice_registry import register_slice

        register_slice("missing-refresh", uuid="stale-missing-uuid", state="StableOK")

        def failing_get_slice(name=None, slice_id=None):
            if slice_id:
                raise RuntimeError(f"uuid lookup failed for {slice_id}")
            raise RuntimeError(f"name lookup failed for {name}")

        mock_fablib.get_slice = failing_get_slice

        resp = client.post("/api/slices/missing-refresh/refresh")

        assert resp.status_code == 502
        detail = resp.json()["detail"]
        assert detail["code"] == "SLICE_RESOLUTION_FAILED"
        assert "uuid lookup failed for stale-missing-uuid" in detail["uuid_lookup_error"]
        assert "name lookup failed for missing-refresh" in detail["name_lookup_error"]

    def test_missing_slice_name_returns_404_with_structured_resolution_error(self, client):
        for method, path in (
            (client.get, "/api/slices/not-a-real-slice"),
            (client.delete, "/api/slices/not-a-real-slice"),
        ):
            resp = method(path)

            assert resp.status_code == 404
            detail = resp.json()["detail"]
            assert detail["code"] == "SLICE_RESOLUTION_FAILED"
            assert detail["slice_name"] == "not-a-real-slice"
            assert "not found" in detail["name_lookup_error"].lower()

    def test_unable_to_find_slice_name_returns_404_with_structured_resolution_error(self, client, mock_fablib):
        mock_fablib.get_slice = MagicMock(
            side_effect=RuntimeError(
                "Unable to find slice bench-fc16-missing-20260712 for this project."
            )
        )

        for method, path in (
            (client.get, "/api/slices/bench-fc16-missing-20260712"),
            (client.delete, "/api/slices/bench-fc16-missing-20260712"),
        ):
            resp = method(path)

            assert resp.status_code == 404
            detail = resp.json()["detail"]
            assert detail["code"] == "SLICE_RESOLUTION_FAILED"
            assert detail["slice_name"] == "bench-fc16-missing-20260712"
            assert "unable to find slice" in detail["name_lookup_error"].lower()

    def test_delete_configuring_slice_surfaces_actionable_orchestrator_error(self, client, mock_fablib):
        live = MockSlice(name="configuring-delete", slice_id="configuring-delete-uuid", state="Configuring")
        mock_fablib._slices[live.get_name()] = live
        live.delete = MagicMock(side_effect=RuntimeError(
            "Unable to delete Slices [configuring-delete] that are not yet stable, "
            "try again later after the slice reaches StableOK or a terminal state. "
            "extra detail " * 25
        ))

        resp = client.delete("/api/slices/configuring-delete")

        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["code"] == "FABRIC_DELETE_FAILED"
        assert "not yet stable" in detail["message"]
        assert "try again later" in detail["message"]

    def test_delete_configuring_slice_preserves_actionable_prefix_before_json_tail(self, client, mock_fablib):
        live = MockSlice(name="configuring-json-tail", slice_id="configuring-json-tail-uuid", state="Configuring")
        mock_fablib._slices[live.get_name()] = live
        live.delete = MagicMock(side_effect=RuntimeError(
            "Unable to delete Slices [configuring-json-tail] that are not yet stable, "
            "try again later after the slice reaches StableOK or a terminal state.\n"
            "{\n"
            '  "status": 500,\n'
            '  "type": "error"\n'
            "}"
        ))

        resp = client.delete("/api/slices/configuring-json-tail")

        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["code"] == "FABRIC_DELETE_FAILED"
        assert "not yet stable" in detail["message"]
        assert "try again later" in detail["message"]


class TestSubmitPreflight:
    def test_submit_returns_422_for_validation_errors_without_fabric_submit(self, client, mock_fablib):
        sid = _create_cross_site_fabnet_draft(client, "submit-preflight-cross-site")
        slice_obj = mock_fablib.get_slice(name="submit-preflight-cross-site")
        slice_obj.submit = MagicMock()

        with patch("app.routes.slices.get_fresh_sites", return_value=[]), \
             patch("app.routes.slices.resolve_sites", side_effect=lambda nodes, sites: (nodes, {})):
            submit = client.post(f"/api/slices/{sid}/submit")

        assert submit.status_code == 422
        detail = submit.json()["detail"]
        assert detail["code"] == "SLICE_VALIDATION_FAILED"
        assert detail["valid"] is False
        error_text = "\n".join(
            f"{issue['message']} {issue['remedy']}"
            for issue in detail["issues"]
            if issue["severity"] == "error"
        )
        assert "fabnet" in error_text.lower()
        assert "DALL" in error_text
        assert "WASH" in error_text
        assert "one FABNet service per site" in error_text
        slice_obj.submit.assert_not_called()

    def test_submit_returns_sanitized_fabric_submit_error(self, client, mock_fablib):
        sid, _ = _create_draft_with_node(client, "submit-honest-error")
        slice_obj = mock_fablib.get_slice(name="submit-honest-error")
        slice_obj.submit = MagicMock(
            side_effect=RuntimeError("FABRIC orchestrator unavailable: maintenance window")
        )

        with patch("app.routes.slices.get_fresh_sites", return_value=[]), \
             patch("app.routes.slices.resolve_sites", side_effect=lambda nodes, sites: (nodes, {})):
            submit = client.post(f"/api/slices/{sid}/submit")

        assert submit.status_code == 502
        detail = submit.json()["detail"]
        assert detail["code"] == "FABRIC_SUBMIT_FAILED"
        assert "orchestrator unavailable" in detail["message"]
        assert "An internal error occurred" not in detail["message"]
        slice_obj.submit.assert_called_once()


# ===========================================================================
# POST /slices/{name}/renew — requires submitted slice (mock FABlib)
# ===========================================================================

class TestRenewSlice:
    def test_renew_invalid_date(self, client):
        sid, _ = _create_draft_with_node(client, "renew-test")
        resp = client.post(f"/api/slices/{sid}/renew",
                           json={"end_date": "not-a-date"})
        assert resp.status_code == 400

    def test_renew_accepts_hours(self, client, mock_fablib):
        sid, _ = _create_draft_with_node(client, "renew-hours")

        resp = client.post(f"/api/slices/{sid}/renew", json={"hours": 6})

        assert resp.status_code == 200
        slice_obj = mock_fablib.get_slice(name="renew-hours")
        assert slice_obj.renew_kwargs["end_date"]
        assert slice_obj.renew_kwargs["days"] is None

    def test_renew_accepts_legacy_days(self, client, mock_fablib):
        _set_max_lease_hours(0)
        sid, _ = _create_draft_with_node(client, "renew-days")

        resp = client.post(f"/api/slices/{sid}/renew", json={"days": 1})

        assert resp.status_code == 200
        slice_obj = mock_fablib.get_slice(name="renew-days")
        assert slice_obj.renew_kwargs["days"] == 1

    def test_renew_caps_days_to_policy_hours(self, client, mock_fablib):
        _set_max_lease_hours(6)
        sid, _ = _create_draft_with_node(client, "renew-policy")

        resp = client.post(f"/api/slices/{sid}/renew", json={"days": 1})

        assert resp.status_code == 200
        slice_obj = mock_fablib.get_slice(name="renew-policy")
        assert slice_obj.renew_kwargs["end_date"]
        assert slice_obj.renew_kwargs["days"] is None

    def test_renew_down_returns_explicit_error(self, client, mock_fablib):
        _set_max_lease_hours(6)
        sid, _ = _create_draft_with_node(client, "renew-down")
        slice_obj = mock_fablib.get_slice(name="renew-down")
        slice_obj._lease_end = datetime.now(timezone.utc) + timedelta(hours=24)

        resp = client.post(f"/api/slices/{sid}/renew", json={"hours": 6})

        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["code"] == "LEASE_CANNOT_BE_SHORTENED"
        assert "cannot be shortened" in detail["message"]
        assert "delete and recreate" in detail["message"].lower()
        assert detail["current_lease_end"]
        assert detail["requested_lease_end"]
        assert slice_obj.renew_kwargs == {}

    def test_renew_nonexistent_slice(self, client):
        resp = client.post("/api/slices/nonexistent/renew",
                           json={"end_date": "2026-12-31T23:59:59Z"})
        assert resp.status_code in (404, 500)


class TestLeasePolicyWarnings:
    def test_list_slices_surfaces_over_policy_lease_warning(self, client, mock_fablib):
        _set_max_lease_hours(6)
        lease_end = datetime.now(timezone.utc) + timedelta(hours=24)
        mock_fablib._slices["over-policy"] = MockSlice(
            name="over-policy",
            slice_id="uuid-over-policy",
            state="StableOK",
            lease_end=lease_end,
        )

        resp = client.get("/api/slices?max_age=0")

        assert resp.status_code == 200
        row = next(item for item in resp.json() if item["name"] == "over-policy")
        assert row["lease_policy_violation"] is True
        warning = row["warnings"][0]
        assert warning["code"] == "LEASE_EXCEEDS_POLICY"
        assert warning["max_lease_hours"] == 6
        assert "delete and recreate" in warning["message"].lower()
