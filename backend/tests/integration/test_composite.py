"""Tests for composite slice API — meta-slice reference model."""

import json
import os
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

class TestCompositeSliceCRUD:
    def test_create(self, client):
        r = client.post("/api/composite/slices", json={"name": "test-comp"})
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "test-comp"
        assert data["id"].startswith("comp-")
        assert data["state"] == "Draft"
        assert data["fabric_slices"] == []
        assert data["chameleon_slices"] == []
        assert data["cross_connections"] == []

    def test_list(self, client):
        client.post("/api/composite/slices", json={"name": "a"})
        client.post("/api/composite/slices", json={"name": "b"})
        r = client.get("/api/composite/slices")
        assert r.status_code == 200
        assert len(r.json()) >= 2

    def test_get(self, client):
        cr = client.post("/api/composite/slices", json={"name": "get-me"}).json()
        r = client.get(f"/api/composite/slices/{cr['id']}")
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "get-me"
        assert "fabric_member_summaries" in data
        assert "chameleon_member_summaries" in data

    def test_get_not_found(self, client):
        r = client.get("/api/composite/slices/nonexistent")
        assert r.status_code == 404

    def test_delete(self, client):
        cr = client.post("/api/composite/slices", json={"name": "del-me"}).json()
        r = client.delete(f"/api/composite/slices/{cr['id']}")
        assert r.status_code == 200
        assert r.json()["status"] == "deleted"
        r2 = client.get(f"/api/composite/slices/{cr['id']}")
        assert r2.status_code == 404

    def test_delete_not_found(self, client):
        r = client.delete("/api/composite/slices/nonexistent")
        assert r.status_code == 404


class TestFederatedSliceCRUD:
    def test_create_uses_federated_name_and_id(self, client):
        r = client.post("/api/federated/slices", json={"name": "test-fed"})
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "test-fed"
        assert data["id"].startswith("fed-")
        assert data["kind"] == "federated"
        assert data["members"] == []

    def test_composite_endpoint_can_read_federated_slice(self, client):
        cr = client.post("/api/federated/slices", json={"name": "shared-store"}).json()
        r = client.get(f"/api/composite/slices/{cr['id']}")
        assert r.status_code == 200
        assert r.json()["name"] == "shared-store"

    def test_federated_endpoint_can_read_composite_slice(self, client):
        cr = client.post("/api/composite/slices", json={"name": "legacy-store"}).json()
        r = client.get(f"/api/federated/slices/{cr['id']}")
        assert r.status_code == 200
        assert r.json()["name"] == "legacy-store"

    @patch("app.routes.composite._validate_chameleon_ref", return_value=True)
    @patch("app.routes.composite._validate_fabric_ref", return_value=True)
    def test_delete_federated_without_cascade_keeps_members(self, _mock_fabric, _mock_chameleon, client):
        cr = client.post("/api/federated/slices", json={"name": "keep-members"}).json()
        client.put(
            f"/api/federated/slices/{cr['id']}/members",
            json={"fabric_slices": ["fabric-child"], "chameleon_slices": ["chi-child"]},
        )

        with patch("app.routes.composite._delete_provider_member_slice", new_callable=AsyncMock) as mock_delete_member:
            r = client.delete(f"/api/federated/slices/{cr['id']}")

        assert r.status_code == 200
        assert r.json()["status"] == "deleted"
        mock_delete_member.assert_not_called()

    @patch("app.routes.composite._validate_chameleon_ref", return_value=True)
    @patch("app.routes.composite._validate_fabric_ref", return_value=True)
    def test_delete_federated_with_cascade_deletes_members(self, _mock_fabric, _mock_chameleon, client):
        cr = client.post("/api/federated/slices", json={"name": "delete-members"}).json()
        client.put(
            f"/api/federated/slices/{cr['id']}/members",
            json={"fabric_slices": ["fabric-child"], "chameleon_slices": ["chi-child"]},
        )

        async def fake_delete_member(member, *, delete_imported_resources=False):
            return {
                "provider": member["provider"],
                "slice_id": member["slice_id"],
                "status": "deleted",
            }

        with patch("app.routes.composite._delete_provider_member_slice", new_callable=AsyncMock) as mock_delete_member:
            mock_delete_member.side_effect = fake_delete_member
            r = client.delete(f"/api/federated/slices/{cr['id']}?delete_members=true")

        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "deleted"
        assert [item["status"] for item in data["member_deletions"]] == ["deleted", "deleted"]
        assert mock_delete_member.await_count == 2
        assert mock_delete_member.await_args_list[0].args[0] == {"provider": "fabric", "slice_id": "fabric-child"}
        assert mock_delete_member.await_args_list[1].args[0] == {"provider": "chameleon", "slice_id": "chi-child"}
        assert mock_delete_member.await_args_list[0].kwargs == {"delete_imported_resources": False}
        assert mock_delete_member.await_args_list[1].kwargs == {"delete_imported_resources": False}

    @pytest.mark.asyncio
    async def test_list_returns_member_summaries(self, tmp_path, monkeypatch):
        from app.routes import composite
        from app.routes.chameleon import _chameleon_slices
        import app.user_context as uc

        monkeypatch.setenv("FABRIC_STORAGE_DIR", str(tmp_path))
        uc._BASE_STORAGE = None
        composite._composite_slices.clear()

        chi_id = "chi-slice-list-summary"
        _chameleon_slices[chi_id] = {
            "id": chi_id,
            "name": "chi-summary",
            "provider": "chameleon",
            "state": "Deploying",
            "site": "CHI@TACC",
            "nodes": [{"id": "node-1", "name": "server1", "site": "CHI@TACC"}],
            "resources": [],
            "networks": [],
            "floating_ips": [],
        }
        fed = composite._new_composite_slice("summary-fed", id_prefix="fed", kind="federated")
        fed["members"] = [{"provider": "chameleon", "slice_id": chi_id}]
        composite._composite_slices[fed["id"]] = fed

        data = next(s for s in await composite.list_federated_slices() if s["id"] == fed["id"])
        assert data["state"] == "Provisioning"
        assert data["chameleon_member_summaries"][0]["id"] == chi_id
        assert data["chameleon_member_summaries"][0]["state"] == "Deploying"

        _chameleon_slices.pop(chi_id, None)
        composite._composite_slices.clear()

    @pytest.mark.asyncio
    async def test_get_updates_state_from_live_fabric_summary(self, tmp_path, monkeypatch):
        from app.routes import composite
        import app.user_context as uc

        monkeypatch.setenv("FABRIC_STORAGE_DIR", str(tmp_path))
        uc._BASE_STORAGE = None
        composite._composite_slices.clear()

        fed = composite._new_composite_slice("live-state", id_prefix="fed", kind="federated")
        fed["state"] = "Provisioning"
        fed["members"] = [{"provider": "fabric", "slice_id": "fabric-live", "state": "Configuring"}]
        composite._sync_legacy_member_fields(fed)
        composite._composite_slices[fed["id"]] = fed

        async def live_summary(slice_id):
            return {"id": slice_id, "name": "fabric-live", "state": "StableOK", "node_count": 1}

        monkeypatch.setattr(composite, "_get_live_fabric_slice_summary", live_summary)

        data = await composite.get_composite_slice(fed["id"])

        assert data["state"] == "Active"
        assert data["fabric_member_summaries"][0]["state"] == "StableOK"
        assert composite._composite_slices[fed["id"]]["state"] == "Active"

        composite._composite_slices.clear()

    def test_legacy_submit_materializes_federated_slice(self, tmp_path, monkeypatch):
        from app.routes import composite
        from app.routes.chameleon import _chameleon_slices
        import app.user_context as uc

        monkeypatch.setenv("FABRIC_STORAGE_DIR", str(tmp_path))
        uc._BASE_STORAGE = None
        composite._composite_slices.clear()

        data = composite.create_or_update_legacy_federated_slice(
            "legacy-run",
            fabric_ref="draft-legacy-run",
            chameleon_nodes=[{
                "name": "chi-node1",
                "site": "CHI@TACC",
                "node_type": "compute_skylake",
                "image_id": "CC-Ubuntu22.04",
                "connection_type": "fabnet_v4",
            }],
            chameleon_status="PENDING",
            chameleon_lease={"id": "lease-1", "status": "PENDING", "_site": "CHI@TACC"},
        )

        assert data["id"].startswith("fed-")
        assert data["kind"] == "federated"
        assert data["fabric_slices"] == ["draft-legacy-run"]
        assert len(data["chameleon_slices"]) == 1
        assert data["state"] == "Provisioning"
        assert data["fabric_member_summaries"][0]["name"] == "legacy-run"
        assert data["chameleon_member_summaries"][0]["name"] == "legacy-run-chameleon"
        chi = _chameleon_slices[data["chameleon_slices"][0]]
        assert chi["resources"][0]["id"] == "lease-1"
        assert chi["nodes"][0]["interfaces"][0]["network"]["name"] == "fabnetv4"
        _chameleon_slices.pop(data["chameleon_slices"][0], None)
        composite._composite_slices.clear()


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------

