"""Tests for config and settings endpoints."""

from unittest.mock import patch, MagicMock, AsyncMock


class TestGetConfig:
    def test_config_returns_status(self, client):
        resp = client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "configured" in data
        assert "has_token" in data
        assert "project_id" in data

    def test_config_shows_configured(self, client):
        resp = client.get("/api/config")
        data = resp.json()
        assert data["configured"] is True


class TestCheckUpdate:
    def test_check_update_returns_version_info(self, client):
        # Mock the external HTTP call to Docker Hub so tests don't hit the network
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"results": []}

        # Clear the update cache to force a fresh check
        from app.routes.config import _update_cache
        _update_cache["result"] = None
        _update_cache["timestamp"] = 0.0

        mock_get = AsyncMock(return_value=mock_resp)
        with patch("app.routes.config.fabric_client") as mock_client:
            mock_client.get = mock_get
            resp = client.get("/api/config/check-update")

        assert resp.status_code == 200
        data = resp.json()
        assert "current_version" in data
        assert "latest_version" in data
        assert "update_available" in data
        assert isinstance(data["update_available"], bool)

    def test_check_update_handles_network_error(self, client):
        import httpx

        # Clear the update cache to force a fresh check
        from app.routes.config import _update_cache
        _update_cache["result"] = None
        _update_cache["timestamp"] = 0.0

        mock_get = AsyncMock(side_effect=httpx.ConnectError("no network"))
        with patch("app.routes.config.fabric_client") as mock_client:
            mock_client.get = mock_get
            resp = client.get("/api/config/check-update")

        assert resp.status_code == 200
        data = resp.json()
        assert data["update_available"] is False


class TestGetSettings:
    def test_settings_returns_dict(self, client):
        resp = client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        # Settings should contain the fabric section
        assert "fabric" in data


class TestGetLoginUrl:
    def test_login_returns_url(self, client):
        resp = client.get("/api/config/login")
        assert resp.status_code == 200
        data = resp.json()
        assert "login_url" in data
        assert "cm.fabric-testbed.net" in data["login_url"]
