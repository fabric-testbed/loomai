"""Advanced tests for AI terminal endpoints.

Covers: model listing, default model, model refresh, browse folders,
tool install/start/stop, and tool status.
"""

import json
from unittest.mock import patch, MagicMock, AsyncMock

import pytest


class TestModelList:
    def test_list_models_returns_200(self, client):
        """Models endpoint should return 200 regardless of network state."""
        resp = client.get("/api/ai/models")
        assert resp.status_code == 200
        data = resp.json()
        # May return a list or a dict with model info
        assert isinstance(data, (list, dict))


class TestDefaultModel:
    def test_get_default_model(self, client):
        resp = client.get("/api/ai/models/default")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_set_default_model(self, client):
        resp = client.put("/api/ai/models/default",
                          json={"model": "test-model-id"})
        assert resp.status_code in (200, 422)


class TestModelRefresh:
    def test_refresh_models(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"id": "refreshed-model"}]}
        with patch("app.http_pool.fabric_client") as mc:
            mc.get = AsyncMock(return_value=mock_resp)
            resp = client.post("/api/ai/models/refresh")
        assert resp.status_code == 200


class TestModelTest:
    def test_test_model(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "hello"}}],
            "usage": {"total_tokens": 10},
        }
        with patch("app.http_pool.fabric_client") as mc:
            mc.post = AsyncMock(return_value=mock_resp)
            resp = client.post("/api/ai/models/test",
                               json={"model": "test-model"})
        assert resp.status_code == 200


class TestToolStatus:
    def test_status_returns_all_tools(self, client):
        resp = client.get("/api/ai/tools/status")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_status_has_known_tools(self, client):
        resp = client.get("/api/ai/tools/status")
        data = resp.json()
        # Should have at least some of the registered tools
        assert len(data) >= 1


class TestToolInstallAdvanced:
    def test_install_nonexistent_tool(self, client):
        resp = client.post("/api/ai/tools/nonexistent/install")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"

    def test_install_already_installed(self, client):
        with patch("app.routes.ai_terminal.is_tool_installed", return_value=True):
            resp = client.post("/api/ai/tools/aider/install")
        assert resp.status_code == 200
        assert resp.json()["status"] == "already_installed"


class TestBrowseFolders:
    def test_browse_storage(self, client):
        resp = client.get("/api/ai/browse-folders")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (list, dict))

    def test_browse_with_path(self, client):
        resp = client.get("/api/ai/browse-folders?path=.")
        assert resp.status_code == 200


class TestOpenCodeWebStatus:
    def test_opencode_status(self, client):
        resp = client.get("/api/ai/opencode-web/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "running" in data or "status" in data

    def test_aider_status(self, client):
        resp = client.get("/api/ai/aider-web/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "running" in data or "status" in data
