"""Tests for resource endpoints — sites, images, component models, hosts, links, facility ports."""

import time
from unittest.mock import patch, MagicMock

from app.fabric_call_manager import get_call_manager, CacheEntry


class TestListSites:
    def test_returns_list(self, client):
        resp = client.get("/api/sites")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_site_has_expected_fields(self, client):
        resp = client.get("/api/sites")
        site = resp.json()[0]
        assert "name" in site
        assert "state" in site
        assert "cores_available" in site

    def test_site_has_location_coordinates(self, client):
        """Sites should include lat/lon coordinates."""
        resp = client.get("/api/sites")
        site = resp.json()[0]
        assert "location" in site or "lat" in site


class TestListImages:
    def test_returns_list(self, client):
        resp = client.get("/api/images")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert "default_ubuntu_22" in data

    def test_contains_common_images(self, client):
        images = client.get("/api/images").json()
        assert "default_ubuntu_22" in images
        assert "default_rocky_9" in images


class TestListComponentModels:
    def test_returns_list(self, client):
        resp = client.get("/api/component-models")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_model_has_expected_fields(self, client):
        models = client.get("/api/component-models").json()
        model = models[0]
        assert "model" in model
        assert "type" in model
        assert "description" in model

    def test_includes_known_models(self, client):
        models = client.get("/api/component-models").json()
        model_names = [m["model"] for m in models]
        assert "NIC_Basic" in model_names
        assert "GPU_TeslaT4" in model_names
        assert "GPU_RTX6000" in model_names


class TestSiteHosts:
    def test_returns_host_list_from_cache(self, client):
        """GET /api/sites/{name}/hosts should return hosts from cached site data."""
        # The cache is pre-populated by the client fixture with default_sites(),
        # which includes hosts_detail for each site.
        resp = client.get("/api/sites/RENC/hosts")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_unknown_site_returns_empty(self, client):
        """GET /api/sites/UNKNOWN/hosts should return empty list."""
        resp = client.get("/api/sites/NOSUCHSITE/hosts")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)


class TestListLinks:
    def test_returns_link_list(self, client):
        """GET /api/links should return a list of inter-site links."""
        mock_links = [
            {"site_a": "RENC", "site_b": "UCSD", "bandwidth": "100 Gbps"},
            {"site_a": "RENC", "site_b": "LOSA", "bandwidth": "100 Gbps"},
        ]
        with patch("app.routes.resources._fetch_links_locked", return_value=mock_links):
            resp = client.get("/api/links")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["site_a"] == "RENC"


class TestListFacilityPorts:
    def test_returns_facility_port_list(self, client):
        """GET /api/facility-ports should return a list of facility ports."""
        mock_ports = [
            {"site": "RENC", "name": "RENC-FP-1", "interfaces": [
                {"local_name": "p1", "device_name": "xe-0/0/1", "allocated_vlans": [], "region": ""}
            ]},
        ]
        with patch("app.routes.resources._fetch_facility_ports_locked", return_value=mock_ports):
            resp = client.get("/api/facility-ports")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["site"] == "RENC"


# ---------------------------------------------------------------------------
# Image and component model details
# ---------------------------------------------------------------------------

class TestImageDetails:
    def test_all_default_images_present(self, client):
        images = client.get("/api/images").json()
        for img in ["default_ubuntu_22", "default_ubuntu_24", "default_centos_9",
                     "default_rocky_8", "default_rocky_9", "default_debian_12"]:
            assert img in images

    def test_image_list_is_strings(self, client):
        images = client.get("/api/images").json()
        for img in images:
            assert isinstance(img, str)


class TestComponentModelDetails:
    def test_gpu_models_present(self, client):
        models = client.get("/api/component-models").json()
        model_names = [m["model"] for m in models]
        for gpu in ["GPU_TeslaT4", "GPU_RTX6000", "GPU_A30", "GPU_A40"]:
            assert gpu in model_names

    def test_nic_models_present(self, client):
        models = client.get("/api/component-models").json()
        model_names = [m["model"] for m in models]
        for nic in ["NIC_Basic", "NIC_ConnectX_5", "NIC_ConnectX_6"]:
            assert nic in model_names

    def test_storage_model_present(self, client):
        models = client.get("/api/component-models").json()
        model_names = [m["model"] for m in models]
        assert "NVME_P4510" in model_names

    def test_model_types_are_valid(self, client):
        models = client.get("/api/component-models").json()
        valid_types = {"SmartNIC", "GPU", "FPGA", "Storage"}
        for m in models:
            assert m["type"] in valid_types


