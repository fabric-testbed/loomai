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


def _as_agent(client):
    """Mark the test client's requests as agent-initiated (the cap only applies to agents)."""
    from app.request_actor import ACTOR_HEADER, AGENT
    client.headers[ACTOR_HEADER] = AGENT


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
        _as_agent(client)
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
        _as_agent(client)
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
        _as_agent(client)
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
        _as_agent(client)
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
        # Sub-day renewals bypass FABlib's whole-day renew() truncation.
        assert slice_obj.submitted_kwargs["lease_in_hours"] == 6
        assert slice_obj.renew_kwargs == {}

    def test_renew_accepts_legacy_days(self, client, mock_fablib):
        _set_max_lease_hours(0)
        sid, _ = _create_draft_with_node(client, "renew-days")

        resp = client.post(f"/api/slices/{sid}/renew", json={"days": 1})

        assert resp.status_code == 200
        slice_obj = mock_fablib.get_slice(name="renew-days")
        assert slice_obj.renew_kwargs["days"] == 1

    def test_renew_caps_days_to_policy_hours(self, client, mock_fablib):
        _set_max_lease_hours(6)
        _as_agent(client)
        sid, _ = _create_draft_with_node(client, "renew-policy")

        resp = client.post(f"/api/slices/{sid}/renew", json={"days": 1})

        assert resp.status_code == 200
        slice_obj = mock_fablib.get_slice(name="renew-policy")
        assert slice_obj.submitted_kwargs["lease_in_hours"] == 6
        assert slice_obj.renew_kwargs == {}

    def test_renew_keeps_full_days_when_under_policy_cap(self, client, mock_fablib):
        """A days request that fits the cap must reach FABlib as days, not a short lease."""
        _set_max_lease_hours(48)
        sid, _ = _create_draft_with_node(client, "renew-days-under-cap")

        resp = client.post(f"/api/slices/{sid}/renew", json={"days": 1})

        assert resp.status_code == 200
        slice_obj = mock_fablib.get_slice(name="renew-days-under-cap")
        assert slice_obj.renew_kwargs["days"] == 1

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
        assert slice_obj.submitted_kwargs == {}

    def test_renew_extends_lease_past_policy_cap_is_rejected_clearly(self, client, mock_fablib):
        """A far-future end_date on an over-cap lease must not become a shortening."""
        _set_max_lease_hours(6)
        _as_agent(client)
        sid, _ = _create_draft_with_node(client, "renew-over-policy")
        slice_obj = mock_fablib.get_slice(name="renew-over-policy")
        slice_obj._lease_end = datetime.now(timezone.utc) + timedelta(hours=24)

        far_future = (datetime.now(timezone.utc) + timedelta(days=19)).isoformat()
        resp = client.post(f"/api/slices/{sid}/renew", json={"end_date": far_future})

        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["code"] == "LEASE_ALREADY_EXCEEDS_POLICY"
        assert detail["max_lease_hours"] == 6
        assert detail["current_lease_end"]
        assert detail["max_allowed_lease_end"]
        assert slice_obj.renew_kwargs == {}
        assert slice_obj.submitted_kwargs == {}

    def test_renew_clamps_to_policy_when_lease_is_under_cap(self, client, mock_fablib):
        _set_max_lease_hours(6)
        _as_agent(client)
        sid, _ = _create_draft_with_node(client, "renew-under-cap")
        slice_obj = mock_fablib.get_slice(name="renew-under-cap")
        slice_obj._lease_end = datetime.now(timezone.utc) + timedelta(hours=2)

        far_future = (datetime.now(timezone.utc) + timedelta(days=19)).isoformat()
        resp = client.post(f"/api/slices/{sid}/renew", json={"end_date": far_future})

        assert resp.status_code == 200
        assert slice_obj.submitted_kwargs["lease_in_hours"] == 6
        codes = [w["code"] for w in resp.json().get("warnings", [])]
        assert "LEASE_CLAMPED_TO_POLICY" in codes

    def test_renew_explicit_end_date_does_not_overshoot(self, client, mock_fablib):
        """An explicit end date rounds down so an identical retry still extends."""
        _set_max_lease_hours(0)
        sid, _ = _create_draft_with_node(client, "renew-exact-end")
        slice_obj = mock_fablib.get_slice(name="renew-exact-end")
        slice_obj._lease_end = datetime.now(timezone.utc) + timedelta(hours=2)
        target = datetime.now(timezone.utc) + timedelta(hours=5, minutes=45)

        resp = client.post(f"/api/slices/{sid}/renew", json={"end_date": target.isoformat()})

        assert resp.status_code == 200
        assert slice_obj.submitted_kwargs["lease_in_hours"] == 5
        assert slice_obj.get_lease_end() <= target

        # The same request again must still read as an extension, not a shortening.
        resp = client.post(f"/api/slices/{sid}/renew", json={"end_date": target.isoformat()})
        assert resp.status_code == 200

    def test_renew_rounds_up_rather_than_shortening(self, client, mock_fablib):
        """Rounding down must not push the new end before the current lease end."""
        _set_max_lease_hours(0)
        sid, _ = _create_draft_with_node(client, "renew-round-up")
        slice_obj = mock_fablib.get_slice(name="renew-round-up")
        slice_obj._lease_end = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
        target = datetime.now(timezone.utc) + timedelta(hours=5, minutes=45)

        resp = client.post(f"/api/slices/{sid}/renew", json={"end_date": target.isoformat()})

        assert resp.status_code == 200
        # Flooring to 5h would end before the current 5h30m lease, so use 6h.
        assert slice_obj.submitted_kwargs["lease_in_hours"] == 6

    def test_renew_within_rounding_band_leaves_lease_untouched(self, client, mock_fablib):
        """Inside the whole-hour rounding band the lease must not move either way."""
        _set_max_lease_hours(0)
        sid, _ = _create_draft_with_node(client, "renew-short-by-minutes")
        slice_obj = mock_fablib.get_slice(name="renew-short-by-minutes")
        lease_end = datetime.now(timezone.utc) + timedelta(hours=10)
        slice_obj._lease_end = lease_end
        target = datetime.now(timezone.utc) + timedelta(hours=9, minutes=30)

        resp = client.post(f"/api/slices/{sid}/renew", json={"end_date": target.isoformat()})

        assert resp.status_code == 200
        body = resp.json()
        assert body["lease_unchanged"] is True
        assert "LEASE_ALREADY_COVERS_REQUEST" in [w["code"] for w in body["warnings"]]
        # Neither extended nor shortened.
        assert slice_obj.renew_kwargs == {}
        assert slice_obj.submitted_kwargs == {}
        assert slice_obj.get_lease_end() == lease_end

    def test_renew_retry_of_successful_renewal_succeeds(self, client, mock_fablib):
        """Re-sending an end date the previous renewal already covered must not fail."""
        _set_max_lease_hours(0)
        sid, _ = _create_draft_with_node(client, "renew-retry")
        slice_obj = mock_fablib.get_slice(name="renew-retry")
        slice_obj._lease_end = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
        # Needs 6h to cover it, so the granted lease overshoots the request.
        target = datetime.now(timezone.utc) + timedelta(hours=5, minutes=45)
        payload = {"end_date": target.isoformat()}

        first = client.post(f"/api/slices/{sid}/renew", json=payload)
        assert first.status_code == 200
        assert slice_obj.submitted_kwargs["lease_in_hours"] == 6
        granted = slice_obj.get_lease_end()

        second = client.post(f"/api/slices/{sid}/renew", json=payload)

        assert second.status_code == 200
        assert second.json()["lease_unchanged"] is True
        assert slice_obj.get_lease_end() == granted

    def test_renew_nonexistent_slice(self, client):
        resp = client.post("/api/slices/nonexistent/renew",
                           json={"end_date": "2026-12-31T23:59:59Z"})
        assert resp.status_code in (404, 500)


