"""Tests for app.routes.schedule — resource scheduling endpoints."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from tests.fixtures.site_data import default_sites, make_site, make_host, make_gpu_components


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _future_iso(hours: int = 24) -> str:
    """Return an ISO timestamp N hours in the future."""
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _past_iso(hours: int = 24) -> str:
    """Return an ISO timestamp N hours in the past."""
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _make_active_slices(entries: list[dict]) -> list[dict]:
    """Build a list of active slice dicts for mocking _get_active_slices."""
    result = []
    for e in entries:
        result.append({
            "name": e.get("name", "test-slice"),
            "id": e.get("id", "uuid-1234"),
            "state": e.get("state", "StableOK"),
            "lease_end": e.get("lease_end", ""),
            "nodes": e.get("nodes", []),
        })
    return result


# ---------------------------------------------------------------------------
# Calendar endpoint
# ---------------------------------------------------------------------------

class TestCalendar:
    def test_calendar_returns_correct_structure(self, client):
        """Calendar returns time_range and sites list."""
        resp = client.get("/api/schedule/calendar?days=7")
        assert resp.status_code == 200
        data = resp.json()
        assert "time_range" in data
        assert "start" in data["time_range"]
        assert "end" in data["time_range"]
        assert "sites" in data
        assert isinstance(data["sites"], list)

    def test_calendar_includes_active_sites(self, client):
        """Active sites from cached data appear in calendar."""
        resp = client.get("/api/schedule/calendar")
        assert resp.status_code == 200
        data = resp.json()
        site_names = [s["name"] for s in data["sites"]]
        # default_sites includes RENC, UCSD, TACC, DALL, STAR (all Active)
        # MAINT is Maintenance and should be excluded
        assert "RENC" in site_names
        assert "UCSD" in site_names
        assert "MAINT" not in site_names

    def test_calendar_site_has_capacity_fields(self, client):
        """Each site in calendar has cores_capacity and cores_available."""
        resp = client.get("/api/schedule/calendar")
        data = resp.json()
        for site in data["sites"]:
            assert "cores_capacity" in site
            assert "cores_available" in site
            assert "ram_capacity" in site
            assert "ram_available" in site
            assert "slices" in site

    def test_calendar_with_active_slices(self, client):
        """Calendar includes slice data when slices are active."""
        mock_slices = _make_active_slices([{
            "name": "my-exp",
            "id": "slice-uuid-1",
            "state": "StableOK",
            "lease_end": _future_iso(48),
            "nodes": [
                {"name": "node1", "site": "RENC", "cores": 4, "ram": 16, "disk": 50},
            ],
        }])

        with patch("app.routes.schedule._get_active_slices",
                    new_callable=AsyncMock, return_value=mock_slices):
            resp = client.get("/api/schedule/calendar")

        assert resp.status_code == 200
        data = resp.json()
        renc = next((s for s in data["sites"] if s["name"] == "RENC"), None)
        assert renc is not None
        assert len(renc["slices"]) == 1
        assert renc["slices"][0]["name"] == "my-exp"
        assert len(renc["slices"][0]["nodes"]) == 1

    def test_calendar_no_slices(self, client):
        """Calendar works with no active slices."""
        with patch("app.routes.schedule._get_active_slices",
                    new_callable=AsyncMock, return_value=[]):
            resp = client.get("/api/schedule/calendar")

        assert resp.status_code == 200
        data = resp.json()
        for site in data["sites"]:
            assert site["slices"] == []

    def test_calendar_multi_site_slice(self, client):
        """A slice with nodes at different sites appears at each site."""
        mock_slices = _make_active_slices([{
            "name": "cross-site",
            "id": "cross-uuid",
            "state": "StableOK",
            "lease_end": _future_iso(24),
            "nodes": [
                {"name": "n1", "site": "RENC", "cores": 2, "ram": 8, "disk": 10},
                {"name": "n2", "site": "UCSD", "cores": 4, "ram": 16, "disk": 50},
            ],
        }])

        with patch("app.routes.schedule._get_active_slices",
                    new_callable=AsyncMock, return_value=mock_slices):
            resp = client.get("/api/schedule/calendar")

        data = resp.json()
        renc = next((s for s in data["sites"] if s["name"] == "RENC"), None)
        ucsd = next((s for s in data["sites"] if s["name"] == "UCSD"), None)
        assert renc is not None and len(renc["slices"]) == 1
        assert ucsd is not None and len(ucsd["slices"]) == 1
        # RENC should have only the RENC node
        assert renc["slices"][0]["nodes"][0]["name"] == "n1"
        assert ucsd["slices"][0]["nodes"][0]["name"] == "n2"


# ---------------------------------------------------------------------------
# Next-available endpoint
# ---------------------------------------------------------------------------

class TestNextAvailable:
    def test_requires_at_least_one_constraint(self, client):
        """Returns 400 if no resource constraints provided."""
        resp = client.get("/api/schedule/next-available")
        assert resp.status_code == 400

    def test_available_now_with_sufficient_resources(self, client):
        """Sites with enough resources appear in available_now."""
        with patch("app.routes.schedule._get_active_slices",
                    new_callable=AsyncMock, return_value=[]):
            resp = client.get("/api/schedule/next-available?cores=4&ram=16")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["available_now"]) > 0
        # RENC has 200 cores, 800 RAM — should be available
        renc = next((s for s in data["available_now"] if s["site"] == "RENC"), None)
        assert renc is not None

    def test_available_now_specific_site(self, client):
        """Filtering by site returns only that site."""
        with patch("app.routes.schedule._get_active_slices",
                    new_callable=AsyncMock, return_value=[]):
            resp = client.get("/api/schedule/next-available?cores=4&ram=16&site=RENC")

        assert resp.status_code == 200
        data = resp.json()
        sites = [s["site"] for s in data["available_now"]]
        assert sites == ["RENC"]

    def test_site_not_found(self, client):
        """Returns 404 for non-existent site."""
        with patch("app.routes.schedule._get_active_slices",
                    new_callable=AsyncMock, return_value=[]):
            resp = client.get("/api/schedule/next-available?cores=4&site=NONEXISTENT")

        assert resp.status_code == 404

    def test_projects_future_availability(self, client):
        """When resources are occupied, projects when they free up."""
        # Site has 2 cores available right now (6 consumed by big-job).
        # Capacity is 8 total. When big-job's lease expires, 6 cores free up
        # giving 8 total available.
        limited_sites = [
            {**make_site("TINY", cores=2, ram=8, disk=20),
             "cores_capacity": 8, "ram_capacity": 32, "disk_capacity": 100},
        ]
        lease_end = _future_iso(12)
        mock_slices = _make_active_slices([{
            "name": "big-job",
            "id": "big-uuid",
            "state": "StableOK",
            "lease_end": lease_end,
            "nodes": [
                {"name": "n1", "site": "TINY", "cores": 6, "ram": 24, "disk": 80},
            ],
        }])

        with patch("app.routes.schedule.get_cached_sites", return_value=limited_sites), \
             patch("app.routes.schedule._get_active_slices",
                   new_callable=AsyncMock, return_value=mock_slices):
            # Request 8 cores — only 2 available now, need to wait for big-job
            resp = client.get("/api/schedule/next-available?cores=8&ram=30&site=TINY")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["available_now"]) == 0
        assert len(data["available_soon"]) == 1
        soon = data["available_soon"][0]
        assert soon["site"] == "TINY"
        assert soon["earliest_time"] == lease_end
        assert soon["projected_cores"] >= 8

    def test_not_available_insufficient_capacity(self, client):
        """Sites that can never meet the requirement go to not_available."""
        limited_sites = [
            make_site("SMALL", cores=4, ram=16, disk=100),
        ]

        with patch("app.routes.schedule.get_cached_sites", return_value=limited_sites), \
             patch("app.routes.schedule._get_active_slices",
                   new_callable=AsyncMock, return_value=[]):
            # Request 128 cores — SMALL only has 4 capacity
            resp = client.get("/api/schedule/next-available?cores=128&site=SMALL")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["available_now"]) == 0
        assert len(data["available_soon"]) == 0
        assert len(data["not_available"]) == 1
        assert data["not_available"][0]["site"] == "SMALL"

    def test_no_slices_all_available(self, client):
        """With no slices, all sites with capacity are available_now."""
        with patch("app.routes.schedule._get_active_slices",
                    new_callable=AsyncMock, return_value=[]):
            resp = client.get("/api/schedule/next-available?cores=2")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["available_now"]) > 0
        assert len(data["available_soon"]) == 0

    def test_gpu_requirement(self, client):
        """GPU constraint filters to sites with that GPU type."""
        # Default sites: UCSD has RTX6000, TACC has RTX6000+T4
        with patch("app.routes.schedule._get_active_slices",
                    new_callable=AsyncMock, return_value=[]):
            resp = client.get("/api/schedule/next-available?cores=2&gpu=GPU_RTX6000")

        assert resp.status_code == 200
        data = resp.json()
        gpu_sites = {s["site"] for s in data["available_now"]}
        # UCSD and TACC have RTX6000
        assert "UCSD" in gpu_sites or "TACC" in gpu_sites
        # RENC, DALL, STAR do not have GPUs
        assert "RENC" not in gpu_sites
        assert "DALL" not in gpu_sites


# ---------------------------------------------------------------------------
# Alternatives endpoint
# ---------------------------------------------------------------------------

class TestAlternatives:
    def test_requires_at_least_one_constraint(self, client):
        """Returns 400 if no resource constraints provided."""
        resp = client.get("/api/schedule/alternatives")
        assert resp.status_code == 400

    def test_preferred_site_available(self, client):
        """If preferred site can meet demand, return early with no alternatives."""
        with patch("app.routes.schedule._get_active_slices",
                    new_callable=AsyncMock, return_value=[]):
            resp = client.get(
                "/api/schedule/alternatives?cores=4&ram=16&preferred_site=RENC"
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["preferred_available"] is True
        assert data["alternatives"] == []

    def test_suggests_different_sites(self, client):
        """When preferred site is full, suggests other sites."""
        limited_sites = [
            make_site("PREF", cores=2, ram=8, disk=50),
            make_site("OTHER", cores=100, ram=400, disk=2000),
        ]

        with patch("app.routes.schedule.get_cached_sites", return_value=limited_sites), \
             patch("app.routes.schedule._get_active_slices",
                   new_callable=AsyncMock, return_value=[]):
            resp = client.get(
                "/api/schedule/alternatives?cores=8&ram=32&preferred_site=PREF"
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["preferred_available"] is False
        diff_site = [a for a in data["alternatives"] if a["type"] == "different_site"]
        assert len(diff_site) == 1
        assert diff_site[0]["site"] == "OTHER"
        assert diff_site[0]["available_now"] is True

    def test_suggests_reduced_config(self, client):
        """When preferred site has partial resources, suggests reduced config."""
        limited_sites = [
            make_site("PREF", cores=8, ram=32, disk=200),
        ]

        with patch("app.routes.schedule.get_cached_sites", return_value=limited_sites), \
             patch("app.routes.schedule._get_active_slices",
                   new_callable=AsyncMock, return_value=[]):
            # Request 16 cores, 64 RAM — PREF only has 8/32
            resp = client.get(
                "/api/schedule/alternatives?cores=16&ram=64&preferred_site=PREF"
            )

        assert resp.status_code == 200
        data = resp.json()
        reduced = [a for a in data["alternatives"] if a["type"] == "reduced_config"]
        assert len(reduced) >= 1
        # Should suggest halving to 8 cores or 32 RAM
        suggestions = [r["suggestion"] for r in reduced]
        assert any("8 cores" in s for s in suggestions)

    def test_suggests_wait_time(self, client):
        """When resources will free up, suggests waiting."""
        # PREF currently has 4 cores / 16 RAM available (occupant using 12/48).
        # Capacity is 16/64. When occupant expires, 12 cores + 48 RAM free up.
        limited_sites = [
            {**make_site("PREF", cores=4, ram=16, disk=100),
             "cores_capacity": 16, "ram_capacity": 64, "disk_capacity": 400},
        ]
        lease_end = _future_iso(6)
        mock_slices = _make_active_slices([{
            "name": "occupant",
            "id": "occ-uuid",
            "state": "StableOK",
            "lease_end": lease_end,
            "nodes": [
                {"name": "n1", "site": "PREF", "cores": 12, "ram": 48, "disk": 300},
            ],
        }])

        with patch("app.routes.schedule.get_cached_sites", return_value=limited_sites), \
             patch("app.routes.schedule._get_active_slices",
                   new_callable=AsyncMock, return_value=mock_slices):
            resp = client.get(
                "/api/schedule/alternatives?cores=16&ram=64&preferred_site=PREF"
            )

        assert resp.status_code == 200
        data = resp.json()
        wait = [a for a in data["alternatives"] if a["type"] == "wait"]
        assert len(wait) == 1
        assert wait[0]["site"] == "PREF"
        assert wait[0]["earliest_time"] == lease_end
        assert "occupant" in wait[0]["freeing_slices"]

    def test_alternatives_sorted(self, client):
        """Alternatives are sorted: different_site first, then reduced, then wait."""
        # PREF currently has 4 cores / 16 RAM available (occupant using 8/32).
        # Capacity is 16/64. When occupant expires, resources free up.
        limited_sites = [
            {**make_site("PREF", cores=4, ram=16, disk=100),
             "cores_capacity": 16, "ram_capacity": 64, "disk_capacity": 200},
            make_site("OTHER", cores=100, ram=400, disk=2000),
        ]
        lease_end = _future_iso(6)
        mock_slices = _make_active_slices([{
            "name": "occupant",
            "id": "occ-uuid",
            "state": "StableOK",
            "lease_end": lease_end,
            "nodes": [
                {"name": "n1", "site": "PREF", "cores": 12, "ram": 48, "disk": 100},
            ],
        }])

        with patch("app.routes.schedule.get_cached_sites", return_value=limited_sites), \
             patch("app.routes.schedule._get_active_slices",
                   new_callable=AsyncMock, return_value=mock_slices):
            resp = client.get(
                "/api/schedule/alternatives?cores=16&ram=64&preferred_site=PREF"
            )

        assert resp.status_code == 200
        data = resp.json()
        types = [a["type"] for a in data["alternatives"]]
        # different_site should come before wait
        if "different_site" in types and "wait" in types:
            assert types.index("different_site") < types.index("wait")

    def test_no_preferred_site(self, client):
        """Works without a preferred site — still returns alternatives."""
        with patch("app.routes.schedule._get_active_slices",
                    new_callable=AsyncMock, return_value=[]):
            resp = client.get("/api/schedule/alternatives?cores=4&ram=16")

        assert resp.status_code == 200
        data = resp.json()
        assert data["preferred_site"] == ""
        assert data["preferred_available"] is False

    def test_all_slices_expired(self, client):
        """Slices with past lease_end don't affect availability projections."""
        limited_sites = [
            make_site("PREF", cores=4, ram=16, disk=100),
        ]
        # Slice with past lease — should not affect calculation
        mock_slices = _make_active_slices([{
            "name": "expired",
            "id": "exp-uuid",
            "state": "StableOK",
            "lease_end": _past_iso(24),
            "nodes": [
                {"name": "n1", "site": "PREF", "cores": 2, "ram": 8, "disk": 50},
            ],
        }])

        with patch("app.routes.schedule.get_cached_sites", return_value=limited_sites), \
             patch("app.routes.schedule._get_active_slices",
                   new_callable=AsyncMock, return_value=mock_slices):
            resp = client.get(
                "/api/schedule/alternatives?cores=4&ram=16&preferred_site=PREF"
            )

        assert resp.status_code == 200
        data = resp.json()
        # PREF has 4 cores/16 RAM available — should be enough
        assert data["preferred_available"] is True


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------

