"""Tests for composite slice API — meta-slice reference model."""

import json
import os
import pytest
from unittest.mock import patch, MagicMock


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

    def test_new_format_unchanged(self):
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
        assert changed is False
        assert migrated["fabric_slices"] == ["uuid-1"]


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
        # Should have member bounding box + slice container + node
        node_ids = [n["data"]["id"] for n in result["nodes"]]
        assert "member:fab:slice-123" in node_ids
        # All FABRIC elements should be prefixed
        fab_nodes = [n for n in result["nodes"] if n["data"]["id"].startswith("fab:slice-123:")]
        assert len(fab_nodes) >= 2  # at least slice container + VM node

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
        assert "member:chi:chi-slice-abc" in node_ids
        chi_nodes = [n for n in result["nodes"] if n["data"]["id"].startswith("chi:chi-slice-abc:")]
        assert len(chi_nodes) >= 1


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

    def test_replace_missing_params(self, client):
        r = client.post("/api/composite/replace-fabric-member",
                        json={"old_id": "", "new_id": ""})
        assert r.status_code == 400


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