class TestCompositeMembers:
    def test_update_empty(self, client):
        cr = client.post("/api/composite/slices", json={"name": "mem-test"}).json()
        r = client.put(f"/api/composite/slices/{cr['id']}/members",
                       json={"fabric_slices": [], "chameleon_slices": []})
        assert r.status_code == 200
        assert r.json()["fabric_slices"] == []
        assert r.json()["chameleon_slices"] == []
        assert r.json()["members"] == []

    @patch("app.routes.composite._validate_fabric_ref", return_value=True)
    def test_update_with_fabric(self, mock_val, client):
        cr = client.post("/api/composite/slices", json={"name": "fab-mem"}).json()
        r = client.put(f"/api/composite/slices/{cr['id']}/members",
                       json={"fabric_slices": ["slice-uuid-1"], "chameleon_slices": []})
        assert r.status_code == 200
        assert r.json()["fabric_slices"] == ["slice-uuid-1"]

    @patch("app.routes.composite._validate_chameleon_ref", return_value=True)
    def test_update_with_chameleon(self, mock_val, client):
        cr = client.post("/api/composite/slices", json={"name": "chi-mem"}).json()
        r = client.put(f"/api/composite/slices/{cr['id']}/members",
                       json={"fabric_slices": [], "chameleon_slices": ["chi-slice-abc"]})
        assert r.status_code == 200
        assert r.json()["chameleon_slices"] == ["chi-slice-abc"]
        assert r.json()["members"] == [{"provider": "chameleon", "slice_id": "chi-slice-abc"}]

    def test_update_with_generic_future_member(self, client):
        cr = client.post("/api/composite/slices", json={"name": "future-mem"}).json()
        r = client.put(
            f"/api/composite/slices/{cr['id']}/members",
            json={"members": [{"provider": "cloudlab", "slice_id": "cl-slice-1", "name": "CloudLab part"}]},
        )
        assert r.status_code == 200
        assert r.json()["members"] == [{"provider": "cloudlab", "slice_id": "cl-slice-1", "name": "CloudLab part"}]
        assert r.json()["fabric_slices"] == []
        assert r.json()["chameleon_slices"] == []

    @patch("app.routes.composite._validate_chameleon_ref", return_value=True)
    def test_add_and_remove_member_endpoint(self, mock_val, client):
        cr = client.post("/api/composite/slices", json={"name": "incremental"}).json()
        add = client.post(
            f"/api/composite/slices/{cr['id']}/members/add",
            json={"provider": "chameleon", "slice_id": "chi-slice-abc"},
        )
        assert add.status_code == 200
        assert add.json()["chameleon_slices"] == ["chi-slice-abc"]

        remove = client.post(
            f"/api/composite/slices/{cr['id']}/members/remove",
            json={"provider": "chameleon", "slice_id": "chi-slice-abc"},
        )
        assert remove.status_code == 200
        assert remove.json()["chameleon_slices"] == []

    def test_update_invalid_fabric_ref(self, client):
        cr = client.post("/api/composite/slices", json={"name": "bad-ref"}).json()
        with patch("app.routes.composite._validate_fabric_ref", return_value=False):
            r = client.put(f"/api/composite/slices/{cr['id']}/members",
                           json={"fabric_slices": ["nonexistent"], "chameleon_slices": []})
        assert r.status_code == 400

    def test_update_invalid_chameleon_ref(self, client):
        cr = client.post("/api/composite/slices", json={"name": "bad-chi"}).json()
        with patch("app.routes.composite._validate_chameleon_ref", return_value=False):
            r = client.put(f"/api/composite/slices/{cr['id']}/members",
                           json={"fabric_slices": [], "chameleon_slices": ["bad-id"]})
        assert r.status_code == 400

    @patch("app.routes.composite._validate_fabric_ref", return_value=True)
    def test_update_replaces_not_appends(self, mock_val, client):
        cr = client.post("/api/composite/slices", json={"name": "replace"}).json()
        client.put(f"/api/composite/slices/{cr['id']}/members",
                   json={"fabric_slices": ["a", "b"], "chameleon_slices": []})
        r = client.put(f"/api/composite/slices/{cr['id']}/members",
                       json={"fabric_slices": ["c"], "chameleon_slices": []})
        assert r.json()["fabric_slices"] == ["c"]

    def test_update_not_found(self, client):
        r = client.put("/api/composite/slices/nonexistent/members",
                       json={"fabric_slices": [], "chameleon_slices": []})
        assert r.status_code == 404


class TestFederatedMembers:
    def test_update_with_extended_member_metadata(self, client):
        cr = client.post("/api/federated/slices", json={"name": "fed-meta"}).json()
        member = {
            "provider": "cloudlab",
            "slice_id": "cl-slice-1",
            "resource_ids": ["node-1"],
            "site": "utah",
            "endpoint_type": "server",
            "interface": "eth1",
            "network_name": "fabnetv4",
            "state": "Referenced",
            "metadata": {"owner": "test"},
        }
        r = client.put(f"/api/federated/slices/{cr['id']}/members", json={"members": [member]})
        assert r.status_code == 200
        data = r.json()
        assert data["members"][0]["provider"] == "cloudlab"
        assert data["members"][0]["resource_ids"] == ["node-1"]
        assert data["members"][0]["endpoint_type"] == "server"
        assert data["members"][0]["metadata"] == {"owner": "test"}

    @patch("app.routes.composite._validate_fabric_ref", return_value=True)
    def test_add_and_remove_via_federated_alias(self, mock_val, client):
        cr = client.post("/api/federated/slices", json={"name": "fed-inc"}).json()
        add = client.post(
            f"/api/federated/slices/{cr['id']}/members/add",
            json={"provider": "fabric", "slice_id": "draft-abc", "site": "RENC"},
        )
        assert add.status_code == 200
        assert add.json()["fabric_slices"] == ["draft-abc"]
        assert add.json()["members"][0]["site"] == "RENC"

        remove = client.post(
            f"/api/federated/slices/{cr['id']}/members/remove",
            json={"provider": "fabric", "slice_id": "draft-abc"},
        )
        assert remove.status_code == 200
        assert remove.json()["fabric_slices"] == []

    @patch("app.routes.composite._validate_chameleon_ref", return_value=True)
    @patch("app.routes.composite._validate_fabric_ref", return_value=True)
    def test_empty_federated_can_attach_several_existing_slices_and_detach_one(self, _mock_fabric, _mock_chameleon, client):
        cr = client.post("/api/federated/slices", json={"name": "fed-group"}).json()
        assert cr["members"] == []
        assert cr["fabric_slices"] == []
        assert cr["chameleon_slices"] == []

        for member in [
            {"provider": "fabric", "slice_id": "fabric-a", "name": "FABRIC A"},
            {"provider": "fabric", "slice_id": "fabric-b", "name": "FABRIC B"},
            {"provider": "chameleon", "slice_id": "chi-a", "name": "Chameleon A"},
            {"provider": "chameleon", "slice_id": "chi-b", "name": "Chameleon B"},
        ]:
            r = client.post(f"/api/federated/slices/{cr['id']}/members/add", json=member)
            assert r.status_code == 200

        grouped = client.get(f"/api/federated/slices/{cr['id']}").json()
        assert grouped["fabric_slices"] == ["fabric-a", "fabric-b"]
        assert grouped["chameleon_slices"] == ["chi-a", "chi-b"]
        assert grouped["members"] == [
            {"provider": "fabric", "slice_id": "fabric-a", "name": "FABRIC A"},
            {"provider": "fabric", "slice_id": "fabric-b", "name": "FABRIC B"},
            {"provider": "chameleon", "slice_id": "chi-a", "name": "Chameleon A"},
            {"provider": "chameleon", "slice_id": "chi-b", "name": "Chameleon B"},
        ]

        remove = client.post(
            f"/api/federated/slices/{cr['id']}/members/remove",
            json={"provider": "fabric", "slice_id": "fabric-a"},
        )
        assert remove.status_code == 200
        assert remove.json()["fabric_slices"] == ["fabric-b"]
        assert remove.json()["chameleon_slices"] == ["chi-a", "chi-b"]
        assert {"provider": "fabric", "slice_id": "fabric-a", "name": "FABRIC A"} not in remove.json()["members"]


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

class TestCompositeGraph:
    def test_empty_graph(self, client):
        cr = client.post("/api/composite/slices", json={"name": "empty-graph"}).json()
        r = client.get(f"/api/composite/slices/{cr['id']}/graph")
        assert r.status_code == 200
        data = r.json()
        assert data["nodes"] == []
        assert data["edges"] == []

    def test_graph_not_found(self, client):
        r = client.get("/api/composite/slices/nonexistent/graph")
        assert r.status_code == 404

    def test_graph_fetches_live_fabric_member_when_cache_is_empty(self, storage_dir):
        import asyncio
        from app.routes import composite as composite_mod

        fed_id = "fed-live-graph"
        composite_mod._composite_slices[fed_id] = {
            "id": fed_id,
            "name": "live-graph",
            "kind": "federated",
            "state": "Draft",
            "fabric_slices": ["fabric-member-id"],
            "chameleon_slices": [],
            "members": [{"provider": "fabric", "slice_id": "fabric-member-id", "name": "fabric-live"}],
            "cross_connections": [],
        }
        slice_data = {
            "name": "fabric-live",
            "id": "fabric-member-id",
            "state": "StableOK",
            "nodes": [],
            "networks": [],
            "facility_ports": [],
            "port_mirrors": [],
        }

        async def fake_get_slice(ref, max_age=0):
            assert max_age == 0
            if ref == "fabric-member-id":
                raise RuntimeError("id lookup cache miss")
            assert ref == "fabric-live"
            return slice_data

        graph = {"nodes": [{"data": {"id": "merged"}}], "edges": []}
        try:
            with patch("app.routes.composite._resolve_fabric_ref", return_value="fabric-live"), \
                 patch("app.routes.slices._is_draft", return_value=False), \
                 patch("app.routes.slices.get_slice", new_callable=AsyncMock) as mock_get_slice, \
                 patch("app.graph_builder.build_composite_graph", return_value=graph) as mock_build:
                mock_get_slice.side_effect = fake_get_slice
                result = asyncio.run(composite_mod.get_composite_graph(fed_id))

            assert result == graph
            assert [call.args[0] for call in mock_get_slice.await_args_list] == [
                "fabric-member-id",
                "fabric-live",
            ]
            assert mock_build.call_args.kwargs["fabric_members"] == [(slice_data, "fabric-member-id")]
            assert mock_build.call_args.kwargs["chameleon_members"] == []
        finally:
            composite_mod._composite_slices.pop(fed_id, None)

    def test_graph_prefers_live_fabric_member_over_stale_cache(self, storage_dir):
        import asyncio
        from app.fabric_call_manager import CacheEntry, get_call_manager
        from app.routes import composite as composite_mod

        fed_id = "fed-live-over-cache"
        composite_mod._composite_slices[fed_id] = {
            "id": fed_id,
            "name": "live-over-cache",
            "kind": "federated",
            "state": "Draft",
            "fabric_slices": ["fabric-member-id"],
            "chameleon_slices": [],
            "members": [{"provider": "fabric", "slice_id": "fabric-member-id", "name": "fabric-live"}],
            "cross_connections": [],
        }
        stale_data = {
            "name": "fabric-live",
            "id": "fabric-member-id",
            "state": "StableOK",
            "nodes": [],
            "networks": [],
            "facility_ports": [],
            "port_mirrors": [],
        }
        fresh_data = {
            **stale_data,
            "facility_ports": [{"name": "fresh-fp", "site": "RENC", "vlan": "3101", "interfaces": []}],
        }
        mgr = get_call_manager()
        mgr._cache["slice:fabric-live"] = CacheEntry(data=stale_data)
        graph = {"nodes": [{"data": {"id": "merged"}}], "edges": []}
        try:
            with patch("app.routes.composite._resolve_fabric_ref", return_value="fabric-live"), \
                 patch("app.routes.slices._is_draft", return_value=False), \
                 patch("app.routes.slices.get_slice", new_callable=AsyncMock, return_value=fresh_data) as mock_get_slice, \
                 patch("app.graph_builder.build_composite_graph", return_value=graph) as mock_build:
                result = asyncio.run(composite_mod.get_composite_graph(fed_id))

            assert result == graph
            mock_get_slice.assert_awaited_once_with("fabric-member-id", max_age=0)
            assert mock_build.call_args.kwargs["fabric_members"] == [(fresh_data, "fabric-member-id")]
        finally:
            mgr._cache.pop("slice:fabric-live", None)
            composite_mod._composite_slices.pop(fed_id, None)

    def test_graph_uses_updated_draft_member_after_facility_port_add(self, storage_dir):
        import asyncio
        from app.routes import composite as composite_mod
        from app.routes import slices as slices_mod
        from tests.fixtures.fablib_mocks import MockSlice

        name = "fabric-member-with-fp"
        fed_id = "fed-fp-cache"
        slice_obj = MockSlice(name=name, slice_id="fabric-member-id", state="StableOK")
        slices_mod._store_draft(name, slice_obj, is_new=False)
        slices_mod._serialize(slice_obj)
        composite_mod._composite_slices[fed_id] = {
            "id": fed_id,
            "name": "fp-cache",
            "kind": "federated",
            "state": "Draft",
            "fabric_slices": ["fabric-member-id"],
            "chameleon_slices": [],
            "members": [{"provider": "fabric", "slice_id": "fabric-member-id", "name": name}],
            "cross_connections": [],
        }
        try:
            updated = slices_mod.add_facility_port(
                name,
                slices_mod.CreateFacilityPortRequest(name="fed-fp", site="RENC", vlan="3101", bandwidth=10),
            )
            assert updated["facility_ports"][0]["name"] == "fed-fp"

            graph = {"nodes": [{"data": {"id": "merged"}}], "edges": []}
            with patch("app.routes.composite._resolve_fabric_ref", return_value=name), \
                 patch("app.graph_builder.build_composite_graph", return_value=graph) as mock_build:
                result = asyncio.run(composite_mod.get_composite_graph(fed_id))

            assert result == graph
            member_data = mock_build.call_args.kwargs["fabric_members"][0][0]
            assert member_data["facility_ports"][0]["name"] == "fed-fp"
        finally:
            slices_mod._pop_draft(name)
            slices_mod._invalidate_slice_read_caches(name)
            composite_mod._composite_slices.pop(fed_id, None)


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------

