"""Tests for Chameleon Cloud integration endpoints.

All Chameleon routes are gated by _require_enabled() and use _get_session()
for OpenStack API calls. We mock both to avoid real Keystone/Blazar/Nova calls.
"""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Mock session factory
# ---------------------------------------------------------------------------

def _make_mock_session(project_id: str = "test-project-id"):
    """Return a mock ChameleonSession with api_get/post/put/delete stubs."""
    session = MagicMock()
    session.project_id = project_id

    # Default responses keyed by (service_type, path_prefix) so tests can
    # override individual calls via side_effect if needed.
    def _api_get(service_type, path):
        if service_type == "reservation":
            if "/os-hosts" in path:
                return {
                    "hosts": [
                        {
                            "node_type": "compute_haswell",
                            "cpu_arch": "x86_64",
                            "reservable": True,
                            "vcpus": 48,
                            "memory_mb": 131072,
                            "local_gb": 200,
                        },
                        {
                            "node_type": "compute_haswell",
                            "cpu_arch": "x86_64",
                            "reservable": True,
                            "vcpus": 48,
                            "memory_mb": 131072,
                            "local_gb": 200,
                        },
                        {
                            "node_type": "compute_skylake",
                            "cpu_arch": "x86_64",
                            "reservable": False,
                            "vcpus": 96,
                            "memory_mb": 196608,
                            "local_gb": 400,
                        },
                    ],
                }
            if "/leases/" in path:
                return {
                    "lease": {
                        "id": "lease-1",
                        "name": "test-lease",
                        "status": "ACTIVE",
                        "start_date": "2026-03-27 10:00",
                        "end_date": "2026-03-27 14:00",
                        "reservations": [
                            {
                                "id": "res-1",
                                "resource_type": "physical:host",
                                "min": 1,
                                "max": 1,
                                "status": "active",
                            }
                        ],
                    }
                }
            if "/leases" in path:
                return {
                    "leases": [
                        {
                            "id": "lease-1",
                            "name": "test-lease",
                            "status": "ACTIVE",
                            "start_date": "2026-03-27 10:00",
                            "end_date": "2026-03-27 14:00",
                            "reservations": [
                                {
                                    "id": "res-1",
                                    "resource_type": "physical:host",
                                    "min": 1,
                                    "max": 1,
                                    "status": "active",
                                    "resource_properties": '["==", "$node_type", "compute_haswell"]',
                                }
                            ],
                            "_site": "CHI@TACC",
                        }
                    ]
                }
        if service_type == "compute":
            if "/servers/detail" in path:
                return {
                    "servers": [
                        {
                            "id": "srv-1",
                            "name": "test-instance",
                            "status": "ACTIVE",
                            "image": {"id": "img-1"},
                            "created": "2026-03-27T10:00:00Z",
                            "addresses": {
                                "my-net": [
                                    {"addr": "10.0.0.1", "OS-EXT-IPS:type": "fixed"},
                                    {"addr": "129.114.1.1", "OS-EXT-IPS:type": "floating"},
                                ]
                            },
                        }
                    ]
                }
            if "/servers/" in path and "/action" not in path:
                return {
                    "server": {
                        "id": "srv-1",
                        "name": "test-instance",
                        "status": "ACTIVE",
                    }
                }
            if "/flavors/detail" in path:
                return {"flavors": [{"id": "bm", "name": "baremetal"}]}
        if service_type == "network":
            if "/v2.0/ports" in path:
                return {"ports": [{"id": "port-1", "device_id": "srv-1", "network_id": "net-1"}]}
            if "/v2.0/networks" in path:
                return {
                    "networks": [
                        {
                            "id": "net-1",
                            "name": "test-net",
                            "status": "ACTIVE",
                            "shared": False,
                            "project_id": project_id,
                            "subnets": ["sub-1"],
                            "provider:segmentation_id": 200,
                        },
                        {
                            "id": "ext-net-1",
                            "name": "public",
                            "status": "ACTIVE",
                            "router:external": True,
                        },
                    ]
                }
            if "/v2.0/subnets" in path:
                return {
                    "subnets": [
                        {
                            "id": "sub-1",
                            "cidr": "192.168.1.0/24",
                            "name": "test-subnet",
                        }
                    ]
                }
        if service_type == "image":
            return {
                "images": [
                    {
                        "id": "img-1",
                        "name": "CC-Ubuntu22.04",
                        "status": "active",
                        "size": 2147483648,
                        "created_at": "2026-01-01T00:00:00Z",
                        "visibility": "public",
                    }
                ]
            }
        return {}

    def _api_post(service_type, path, body=None):
        if service_type == "reservation" and "/leases" in path:
            return {
                "lease": {
                    "id": "new-lease-1",
                    "name": body.get("name", "test") if body else "test",
                    "status": "PENDING",
                    "start_date": "2026-03-27 10:00",
                    "end_date": "2026-03-27 14:00",
                    "reservations": body.get("reservations", []) if body else [],
                }
            }
        if service_type == "compute" and "/servers" in path and "/action" not in path:
            return {
                "server": {
                    "id": "new-srv-1",
                    "name": "new-instance",
                    "status": "BUILD",
                }
            }
        if service_type == "compute" and "/action" in path:
            return {}
        if service_type == "network" and "/v2.0/networks" in path:
            return {"network": {"id": "new-net-1", "name": "my-net", "status": "ACTIVE", "shared": False}}
        if service_type == "network" and "/v2.0/subnets" in path:
            return {"subnet": {"id": "new-sub-1", "cidr": "10.0.0.0/24", "name": "my-net-subnet"}}
        if service_type == "network" and "/v2.0/floatingips" in path:
            return {"floatingip": {"id": "fip-1", "floating_ip_address": "129.114.2.2"}}
        return {}

    def _api_put(service_type, path, body=None):
        if service_type == "reservation" and "/leases/" in path:
            return {
                "lease": {
                    "id": "lease-1",
                    "name": "test-lease",
                    "status": "ACTIVE",
                    "end_date": "2026-03-27 16:00",
                }
            }
        return {}

    def _api_delete(service_type, path):
        return {}

    session.api_get = MagicMock(side_effect=_api_get)
    session.api_post = MagicMock(side_effect=_api_post)
    session.api_put = MagicMock(side_effect=_api_put)
    session.api_delete = MagicMock(side_effect=_api_delete)
    session.get_token = MagicMock(return_value="fake-token")
    return session


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _chameleon_patches():
    """Patch the chameleon route guards and session factory for all tests."""
    mock_session = _make_mock_session()

    with patch("app.routes.chameleon._require_enabled", return_value=None), \
         patch("app.routes.chameleon.get_session", return_value=mock_session), \
         patch("app.routes.chameleon.is_configured", return_value=True), \
         patch("app.routes.chameleon.get_configured_sites", return_value=["CHI@TACC"]), \
         patch("app.routes.chameleon.run_in_chi_pool", side_effect=lambda fn, *a: fn(*a)):
        # run_in_chi_pool is replaced with synchronous execution
        yield mock_session