class TestLeasePolicyWarnings:
    def test_list_slices_surfaces_over_policy_lease_warning(self, client, mock_fablib):
        _set_max_lease_hours(6)
        _as_agent(client)
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

    def test_slice_payload_exposes_cap_for_compliant_lease(self, client, mock_fablib):
        _set_max_lease_hours(6)
        _as_agent(client)
        mock_fablib._slices["compliant"] = MockSlice(
            name="compliant",
            slice_id="uuid-compliant",
            state="StableOK",
            lease_end=datetime.now(timezone.utc) + timedelta(hours=2),
        )

        resp = client.get("/api/slices?max_age=0")

        assert resp.status_code == 200
        row = next(item for item in resp.json() if item["name"] == "compliant")
        assert row["max_lease_hours"] == 6
        assert "lease_policy_violation" not in row

    def test_slice_payload_omits_cap_when_disabled(self, client, mock_fablib):
        _set_max_lease_hours(0)
        mock_fablib._slices["uncapped"] = MockSlice(
            name="uncapped",
            slice_id="uuid-uncapped",
            state="StableOK",
            lease_end=datetime.now(timezone.utc) + timedelta(hours=48),
        )

        resp = client.get("/api/slices?max_age=0")

        assert resp.status_code == 200
        row = next(item for item in resp.json() if item["name"] == "uncapped")
        assert "max_lease_hours" not in row


