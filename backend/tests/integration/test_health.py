"""Tests for GET /api/health — validates TestClient setup works."""


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