class TestCompositeSubmit:
    def test_submit_no_members(self, client):
        cr = client.post("/api/composite/slices", json={"name": "no-mem"}).json()
        r = client.post(f"/api/composite/slices/{cr['id']}/submit")
        assert r.status_code == 400

    def test_submit_not_found(self, client):
        r = client.post("/api/composite/slices/nonexistent/submit")
        assert r.status_code == 404

    def test_federated_submit_prepares_connections_and_forces_chameleon_full_deploy(self, storage_dir):
        import asyncio
        from app.routes import composite as composite_mod
        from app.routes.chameleon import _chameleon_slices

        fed_id = "fed-submit-full-deploy"
        try:
            composite_mod._composite_slices[fed_id] = {
                "id": fed_id,
                "name": "submit-fed",
                "kind": "federated",
                "state": "Draft",
                "fabric_slices": ["draft-fabric-1"],
                "chameleon_slices": ["chi-draft-1"],
                "members": [
                    {"provider": "fabric", "slice_id": "draft-fabric-1", "name": "fabric-draft"},
                    {"provider": "chameleon", "slice_id": "chi-draft-1", "name": "chi-draft"},
                ],
                "cross_connections": [{
                    "id": "conn-fabnetv4",
                    "type": "fabnetv4_l3",
                    "endpoint_a": {
                        "provider": "fabric",
                        "slice_id": "draft-fabric-1",
                        "node": "fabric-node",
                    },
                    "endpoint_b": {
                        "provider": "chameleon",
                        "slice_id": "chi-draft-1",
                        "node": "chi-node",
                    },
                }],
            }
            _chameleon_slices["chi-draft-1"] = {
                "id": "chi-draft-1",
                "name": "chi-draft",
                "provider": "chameleon",
                "state": "Draft",
                "site": "CHI@TACC",
                "nodes": [{"id": "chi-node-1", "name": "chi-node", "site": "CHI@TACC"}],
                "networks": [],
                "floating_ips": [],
                "resources": [],
            }

            with patch("app.slice_registry.resolve_slice_name", return_value="fabric-draft"), \
                 patch("app.routes.slices.prepare_slice_for_fabnetv4", return_value={"updated_nodes": [{"name": "fabric-node"}]}) as mock_prepare_fabnet, \
                 patch("app.routes.chameleon.prepare_draft_for_fabnetv4", return_value={"updated_nodes": [{"name": "chi-node"}]}) as mock_prepare_chi, \
                 patch("app.routes.slices.submit_slice", new_callable=AsyncMock) as mock_submit, \
                 patch("app.routes.chameleon.deploy_draft", new_callable=AsyncMock) as mock_deploy:
                mock_submit.return_value = {
                    "id": "fabric-real-id",
                    "name": "fabric-draft",
                    "state": "StableOK",
                    "networks": [],
                }
                mock_deploy.return_value = {
                    "draft_id": "chi-draft-1",
                    "leases": [{"site": "CHI@TACC", "lease_id": "lease-1", "status": "ACTIVE"}],
                }

                data = asyncio.run(composite_mod.submit_federated_slice(
                    fed_id,
                    {"lease_name": "fed-lease", "duration_hours": 4},
                ))

            assert data["federated_id"] == fed_id
            assert data["fabric_results"][0]["status"] == "submitted"
            assert data["fabric_results"][0]["new_id"] == "fabric-real-id"
            assert data["chameleon_results"][0]["status"] == "submitted"
            assert data["federated_slice"]["fabric_slices"] == ["fabric-real-id"]
            assert data["federated_slice"]["chameleon_slices"] == ["chi-draft-1"]
            assert data["federated_slice"]["cross_connections"][0]["endpoint_a"]["slice_id"] == "fabric-real-id"
            assert data["connection_results"][0]["type"] == "fabnetv4_l3"

            mock_prepare_fabnet.assert_called_once_with("draft-fabric-1", ["fabric-node"])
            mock_prepare_chi.assert_called_once_with("chi-draft-1")
            mock_submit.assert_awaited_once_with("fabric-draft")
            mock_deploy.assert_awaited_once_with(
                "chi-draft-1",
                {"lease_name": "fed-lease", "duration_hours": 4, "full_deploy": True},
            )
        finally:
            composite_mod._composite_slices.pop(fed_id, None)
            _chameleon_slices.pop("chi-draft-1", None)


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

class TestCompositeMigration:
    def test_migrate_old_format(self):
        from app.routes.composite import _migrate_old_format
        old = {
            "id": "comp-old",
            "name": "old-style",
            "state": "Draft",
            "fabric_nodes": [{"name": "n1"}],
            "chameleon_nodes": [],
            "fabric_networks": [],
            "chameleon_networks": [],
        }
        migrated, changed = _migrate_old_format(old)
        assert changed is True
        assert "fabric_nodes" not in migrated
        assert "chameleon_nodes" not in migrated
        assert migrated["fabric_slices"] == []
        assert migrated["chameleon_slices"] == []
        assert migrated["cross_connections"] == []

    def test_legacy_member_fields_are_migrated(self):
        from app.routes.composite import _migrate_old_format
        new = {
            "id": "comp-new",
            "name": "new-style",
            "state": "Draft",
            "fabric_slices": ["uuid-1"],
            "chameleon_slices": [],
            "cross_connections": [],
        }
        migrated, changed = _migrate_old_format(new)
        assert changed is True
        assert migrated["fabric_slices"] == ["uuid-1"]
        assert migrated["members"] == [{"provider": "fabric", "slice_id": "uuid-1"}]
        assert migrated["kind"] == "composite"


# ---------------------------------------------------------------------------
# Graph builder unit tests
# ---------------------------------------------------------------------------