class TestAgentOnlyLeaseCap:
    """The lease cap applies to agent-initiated requests only; people use FABRIC's limits."""

    def test_user_submit_is_not_capped(self, client, mock_fablib):
        _set_max_lease_hours(6)
        sid, _ = _create_draft_with_node(client, "user-submit-uncapped")

        with patch("app.routes.slices.get_fresh_sites", return_value=[]), \
             patch("app.routes.slices.resolve_sites", side_effect=lambda nodes, sites: (nodes, {})):
            submit = client.post(f"/api/slices/{sid}/submit", json={"lease_hours": 24})

        assert submit.status_code == 200
        slice_obj = mock_fablib.get_slice(name="user-submit-uncapped")
        assert slice_obj.submitted_kwargs["lease_in_hours"] == 24
        assert not submit.json().get("warnings")

    def test_user_renew_past_cap_succeeds(self, client, mock_fablib):
        _set_max_lease_hours(6)
        sid, _ = _create_draft_with_node(client, "user-renew-uncapped")
        slice_obj = mock_fablib.get_slice(name="user-renew-uncapped")
        slice_obj._lease_end = datetime.now(timezone.utc) + timedelta(hours=24)

        target = datetime.now(timezone.utc) + timedelta(hours=48, minutes=30)
        resp = client.post(f"/api/slices/{sid}/renew", json={"end_date": target.isoformat()})

        assert resp.status_code == 200
        assert slice_obj.submitted_kwargs["lease_in_hours"] == 48
        assert "max_lease_hours" not in resp.json()

    def test_user_slice_payload_has_no_cap_fields(self, client, mock_fablib):
        _set_max_lease_hours(6)
        mock_fablib._slices["user-long"] = MockSlice(
            name="user-long",
            slice_id="uuid-user-long",
            state="StableOK",
            lease_end=datetime.now(timezone.utc) + timedelta(hours=24),
        )

        resp = client.get("/api/slices?max_age=0")

        assert resp.status_code == 200
        row = next(item for item in resp.json() if item["name"] == "user-long")
        assert "max_lease_hours" not in row
        assert "lease_policy_violation" not in row

    def test_chat_tool_renew_is_capped(self, client, mock_fablib):
        import asyncio
        from app.routes.ai_chat import execute_tool

        _set_max_lease_hours(6)
        _create_draft_with_node(client, "chat-renew-capped")
        slice_obj = mock_fablib.get_slice(name="chat-renew-capped")
        slice_obj._lease_end = datetime.now(timezone.utc) + timedelta(hours=2)

        result = json.loads(asyncio.run(
            execute_tool("renew_slice", {"slice_name": "chat-renew-capped", "hours": 24})
        ))

        assert slice_obj.submitted_kwargs["lease_in_hours"] == 6
        assert "LEASE_CLAMPED_TO_POLICY" in [w["code"] for w in result.get("warnings", [])]

    def test_cached_slice_list_is_annotated_per_caller(self, client, mock_fablib):
        """One caller's lease-policy view must not leak to the next via the list cache."""
        from app.request_actor import ACTOR_HEADER, AGENT

        _set_max_lease_hours(6)
        mock_fablib._slices["cached-long"] = MockSlice(
            name="cached-long",
            slice_id="uuid-cached-long",
            state="StableOK",
            lease_end=datetime.now(timezone.utc) + timedelta(hours=24),
        )

        def row(headers=None, max_age=30):
            resp = client.get(f"/api/slices?max_age={max_age}", headers=headers or {})
            assert resp.status_code == 200
            return next(item for item in resp.json() if item["name"] == "cached-long")

        # Agent populates the cache, then a person reads it.
        agent_row = row({ACTOR_HEADER: AGENT}, max_age=0)
        assert agent_row["max_lease_hours"] == 6
        assert agent_row["lease_policy_violation"] is True
        user_row = row()
        assert "max_lease_hours" not in user_row
        assert "lease_policy_violation" not in user_row

        # Person populates the cache, then an agent reads it.
        assert "max_lease_hours" not in row(max_age=0)
        assert row({ACTOR_HEADER: AGENT})["lease_policy_violation"] is True


class TestNoSliceWorkdirs:
    def test_create_and_view_do_not_create_storage_folders(self, client, storage_dir, mock_fablib):
        sid, _ = _create_draft_with_node(client, "no-workdir-slice")
        mock_fablib._slices["no-workdir-live"] = MockSlice(
            name="no-workdir-live", slice_id="uuid-no-workdir", state="StableOK",
            lease_end=datetime.now(timezone.utc) + timedelta(hours=2),
        )

        assert client.get(f"/api/slices/{sid}").status_code == 200
        assert client.get("/api/slices/no-workdir-live?max_age=0").status_code == 200

        assert not (storage_dir / "no-workdir-slice").exists()
        assert not (storage_dir / "no-workdir-live").exists()


