"""Tests for GET /api/health and GET /api/health/detailed."""

from unittest.mock import patch, MagicMock, AsyncMock


class TestHealth:
    def test_health_returns_ok(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_health_shows_configured(self, client):
        resp = client.get("/api/health")
        data = resp.json()
        assert "configured" in data
        assert data["configured"] is True

    def test_health_not_configured(self, client):
        """GET /api/health should report configured=False when FABlib is not set up."""
        with patch("app.fablib_manager.is_configured", return_value=False):
            resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is False


class TestHealthDetailed:
    def test_detailed_returns_checks(self, client):
        """GET /api/health/detailed should return checks dict with subsystems."""
        resp = client.get("/api/health/detailed")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert data["status"] in ("healthy", "degraded")
        assert "checks" in data
        assert "uptime_seconds" in data
        assert isinstance(data["uptime_seconds"], (int, float))

    def test_detailed_includes_fablib_check(self, client):
        """GET /api/health/detailed should include a fablib check."""
        resp = client.get("/api/health/detailed")
        data = resp.json()
        assert "fablib" in data["checks"]
        # The mock_fablib fixture patches is_configured to return True
        assert data["checks"]["fablib"]["ok"] is True

    def test_detailed_includes_storage_check(self, client):
        """GET /api/health/detailed should include a storage check."""
        resp = client.get("/api/health/detailed")
        data = resp.json()
        assert "storage" in data["checks"]

    def test_detailed_includes_version(self, client):
        """GET /api/health/detailed should include the version."""
        resp = client.get("/api/health/detailed")
        data = resp.json()
        assert "version" in data

    def test_detailed_includes_slices_info(self, client):
        """GET /api/health/detailed should include slice counts."""
        resp = client.get("/api/health/detailed")
        data = resp.json()
        assert "slices" in data
        assert "active" in data["slices"]
        assert "total" in data["slices"]

    def test_detailed_degraded_when_not_configured(self, client):
        """GET /api/health/detailed should report degraded when FABlib not configured."""
        with patch("app.fablib_manager.is_configured", return_value=False):
            resp = client.get("/api/health/detailed")
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["checks"]["fablib"]["ok"] is False