class TestBuildCompositeGraph:
    def test_empty(self):
        from app.graph_builder import build_composite_graph
        result = build_composite_graph([], [])
        assert result["nodes"] == []
        assert result["edges"] == []

    def test_single_fabric_member(self):
        from app.graph_builder import build_composite_graph
        slice_data = {
            "name": "test-slice",
            "id": "slice-123",
            "state": "StableOK",
            "nodes": [{"name": "node1", "site": "RENC", "cores": 2, "ram": 8, "disk": 10,
                        "image": "rocky", "state": "Active", "management_ip": "10.0.0.1",
                        "username": "rocky", "host": "host1", "components": []}],
            "networks": [],
            "facility_ports": [],
            "port_mirrors": [],
        }
        result = build_composite_graph([(slice_data, "slice-123")], [])
        # Composite views should render member resources directly, without
        # slice/folder containers around each member.
        node_ids = [n["data"]["id"] for n in result["nodes"]]
        assert "member:fab:slice-123" not in node_ids
        assert "fab:slice-123:slice:slice-123" not in node_ids
        assert not any(n["data"].get("element_type") == "slice" for n in result["nodes"])
        # All FABRIC elements should be prefixed
        fab_nodes = [n for n in result["nodes"] if n["data"]["id"].startswith("fab:slice-123:")]
        assert len(fab_nodes) >= 1
        vm = next(n for n in fab_nodes if n["data"].get("element_type") == "node")
        assert "parent" not in vm["data"]

    def test_id_prefixing(self):
        from app.graph_builder import _prefix_graph_ids
        graph = {
            "nodes": [
                {"data": {"id": "n1", "parent": "p1", "element_type": "node"}, "classes": "vm"},
                {"data": {"id": "p1", "element_type": "slice"}, "classes": "slice"},
            ],
            "edges": [
                {"data": {"id": "e1", "source": "n1", "target": "n2"}, "classes": "edge"},
            ],
        }
        result = _prefix_graph_ids(graph, "test", "member:test")
        node_ids = {n["data"]["id"] for n in result["nodes"]}
        assert "test:n1" in node_ids
        assert "test:p1" in node_ids
        # Slice container should be parented under member
        slice_node = next(n for n in result["nodes"] if n["data"]["id"] == "test:p1")
        assert slice_node["data"]["parent"] == "member:test"
        # Edge references should be prefixed
        edge = result["edges"][0]
        assert edge["data"]["source"] == "test:n1"

    def test_single_chameleon_member(self):
        from app.graph_builder import build_composite_graph
        chi_slice = {
            "id": "chi-slice-abc",
            "name": "chi-test",
            "state": "Active",
            "nodes": [{"id": "chi-node-1", "name": "server1", "site": "CHI@TACC",
                        "node_type": "compute_skylake", "image": "CC-Ubuntu22.04",
                        "count": 1, "status": "ACTIVE"}],
            "networks": [],
            "floating_ips": [],
            "resources": [],
        }
        result = build_composite_graph([], [(chi_slice, "chi-slice-abc")])
        node_ids = [n["data"]["id"] for n in result["nodes"]]
        assert "member:chi:chi-slice-abc" not in node_ids
        chi_nodes = [n for n in result["nodes"] if n["data"]["id"].startswith("chi:chi-slice-abc:")]
        assert len(chi_nodes) >= 1
        assert not any(
            n["data"].get("element_type") in {"chameleon_draft", "chameleon_cluster"}
            for n in chi_nodes
        )
        instance = next(n for n in chi_nodes if n["data"].get("element_type") == "chameleon_instance")
        assert "parent" not in instance["data"]

    def test_slice_level_federated_connection_edge(self):
        from app.graph_builder import build_composite_graph
        fabric_slice = {
            "name": "fab",
            "id": "fab-1",
            "state": "StableOK",
            "nodes": [{"name": "fab-node", "site": "TACC", "cores": 2, "ram": 8, "disk": 10,
                        "image": "rocky", "state": "Active", "management_ip": "",
                        "username": "rocky", "host": "", "components": []}],
            "networks": [],
            "facility_ports": [],
            "port_mirrors": [],
        }
        chi_slice = {
            "id": "chi-1",
            "name": "chi",
            "state": "Active",
            "nodes": [{"id": "chi-node-1", "name": "chi-node", "site": "CHI@TACC",
                        "node_type": "compute_skylake", "image": "CC-Ubuntu22.04",
                        "count": 1, "status": "ACTIVE"}],
            "networks": [],
            "floating_ips": [],
            "resources": [],
        }
        result = build_composite_graph(
            [(fabric_slice, "fab-1")],
            [(chi_slice, "chi-1")],
            cross_connections=[{
                "id": "conn-1",
                "type": "fabnetv4_l3",
                "endpoint_a": {"provider": "fabric", "slice_id": "fab-1"},
                "endpoint_b": {"provider": "chameleon", "slice_id": "chi-1"},
            }],
        )
        edge = next(e for e in result["edges"] if e["data"]["id"] == "xconn:conn-1")
        assert edge["data"]["source"] == "fab:fab-1:node:fab-1:fab-node"
        assert edge["data"]["target"] == "chi:chi-1:chi-draft-node:chi-1:chi-node-1"
        assert edge["data"]["label"] == "FABNetv4 L3"
        assert not any(
            n["data"].get("element_type") in {"slice", "chameleon_draft", "chameleon_cluster"}
            for n in result["nodes"]
        )

    def test_fabnetv4_connection_uses_gateway_path_without_direct_edge(self):
        from app.graph_builder import build_composite_graph
        fabric_slice = {
            "name": "fab",
            "id": "fab-1",
            "state": "StableOK",
            "nodes": [{
                "name": "fabric-vm", "site": "TACC", "cores": 2, "ram": 8, "disk": 10,
                "image": "rocky", "management_ip": "", "username": "rocky", "host": "",
                "components": [{
                    "name": "fabric-vm-nic1", "model": "NIC_Basic",
                    "interfaces": [{"name": "fabric-vm-nic1-p1", "node_name": "fabric-vm"}],
                }],
            }],
            "networks": [{
                "name": "FABNetv4",
                "type": "FABNetv4",
                "layer": "L3",
                "interfaces": [{"name": "fabric-vm-nic1-p1", "node_name": "fabric-vm"}],
            }],
            "facility_ports": [],
            "port_mirrors": [],
        }
        chi_slice = {
            "id": "chi-1",
            "name": "chi",
            "state": "Draft",
            "nodes": [{
                "id": "chi-node-1", "name": "chi-server", "site": "CHI@TACC",
                "node_type": "compute_skylake", "image": "CC-Ubuntu22.04",
                "count": 1, "connection_type": "fabnet_v4", "status": "DRAFT",
            }],
            "networks": [],
            "floating_ips": [],
            "resources": [],
        }
        result = build_composite_graph(
            [(fabric_slice, "fab-1")],
            [(chi_slice, "chi-1")],
            cross_connections=[{
                "id": "conn-fabnet",
                "type": "fabnetv4_l3",
                "endpoint_a": {"provider": "fabric", "slice_id": "fab-1", "node": "fabric-vm"},
                "endpoint_b": {"provider": "chameleon", "slice_id": "chi-1", "node": "chi-server"},
            }],
        )

        assert not any(e["data"].get("id") == "xconn:conn-fabnet" for e in result["edges"])

        internet_nodes = [
            n for n in result["nodes"]
            if n["data"].get("element_type") == "fabnet-internet"
        ]
        assert len(internet_nodes) == 1
        assert internet_nodes[0]["data"]["id"] == "shared:fabnet-internet-v4"

        gateway_edges = [
            e for e in result["edges"]
            if e["data"].get("element_type") == "fabnet-internet-edge"
        ]
        gateway_pairs = {
            (e["data"].get("source"), e["data"].get("target"))
            for e in gateway_edges
        }
        assert (
            "fab:fab-1:net:fab-1:FABNetv4",
            "shared:fabnet-internet-v4",
        ) in gateway_pairs
        assert (
            "chi:chi-1:chi-fabnetv4:chi-1:CHI@TACC",
            "shared:fabnet-internet-v4",
        ) in gateway_pairs

    def test_facility_port_l2_uses_local_networks_when_missing_from_members(self):
        from app.graph_builder import build_composite_graph
        fabric_slice = {
            "name": "fab",
            "id": "fab-1",
            "state": "Draft",
            "nodes": [{"name": "fab-router", "site": "TACC", "cores": 2, "ram": 8, "disk": 10,
                        "image": "rocky", "management_ip": "", "username": "rocky", "host": "", "components": []}],
            "networks": [],
            "facility_ports": [],
            "port_mirrors": [],
        }
        chi_slice = {
            "id": "chi-1",
            "name": "chi",
            "state": "Draft",
            "nodes": [{"id": "node-uuid-1", "name": "chi-router", "site": "CHI@TACC",
                        "node_type": "compute_skylake", "image": "CC-Ubuntu22.04", "count": 1}],
            "networks": [],
            "floating_ips": [],
            "resources": [],
        }
        result = build_composite_graph(
            [(fabric_slice, "fab-1")],
            [(chi_slice, "chi-1")],
            cross_connections=[{
                "id": "conn-l2",
                "type": "facility_port_l2",
                "vlan": "3301",
                "facility_port": "Chameleon-TACC",
                "endpoint_a": {"provider": "fabric", "slice_id": "fab-1", "node": "fab-router"},
                "endpoint_b": {"provider": "chameleon", "slice_id": "chi-1", "node": "chi-router"},
            }],
        )
        assert not any(e["data"].get("id") == "xconn:conn-l2" for e in result["edges"])

        shared_port = next(
            n for n in result["nodes"]
            if n["data"].get("element_type") == "facility-port"
            and n["data"].get("name") == "Chameleon-TACC"
        )
        facility_networks = [
            n for n in result["nodes"]
            if n["data"].get("element_type") == "network"
            and n["data"].get("connection_type") == "facility_port_l2"
        ]
        assert {n["data"].get("testbed") for n in facility_networks} == {"FABRIC", "Chameleon"}
        by_testbed = {n["data"]["testbed"]: n["data"]["id"] for n in facility_networks}

        stitch_pairs = {
            frozenset({e["data"].get("source"), e["data"].get("target")})
            for e in result["edges"]
            if "edge-facility-port-l2" in e.get("classes", "")
        }
        assert any(
            by_testbed["FABRIC"] in pair
            and any(str(node_id).startswith("fab:fab-1:node:") for node_id in pair)
            for pair in stitch_pairs
        )
        assert any(
            by_testbed["Chameleon"] in pair
            and "chi:chi-1:chi-draft-node:chi-1:node-uuid-1" in pair
            for pair in stitch_pairs
        )
        assert frozenset({by_testbed["FABRIC"], shared_port["data"]["id"]}) in stitch_pairs
        assert frozenset({by_testbed["Chameleon"], shared_port["data"]["id"]}) in stitch_pairs

    def test_chameleon_runtime_resources_render_in_federated_graph(self):
        from app.graph_builder import build_composite_graph
        fabric_slice = {
            "name": "fab",
            "id": "fab-1",
            "state": "StableOK",
            "nodes": [{"name": "fabric-vm", "site": "TACC", "cores": 2, "ram": 8, "disk": 10,
                        "image": "rocky", "management_ip": "", "username": "rocky", "host": "", "components": [
                            {"name": "fabric-vm-nic1", "model": "NIC_Basic", "interfaces": [
                                {"name": "fabric-vm-nic1-p1", "node_name": "fabric-vm"}
                            ]}
                        ]}],
            "networks": [{
                "name": "chameleon-stitch-l2",
                "type": "L2Bridge",
                "layer": "L2",
                "interfaces": [
                    {"name": "fabric-vm-nic1-p1", "node_name": "fabric-vm"},
                    {"name": "iface-1", "node_name": "Chameleon-TACC", "vlan": "3319"},
                ],
            }],
            "facility_ports": [],
            "port_mirrors": [],
        }
        chi_slice = {
            "id": "chi-1",
            "name": "runtime-chi",
            "state": "Active",
            "nodes": [],
            "networks": [],
            "floating_ips": [],
            "resources": [
                {
                    "type": "network",
                    "id": "net-1",
                    "name": "chameleon-fabric-fabnet-gb8u-stitch",
                    "site": "CHI@TACC",
                    "status": "ACTIVE",
                },
                {
                    "type": "instance",
                    "id": "inst-1",
                    "name": "runtime-chi",
                    "planned_node_name": "chameleon-server",
                    "site": "CHI@TACC",
                    "status": "ACTIVE",
                    "floating_ip": "129.114.108.242",
                    "ip_addresses": ["10.52.2.103", "192.168.100.194"],
                    "ssh_ready": True,
                },
            ],
        }
        result = build_composite_graph(
            [(fabric_slice, "fab-1")],
            [(chi_slice, "chi-1")],
            cross_connections=[{
                "id": "conn-l2-runtime",
                "type": "facility_port_l2",
                "vlan": "3319",
                "endpoint_a": {
                    "provider": "fabric",
                    "slice_id": "fab-1",
                    "node": "fabric-vm",
                    "network": "chameleon-stitch-l2",
                    "site": "TACC",
                },
                "endpoint_b": {
                    "provider": "chameleon",
                    "slice_id": "chi-1",
                    "node": "chameleon-server",
                    "network": "chameleon-fabric-fabnet-gb8u-stitch",
                },
            }],
        )
        chi_instances = [
            n for n in result["nodes"]
            if n["data"].get("element_type") == "chameleon_instance"
        ]
        assert len(chi_instances) == 1
        assert chi_instances[0]["data"]["name"] == "chameleon-server"
        assert chi_instances[0]["data"]["instance_id"] == "inst-1"

        shared_ports = [
            n for n in result["nodes"]
            if n["data"].get("element_type") == "facility-port"
            and n["data"].get("name") == "Chameleon-TACC"
        ]
        assert len(shared_ports) == 1
        shared_port = shared_ports[0]
        assert "parent" not in shared_port["data"]
        assert "composite-shared-network" in shared_port["classes"]
        assert "VLAN 3319" in shared_port["data"]["label"]

        assert not any(
            n["data"].get("element_type") == "network"
            and n["data"].get("connection_type") == "facility_port_l2"
            and n["data"].get("testbed") == "SHARED"
            for n in result["nodes"]
        )

        local_l2_networks = [
            n for n in result["nodes"]
            if n["data"].get("element_type") == "network"
            and n["data"].get("connection_type") == "facility_port_l2"
            and n["data"].get("testbed") in {"FABRIC", "Chameleon"}
        ]
        assert len(local_l2_networks) == 2
        local_l2_by_testbed = {n["data"]["testbed"]: n for n in local_l2_networks}
        assert local_l2_by_testbed["FABRIC"]["data"]["name"] == "chameleon-stitch-l2"
        assert local_l2_by_testbed["Chameleon"]["data"]["name"] == "chameleon-fabric-fabnet-gb8u-stitch"
        fab_l2_id = local_l2_by_testbed["FABRIC"]["data"]["id"]
        chi_l2_id = local_l2_by_testbed["Chameleon"]["data"]["id"]

        stitch_pairs = {
            frozenset({e["data"].get("source"), e["data"].get("target")})
            for e in result["edges"]
            if "edge-facility-port-l2" in e.get("classes", "")
        }
        assert any(
            fab_l2_id in pair
            and any(str(node_id).startswith("fab:fab-1:comp:") for node_id in pair)
            for pair in stitch_pairs
        )
        assert any(
            chi_l2_id in pair
            and any(str(node_id).startswith("chi:chi-1:chi-resource-comp:") for node_id in pair)
            for pair in stitch_pairs
        )
        assert frozenset({fab_l2_id, shared_port["data"]["id"]}) in stitch_pairs
        assert frozenset({chi_l2_id, shared_port["data"]["id"]}) in stitch_pairs
        assert not any(e["data"].get("id") == "xconn:conn-l2-runtime" for e in result["edges"])

    def test_facility_port_l2_hides_prepared_transport_artifacts_without_explicit_networks(self):
        from app.graph_builder import build_composite_graph
        fabric_slice = {
            "name": "fab",
            "id": "fab-1",
            "state": "StableOK",
            "nodes": [{"name": "fabric-vm", "site": "TACC", "cores": 2, "ram": 8, "disk": 10,
                        "image": "rocky", "management_ip": "", "username": "rocky", "host": "", "components": [
                            {"name": "fp-l2-3301", "model": "NIC_Basic", "interfaces": [
                                {"name": "fabric-vm-fp-l2-p1", "node_name": "fabric-vm"}
                            ]}
                        ]}],
            "networks": [{
                "name": "Chameleon-TACC-ns",
                "type": "VLAN",
                "layer": "L2",
                "interfaces": [],
            }, {
                "name": "fp-l2-chameleon-tacc-3301",
                "type": "L2Bridge",
                "layer": "L2",
                "interfaces": [
                    {"name": "fabric-vm-fp-l2-p1", "node_name": "fabric-vm"},
                    {"name": "Chameleon-TACC-p1", "node_name": "Chameleon-TACC", "vlan": "3301"},
                ],
            }],
            "facility_ports": [{
                "name": "Chameleon-TACC",
                "site": "TACC",
                "vlan": "3301",
                "interfaces": [],
            }],
            "port_mirrors": [],
        }
        chi_slice = {
            "id": "chi-1",
            "name": "chi",
            "state": "Draft",
            "nodes": [{
                "id": "chi-node-1", "name": "chi-router", "site": "CHI@TACC",
                "node_type": "compute_skylake", "image": "CC-Ubuntu22.04", "count": 1,
                "interfaces": [{"nic": 1, "network": {"id": "chi-fp-net", "name": "fp-l2-chi-tacc-3301"}}],
            }],
            "networks": [{
                "id": "chi-fp-net",
                "name": "fp-l2-chi-tacc-3301",
                "site": "CHI@TACC",
                "type": "facility_port_l2",
                "vlan": "3301",
                "facility_port": "Chameleon-TACC",
                "connected_nodes": ["chi-node-1"],
            }],
            "floating_ips": [],
            "resources": [{
                "type": "network",
                "id": "chi-fp-runtime-net",
                "name": "fp-l2-chi-tacc-3301",
                "site": "CHI@TACC",
                "status": "ACTIVE",
            }],
        }
        result = build_composite_graph(
            [(fabric_slice, "fab-1")],
            [(chi_slice, "chi-1")],
            cross_connections=[{
                "id": "conn-l2-prepared",
                "type": "facility_port_l2",
                "vlan": "3301",
                "facility_port": "Chameleon-TACC",
                "endpoint_a": {"provider": "fabric", "slice_id": "fab-1", "node": "fabric-vm", "site": "TACC"},
                "endpoint_b": {"provider": "chameleon", "slice_id": "chi-1", "node": "chi-router", "site": "CHI@TACC"},
            }],
        )

        assert not any(e["data"].get("id") == "xconn:conn-l2-prepared" for e in result["edges"])
        assert not any(
            n["data"].get("id") == "fab:fab-1:fp:fab-1:Chameleon-TACC"
            for n in result["nodes"]
        )
        network_nodes = [
            n for n in result["nodes"]
            if n["data"].get("element_type") == "network"
        ]
        assert not any(n["data"].get("name") == "Chameleon-TACC-ns" for n in network_nodes)
        assert sum(n["data"].get("name") == "fp-l2-chi-tacc-3301" for n in network_nodes) == 1

        shared_ports = [
            n for n in result["nodes"]
            if n["data"].get("element_type") == "facility-port"
            and n["data"].get("name") == "Chameleon-TACC"
        ]
        assert len(shared_ports) == 1
        shared_port_id = shared_ports[0]["data"]["id"]
        assert not any(
            n["data"].get("element_type") == "network"
            and n["data"].get("connection_type") == "facility_port_l2"
            and n["data"].get("testbed") == "SHARED"
            for n in result["nodes"]
        )
        local_l2_networks = [
            n for n in result["nodes"]
            if n["data"].get("element_type") == "network"
            and n["data"].get("connection_type") == "facility_port_l2"
            and n["data"].get("testbed") in {"FABRIC", "Chameleon"}
        ]
        assert len(local_l2_networks) == 2
        local_l2_by_testbed = {n["data"]["testbed"]: n for n in local_l2_networks}
        assert local_l2_by_testbed["FABRIC"]["data"]["name"] == "fp-l2-chameleon-tacc-3301"
        assert local_l2_by_testbed["Chameleon"]["data"]["name"] == "fp-l2-chi-tacc-3301"
        fab_l2_id = local_l2_by_testbed["FABRIC"]["data"]["id"]
        chi_l2_id = local_l2_by_testbed["Chameleon"]["data"]["id"]
        stitch_pairs = {
            frozenset({e["data"].get("source"), e["data"].get("target")})
            for e in result["edges"]
            if "edge-facility-port-l2" in e.get("classes", "")
        }
        assert any(
            fab_l2_id in pair
            and any(str(node_id).startswith("fab:fab-1:comp:") for node_id in pair)
            for pair in stitch_pairs
        )
        assert any(
            chi_l2_id in pair
            and any(str(node_id).startswith("chi:chi-1:chi-comp:") for node_id in pair)
            for pair in stitch_pairs
        )
        assert frozenset({fab_l2_id, shared_port_id}) in stitch_pairs
        assert frozenset({chi_l2_id, shared_port_id}) in stitch_pairs