class TestParseIso:
    def test_valid_iso(self):
        from app.routes.schedule import _parse_iso
        dt = _parse_iso("2025-06-15T12:00:00+00:00")
        assert dt is not None
        assert dt.year == 2025

    def test_empty_string(self):
        from app.routes.schedule import _parse_iso
        assert _parse_iso("") is None

    def test_invalid_string(self):
        from app.routes.schedule import _parse_iso
        assert _parse_iso("not-a-date") is None

    def test_z_suffix(self):
        from app.routes.schedule import _parse_iso
        dt = _parse_iso("2025-06-15T12:00:00Z")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_naive_datetime(self):
        from app.routes.schedule import _parse_iso
        dt = _parse_iso("2025-06-15T12:00:00")
        assert dt is not None
        assert dt.tzinfo is not None  # Should be made UTC


class TestMeetsRequirements:
    def test_all_met(self):
        from app.routes.schedule import _meets_requirements
        avail = {"cores": 32, "ram": 128, "disk": 500}
        site = {"components": {}}
        assert _meets_requirements(avail, 4, 16, 50, site) is True

    def test_cores_insufficient(self):
        from app.routes.schedule import _meets_requirements
        avail = {"cores": 2, "ram": 128, "disk": 500}
        site = {"components": {}}
        assert _meets_requirements(avail, 4, 16, 50, site) is False

    def test_zero_constraints_always_pass(self):
        from app.routes.schedule import _meets_requirements
        avail = {"cores": 0, "ram": 0, "disk": 0}
        site = {"components": {}}
        assert _meets_requirements(avail, 0, 0, 0, site) is True