@pytest.fixture(autouse=True)
def _clear_drafts():
    """Clear the in-memory draft/slice stores between tests."""
    from app.routes.chameleon import _chameleon_slices, _chameleon_slice_nodes
    _chameleon_slices.clear()
    _chameleon_slice_nodes.clear()
    yield
    _chameleon_slices.clear()
    _chameleon_slice_nodes.clear()


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

class TestChameleonStatus:
    def test_status_returns_enabled(self, client):
        with patch("app.settings_manager.is_chameleon_enabled", return_value=True), \
             patch("app.settings_manager.get_chameleon_sites", return_value={"CHI@TACC": {"auth_url": "https://chi.tacc.utexas.edu:5000/v3"}}), \
             patch("app.settings_manager.is_chameleon_site_configured", return_value=True):
            resp = client.get("/api/chameleon/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert data["configured"] is True
        assert "CHI@TACC" in data["sites"]

    def test_status_disabled(self, client):
        with patch("app.settings_manager.is_chameleon_enabled", return_value=False):
            resp = client.get("/api/chameleon/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False


# ---------------------------------------------------------------------------
# Sites & Resources
# ---------------------------------------------------------------------------

class TestChameleonSites:
    def test_list_sites(self, client):
        with patch("app.settings_manager.get_chameleon_sites", return_value={
                "CHI@TACC": {"auth_url": "https://chi.tacc.utexas.edu:5000/v3"}
             }), \
             patch("app.settings_manager.is_chameleon_site_configured", return_value=True):
            resp = client.get("/api/chameleon/sites")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["name"] == "CHI@TACC"
        assert data[0]["configured"] is True

    def test_site_availability(self, client):
        resp = client.get("/api/chameleon/sites/CHI@TACC/availability")
        assert resp.status_code == 200
        data = resp.json()
        assert "hosts" in data
        assert "flavors" in data
        assert data["site"] == "CHI@TACC"

    def test_site_node_types(self, client):
        resp = client.get("/api/chameleon/sites/CHI@TACC/node-types")
        assert resp.status_code == 200
        data = resp.json()
        assert data["site"] == "CHI@TACC"
        assert len(data["node_types"]) > 0
        # compute_haswell has 2 hosts (both reservable)
        haswell = next(t for t in data["node_types"] if t["node_type"] == "compute_haswell")
        assert haswell["total"] == 2
        assert haswell["reservable"] == 2

    def test_site_node_types_detail(self, client):
        resp = client.get("/api/chameleon/sites/CHI@TACC/node-types/detail")
        assert resp.status_code == 200
        data = resp.json()
        assert data["site"] == "CHI@TACC"
        haswell = next(t for t in data["node_types"] if t["node_type"] == "compute_haswell")
        assert haswell["cpu_arch"] == "x86_64"
        assert haswell["cpu_count"] == 48
        assert haswell["ram_gb"] == 128

    def test_site_node_types_detail_query_compat(self, client):
        resp = client.get("/api/chameleon/sites/CHI@TACC/node-types?detail=true")
        assert resp.status_code == 200
        data = resp.json()
        haswell = next(t for t in data["node_types"] if t["node_type"] == "compute_haswell")
        assert haswell["cpu_count"] == 48
        assert haswell["ram_gb"] == 128

    def test_site_images(self, client):
        resp = client.get("/api/chameleon/sites/CHI@TACC/images")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["name"] == "CC-Ubuntu22.04"


# ---------------------------------------------------------------------------
# Leases
# ---------------------------------------------------------------------------

class TestChameleonLeases:
    def test_list_leases(self, client):
        resp = client.get("/api/chameleon/leases")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["id"] == "lease-1"
        assert data[0]["_site"] == "CHI@TACC"

    def test_list_leases_by_site(self, client):
        resp = client.get("/api/chameleon/leases?site=CHI@TACC")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_get_lease(self, client):
        resp = client.get("/api/chameleon/leases/lease-1?site=CHI@TACC")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "lease-1"
        assert data["_site"] == "CHI@TACC"

    def test_create_lease(self, client):
        resp = client.post("/api/chameleon/leases", json={
            "site": "CHI@TACC",
            "name": "my-lease",
            "node_type": "compute_haswell",
            "node_count": 1,
            "duration_hours": 4,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "new-lease-1"
        assert data["_site"] == "CHI@TACC"

    def test_create_lease_with_start_date(self, client):
        resp = client.post("/api/chameleon/leases", json={
            "site": "CHI@TACC",
            "name": "future-lease",
            "node_type": "compute_haswell",
            "node_count": 2,
            "duration_hours": 8,
            "start_date": "2026-04-01T10:00:00Z",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "new-lease-1"

    def test_create_lease_network_resource(self, client):
        resp = client.post("/api/chameleon/leases", json={
            "site": "CHI@TACC",
            "name": "net-lease",
            "resource_type": "network",
            "network_name": "my-net",
            "duration_hours": 4,
        })
        assert resp.status_code == 200

    def test_create_lease_floating_ip_resource(self, client):
        resp = client.post("/api/chameleon/leases", json={
            "site": "CHI@TACC",
            "name": "fip-lease",
            "resource_type": "virtual:floatingip",
            "node_count": 2,
            "duration_hours": 4,
        })
        assert resp.status_code == 200

    def test_extend_lease(self, client):
        resp = client.put("/api/chameleon/leases/lease-1/extend", json={
            "site": "CHI@TACC",
            "hours": 2,
        })
        assert resp.status_code == 200

    def test_delete_lease(self, client):
        resp = client.delete("/api/chameleon/leases/lease-1?site=CHI@TACC")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "deleted"


# ---------------------------------------------------------------------------
# Instances
# ---------------------------------------------------------------------------

class TestChameleonInstances:
    def test_list_instances(self, client):
        resp = client.get("/api/chameleon/instances")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["id"] == "srv-1"
        assert data[0]["floating_ip"] == "129.114.1.1"
        assert "10.0.0.1" in data[0]["ip_addresses"]

    def test_list_instances_by_site(self, client):
        resp = client.get("/api/chameleon/instances?site=CHI@TACC")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_get_instance(self, client):
        resp = client.get("/api/chameleon/instances/srv-1?site=CHI@TACC")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "srv-1"

    def test_create_instance(self, client):
        resp = client.post("/api/chameleon/instances", json={
            "site": "CHI@TACC",
            "name": "my-instance",
            "image_id": "img-1",
            "reservation_id": "res-1",
            "lease_id": "lease-1",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "new-srv-1"

    def test_create_instance_with_network_and_key(self, client):
        resp = client.post("/api/chameleon/instances", json={
            "site": "CHI@TACC",
            "name": "full-instance",
            "image_id": "img-1",
            "reservation_id": "res-1",
            "key_name": "my-key",
            "network_id": "net-1",
        })
        assert resp.status_code == 200

    def test_create_instance_encodes_user_data_for_nova(self, client, _chameleon_patches):
        user_data = "#cloud-config\nruncmd:\n  - [ echo, ok ]\n"
        resp = client.post("/api/chameleon/instances", json={
            "site": "CHI@TACC",
            "name": "userdata-instance",
            "image_id": "img-1",
            "reservation_id": "res-1",
            "network_id": "net-1",
            "user_data": user_data,
        })
        assert resp.status_code == 200
        compute_posts = [
            call for call in _chameleon_patches.api_post.call_args_list
            if call.args[0] == "compute" and call.args[1] == "/servers"
        ]
        server_body = compute_posts[-1].args[2]
        encoded = server_body["server"]["user_data"]
        assert base64.b64decode(encoded).decode() == user_data

    def test_delete_instance(self, client):
        resp = client.delete("/api/chameleon/instances/srv-1?site=CHI@TACC")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "deleted"

    def test_reboot_instance(self, client):
        resp = client.post("/api/chameleon/instances/srv-1/reboot", json={
            "site": "CHI@TACC",
            "type": "SOFT",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "rebooting"

    def test_reboot_instance_hard(self, client):
        resp = client.post("/api/chameleon/instances/srv-1/reboot", json={
            "site": "CHI@TACC",
            "type": "HARD",
        })
        assert resp.status_code == 200

    def test_stop_instance(self, client):
        resp = client.post("/api/chameleon/instances/srv-1/stop", json={
            "site": "CHI@TACC",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "stopping"

    def test_start_instance(self, client):
        resp = client.post("/api/chameleon/instances/srv-1/start", json={
            "site": "CHI@TACC",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "starting"

    def test_associate_floating_ip(self, client):
        """Test allocating and associating a floating IP via Neutron."""
        resp = client.post("/api/chameleon/instances/srv-1/associate-ip", json={
            "site": "CHI@TACC",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["floating_ip"] == "129.114.2.2"
        assert data["instance_id"] == "srv-1"

    def test_disassociate_floating_ip(self, client):
        resp = client.post("/api/chameleon/instances/srv-1/disassociate-ip", json={
            "site": "CHI@TACC",
            "floating_ip": "129.114.5.5",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "disassociated"


# ---------------------------------------------------------------------------
# Networks
# ---------------------------------------------------------------------------

class TestChameleonNetworks:
    def test_list_networks(self, client):
        resp = client.get("/api/chameleon/networks")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["id"] == "net-1"
        assert data[0]["site"] == "CHI@TACC"
        assert len(data[0]["subnet_details"]) == 1

    def test_list_networks_by_site(self, client):
        resp = client.get("/api/chameleon/networks?site=CHI@TACC")
        assert resp.status_code == 200

    def test_create_network_simple(self, client):
        resp = client.post("/api/chameleon/networks", json={
            "site": "CHI@TACC",
            "name": "my-net",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "new-net-1"

    def test_create_network_with_cidr(self, client):
        resp = client.post("/api/chameleon/networks", json={
            "site": "CHI@TACC",
            "name": "my-net",
            "cidr": "10.0.0.0/24",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "new-net-1"
        assert len(data["subnet_details"]) == 1

    def test_create_vlan_network_includes_provider_fields(self, storage_dir):
        from app.routes.chameleon import create_network

        class Request:
            async def json(self):
                return {
                    "site": "CHI@TACC",
                    "name": "fp-l2-tacc-3301",
                    "vlan": 3301,
                    "physical_network": "physnet1",
                }

        async def _run_sync(fn, *args):
            return fn(*args)

        session = _make_mock_session()
        with patch("app.routes.chameleon._require_enabled", return_value=None), \
             patch("app.routes.chameleon.get_session", return_value=session), \
             patch("app.routes.chameleon.run_in_chi_pool", side_effect=_run_sync):
            data = asyncio.run(create_network(Request()))

        assert data["vlan"] == 3301
        body = session.api_post.call_args_list[-1].args[2]["network"]
        assert body["provider:network_type"] == "vlan"
        assert body["provider:segmentation_id"] == 3301
        assert body["provider:physical_network"] == "physnet1"

    def test_delete_network(self, client):
        resp = client.delete("/api/chameleon/networks/net-1?site=CHI@TACC")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "deleted"



def test_upload_chameleon_keypair_private_key(client, storage_dir, _chameleon_patches, monkeypatch):
    session = _chameleon_patches
    session.api_get = MagicMock(return_value={
        "keypairs": [{"keypair": {"name": "site-key", "fingerprint": "aa:bb"}}],
    })

    from app.routes import chameleon as chm

    def _write_fixture_key(path, private_key):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(private_key)
        path.chmod(0o600)
        return str(path)

    monkeypatch.setattr(chm, "_write_chameleon_private_key", _write_fixture_key)
    key_text = b"test-private-key-placeholder\n"
    resp = client.post(
        "/api/chameleon/keypairs/site-key/private-key?site=CHI@TACC",
        files={"private_key": ("site-key.pem", key_text, "text/plain")},
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "saved"
    assert data["name"] == "site-key"
    key_path = storage_dir / "fabric_config" / "chameleon_key_CHI@TACC_site-key"
    assert key_path.read_text() == key_text.decode("utf-8")
    assert oct(key_path.stat().st_mode & 0o777) == "0o600"

    list_resp = client.get("/api/chameleon/keypairs?site=CHI@TACC")
    assert list_resp.status_code == 200
    keypair = list_resp.json()[0]
    assert keypair["has_private_key"] is True
    assert keypair["private_key_path"] == str(key_path)

# ---------------------------------------------------------------------------
# VLAN Negotiation
# ---------------------------------------------------------------------------

class TestVLANNegotiation:
    def test_list_chameleon_facility_ports_maps_site_and_vlan(self, storage_dir):
        from app.routes.chameleon import list_chameleon_facility_ports

        async def _run_sync(fn, *args):
            return fn(*args)

        with patch("app.routes.chameleon._require_enabled", return_value=None), \
             patch("app.routes.resources._fetch_facility_ports_locked", return_value=[
                 {
                     "name": "Chameleon-TACC",
                     "site": "TACC",
                     "interfaces": [{"name": "port1", "vlan_range": ["3301-3303"]}],
                 }
             ]), patch("app.routes.chameleon.run_in_chi_pool", side_effect=_run_sync):
            data = asyncio.run(list_chameleon_facility_ports(site="CHI@TACC"))

        assert data["chameleon_site"] == "CHI@TACC"
        assert data["fabric_site"] == "TACC"
        assert data["suggested_vlan"] == 3301
        assert data["facility_ports"][0]["name"] == "Chameleon-TACC"

    def test_negotiate_vlan_auto_site(self, client):
        with patch("app.routes.resources._fetch_facility_ports_locked", return_value=[
            {
                "site": "TACC",
                "interfaces": [{"vlan_range": ["200-210"]}],
            }
        ]):
            resp = client.post("/api/chameleon/negotiate-vlan", json={
                "chameleon_site": "CHI@TACC",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert "fabric_site" in data
        assert "chameleon_site" in data
        assert "suggested_vlan" in data

    def test_negotiate_vlan_explicit_site(self, client):
        with patch("app.routes.resources._fetch_facility_ports_locked", return_value=[
            {
                "site": "STAR",
                "interfaces": [{"vlan_range": ["300-310"]}],
            }
        ]):
            resp = client.post("/api/chameleon/negotiate-vlan", json={
                "fabric_site": "STAR",
                "chameleon_site": "CHI@UC",
            })
        assert resp.status_code == 200

    def test_negotiate_vlan_unknown_chameleon_site(self, client):
        resp = client.post("/api/chameleon/negotiate-vlan", json={
            "chameleon_site": "CHI@UNKNOWN",
        })
        assert resp.status_code == 400

    def test_prepare_draft_for_facility_port_l2_creates_vlan_network_and_attaches_node(self, storage_dir):
        from app.routes.chameleon import _chameleon_slices, prepare_draft_for_facility_port_l2

        draft_id = "chi-fp-l2"
        _chameleon_slices[draft_id] = {
            "id": draft_id,
            "name": "chi-fp",
            "site": "CHI@TACC",
            "nodes": [
                {
                    "id": "node-1",
                    "name": "router",
                    "site": "CHI@TACC",
                    "interfaces": [{"nic": 0, "network": {"id": "shared", "name": "sharednet1"}}, {"nic": 1, "network": None}],
                },
                {
                    "id": "node-2",
                    "name": "observer",
                    "site": "CHI@TACC",
                    "interfaces": [{"nic": 0, "network": {"id": "shared", "name": "sharednet1"}}],
                },
            ],
            "networks": [],
        }
        session = MagicMock()
        session.api_get.return_value = {"networks": []}
        session.api_post.return_value = {"network": {"id": "net-fp", "name": "fp-l2-chi-tacc-3301", "status": "ACTIVE"}}

        try:
            with patch("app.routes.resources._fetch_facility_ports_locked", return_value=[
                {
                    "name": "Chameleon-TACC",
                    "site": "TACC",
                    "interfaces": [{"name": "port1", "vlan_range": ["3301-3303"]}],
                }
            ]), patch("app.routes.chameleon.get_session", return_value=session):
                result = prepare_draft_for_facility_port_l2(
                    draft_id,
                    vlan=3301,
                    facility_port="Chameleon-TACC",
                    node_name="router",
                )

            assert result["vlan"] == 3301
            assert result["facility_port"] == "Chameleon-TACC"
            router = _chameleon_slices[draft_id]["nodes"][0]
            observer = _chameleon_slices[draft_id]["nodes"][1]
            assert router["interfaces"][1]["network"] == {"id": "net-fp", "name": "fp-l2-chi-tacc-3301"}
            assert all(iface["network"].get("name") != "fp-l2-chi-tacc-3301" for iface in observer["interfaces"])
            assert _chameleon_slices[draft_id]["networks"][0]["type"] == "facility_port_l2"
            assert _chameleon_slices[draft_id]["networks"][0]["vlan"] == 3301
        finally:
            _chameleon_slices.pop(draft_id, None)


# ---------------------------------------------------------------------------
# Drafts
# ---------------------------------------------------------------------------

class TestChameleonDrafts:
    def test_create_and_list_drafts(self, client):
        resp = client.post("/api/chameleon/drafts", json={
            "name": "my-experiment",
            "site": "CHI@TACC",
        })
        assert resp.status_code == 200
        draft = resp.json()
        assert draft["name"] == "my-experiment"
        assert draft["site"] == "CHI@TACC"
        draft_id = draft["id"]

        # List
        resp = client.get("/api/chameleon/drafts")
        assert resp.status_code == 200
        drafts = resp.json()
        assert len(drafts) == 1
        assert drafts[0]["id"] == draft_id

    def test_get_draft(self, client):
        resp = client.post("/api/chameleon/drafts", json={"name": "test"})
        draft_id = resp.json()["id"]

        resp = client.get(f"/api/chameleon/drafts/{draft_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "test"

    def test_get_draft_adopts_spawning_instance_for_planned_node(self, storage_dir):
        from app.routes.chameleon import _chameleon_slices, get_draft

        _chameleon_slices["chi-slice-spawning"] = {
            "id": "chi-slice-spawning",
            "name": "spawning",
            "state": "Active",
            "site": "CHI@TACC",
            "sites": ["CHI@TACC"],
            "nodes": [{
                "id": "node-1",
                "name": "spawning-server",
                "node_type": "compute_haswell",
                "image": "CC-Ubuntu22.04",
                "count": 1,
                "site": "CHI@TACC",
            }],
            "networks": [],
            "floating_ips": [],
            "resources": [{
                "resource_id": "lease-1",
                "provider": "chameleon",
                "type": "lease",
                "id": "lease-1",
                "lease_id": "lease-1",
                "name": "lease",
                "site": "CHI@TACC",
                "status": "ACTIVE",
                "reservations": [{"id": "reservation-1"}],
            }],
        }

        with patch("app.routes.chameleon._fetch_live_instances", new=AsyncMock(return_value=[{
            "id": "srv-spawning",
            "name": "spawning-server",
            "site": "CHI@TACC",
            "status": "SPAWNING",
            "metadata": {"lease_id": "lease-1"},
            "reservation_id": "reservation-1",
            "ip_addresses": [],
            "floating_ip": None,
        }])):
            draft = asyncio.run(get_draft("chi-slice-spawning"))

        instance = next(resource for resource in draft["resources"] if resource["type"] == "instance")
        assert instance["id"] == "srv-spawning"
        assert instance["status"] == "SPAWNING"
        assert instance["planned_node_id"] == "node-1"
        assert draft["state"] == "Deploying"
        assert draft["nodes"][0]["status"] == "SPAWNING"
        assert draft["nodes"][0]["instance_id"] == "srv-spawning"

    def test_get_draft_not_found(self, client):
        resp = client.get("/api/chameleon/drafts/nonexistent")
        assert resp.status_code == 404

    def test_delete_draft(self, client):
        resp = client.post("/api/chameleon/drafts", json={"name": "to-delete"})
        draft_id = resp.json()["id"]

        resp = client.delete(f"/api/chameleon/drafts/{draft_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

        # Confirm deleted
        resp = client.get(f"/api/chameleon/drafts/{draft_id}")
        assert resp.status_code == 404

    def test_delete_draft_not_found(self, client):
        resp = client.delete("/api/chameleon/drafts/nonexistent")
        assert resp.status_code == 404

    def test_add_and_remove_draft_node(self, client):
        resp = client.post("/api/chameleon/drafts", json={"name": "topo"})
        draft_id = resp.json()["id"]

        # Add node
        resp = client.post(f"/api/chameleon/drafts/{draft_id}/nodes", json={
            "name": "node1",
            "node_type": "compute_skylake",
            "image": "CC-Ubuntu22.04",
            "count": 2,
            "site": "CHI@TACC",
            "key_name": "project-key",
        })
        assert resp.status_code == 200
        draft = resp.json()
        assert len(draft["nodes"]) == 1
        node_id = draft["nodes"][0]["id"]
        assert draft["nodes"][0]["node_type"] == "compute_skylake"
        assert draft["nodes"][0]["count"] == 2
        assert draft["nodes"][0]["key_name"] == "project-key"

        # Clear the per-node key override back to the site default
        resp = client.put(f"/api/chameleon/drafts/{draft_id}/nodes/{node_id}", json={"key_name": ""})
        assert resp.status_code == 200
        assert resp.json()["nodes"][0]["key_name"] == ""

        # Remove node
        resp = client.delete(f"/api/chameleon/drafts/{draft_id}/nodes/{node_id}")
        assert resp.status_code == 200
        assert len(resp.json()["nodes"]) == 0

    def test_add_node_to_nonexistent_draft(self, client):
        resp = client.post("/api/chameleon/drafts/bad-id/nodes", json={"name": "n1"})
        assert resp.status_code == 404

    def test_remove_nonexistent_node(self, client):
        resp = client.post("/api/chameleon/drafts", json={"name": "topo"})
        draft_id = resp.json()["id"]
        resp = client.delete(f"/api/chameleon/drafts/{draft_id}/nodes/bad-node-id")
        assert resp.status_code == 404

    def test_add_and_remove_draft_network(self, client):
        resp = client.post("/api/chameleon/drafts", json={"name": "net-topo"})
        draft_id = resp.json()["id"]

        resp = client.post(f"/api/chameleon/drafts/{draft_id}/networks", json={
            "name": "my-net",
            "connected_nodes": [],
        })
        assert resp.status_code == 200
        draft = resp.json()
        assert len(draft["networks"]) == 1
        net_id = draft["networks"][0]["id"]

        resp = client.delete(f"/api/chameleon/drafts/{draft_id}/networks/{net_id}")
        assert resp.status_code == 200
        assert len(resp.json()["networks"]) == 0

    def test_remove_nonexistent_network(self, client):
        resp = client.post("/api/chameleon/drafts", json={"name": "topo"})
        draft_id = resp.json()["id"]
        resp = client.delete(f"/api/chameleon/drafts/{draft_id}/networks/bad-net-id")
        assert resp.status_code == 404

    def test_set_draft_floating_ips(self, client):
        resp = client.post("/api/chameleon/drafts", json={"name": "fip-test"})
        draft_id = resp.json()["id"]

        # Add a node first
        resp = client.post(f"/api/chameleon/drafts/{draft_id}/nodes", json={"name": "n1", "site": "CHI@TACC"})
        node_id = resp.json()["nodes"][0]["id"]

        # Set floating IPs
        resp = client.put(f"/api/chameleon/drafts/{draft_id}/floating-ips", json={
            "node_ids": [node_id],
        })
        assert resp.status_code == 200
        assert resp.json()["floating_ips"] == [{"node_id": node_id, "nic": 0}]

    def test_floating_ips_nonexistent_draft(self, client):
        resp = client.put("/api/chameleon/drafts/bad-id/floating-ips", json={"node_ids": []})
        assert resp.status_code == 404

    def test_draft_graph(self, client):
        resp = client.post("/api/chameleon/drafts", json={"name": "g-test", "site": "CHI@TACC"})
        draft_id = resp.json()["id"]

        # Add nodes and network for the graph
        client.post(f"/api/chameleon/drafts/{draft_id}/nodes", json={"name": "n1", "site": "CHI@TACC"})

        with patch("app.graph_builder.build_chameleon_slice_graph", return_value={"nodes": [], "edges": []}):
            resp = client.get(f"/api/chameleon/drafts/{draft_id}/graph")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Deploy draft
# ---------------------------------------------------------------------------

class TestDeployDraft:
    def test_deploy_draft(self, client):
        # Create a draft with a node
        resp = client.post("/api/chameleon/drafts", json={
            "name": "deploy-test",
            "site": "CHI@TACC",
        })
        draft_id = resp.json()["id"]
        client.post(f"/api/chameleon/drafts/{draft_id}/nodes", json={
            "name": "node1",
            "node_type": "compute_haswell",
            "site": "CHI@TACC",
        })

        resp = client.post(f"/api/chameleon/drafts/{draft_id}/deploy", json={
            "lease_name": "my-lease",
            "duration_hours": 8,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["draft_id"] == draft_id
        assert len(data["leases"]) == 1
        assert data["leases"][0]["lease_id"] == "new-lease-1"
        assert data["leases"][0]["site"] == "CHI@TACC"

    def test_deploy_draft_not_found(self, client):
        resp = client.post("/api/chameleon/drafts/bad-id/deploy", json={
            "lease_name": "x",
        })
        assert resp.status_code == 404

    def test_deploy_draft_no_nodes(self, client):
        resp = client.post("/api/chameleon/drafts", json={"name": "empty"})
        draft_id = resp.json()["id"]
        resp = client.post(f"/api/chameleon/drafts/{draft_id}/deploy", json={
            "lease_name": "x",
        })
        assert resp.status_code == 400

    def test_deploy_draft_with_networks_and_floating_ips(self, client):
        resp = client.post("/api/chameleon/drafts", json={
            "name": "full-deploy",
            "site": "CHI@TACC",
        })
        draft_id = resp.json()["id"]
        # Add node
        resp = client.post(f"/api/chameleon/drafts/{draft_id}/nodes", json={
            "name": "n1", "node_type": "compute_haswell", "site": "CHI@TACC",
        })
        node_id = resp.json()["nodes"][0]["id"]
        # Add network
        client.post(f"/api/chameleon/drafts/{draft_id}/networks", json={
            "name": "net1", "connected_nodes": [node_id],
        })
        # Add floating IP
        client.put(f"/api/chameleon/drafts/{draft_id}/floating-ips", json={
            "node_ids": [node_id],
        })

        resp = client.post(f"/api/chameleon/drafts/{draft_id}/deploy", json={
            "lease_name": "full-lease",
            "duration_hours": 4,
        })
        assert resp.status_code == 200

    def test_full_deploy_launches_instance_without_sleep_when_lease_is_active(self, storage_dir, _chameleon_patches):
        session = _chameleon_patches
        draft_id = "draft-full-orchestration"
        node_id = "node-server1"

        from app.routes.chameleon import _chameleon_slices, deploy_draft
        _chameleon_slices[draft_id] = {
            "id": draft_id,
            "name": "full-orchestration",
            "provider": "chameleon",
            "state": "Draft",
            "created": "2026-06-08T12:00:00Z",
            "updated": "2026-06-08T12:00:00Z",
            "site": "CHI@TACC",
            "sites": ["CHI@TACC"],
            "nodes": [{
                "id": node_id,
                "name": "server1",
                "node_type": "compute_haswell",
                "image": "CC-Ubuntu22.04",
                "site": "CHI@TACC",
                "count": 1,
            }],
            "networks": [],
            "floating_ips": [],
            "resources": [],
        }

        with patch("asyncio.sleep", new_callable=AsyncMock) as sleep_mock, \
             patch("app.routes.chameleon._ensure_keypair_at_site", return_value={"name": "loomai-key"}), \
             patch("app.routes.chameleon.ensure_routable_network", return_value={
                 "network_id": "fallback-net-1",
                 "network_name": "sharednet1",
                 "type": "provider",
             }):
            data = asyncio.run(deploy_draft(draft_id, {
                "lease_name": "full-orchestration-lease",
                "duration_hours": 4,
                "full_deploy": True,
            }))

        sleep_mock.assert_not_awaited()
        assert data["leases"][0]["status"] == "ACTIVE"
        assert data["leases"][0]["reservations"][0]["id"] == "res-1"

        stored = _chameleon_slices[draft_id]
        lease = next(r for r in stored["resources"] if r["type"] == "lease")
        instance = next(r for r in stored["resources"] if r["type"] == "instance")
        assert lease["id"] == "new-lease-1"
        assert lease["status"] == "ACTIVE"
        assert instance["id"] == "new-srv-1"
        assert instance["name"] == "server1"
        assert instance["planned_node_id"] == node_id
        assert instance["planned_node_name"] == "server1"
        assert instance["lease_id"] == "new-lease-1"
        assert instance["status"] == "BUILD"

        compute_posts = [
            call for call in session.api_post.call_args_list
            if call.args[:2] == ("compute", "/servers")
        ]
        assert len(compute_posts) == 1
        body = compute_posts[0].args[2]
        assert body["os:scheduler_hints"]["reservation"] == "res-1"
        assert body["server"]["name"] == "server1"
        assert body["server"]["imageRef"] == "img-1"
        assert body["server"]["key_name"] == "loomai-key"
        assert body["server"]["networks"] == [{"uuid": "fallback-net-1"}]


# ---------------------------------------------------------------------------
# Schedule Calendar
# ---------------------------------------------------------------------------

class TestScheduleCalendar:
    def test_calendar(self, client):
        resp = client.get("/api/chameleon/schedule/calendar")
        assert resp.status_code == 200
        data = resp.json()
        assert "time_range" in data
        assert "sites" in data
        assert len(data["sites"]) == 1
        assert data["sites"][0]["name"] == "CHI@TACC"

    def test_calendar_with_days(self, client):
        resp = client.get("/api/chameleon/schedule/calendar?days=7")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Chameleon Slice Nodes
# ---------------------------------------------------------------------------

class TestChameleonSliceNodes:
    def test_get_empty_slice_nodes(self, client):
        resp = client.get("/api/chameleon/slice-nodes/test-slice")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_add_and_get_slice_node(self, client):
        resp = client.post("/api/chameleon/slice-nodes/test-slice", json={
            "name": "chi-node1",
            "site": "CHI@TACC",
            "node_type": "compute_skylake",
        })
        assert resp.status_code == 200
        nodes = resp.json()["chameleon_nodes"]
        assert len(nodes) == 1
        assert nodes[0]["name"] == "chi-node1"

        # Verify via GET
        resp = client.get("/api/chameleon/slice-nodes/test-slice")
        assert len(resp.json()) == 1

    def test_remove_slice_node(self, client):
        client.post("/api/chameleon/slice-nodes/test-slice", json={
            "name": "chi-node1",
        })
        resp = client.delete("/api/chameleon/slice-nodes/test-slice/chi-node1")
        assert resp.status_code == 200
        assert resp.json()["chameleon_nodes"] == []


# ---------------------------------------------------------------------------
# Connection test endpoint
# ---------------------------------------------------------------------------

class TestConnectionTest:
    def test_connection_test(self, client):
        with patch("app.settings_manager.get_chameleon_sites", return_value={"CHI@TACC": {}}), \
             patch("app.settings_manager.is_chameleon_site_configured", return_value=True):
            resp = client.post("/api/chameleon/test", json={"site": "CHI@TACC"})
        assert resp.status_code == 200
        data = resp.json()
        assert "CHI@TACC" in data
        assert data["CHI@TACC"]["ok"] is True


# ---------------------------------------------------------------------------
# Find Availability
# ---------------------------------------------------------------------------

class TestFindAvailability:
    def test_find_availability_available_now(self, client):
        resp = client.post("/api/chameleon/find-availability", json={
            "site": "CHI@TACC",
            "node_type": "compute_haswell",
            "node_count": 1,
            "duration_hours": 4,
        })
        assert resp.status_code == 200
        data = resp.json()
        # 2 haswell hosts, 1 reserved via active lease = 1 available
        # The mock lease has max=1, so reserved_now=1, available_now=1
        assert data["total"] == 2

    def test_find_availability_not_enough_exist(self, client):
        resp = client.post("/api/chameleon/find-availability", json={
            "site": "CHI@TACC",
            "node_type": "compute_haswell",
            "node_count": 10,
            "duration_hours": 4,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data
        assert "Only" in data["error"]


# ---------------------------------------------------------------------------
# Import reservation
# ---------------------------------------------------------------------------

class TestChameleonImportReservation:
    def test_import_reservation_matches_planned_node_name(self, client):
        from app.routes.chameleon import _chameleon_slices

        _chameleon_slices["chi-slice-test"] = {
            "id": "chi-slice-test",
            "name": "test",
            "state": "Draft",
            "nodes": [{
                "id": "node-1",
                "name": "test-instance",
                "node_type": "compute_haswell",
                "image": "CC-Ubuntu22.04",
                "count": 1,
                "site": "CHI@TACC",
            }],
            "networks": [],
            "floating_ips": [],
            "resources": [],
        }

        resp = client.post(
            "/api/chameleon/slices/chi-slice-test/import-reservation",
            json={"site": "CHI@TACC", "lease_id": "lease-1"},
        )

        assert resp.status_code == 200
        assert resp.json()["imported"] == 1
        resource = next(
            r for r in _chameleon_slices["chi-slice-test"]["resources"]
            if r["type"] == "instance"
        )
        assert resource["id"] == "srv-1"
        assert resource["planned_node_id"] == "node-1"

    def test_import_reservation_supports_manual_instance_ids(self, client):
        from app.routes.chameleon import _chameleon_slices

        _chameleon_slices["chi-slice-manual"] = {
            "id": "chi-slice-manual",
            "name": "manual",
            "state": "Draft",
            "nodes": [],
            "networks": [],
            "floating_ips": [],
            "resources": [],
        }

        resp = client.post(
            "/api/chameleon/slices/chi-slice-manual/import-reservation",
            json={"site": "CHI@TACC", "lease_id": "lease-1", "instance_ids": ["srv-1"]},
        )

        assert resp.status_code == 200
        assert resp.json()["imported"] == 1
        resource = next(
            r for r in _chameleon_slices["chi-slice-manual"]["resources"]
            if r["type"] == "instance"
        )
        assert resource["name"] == "test-instance"


class TestChameleonResourceMembership:
    def test_add_resource_updates_status_in_place(self, storage_dir):
        from app.routes.chameleon import _chameleon_slices, add_chameleon_slice_resource

        _chameleon_slices["chi-slice-status"] = {
            "id": "chi-slice-status",
            "name": "status",
            "state": "Deploying",
            "site": "CHI@TACC",
            "nodes": [],
            "networks": [],
            "floating_ips": [],
            "resources": [{
                "resource_id": "res-existing",
                "provider": "chameleon",
                "type": "lease",
                "id": "lease-1",
                "provider_id": "lease-1",
                "name": "lease",
                "site": "CHI@TACC",
                "status": "DEPLOYING",
            }],
        }

        class Request:
            async def json(self):
                return {"type": "lease", "id": "lease-1", "name": "lease", "site": "CHI@TACC", "status": "ACTIVE"}

        updated = asyncio.run(add_chameleon_slice_resource("chi-slice-status", Request()))
        resources = updated["resources"]
        assert len(resources) == 1
        assert resources[0]["resource_id"] == "res-existing"
        assert resources[0]["status"] == "ACTIVE"

    def test_add_active_instance_merges_into_planned_node_and_graph(self, storage_dir):
        from app.routes.chameleon import _chameleon_slices, add_chameleon_slice_resource, get_draft_graph

        _chameleon_slices["chi-slice-merge"] = {
            "id": "chi-slice-merge",
            "name": "merge",
            "state": "Deploying",
            "site": "CHI@TACC",
            "nodes": [{
                "id": "node-1",
                "name": "chameleon-ssh-node1",
                "node_type": "compute_haswell",
                "image": "CC-Ubuntu22.04",
                "count": 1,
                "site": "CHI@TACC",
            }],
            "networks": [],
            "floating_ips": [],
            "resources": [],
        }

        class Request:
            async def json(self):
                return {
                    "type": "instance",
                    "id": "srv-1",
                    "name": "srv-runtime-name",
                    "site": "CHI@TACC",
                    "status": "ACTIVE",
                    "floating_ip": "129.114.1.10",
                    "ip_addresses": ["10.0.0.5"],
                    "planned_node_name": "chameleon-ssh-node1",
                    "ssh_user": "cc",
                }

        updated = asyncio.run(add_chameleon_slice_resource("chi-slice-merge", Request()))
        merged = updated["nodes"][0]
        assert merged["status"] == "ACTIVE"
        assert merged["instance_id"] == "srv-1"
        assert merged["floating_ip"] == "129.114.1.10"
        assert merged["management_ip"] == "129.114.1.10"
        assert merged["ssh_command"] == "ssh cc@129.114.1.10"

        with patch("app.routes.chameleon._fetch_live_instances", new=AsyncMock(return_value=[])):
            graph = asyncio.run(get_draft_graph("chi-slice-merge"))
        instance_nodes = [
            node for node in graph["nodes"]
            if node["data"].get("element_type") == "chameleon_instance"
        ]
        assert len(instance_nodes) == 1
        assert instance_nodes[0]["data"]["status"] == "ACTIVE"
        assert instance_nodes[0]["data"]["instance_id"] == "srv-1"

    def test_add_resource_defaults_to_managed(self, storage_dir):
        from app.routes.chameleon import _chameleon_slices, add_chameleon_slice_resource

        _chameleon_slices["chi-slice-resource"] = {
            "id": "chi-slice-resource",
            "name": "resource",
            "state": "Draft",
            "site": "CHI@TACC",
            "nodes": [],
            "networks": [],
            "floating_ips": [],
            "resources": [],
        }

        class Request:
            async def json(self):
                return {"type": "instance", "id": "srv-managed", "name": "managed", "site": "CHI@TACC"}

        updated = asyncio.run(add_chameleon_slice_resource("chi-slice-resource", Request()))
        resource = updated["resources"][0]
        assert resource["provider"] == "chameleon"
        assert resource["provider_id"] == "srv-managed"
        assert resource["ownership"] == "managed"
        assert resource["delete_with_slice"] is True

    def test_add_imported_resource_prevents_cross_slice_duplicate(self, storage_dir):
        from fastapi import HTTPException

        from app.routes.chameleon import _chameleon_slices, add_chameleon_slice_resource

        base = {
            "state": "Draft",
            "site": "CHI@TACC",
            "nodes": [],
            "networks": [],
            "floating_ips": [],
            "resources": [],
        }
        _chameleon_slices["chi-slice-a"] = {"id": "chi-slice-a", "name": "a", **base}
        _chameleon_slices["chi-slice-b"] = {"id": "chi-slice-b", "name": "b", **base, "resources": []}

        class Request:
            async def json(self):
                return {"type": "instance", "id": "srv-shared", "name": "server", "ownership": "imported"}

        asyncio.run(add_chameleon_slice_resource("chi-slice-a", Request()))

        with pytest.raises(HTTPException) as exc:
            asyncio.run(add_chameleon_slice_resource("chi-slice-b", Request()))
        assert exc.value.status_code == 409

    def test_import_reservation_marks_resources_imported(self, storage_dir):
        from app.routes.chameleon import _chameleon_slices, import_reservation

        _chameleon_slices["chi-slice-imported"] = {
            "id": "chi-slice-imported",
            "name": "imported",
            "state": "Draft",
            "nodes": [],
            "networks": [],
            "floating_ips": [],
            "resources": [],
        }

        class Request:
            async def json(self):
                return {"site": "CHI@TACC", "lease_id": "lease-1", "instance_ids": ["srv-1"]}

        async def run_inline(fn, *args):
            return fn(*args)

        with patch("app.routes.chameleon.run_in_chi_pool", side_effect=run_inline):
            result = asyncio.run(import_reservation("chi-slice-imported", Request()))
        assert result["imported"] == 1
        resources = _chameleon_slices["chi-slice-imported"]["resources"]
        assert {r["type"] for r in resources} == {"lease", "instance"}
        assert all(r["ownership"] == "imported" for r in resources)
        assert all(r["delete_with_slice"] is False for r in resources)
        lease = next(r for r in resources if r["type"] == "lease")
        assert lease["reservations"][0]["id"] == "res-1"

    def test_removing_lease_resource_detaches_lease_group(self, storage_dir):
        from app.routes.chameleon import _chameleon_slices, remove_chameleon_slice_resource

        _chameleon_slices["chi-slice-group"] = {
            "id": "chi-slice-group",
            "name": "group",
            "state": "Active",
            "nodes": [{
                "id": "node-1",
                "name": "server-1",
                "node_type": "compute_haswell",
                "image": "CC-Ubuntu22.04",
                "count": 1,
                "site": "CHI@TACC",
                "status": "ACTIVE",
                "instance_id": "srv-1",
                "runtime_resource_id": "res-instance",
                "lease_id": "lease-1",
                "management_ip": "129.114.1.1",
            }],
            "networks": [],
            "floating_ips": [],
            "resources": [
                {
                    "resource_id": "res-lease",
                    "provider": "chameleon",
                    "type": "lease",
                    "id": "lease-1",
                    "provider_id": "lease-1",
                    "name": "test-lease",
                    "site": "CHI@TACC",
                },
                {
                    "resource_id": "res-instance",
                    "provider": "chameleon",
                    "type": "instance",
                    "id": "srv-1",
                    "provider_id": "srv-1",
                    "name": "server-1",
                    "site": "CHI@TACC",
                    "lease_id": "lease-1",
                    "planned_node_id": "node-1",
                },
                {
                    "resource_id": "res-other",
                    "provider": "chameleon",
                    "type": "instance",
                    "id": "srv-2",
                    "provider_id": "srv-2",
                    "name": "server-2",
                    "site": "CHI@TACC",
                    "lease_id": "lease-2",
                },
            ],
        }

        class Request:
            async def json(self):
                return {"resource_id": "res-lease"}

        updated = asyncio.run(remove_chameleon_slice_resource("chi-slice-group", Request()))
        assert [r["resource_id"] for r in updated["resources"]] == ["res-other"]
        node = updated["nodes"][0]
        assert "instance_id" not in node
        assert "runtime_resource_id" not in node
        assert "management_ip" not in node
        assert "lease_id" not in node


# ---------------------------------------------------------------------------
# Graph endpoint
# ---------------------------------------------------------------------------

class TestChameleonGraph:
    def test_chameleon_graph(self, client):
        with patch("app.graph_builder.build_chameleon_elements", return_value={"nodes": [], "edges": []}):
            resp = client.get("/api/chameleon/graph")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class TestHelperFunctions:
    def test_int_or(self):
        from app.routes.chameleon import _int_or
        assert _int_or(42) == 42
        assert _int_or("10") == 10
        assert _int_or(None) == 0
        assert _int_or("bad", 5) == 5
        assert _int_or(None, 99) == 99

    def test_parse_vlan_ranges(self):
        from app.routes.chameleon import _parse_vlan_ranges
        result = _parse_vlan_ranges(["200-205", "300", "bad"])
        assert result == {200, 201, 202, 203, 204, 205, 300}

    def test_parse_vlan_ranges_empty(self):
        from app.routes.chameleon import _parse_vlan_ranges
        assert _parse_vlan_ranges([]) == set()
        assert _parse_vlan_ranges(["", "  "]) == set()

    def test_parse_iso(self):
        from app.routes.chameleon import _parse_iso
        dt = _parse_iso("2026-03-27T10:00:00Z")
        assert dt is not None
        assert dt.year == 2026

        assert _parse_iso("") is None
        assert _parse_iso("bad-date") is None