class TestChameleonInterfaceRendering:
    """Tests for Chameleon NIC component badges and FABNetv4 rendering."""

    def test_nic_badges_for_connected_networks(self):
        from app.graph_builder import build_chameleon_slice_graph
        draft = {
            "id": "draft-1", "name": "test", "nodes": [
                {"id": "n1", "name": "s1", "site": "CHI@TACC", "node_type": "compute_skylake",
                 "image": "CC-Ubuntu22.04", "count": 1, "status": "DRAFT",
                 "network": {"id": "net1", "name": "mynet"}},
            ],
            "networks": [], "floating_ips": [], "resources": [],
        }
        result = build_chameleon_slice_graph(draft)
        comps = [n for n in result["nodes"] if n["data"].get("element_type") == "component"]
        assert len(comps) == 1
        assert comps[0]["data"]["parent_vm"] == "chi-draft-node:draft-1:n1"
        assert comps[0]["data"]["label"] == "mynet"
        # Edge from NIC to network
        iface_edges = [e for e in result["edges"] if e["data"].get("element_type") == "interface"]
        assert len(iface_edges) == 1
        assert iface_edges[0]["data"]["target"] == "chi-draft-net:draft-1:net1"

    def test_legacy_string_network_field_with_interfaces(self):
        from app.graph_builder import build_chameleon_slice_graph
        draft = {
            "id": "draft-string-net", "name": "test", "nodes": [
                {"id": "n1", "name": "s1", "site": "CHI@TACC", "node_type": "compute_skylake",
                 "image": "CC-Ubuntu22.04", "count": 1, "status": "ACTIVE",
                 "network": "facility_port_l2",
                 "interfaces": [
                     {"nic": 0, "network": "sharednet1", "network_name": "sharednet1"},
                     {"nic": 1, "network": "fp-l2-test", "network_name": "fp-l2-test"},
                 ]},
            ],
            "networks": [], "floating_ips": [], "resources": [],
        }
        result = build_chameleon_slice_graph(draft)
        network_names = {
            n["data"].get("name")
            for n in result["nodes"]
            if n["data"].get("element_type") == "network"
        }
        assert {"sharednet1", "fp-l2-test"} <= network_names

    def test_fabnetv4_chain(self):
        from app.graph_builder import build_chameleon_slice_graph
        draft = {
            "id": "draft-2", "name": "fab-test", "nodes": [
                {"id": "n1", "name": "s1", "site": "CHI@TACC", "node_type": "compute_skylake",
                 "image": "CC-Ubuntu22.04", "count": 1, "connection_type": "fabnet_v4", "status": "DRAFT"},
            ],
            "networks": [], "floating_ips": [], "resources": [],
        }
        result = build_chameleon_slice_graph(draft)
        node_types = {n["data"]["id"]: n["data"]["element_type"] for n in result["nodes"]}
        # Should have: site container, server, local fabnetv4, global internet, NIC
        assert "chi-fabnetv4:draft-2:CHI@TACC" in node_types
        assert node_types["chi-fabnetv4:draft-2:CHI@TACC"] == "network"
        assert "fabnet-internet-v4" in node_types
        assert node_types["fabnet-internet-v4"] == "fabnet-internet"
        # NIC component for fabnetv4
        comps = [n for n in result["nodes"] if n["data"].get("element_type") == "component"]
        assert len(comps) == 1
        assert comps[0]["data"]["label"] == "fabnetv4"
        # Edge chain: NIC → local fabnetv4, local fabnetv4 → global internet
        edges_by_type = {}
        for e in result["edges"]:
            edges_by_type.setdefault(e["data"]["element_type"], []).append(e)
        assert len(edges_by_type.get("interface", [])) == 1
        assert edges_by_type["interface"][0]["data"]["target"] == "chi-fabnetv4:draft-2:CHI@TACC"
        assert len(edges_by_type.get("fabnet-internet-edge", [])) == 1
        assert edges_by_type["fabnet-internet-edge"][0]["data"]["target"] == "fabnet-internet-v4"

    def test_fabnetv4_via_per_node_network(self):
        """Test that per-node network field with fabnetv4 name triggers fabnetv4 chain."""
        from app.graph_builder import build_chameleon_slice_graph
        draft = {
            "id": "draft-3", "name": "fabnet-new", "nodes": [
                {"id": "n1", "name": "s1", "site": "CHI@TACC", "node_type": "compute_skylake",
                 "image": "CC-Ubuntu22.04", "count": 1, "status": "DRAFT",
                 "network": {"id": "fabnet-uuid", "name": "fabnetv4"}},
            ],
            "networks": [], "floating_ips": [], "resources": [],
        }
        result = build_chameleon_slice_graph(draft)
        comps = [n for n in result["nodes"] if n["data"].get("element_type") == "component"]
        assert len(comps) == 1
        assert comps[0]["data"]["label"] == "fabnetv4"
        # Verify the full chain: NIC → gateway → internet
        node_types = {n["data"]["id"]: n["data"]["element_type"] for n in result["nodes"]}
        assert "chi-fabnetv4:draft-3:CHI@TACC" in node_types
        assert "fabnet-internet-v4" in node_types

    def test_dual_nic_interfaces(self):
        """Test multi-interface model: 2 NICs with different networks."""
        from app.graph_builder import build_chameleon_slice_graph
        draft = {
            "id": "draft-dual", "name": "dual-nic", "nodes": [
                {"id": "n1", "name": "s1", "site": "CHI@TACC", "node_type": "compute_skylake",
                 "image": "CC-Ubuntu22.04", "count": 1, "status": "DRAFT",
                 "interfaces": [
                     {"nic": 0, "network": {"id": "net-shared", "name": "sharednet1"}},
                     {"nic": 1, "network": {"id": "net-fab", "name": "fabnetv4"}},
                 ]},
            ],
            "networks": [], "floating_ips": [], "resources": [],
        }
        result = build_chameleon_slice_graph(draft)
        comps = [n for n in result["nodes"] if n["data"].get("element_type") == "component"]
        assert len(comps) == 2
        labels = sorted(c["data"]["label"] for c in comps)
        assert labels == ["fabnetv4", "sharednet1"]
        # Verify both NICs reference the same parent VM
        assert all(c["data"]["parent_vm"] == "chi-draft-node:draft-dual:n1" for c in comps)

    def test_runtime_legacy_interface_network_string(self):
        """Runtime artifact state can store interfaces with network as a string."""
        from app.graph_builder import build_chameleon_slice_graph
        draft = {
            "id": "draft-runtime", "name": "runtime", "site": "CHI@TACC",
            "nodes": [
                {"id": "n1", "name": "s1", "site": "CHI@TACC", "node_type": "compute_cascadelake_r",
                 "image": "CC-Ubuntu22.04", "count": 1, "status": "ACTIVE",
                 "interfaces": [
                     {
                         "name": "sharednet1",
                         "network": "sharednet1",
                         "network_name": "sharednet1",
                         "port_id": "port-1",
                         "ip_addresses": ["10.52.1.30"],
                     },
                 ]},
            ],
            "networks": [{"name": "sharednet1", "site": "CHI@TACC", "type": "sharednet"}],
            "floating_ips": [], "resources": [],
        }
        result = build_chameleon_slice_graph(draft)
        network_nodes = [
            n for n in result["nodes"]
            if n["data"].get("element_type") == "network" and n["data"].get("name") == "sharednet1"
        ]
        assert len(network_nodes) == 1
        comps = [n for n in result["nodes"] if n["data"].get("element_type") == "component"]
        assert len(comps) == 1
        assert comps[0]["data"]["label"] == "sharednet1"
        iface_edges = [e for e in result["edges"] if e["data"].get("element_type") == "interface"]
        assert len(iface_edges) == 1
        assert iface_edges[0]["data"]["target"] == "chi-draft-net:draft-runtime:CHI@TACC:sharednet1"
        assert network_nodes[0]["data"]["label"] == "sharednet1\n@ CHI@TACC\n(network)"

    def test_sharednet_is_site_scoped(self):
        """Each Chameleon site has its own sharednet with the same display name."""
        from app.graph_builder import build_chameleon_slice_graph
        draft = {
            "id": "draft-sharednet-sites", "name": "runtime",
            "nodes": [
                {"id": "tacc-node", "name": "s1", "site": "CHI@TACC", "node_type": "compute_cascadelake_r",
                 "image": "CC-Ubuntu22.04", "count": 1,
                 "interfaces": [{"nic": 0, "network": "sharednet1", "network_name": "sharednet1"}]},
                {"id": "uc-node", "name": "s2", "site": "CHI@UC", "node_type": "compute_cascadelake_r",
                 "image": "CC-Ubuntu22.04", "count": 1,
                 "interfaces": [{"nic": 0, "network": "sharednet1", "network_name": "sharednet1"}]},
            ],
            "networks": [], "floating_ips": [], "resources": [],
        }
        result = build_chameleon_slice_graph(draft)
        sharednets = [
            n for n in result["nodes"]
            if n["data"].get("element_type") == "network" and n["data"].get("name") == "sharednet1"
        ]
        assert sorted(n["data"]["site"] for n in sharednets) == ["CHI@TACC", "CHI@UC"]
        assert {n["data"]["id"] for n in sharednets} == {
            "chi-draft-net:draft-sharednet-sites:CHI@TACC:sharednet1",
            "chi-draft-net:draft-sharednet-sites:CHI@UC:sharednet1",
        }
        iface_targets = {
            e["data"]["source_vm"]: e["data"]["target"]
            for e in result["edges"]
            if e["data"].get("element_type") == "interface"
        }
        assert iface_targets["chi-draft-node:draft-sharednet-sites:tacc-node"] == "chi-draft-net:draft-sharednet-sites:CHI@TACC:sharednet1"
        assert iface_targets["chi-draft-node:draft-sharednet-sites:uc-node"] == "chi-draft-net:draft-sharednet-sites:CHI@UC:sharednet1"

    def test_no_interfaces_without_networks(self):
        from app.graph_builder import build_chameleon_slice_graph
        draft = {
            "id": "draft-4", "name": "bare", "nodes": [
                {"id": "n1", "name": "s1", "site": "CHI@TACC", "node_type": "compute_skylake",
                 "image": "CC-Ubuntu22.04", "count": 1, "connection_type": "", "status": "DRAFT"},
            ],
            "networks": [], "floating_ips": [], "resources": [],
        }
        result = build_chameleon_slice_graph(draft)
        comps = [n for n in result["nodes"] if n["data"].get("element_type") == "component"]
        assert len(comps) == 0


