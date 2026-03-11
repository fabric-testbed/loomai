"""Tests for app.site_resolver — pure function with complex logic."""

import pytest

from app.site_resolver import (
    resolve_sites,
    _build_availability,
    _host_can_fit,
    _site_can_host,
    _site_can_host_group,
    _node_component_requirements,
    _int_or,
    _subtract_resources,
    _node_demand,
    _fallback_resolve,
)
from tests.fixtures.site_data import (
    default_sites,
    constrained_sites,
    gpu_only_sites,
    make_site,
    make_host,
    make_gpu_components,
)


# ---------------------------------------------------------------------------
# _int_or
# ---------------------------------------------------------------------------

class TestIntOr:
    def test_valid_int(self):
        assert _int_or(42, 0) == 42

    def test_string_int(self):
        assert _int_or("10", 0) == 10

    def test_none_returns_default(self):
        assert _int_or(None, 5) == 5

    def test_negative_returns_default(self):
        assert _int_or(-1, 5) == 5

    def test_non_numeric_returns_default(self):
        assert _int_or("abc", 0) == 0


# ---------------------------------------------------------------------------
# _build_availability
# ---------------------------------------------------------------------------

class TestBuildAvailability:
    def test_active_sites_included(self):
        sites = [make_site("RENC", cores=100, ram=400, disk=2000)]
        avail = _build_availability(sites)
        assert "RENC" in avail
        assert avail["RENC"]["cores"] == 100
        assert avail["RENC"]["ram"] == 400

    def test_inactive_sites_excluded(self):
        sites = [make_site("DOWN", state="Maintenance")]
        avail = _build_availability(sites)
        assert "DOWN" not in avail

    def test_component_availability_mapped(self):
        sites = [make_site("GPU-SITE", components=make_gpu_components(rtx=3))]
        avail = _build_availability(sites)
        assert avail["GPU-SITE"]["components"]["GPU_RTX6000"] == 3

    def test_hosts_included(self):
        sites = [make_site("RENC", hosts=[make_host("w1", cores=32)])]
        avail = _build_availability(sites)
        assert len(avail["RENC"]["hosts"]) == 1
        assert avail["RENC"]["hosts"][0]["cores"] == 32


# ---------------------------------------------------------------------------
# _node_component_requirements
# ---------------------------------------------------------------------------

class TestNodeComponentRequirements:
    def test_no_components(self):
        assert _node_component_requirements({"components": []}) == {}

    def test_nic_basic_not_tracked(self):
        # NIC_Basic uses SharedNIC — not in COMPONENT_RESOURCE_MAP
        reqs = _node_component_requirements({
            "components": [{"model": "NIC_Basic"}]
        })
        assert reqs == {}

    def test_gpu_tracked(self):
        reqs = _node_component_requirements({
            "components": [{"model": "GPU_RTX6000"}, {"model": "GPU_RTX6000"}]
        })
        assert reqs == {"GPU_RTX6000": 2}

    def test_mixed_components(self):
        reqs = _node_component_requirements({
            "components": [
                {"model": "GPU_TeslaT4"},
                {"model": "NIC_ConnectX_6"},
            ]
        })
        assert reqs == {"GPU_TeslaT4": 1, "NIC_ConnectX_6": 1}


# ---------------------------------------------------------------------------
# _host_can_fit
# ---------------------------------------------------------------------------

class TestHostCanFit:
    def test_fits(self):
        host = {"cores": 32, "ram": 128, "disk": 500, "components": {}}
        assert _host_can_fit(host, 4, 16, 50, {}) is True

    def test_not_enough_cores(self):
        host = {"cores": 2, "ram": 128, "disk": 500, "components": {}}
        assert _host_can_fit(host, 4, 16, 50, {}) is False

    def test_not_enough_ram(self):
        host = {"cores": 32, "ram": 8, "disk": 500, "components": {}}
        assert _host_can_fit(host, 4, 16, 50, {}) is False

    def test_not_enough_disk(self):
        host = {"cores": 32, "ram": 128, "disk": 20, "components": {}}
        assert _host_can_fit(host, 4, 16, 50, {}) is False

    def test_component_check(self):
        host = {"cores": 32, "ram": 128, "disk": 500,
                "components": {"GPU_RTX6000": 1}}
        assert _host_can_fit(host, 4, 16, 50, {"GPU_RTX6000": 1}) is True
        assert _host_can_fit(host, 4, 16, 50, {"GPU_RTX6000": 2}) is False


# ---------------------------------------------------------------------------
# _site_can_host
# ---------------------------------------------------------------------------