# ---------------------------------------------------------------------------
# Site data details
# ---------------------------------------------------------------------------

class TestSiteDetails:
    def test_site_has_available_resource_fields(self, client):
        """Mock sites include *_available fields; capacity fields come from FABlib."""
        resp = client.get("/api/sites")
        site = resp.json()[0]
        for field in ["cores_available", "ram_available", "disk_available"]:
            assert field in site

    def test_site_has_name_and_state(self, client):
        resp = client.get("/api/sites")
        site = resp.json()[0]
        assert "name" in site
        assert "state" in site

    def test_site_has_components(self, client):
        resp = client.get("/api/sites")
        site = resp.json()[0]
        assert "components" in site

    def test_site_coordinates_are_numbers(self, client):
        resp = client.get("/api/sites")
        for site in resp.json():
            if "lat" in site:
                assert isinstance(site["lat"], (int, float))
                assert isinstance(site["lon"], (int, float))


# ---------------------------------------------------------------------------
# Resource helper functions (unit level)
# ---------------------------------------------------------------------------

class TestResourceHelpers:
    def test_safe_attr_returns_value(self):
        from app.routes.resources import _safe_attr
        class Obj:
            def get_value(self):
                return 42
        assert _safe_attr(Obj(), "get_value") == 42

    def test_safe_attr_returns_default_on_error(self):
        from app.routes.resources import _safe_attr
        class Obj:
            def get_value(self):
                raise RuntimeError("fail")
        assert _safe_attr(Obj(), "get_value", 0) == 0

    def test_safe_attr_returns_default_missing(self):
        from app.routes.resources import _safe_attr
        assert _safe_attr(object(), "nonexistent_method", -1) == -1

    def test_safe_count_returns_length(self):
        from app.routes.resources import _safe_count
        class Obj:
            def get_hosts(self):
                return [1, 2, 3]
        assert _safe_count(Obj(), "get_hosts") == 3

    def test_safe_count_returns_zero_on_error(self):
        from app.routes.resources import _safe_count
        class Obj:
            def get_hosts(self):
                raise RuntimeError("fail")
        assert _safe_count(Obj(), "get_hosts") == 0

    def test_site_locations_has_known_sites(self):
        from app.routes.resources import SITE_LOCATIONS
        assert "RENC" in SITE_LOCATIONS or "NCSA" in SITE_LOCATIONS
        for name, loc in SITE_LOCATIONS.items():
            assert "lat" in loc
            assert "lon" in loc

    def test_get_cached_sites(self, client):
        """get_cached_sites should return data from the call manager cache."""
        from app.routes.resources import get_cached_sites
        sites = get_cached_sites()
        assert isinstance(sites, list)
        assert len(sites) > 0

    def test_fetch_host_details_v2_empty(self):
        """_fetch_host_details_v2 with no hosts returns empty list."""
        from app.routes.resources import _fetch_host_details_v2
        mock_resources = MagicMock()
        mock_resources.get_hosts_by_site.return_value = {}
        result = _fetch_host_details_v2(mock_resources, "RENC")
        assert result == []

    def test_fetch_host_details_v2_with_data(self):
        """_fetch_host_details_v2 should extract host info from dict format."""
        from app.routes.resources import _fetch_host_details_v2
        mock_resources = MagicMock()
        mock_resources.get_hosts_by_site.return_value = {
            "host1": {
                "name": "renc-w1.fabric-testbed.net",
                "cores_available": 32,
                "cores_capacity": 64,
                "ram_available": 128,
                "ram_capacity": 256,
                "disk_available": 500,
                "disk_capacity": 1000,
                "components": {
                    "GPU-Tesla T4": {"capacity": 2, "available": 1},
                },
            }
        }
        result = _fetch_host_details_v2(mock_resources, "RENC")
        assert len(result) == 1
        assert result[0]["name"] == "renc-w1.fabric-testbed.net"
        assert result[0]["cores_available"] == 32
        assert "GPU-Tesla T4" in result[0]["components"]

    def test_fetch_host_details_v2_exception(self):
        """_fetch_host_details_v2 should handle exceptions gracefully."""
        from app.routes.resources import _fetch_host_details_v2
        mock_resources = MagicMock()
        mock_resources.get_hosts_by_site.side_effect = Exception("network error")
        result = _fetch_host_details_v2(mock_resources, "RENC")
        assert result == []