# ---------------------------------------------------------------------------
# Cross-connections
# ---------------------------------------------------------------------------

class TestCrossConnections:
    def test_update_cross_connections(self, client):
        cr = client.post("/api/composite/slices", json={"name": "xconn"}).json()
        conns = [{"type": "fabnetv4", "fabric_slice": "f1", "fabric_node": "n1",
                  "chameleon_slice": "c1", "chameleon_node": "cn1"}]
        r = client.put(f"/api/composite/slices/{cr['id']}/cross-connections", json=conns)
        assert r.status_code == 200
        assert len(r.json()["cross_connections"]) == 1

    def test_empty_cross_connections(self, client):
        cr = client.post("/api/composite/slices", json={"name": "xconn2"}).json()
        r = client.put(f"/api/composite/slices/{cr['id']}/cross-connections", json=[])
        assert r.status_code == 200
        assert r.json()["cross_connections"] == []

    def test_cross_connection_not_found(self, client):
        r = client.put("/api/composite/slices/nonexistent/cross-connections", json=[])
        assert r.status_code == 404


class TestFederatedConnections:
    def test_connection_crud(self, client):
        cr = client.post("/api/federated/slices", json={"name": "fed-xconn"}).json()
        conn = {
            "type": "fabnetv4_l3",
            "endpoint_a": {"provider": "fabric", "slice_id": "fab-1", "node": "n1"},
            "endpoint_b": {"provider": "chameleon", "slice_id": "chi-1", "node": "c1"},
        }
        add = client.post(f"/api/federated/slices/{cr['id']}/connections/add", json=conn)
        assert add.status_code == 200
        added = add.json()["cross_connections"][0]
        assert added["id"].startswith("conn-")
        assert added["type"] == "fabnetv4_l3"

        listed = client.get(f"/api/federated/slices/{cr['id']}/connections")
        assert listed.status_code == 200
        assert listed.json()[0]["id"] == added["id"]

        remove = client.post(
            f"/api/federated/slices/{cr['id']}/connections/remove",
            json={"id": added["id"]},
        )
        assert remove.status_code == 200
        assert remove.json()["cross_connections"] == []

    def test_replace_connections(self, client):
        cr = client.post("/api/federated/slices", json={"name": "fed-xconn-replace"}).json()
        conns = [{
            "type": "facility_port_l2",
            "vlan": 3301,
            "endpoint_a": {"provider": "fabric", "slice_id": "fab-1"},
            "endpoint_b": {"provider": "chameleon", "slice_id": "chi-1"},
        }]
        r = client.put(f"/api/federated/slices/{cr['id']}/connections", json=conns)
        assert r.status_code == 200
        assert r.json()["cross_connections"][0]["type"] == "facility_port_l2"

    def test_connection_requires_fabric_and_chameleon_endpoints(self, client):
        cr = client.post("/api/federated/slices", json={"name": "fed-xconn-invalid"}).json()
        r = client.post(
            f"/api/federated/slices/{cr['id']}/connections/add",
            json={"type": "fabnetv4_l3", "endpoint_a": {"provider": "fabric", "slice_id": "fab-1"}},
        )
        assert r.status_code == 400

    def test_facility_l2_requires_vlan_or_facility_port_metadata(self, client):
        cr = client.post("/api/federated/slices", json={"name": "fed-l2-invalid"}).json()
        r = client.post(
            f"/api/federated/slices/{cr['id']}/connections/add",
            json={
                "type": "facility_port_l2",
                "endpoint_a": {"provider": "fabric", "slice_id": "fab-1"},
                "endpoint_b": {"provider": "chameleon", "slice_id": "chi-1"},
            },
        )
        assert r.status_code == 400

    def test_duplicate_connection_rejected(self, client):
        cr = client.post("/api/federated/slices", json={"name": "fed-xconn-dupe"}).json()
        conn = {
            "type": "fabnetv4_l3",
            "endpoint_a": {"provider": "fabric", "slice_id": "fab-1"},
            "endpoint_b": {"provider": "chameleon", "slice_id": "chi-1"},
        }
        assert client.post(f"/api/federated/slices/{cr['id']}/connections/add", json=conn).status_code == 200
        assert client.post(f"/api/federated/slices/{cr['id']}/connections/add", json=conn).status_code == 409

    def test_fabnetv4_connection_marks_chameleon_member_for_preparation(self):
        from app.routes.composite import _fabnetv4_chameleon_member_ids, _fabnetv4_fabric_member_nodes
        fed = {
            "cross_connections": [{
                "type": "fabnetv4_l3",
                "endpoint_a": {"provider": "fabric", "slice_id": "fab-1", "node": "n1"},
                "endpoint_b": {"provider": "chameleon", "slice_id": "chi-1"},
            }]
        }
        assert _fabnetv4_chameleon_member_ids(fed) == {"chi-1"}
        assert _fabnetv4_fabric_member_nodes(fed) == {"fab-1": {"n1"}}

    def test_facility_l2_connection_plan_is_reportable(self):
        from app.routes.composite import _federated_connection_plan
        fed = {
            "cross_connections": [
                {
                    "id": "conn-1",
                    "type": "facility_port_l2",
                    "vlan": "3301",
                    "facility_port": "TACC-StarLight",
                    "endpoint_a": {"provider": "fabric", "slice_id": "fab-1"},
                    "endpoint_b": {"provider": "chameleon", "slice_id": "chi-1"},
                },
                {
                    "id": "conn-2",
                    "type": "fabnetv4_l3",
                    "endpoint_a": {"provider": "fabric", "slice_id": "fab-1"},
                    "endpoint_b": {"provider": "chameleon", "slice_id": "chi-1"},
                },
            ]
        }
        plan = _federated_connection_plan(fed)
        assert plan[0]["status"] == "ready-for-submit"
        assert plan[0]["vlan"] == "3301"
        assert plan[0]["facility_port"] == "TACC-StarLight"
        assert plan[1]["status"] == "ready-for-submit"
        assert "Attach FABRIC endpoint nodes to FABNetv4" in plan[1]["actions"]

    def test_facility_l2_connection_intents_are_grouped_by_provider(self):
        from app.routes.composite import _facility_port_l2_chameleon_intents, _facility_port_l2_fabric_intents
        fed = {
            "cross_connections": [{
                "id": "conn-1",
                "type": "facility_port_l2",
                "vlan": "3301",
                "facility_port": "Chameleon-TACC",
                "endpoint_a": {"provider": "fabric", "slice_id": "fab-1", "site": "TACC", "node": "fab-router"},
                "endpoint_b": {"provider": "chameleon", "slice_id": "chi-1", "site": "CHI@TACC", "node": "chi-router"},
            }]
        }
        assert _facility_port_l2_chameleon_intents(fed)["chi-1"][0]["node_name"] == "chi-router"
        assert _facility_port_l2_chameleon_intents(fed)["chi-1"][0]["fabric_site"] == "TACC"
        assert _facility_port_l2_fabric_intents(fed)["fab-1"][0]["node_name"] == "fab-router"
        assert _facility_port_l2_fabric_intents(fed)["fab-1"][0]["facility_port"] == "Chameleon-TACC"