class TestSiteCanHost:
    def test_site_with_enough_resources(self):
        avail = {"cores": 100, "ram": 400, "disk": 2000,
                 "components": {}, "hosts": []}
        assert _site_can_host(avail, 4, 16, 50, {}) is True

    def test_site_insufficient_cores(self):
        avail = {"cores": 2, "ram": 400, "disk": 2000,
                 "components": {}, "hosts": []}
        assert _site_can_host(avail, 4, 16, 50, {}) is False

    def test_host_level_validation(self):
        # Site has enough total but no single host can fit
        avail = {
            "cores": 100, "ram": 400, "disk": 2000,
            "components": {}, "hosts": [
                {"cores": 2, "ram": 8, "disk": 100, "components": {}},
                {"cores": 2, "ram": 8, "disk": 100, "components": {}},
            ]
        }
        assert _site_can_host(avail, 4, 16, 50, {}) is False

    def test_skips_host_check_when_no_hosts(self):
        avail = {"cores": 100, "ram": 400, "disk": 2000,
                 "components": {}, "hosts": []}
        assert _site_can_host(avail, 4, 16, 50, {}) is True


# ---------------------------------------------------------------------------
# _site_can_host_group
# ---------------------------------------------------------------------------

class TestSiteCanHostGroup:
    def test_group_fits(self):
        avail = {
            "cores": 100, "ram": 400, "disk": 2000,
            "components": {}, "hosts": [
                {"cores": 32, "ram": 128, "disk": 500, "components": {}},
                {"cores": 32, "ram": 128, "disk": 500, "components": {}},
            ]
        }
        group = [
            {"cores": 4, "ram": 16, "disk": 50, "comp_reqs": {}},
            {"cores": 4, "ram": 16, "disk": 50, "comp_reqs": {}},
        ]
        assert _site_can_host_group(avail, group) is True

    def test_group_exceeds_site_totals(self):
        avail = {
            "cores": 4, "ram": 16, "disk": 50,
            "components": {}, "hosts": [
                {"cores": 32, "ram": 128, "disk": 500, "components": {}},
            ]
        }
        group = [
            {"cores": 4, "ram": 16, "disk": 50, "comp_reqs": {}},
            {"cores": 4, "ram": 16, "disk": 50, "comp_reqs": {}},
        ]
        assert _site_can_host_group(avail, group) is False


# ---------------------------------------------------------------------------
# _subtract_resources
# ---------------------------------------------------------------------------

class TestSubtractResources:
    def test_subtracts_basic(self):
        avail = {"cores": 100, "ram": 400, "disk": 2000, "components": {}}
        _subtract_resources(avail, 10, 32, 100, {})
        assert avail["cores"] == 90
        assert avail["ram"] == 368
        assert avail["disk"] == 1900

    def test_subtracts_components(self):
        avail = {"cores": 100, "ram": 400, "disk": 2000,
                 "components": {"GPU_RTX6000": 3}}
        _subtract_resources(avail, 0, 0, 0, {"GPU_RTX6000": 1})
        assert avail["components"]["GPU_RTX6000"] == 2


# ---------------------------------------------------------------------------
# resolve_sites: explicit sites
# ---------------------------------------------------------------------------

class TestResolveSitesExplicit:
    def test_explicit_site_passes_through(self):
        node_defs = [{"name": "n1", "site": "RENC", "cores": 2, "ram": 8, "disk": 10}]
        resolved, groups = resolve_sites(node_defs, default_sites())
        assert resolved[0]["site"] == "RENC"
        assert groups == {}

    def test_multiple_explicit_sites(self):
        node_defs = [
            {"name": "n1", "site": "RENC", "cores": 2, "ram": 8, "disk": 10},
            {"name": "n2", "site": "UCSD", "cores": 2, "ram": 8, "disk": 10},
        ]
        resolved, groups = resolve_sites(node_defs, default_sites())
        assert resolved[0]["site"] == "RENC"
        assert resolved[1]["site"] == "UCSD"


# ---------------------------------------------------------------------------
# resolve_sites: auto
# ---------------------------------------------------------------------------

class TestResolveSitesAuto:
    def test_auto_gets_assigned(self):
        node_defs = [{"name": "n1", "site": "auto", "cores": 2, "ram": 8, "disk": 10}]
        resolved, groups = resolve_sites(node_defs, default_sites())
        assert resolved[0]["site"] != "auto"
        assert resolved[0]["site"] in ["RENC", "UCSD", "TACC", "DALL", "STAR"]

    def test_empty_site_treated_as_auto(self):
        node_defs = [{"name": "n1", "site": "", "cores": 2, "ram": 8, "disk": 10}]
        resolved, _ = resolve_sites(node_defs, default_sites())
        assert resolved[0]["site"] != ""

    def test_auto_respects_resource_constraints(self):
        # Node needs 64 cores — only BIG site can fit
        node_defs = [{"name": "n1", "site": "auto", "cores": 64, "ram": 200, "disk": 500}]
        resolved, _ = resolve_sites(node_defs, constrained_sites())
        assert resolved[0]["site"] == "BIG"