class TestSliceConcurrencyGuards:
    def _live(self, mock_fablib, name, uuid):
        mock_fablib._slices[name] = MockSlice(
            name=name, slice_id=uuid, state="StableOK",
            lease_end=datetime.now(timezone.utc) + timedelta(hours=2),
        )
        return mock_fablib._slices[name]

    def test_get_slice_keeps_unsubmitted_edits_on_loaded_slice(self, client, mock_fablib):
        self._live(mock_fablib, "live-edit", "uuid-live-edit")
        assert client.get("/api/slices/live-edit").status_code == 200   # loads as draft
        add = client.post("/api/slices/live-edit/nodes", json={"name": "n-new", "site": "RENC"})
        assert add.status_code == 200 and add.json()["dirty"] is True

        got = client.get("/api/slices/live-edit")   # used to refetch and drop the edit

        assert got.status_code == 200
        assert got.json()["dirty"] is True
        assert "n-new" in [n["name"] for n in got.json()["nodes"]]

    def test_refresh_discards_unsubmitted_edits(self, client, mock_fablib):
        from app.routes import slices as slices_mod
        self._live(mock_fablib, "live-refresh", "uuid-live-refresh")
        client.get("/api/slices/live-refresh")
        client.post("/api/slices/live-refresh/nodes", json={"name": "tmp", "site": "RENC"})
        assert "live-refresh" in slices_mod._draft_dirty

        assert client.post("/api/slices/live-refresh/refresh").status_code == 200
        assert "live-refresh" not in slices_mod._draft_dirty

    def test_delete_uses_fabric_when_registry_has_real_uuid(self, client, mock_fablib):
        from app.routes import slices as slices_mod
        from app.slice_registry import register_slice, get_slice_uuid
        live = self._live(mock_fablib, "live-del", "uuid-live-del")
        register_slice("live-del", uuid="uuid-live-del", state="StableOK")
        # A stale "new" draft of the same name (the resurrection bug's residue).
        slices_mod._store_draft("live-del", MockSlice(name="live-del"), is_new=True)

        resp = client.delete("/api/slices/uuid-live-del")

        assert resp.status_code == 200
        assert live._state == "Dead"                 # FABRIC delete happened
        assert get_slice_uuid("live-del") == "uuid-live-del"

    def test_delete_blocked_while_submit_in_progress(self, client):
        from app.routes import slices as slices_mod
        with slices_mod._draft_lock:
            slices_mod._submitting["sub-del"] = {"name": "sub-del", "state": "Submitting"}
        try:
            resp = client.delete("/api/slices/sub-del")
        finally:
            slices_mod._end_submit("sub-del")
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "SLICE_SUBMIT_IN_PROGRESS"

    def test_get_and_list_show_submitting_snapshot(self, client):
        from app.routes import slices as slices_mod
        snap = {"name": "sub-get", "id": "draft-sg", "state": "Submitting", "dirty": False,
                "nodes": [{"name": "n1"}], "networks": [], "facility_ports": [],
                "port_mirrors": [], "error_messages": [], "graph": {"nodes": [], "edges": []}}
        with slices_mod._draft_lock:
            slices_mod._submitting["sub-get"] = snap
        try:
            got = client.get("/api/slices/sub-get")
            listed = client.get("/api/slices?max_age=0")
        finally:
            slices_mod._end_submit("sub-get")
        assert got.status_code == 200 and got.json()["state"] == "Submitting"
        row = next(r for r in listed.json() if r["name"] == "sub-get")
        assert row["state"] == "Submitting"

    def test_reconcile_projects_leaves_env_and_fablib_project_untouched(self, client, mock_fablib):
        import os
        from app.routes import slices as slices_mod
        original = os.environ.get("FABRIC_PROJECT_ID", "")
        mgr = mock_fablib.get_manager()
        projects = [{"uuid": "proj-a", "name": "A"}, {"uuid": "proj-b", "name": "B"}]
        with patch.object(mgr, "get_project_info", return_value=projects, create=True):
            resp = client.post("/api/slices/reconcile-projects")

        assert resp.status_code == 200
        assert resp.json()["projects_scanned"] == 2
        assert os.environ.get("FABRIC_PROJECT_ID", "") == original
        assert mock_fablib.get_project_id() == original
        assert slices_mod._reconcile_idle.is_set()