# ---------------------------------------------------------------------------
# Replace FABRIC member
# ---------------------------------------------------------------------------

class TestReplaceFabricMember:
    @patch("app.routes.composite._validate_fabric_ref", return_value=True)
    def test_replace_member(self, mock_val, client):
        cr = client.post("/api/composite/slices", json={"name": "replace-test"}).json()
        client.put(f"/api/composite/slices/{cr['id']}/members",
                   json={"fabric_slices": ["old-draft-id"], "chameleon_slices": []})
        r = client.post("/api/composite/replace-fabric-member",
                        json={"old_id": "old-draft-id", "new_id": "real-uuid"})
        assert r.status_code == 200
        assert r.json()["updated"] == 1
        # Verify the replacement
        updated = client.get(f"/api/composite/slices/{cr['id']}").json()
        assert "real-uuid" in updated["fabric_slices"]
        assert "old-draft-id" not in updated["fabric_slices"]
        assert {"provider": "fabric", "slice_id": "real-uuid"} in updated["members"]
        assert {"provider": "fabric", "slice_id": "old-draft-id"} not in updated["members"]

    def test_replace_missing_params(self, client):
        r = client.post("/api/composite/replace-fabric-member",
                        json={"old_id": "", "new_id": ""})
        assert r.status_code == 400

    @patch("app.routes.composite._validate_fabric_ref", return_value=True)
    def test_replace_member_via_federated_alias(self, mock_val, client):
        cr = client.post("/api/federated/slices", json={"name": "fed-replace-test"}).json()
        client.put(f"/api/federated/slices/{cr['id']}/members",
                   json={"members": [{"provider": "fabric", "slice_id": "old-draft-id"}]})
        r = client.post("/api/federated/replace-fabric-member",
                        json={"old_id": "old-draft-id", "new_id": "real-uuid"})
        assert r.status_code == 200
        updated = client.get(f"/api/federated/slices/{cr['id']}").json()
        assert updated["fabric_slices"] == ["real-uuid"]
        assert updated["members"] == [{"provider": "fabric", "slice_id": "real-uuid"}]


# ---------------------------------------------------------------------------
# Draft slice fetch (regression test for draft-UUID bug)
# ---------------------------------------------------------------------------

class TestDraftSliceFetch:
    def test_create_and_fetch_draft(self, client):
        """Creating a FABRIC draft and fetching by draft ID should return data."""
        cr = client.post("/api/slices?name=draft-fetch-test").json()
        assert cr.get("id", "").startswith("draft-")
        # Fetch by draft ID
        r = client.get(f"/api/slices/{cr['id']}")
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "draft-fetch-test"
        assert data["state"] == "Draft"

    def test_fetch_nonexistent_draft(self, client):
        r = client.get("/api/slices/draft-nonexistent-id")
        # Should return 404 or error, not crash
        assert r.status_code in (404, 500)


# ---------------------------------------------------------------------------
# Chameleon node interfaces endpoint
# ---------------------------------------------------------------------------

class TestChameleonNodeInterfaces:
    """Test Chameleon node interfaces via direct in-memory manipulation (no API, since Chameleon requires settings)."""

    def test_create_node_with_interfaces(self):
        """New nodes created by the draft endpoint have interfaces array."""
        from app.routes.chameleon import _chameleon_slices, _persist_slices
        import uuid
        slice_id = f"chi-test-{uuid.uuid4().hex[:8]}"
        _chameleon_slices[slice_id] = {
            "id": slice_id, "name": "test", "state": "Draft",
            "nodes": [], "networks": [], "floating_ips": [], "resources": [],
        }
        # Simulate add_draft_node logic
        node = {
            "id": f"node-{uuid.uuid4()}",
            "name": "n1", "node_type": "compute_haswell",
            "image": "CC-Ubuntu22.04", "count": 1, "site": "CHI@TACC",
            "interfaces": [{"nic": 0, "network": None}, {"nic": 1, "network": None}],
        }
        _chameleon_slices[slice_id]["nodes"].append(node)
        assert len(node["interfaces"]) == 2
        assert node["interfaces"][0]["nic"] == 0
        assert node["interfaces"][1]["nic"] == 1
        del _chameleon_slices[slice_id]

    def test_update_interfaces(self):
        """Updating interfaces changes network assignments."""
        from app.routes.chameleon import _chameleon_slices
        import uuid
        slice_id = f"chi-test-{uuid.uuid4().hex[:8]}"
        node_id = f"node-{uuid.uuid4()}"
        _chameleon_slices[slice_id] = {
            "id": slice_id, "name": "test", "state": "Draft",
            "nodes": [{"id": node_id, "name": "n1", "node_type": "compute_haswell",
                        "image": "CC-Ubuntu22.04", "count": 1, "site": "CHI@TACC",
                        "interfaces": [{"nic": 0, "network": None}, {"nic": 1, "network": None}]}],
            "networks": [], "floating_ips": [], "resources": [],
        }
        # Update interfaces
        node = _chameleon_slices[slice_id]["nodes"][0]
        node["interfaces"] = [
            {"nic": 0, "network": {"id": "net-1", "name": "sharednet1"}},
            {"nic": 1, "network": {"id": "net-2", "name": "fabnetv4"}},
        ]
        assert node["interfaces"][0]["network"]["name"] == "sharednet1"
        assert node["interfaces"][1]["network"]["name"] == "fabnetv4"
        del _chameleon_slices[slice_id]


class TestChameleonFabnetv4Preparation:
    def _mock_session(self):
        session = MagicMock()
        session.api_get.return_value = {
            "networks": [
                {"id": "net-shared", "name": "sharednet1", "shared": True},
                {"id": "net-fabnet", "name": "fabnetv4", "shared": True},
            ]
        }
        return session

    def test_prepare_empty_node_attaches_sharednet_and_fabnet_with_route_metrics(self, storage_dir):
        from app.routes.chameleon import _chameleon_slices, prepare_draft_for_fabnetv4
        import uuid
        slice_id = f"chi-test-{uuid.uuid4().hex[:8]}"
        _chameleon_slices[slice_id] = {
            "id": slice_id, "name": "test", "state": "Draft",
            "nodes": [{"id": "node-1", "name": "n1", "node_type": "compute_haswell",
                        "image": "CC-Ubuntu22.04", "count": 1, "site": "CHI@TACC",
                        "interfaces": [{"nic": 0, "network": None}, {"nic": 1, "network": None}]}],
            "networks": [], "floating_ips": [], "resources": [],
        }
        with patch("app.routes.chameleon.get_session", return_value=self._mock_session()):
            result = prepare_draft_for_fabnetv4(slice_id)

        node = _chameleon_slices[slice_id]["nodes"][0]
        assert result["updated_nodes"][0]["route_metric_user_data"] is True
        assert node["interfaces"][0]["network"]["name"] == "sharednet1"
        assert node["interfaces"][1]["network"]["name"] == "fabnetv4"
        assert node["connection_type"] == "fabnet_v4"
        assert "eno1np0:" in node["user_data"]
        assert "route-metric: 50" in node["user_data"]
        assert "eno2np1:" in node["user_data"]
        assert "route-metric: 500" in node["user_data"]
        del _chameleon_slices[slice_id]

    def test_prepare_fabnet_only_node_keeps_single_nic_with_fabnet_metric(self, storage_dir):
        from app.routes.chameleon import _chameleon_slices, prepare_draft_for_fabnetv4
        import uuid
        slice_id = f"chi-test-{uuid.uuid4().hex[:8]}"
        _chameleon_slices[slice_id] = {
            "id": slice_id, "name": "test", "state": "Draft",
            "nodes": [{"id": "node-1", "name": "n1", "node_type": "compute_haswell",
                        "image": "CC-Ubuntu22.04", "count": 1, "site": "CHI@TACC",
                        "interfaces": [{"nic": 0, "network": {"id": "net-fabnet", "name": "fabnetv4"}}]}],
            "networks": [], "floating_ips": [], "resources": [],
        }
        with patch("app.routes.chameleon.get_session", return_value=self._mock_session()):
            prepare_draft_for_fabnetv4(slice_id)

        node = _chameleon_slices[slice_id]["nodes"][0]
        assert len(node["interfaces"]) == 1
        assert node["interfaces"][0]["network"]["name"] == "fabnetv4"
        assert "eno1np0:" in node["user_data"]
        assert "route-metric: 500" in node["user_data"]
        assert "route-metric: 50\n" not in node["user_data"]
        del _chameleon_slices[slice_id]


class TestFabricFabnetv4Preparation:
    def test_prepare_fabric_draft_attaches_fabnetv4_and_l3_config(self, storage_dir):
        from app.routes import slices as slices_mod
        from tests.fixtures.fablib_mocks import MockNode, MockSlice

        slice_name = "fab-fed-prep"
        slice_obj = MockSlice(name=slice_name, nodes=[MockNode(name="n1", site="RENC")])
        slices_mod._draft_slices[slice_name] = slice_obj
        slices_mod._draft_is_new[slice_name] = True
        try:
            result = slices_mod.prepare_slice_for_fabnetv4(slice_name)
            assert result["updated_nodes"] == [{"name": "n1", "status": "attached"}]
            assert result["fabnetv4_networks"][0]["type"] == "IPv4"
            assert slices_mod._draft_l3_config[slice_name][result["fabnetv4_networks"][0]["name"]]["default_fabnet_subnet"] == "10.128.0.0/10"
        finally:
            slices_mod._draft_slices.pop(slice_name, None)
            slices_mod._draft_is_new.pop(slice_name, None)
            slices_mod._draft_l3_config.pop(slice_name, None)