# ---------------------------------------------------------------------------
# resolve_sites: @group co-location
# ---------------------------------------------------------------------------

class TestResolveSitesGroups:
    def test_group_nodes_get_same_site(self):
        node_defs = [
            {"name": "n1", "site": "@compute", "cores": 2, "ram": 8, "disk": 10},
            {"name": "n2", "site": "@compute", "cores": 2, "ram": 8, "disk": 10},
        ]
        resolved, groups = resolve_sites(node_defs, default_sites())
        assert resolved[0]["site"] == resolved[1]["site"]
        assert groups == {"n1": "@compute", "n2": "@compute"}

    def test_different_groups_can_get_different_sites(self):
        node_defs = [
            {"name": "n1", "site": "@group-a", "cores": 2, "ram": 8, "disk": 10},
            {"name": "n2", "site": "@group-b", "cores": 2, "ram": 8, "disk": 10},
        ]
        resolved, groups = resolve_sites(node_defs, default_sites())
        # Both should be resolved (not @group anymore)
        assert not resolved[0]["site"].startswith("@")
        assert not resolved[1]["site"].startswith("@")

    def test_group_respects_resource_constraints(self):
        # Two nodes that together need 8 cores — only BIG can fit both
        node_defs = [
            {"name": "n1", "site": "@pair", "cores": 4, "ram": 16, "disk": 40,
             "components": []},
            {"name": "n2", "site": "@pair", "cores": 4, "ram": 16, "disk": 40,
             "components": []},
        ]
        sites = constrained_sites()
        # SMALL has 4 cores total — can't fit both
        resolved, _ = resolve_sites(node_defs, sites)
        assert resolved[0]["site"] == "BIG"
        assert resolved[1]["site"] == "BIG"


# ---------------------------------------------------------------------------
# resolve_sites: GPU filtering
# ---------------------------------------------------------------------------

class TestResolveSitesGPU:
    def test_gpu_node_lands_on_gpu_site(self):
        node_defs = [
            {"name": "gpu1", "site": "auto", "cores": 4, "ram": 16, "disk": 50,
             "components": [{"model": "GPU_RTX6000"}]},
        ]
        resolved, _ = resolve_sites(node_defs, gpu_only_sites())
        assert resolved[0]["site"] == "HAS-GPU"


# ---------------------------------------------------------------------------
# resolve_sites: fallback
# ---------------------------------------------------------------------------

class TestResolveSitesFallback:
    def test_fallback_with_no_active_sites(self):
        # All sites in maintenance — should use fallback
        sites = [make_site("S1", state="Maintenance"), make_site("S2", state="Maintenance")]
        node_defs = [{"name": "n1", "site": "auto", "cores": 2, "ram": 8, "disk": 10}]
        resolved, _ = resolve_sites(node_defs, sites)
        # Fallback picks from site name list
        assert resolved[0]["site"] in ["S1", "S2"]

    def test_empty_sites_list(self):
        node_defs = [{"name": "n1", "site": "auto", "cores": 2, "ram": 8, "disk": 10}]
        resolved, _ = resolve_sites(node_defs, [])
        # No sites available — returns original (unchanged)
        assert resolved[0]["site"] == "auto"


# ---------------------------------------------------------------------------
# _fallback_resolve
# ---------------------------------------------------------------------------

class TestFallbackResolve:
    def test_auto_assigned(self):
        node_defs = [{"name": "n1", "site": "auto"}]
        resolved, groups = _fallback_resolve(node_defs, ["S1", "S2"])
        assert resolved[0]["site"] in ["S1", "S2"]
        assert groups == {}

    def test_group_co_located(self):
        node_defs = [
            {"name": "n1", "site": "@grp"},
            {"name": "n2", "site": "@grp"},
        ]
        resolved, groups = _fallback_resolve(node_defs, ["S1", "S2"])
        assert resolved[0]["site"] == resolved[1]["site"]
        assert groups == {"n1": "@grp", "n2": "@grp"}

    def test_explicit_untouched(self):
        node_defs = [{"name": "n1", "site": "RENC"}]
        resolved, _ = _fallback_resolve(node_defs, ["S1", "S2"])
        assert resolved[0]["site"] == "RENC"


# ---------------------------------------------------------------------------
# _node_demand
# ---------------------------------------------------------------------------

class TestNodeDemand:
    def test_defaults(self):
        assert _node_demand({}) == 2 + 8 + 10  # default cores+ram+disk

    def test_custom_values(self):
        assert _node_demand({"cores": 8, "ram": 32, "disk": 100}) == 140