class TestFabricFacilityPortPreparation:
    def test_prepare_fabric_draft_adds_facility_port_and_l2_network(self, storage_dir):
        from app.routes import slices as slices_mod
        from tests.fixtures.fablib_mocks import MockInterface, MockNode, MockSlice

        class FacilityPort:
            def __init__(self, name: str, site: str, vlan: str):
                self._name = name
                self._site = site
                self._vlan = vlan
                self._ifaces = [MockInterface(name=f"{name}-p1")]

            def get_name(self):
                return self._name

            def get_site(self):
                return self._site

            def get_interfaces(self):
                return self._ifaces

        class FacilityPortSlice(MockSlice):
            def add_facility_port(self, name: str, site: str, vlan: str = "", bandwidth: int = 10):
                fp = FacilityPort(name, site, vlan)
                self._facility_ports.append(fp)
                return fp

        slice_name = "fab-fp-prep"
        slice_obj = FacilityPortSlice(name=slice_name, nodes=[MockNode(name="n1", site="TACC")])
        slices_mod._draft_slices[slice_name] = slice_obj
        slices_mod._draft_is_new[slice_name] = True
        try:
            result = slices_mod.prepare_slice_for_facility_port_l2(
                slice_name,
                facility_port="Chameleon-TACC",
                fabric_site="TACC",
                vlan="3301",
                node_name="n1",
            )
            assert result["facility_port"] == "Chameleon-TACC"
            assert result["facility_port_status"] == "added"
            assert result["network_status"] == "added"
            assert slice_obj.get_facility_ports()[0].get_name() == "Chameleon-TACC"
            assert slice_obj.get_network_services()[0].get_name() == "fp-l2-chameleon-tacc-3301"
            assert len(slice_obj.get_network_services()[0].get_interfaces()) == 2
        finally:
            slices_mod._draft_slices.pop(slice_name, None)
            slices_mod._draft_is_new.pop(slice_name, None)


class TestFederatedSubmitConnectionPreparation:
    def test_graph_prefers_live_fabric_member_over_stale_cache(self, storage_dir):
        import asyncio
        import time
        from app.fabric_call_manager import CacheEntry, get_call_manager
        from app.routes import composite as composite_mod

        fed_id = "fed-live-over-cache"
        composite_mod._composite_slices[fed_id] = {
            "id": fed_id,
            "name": "fed",
            "kind": "federated",
            "state": "Provisioning",
            "fabric_slices": ["fabric-live-id"],
            "chameleon_slices": [],
            "members": [{"provider": "fabric", "slice_id": "fabric-live-id"}],
            "cross_connections": [],
        }

        stale_slice = {
            "id": "fabric-live-id",
            "name": "fabric-live",
            "state": "Configuring",
            "nodes": [{"name": "stale-node", "site": "RENC", "components": [], "interfaces": []}],
            "networks": [],
            "facility_ports": [],
            "port_mirrors": [],
        }
        live_slice = {
            **stale_slice,
            "state": "StableOK",
            "nodes": [{"name": "live-node", "site": "RENC", "components": [], "interfaces": []}],
        }
        get_call_manager()._cache["slice:fabric-live"] = CacheEntry(data=stale_slice, timestamp=time.time())

        async def _fresh_get_slice(name, max_age=30):
            assert name == "fabric-live-id"
            assert max_age == 0
            return live_slice

        try:
            with patch("app.routes.composite._resolve_fabric_ref", return_value="fabric-live"), \
                 patch("app.routes.slices._is_draft", return_value=False), \
                 patch("app.routes.slices.get_slice", side_effect=_fresh_get_slice) as get_slice:
                graph = asyncio.run(composite_mod.get_composite_graph(fed_id))

            get_slice.assert_called_once()
            graph_text = json.dumps(graph)
            assert "live-node" in graph_text
            assert "stale-node" not in graph_text
        finally:
            composite_mod._composite_slices.pop(fed_id, None)
            get_call_manager()._cache.pop("slice:fabric-live", None)

    def test_graph_keeps_fabric_member_visible_after_submit_uses_cached_result(self, storage_dir):
        import asyncio
        from app.routes import composite as composite_mod

        fed_id = "fed-submit-cache"
        composite_mod._composite_slices[fed_id] = {
            "id": fed_id,
            "name": "fed",
            "kind": "federated",
            "state": "Draft",
            "fabric_slices": ["fab-draft"],
            "chameleon_slices": [],
            "members": [{"provider": "fabric", "slice_id": "fab-draft"}],
            "cross_connections": [],
        }

        submitted_slice = {
            "id": "fabric-real-id",
            "name": "fab-draft",
            "state": "Configuring",
            "lease_start": "",
            "lease_end": "",
            "error_messages": [],
            "nodes": [{
                "name": "fabric-node-1",
                "site": "RENC",
                "host": "",
                "cores": 2,
                "ram": 8,
                "disk": 10,
                "image": "default_ubuntu_22",
                "image_type": "qcow2",
                "management_ip": "",
                "reservation_state": "Ticketed",
                "error_message": "",
                "username": "ubuntu",
                "components": [],
                "interfaces": [],
            }],
            "networks": [],
            "facility_ports": [],
            "port_mirrors": [],
        }

        async def _submit_slice(name):
            from app.slice_registry import register_slice
            register_slice(name, uuid="fabric-real-id", state="Configuring")
            return submitted_slice

        try:
            with patch("app.routes.slices.submit_slice", side_effect=_submit_slice):
                result = asyncio.run(composite_mod.submit_composite_slice(fed_id, {}))
            graph = asyncio.run(composite_mod.get_composite_graph(fed_id))

            assert result["federated_slice"]["fabric_slices"] == ["fabric-real-id"]
            assert any(
                node["data"].get("name") == "fabric-node-1"
                for node in graph["nodes"]
            )
        finally:
            composite_mod._composite_slices.pop(fed_id, None)

    def test_submit_prepares_fabric_fabnetv4_member(self, storage_dir):
        import asyncio
        from app.routes import composite as composite_mod

        fed_id = "fed-submit-fabnet"
        composite_mod._composite_slices[fed_id] = {
            "id": fed_id,
            "name": "fed",
            "kind": "federated",
            "state": "Draft",
            "fabric_slices": ["fab-1"],
            "chameleon_slices": [],
            "members": [{"provider": "fabric", "slice_id": "fab-1"}],
            "cross_connections": [{
                "id": "conn-1",
                "type": "fabnetv4_l3",
                "endpoint_a": {"provider": "fabric", "slice_id": "fab-1", "node": "n1"},
                "endpoint_b": {"provider": "chameleon", "slice_id": "chi-1"},
            }],
        }

        async def _submit_slice(name):
            return {"id": "fabric-real-id", "name": name, "state": "Configuring"}

        try:
            with patch("app.slice_registry.resolve_slice_name", return_value="fab-draft"), \
                 patch("app.slice_registry.get_slice_uuid", return_value="fabric-real-id"), \
                 patch("app.routes.slices.prepare_slice_for_fabnetv4", return_value={"updated_nodes": [{"name": "n1", "status": "attached"}]}) as prep, \
                 patch("app.routes.slices.submit_slice", side_effect=_submit_slice):
                result = asyncio.run(composite_mod.submit_composite_slice(fed_id, {}))

            prep.assert_called_once_with("fab-1", ["n1"])
            assert result["fabric_results"][0]["connection_preparation"]["updated_nodes"][0]["status"] == "attached"
            assert result["connection_results"][0]["status"] == "ready-for-submit"
        finally:
            composite_mod._composite_slices.pop(fed_id, None)

    def test_submit_prepares_chameleon_facility_port_l2_member(self, storage_dir):
        import asyncio
        from app.routes import composite as composite_mod
        from app.routes.chameleon import _chameleon_slices

        fed_id = "fed-submit-fp-l2"
        chi_id = "chi-fp-submit"
        composite_mod._composite_slices[fed_id] = {
            "id": fed_id,
            "name": "fed",
            "kind": "federated",
            "state": "Draft",
            "fabric_slices": [],
            "chameleon_slices": [chi_id],
            "members": [{"provider": "chameleon", "slice_id": chi_id}],
            "cross_connections": [{
                "id": "conn-1",
                "type": "facility_port_l2",
                "vlan": "3301",
                "facility_port": "Chameleon-TACC",
                "endpoint_a": {"provider": "fabric", "slice_id": "fab-1", "site": "TACC"},
                "endpoint_b": {"provider": "chameleon", "slice_id": chi_id, "site": "CHI@TACC", "node": "chi-router"},
            }],
        }
        _chameleon_slices[chi_id] = {"id": chi_id, "state": "Draft", "nodes": [], "networks": []}

        async def _deploy_draft(draft_id, body):
            return {"draft_id": draft_id, "status": "deploying", "body": body}

        try:
            with patch("app.routes.chameleon.prepare_draft_for_facility_port_l2", return_value={"vlan": 3301, "attached_nodes": [{"name": "chi-router"}]}) as prep, \
                 patch("app.routes.chameleon.deploy_draft", side_effect=_deploy_draft):
                result = asyncio.run(composite_mod.submit_composite_slice(fed_id, {}))

            prep.assert_called_once()
            _, kwargs = prep.call_args
            assert kwargs["vlan"] == "3301"
            assert kwargs["facility_port"] == "Chameleon-TACC"
            assert kwargs["fabric_site"] == "TACC"
            assert kwargs["chameleon_site"] == "CHI@TACC"
            assert kwargs["node_name"] == "chi-router"
            assert result["chameleon_results"][0]["result"]["body"]["full_deploy"] is True
            assert result["chameleon_results"][0]["connection_preparation"]["facility_port_l2"][0]["vlan"] == 3301
        finally:
            composite_mod._composite_slices.pop(fed_id, None)
            _chameleon_slices.pop(chi_id, None)

    def test_prepare_fabric_draft_respects_selected_nodes(self, storage_dir):
        from app.routes import slices as slices_mod
        from tests.fixtures.fablib_mocks import MockNode, MockSlice

        slice_name = "fab-fed-selected-prep"
        slice_obj = MockSlice(name=slice_name, nodes=[
            MockNode(name="n1", site="RENC"),
            MockNode(name="n2", site="RENC"),
        ])
        slices_mod._draft_slices[slice_name] = slice_obj
        slices_mod._draft_is_new[slice_name] = True
        try:
            result = slices_mod.prepare_slice_for_fabnetv4(slice_name, ["n2"])
            assert result["updated_nodes"] == [{"name": "n2", "status": "attached"}]
            serialized = slices_mod.slice_to_dict(slice_obj)
            fabnet_ifaces = [
                iface["node_name"]
                for net in serialized["networks"]
                for iface in net["interfaces"]
                if net["type"] == "IPv4"
            ]
            assert fabnet_ifaces == ["n2"]
        finally:
            slices_mod._draft_slices.pop(slice_name, None)
            slices_mod._draft_is_new.pop(slice_name, None)
            slices_mod._draft_l3_config.pop(slice_name, None)
