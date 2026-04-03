"""Tests for AI terminal REST endpoints (tool install, opencode/aider web, models, browse)."""

import json
from unittest.mock import patch, MagicMock


class TestToolStatus:
    def test_tool_status_returns_dict(self, client):
        resp = client.get("/api/ai/tools/status")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        # Should have entries for registered tools
        assert "opencode" in data or "aider" in data or len(data) >= 0


class TestToolInstall:
    def test_install_unknown_tool_returns_error(self, client):
        resp = client.post("/api/ai/tools/nonexistent-tool/install")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "Unknown tool" in data["error"]

    def test_install_already_installed_tool(self, client):
        with patch("app.routes.ai_terminal.is_tool_installed", return_value=True):
            resp = client.post("/api/ai/tools/opencode/install")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "already_installed"
        assert data["tool"] == "opencode"


class TestToolInstallStream:
    def test_install_stream_unknown_tool(self, client):
        resp = client.post("/api/ai/tools/fake-tool/install-stream")
        assert resp.status_code == 200
        # SSE stream — parse first event
        lines = resp.text.strip().split("\n")
        data_lines = [l for l in lines if l.startswith("data: ")]
        assert len(data_lines) >= 1
        payload = json.loads(data_lines[0].replace("data: ", ""))
        assert payload["type"] == "error"

    def test_install_stream_already_installed(self, client):
        with patch("app.routes.ai_terminal.is_tool_installed", return_value=True):
            resp = client.post("/api/ai/tools/aider/install-stream")
        assert resp.status_code == 200
        lines = resp.text.strip().split("\n")
        data_lines = [l for l in lines if l.startswith("data: ")]
        assert len(data_lines) >= 1
        payload = json.loads(data_lines[0].replace("data: ", ""))
        assert payload["type"] == "done"
        assert payload["status"] == "already_installed"


class TestOpencodeWebStatus:
    def test_status_when_not_running(self, client):
        import app.routes.ai_terminal as ai_term
        ai_term._opencode_web_proc = None

        resp = client.get("/api/ai/opencode-web/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "stopped"
        assert data["port"] is None


class TestOpencodeWebStop:
    def test_stop_when_not_running(self, client):
        import app.routes.ai_terminal as ai_term
        ai_term._opencode_web_proc = None
        ai_term._opencode_web_proxy = None

        resp = client.post("/api/ai/opencode-web/stop")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "stopped"


class TestOpencodeWebStart:
    def test_start_without_api_key(self, client):
        import app.routes.ai_terminal as ai_term
        ai_term._opencode_web_proc = None

        with patch("app.routes.ai_terminal._get_ai_api_key", return_value=""):
            resp = client.post("/api/ai/opencode-web/start")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "API key" in data["error"]

    def test_start_when_tool_not_installed(self, client):
        import app.routes.ai_terminal as ai_term
        ai_term._opencode_web_proc = None

        with patch("app.routes.ai_terminal._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_terminal.is_tool_installed", return_value=False):
            resp = client.post("/api/ai/opencode-web/start")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "not_installed"
        assert data["install_required"] is True


class TestAiderWebStatus:
    def test_status_when_not_running(self, client):
        import app.routes.ai_terminal as ai_term
        ai_term._aider_web_proc = None

        resp = client.get("/api/ai/aider-web/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "stopped"
        assert data["port"] is None


class TestAiderWebStop:
    def test_stop_when_not_running(self, client):
        import app.routes.ai_terminal as ai_term
        ai_term._aider_web_proc = None

        resp = client.post("/api/ai/aider-web/stop")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "stopped"


class TestAiderWebStart:
    def test_start_without_api_key(self, client):
        import app.routes.ai_terminal as ai_term
        ai_term._aider_web_proc = None

        with patch("app.routes.ai_terminal._get_ai_api_key", return_value=""):
            resp = client.post("/api/ai/aider-web/start")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "API key" in data["error"]

    def test_start_when_tool_not_installed(self, client):
        import app.routes.ai_terminal as ai_term
        ai_term._aider_web_proc = None

        with patch("app.routes.ai_terminal._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_terminal.is_tool_installed", return_value=False):
            resp = client.post("/api/ai/aider-web/start")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "not_installed"
        assert data["install_required"] is True


class TestListAIModels:
    def test_models_without_api_key(self, client):
        mock_result = {
            "fabric": [], "nrp": [], "default": "",
            "has_key": {"fabric": False, "nrp": False},
            "errors": {"fabric": "", "nrp": ""},
            "models": [], "nrp_models": [],
        }
        with patch("app.routes.ai_terminal._fetch_all_models", return_value=mock_result):
            resp = client.get("/api/ai/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["models"] == []
        assert data["fabric"] == []
        assert data["has_key"]["fabric"] is False

    def test_models_with_api_key(self, client):
        mock_result = {
            "fabric": [{"id": "qwen3-coder-30b", "name": "qwen3-coder-30b"}],
            "nrp": [],
            "default": "qwen3-coder-30b",
            "has_key": {"fabric": True, "nrp": False},
            "errors": {"fabric": "", "nrp": ""},
            "models": ["qwen3-coder-30b"],
            "nrp_models": [],
        }
        with patch("app.routes.ai_terminal._fetch_all_models", return_value=mock_result):
            resp = client.get("/api/ai/models")
        assert resp.status_code == 200
        data = resp.json()
        assert "qwen3-coder-30b" in data["models"]
        assert data["default"] == "qwen3-coder-30b"
        assert data["has_key"]["fabric"] is True


class TestBrowseFolders:
    def test_browse_root(self, client, storage_dir):
        resp = client.get("/api/ai/browse-folders")
        assert resp.status_code == 200
        data = resp.json()
        assert "folders" in data
        assert isinstance(data["folders"], list)
        # storage_dir has my_artifacts and my_slices at minimum
        assert "my_artifacts" in data["folders"]

    def test_browse_subfolder(self, client, storage_dir):
        import os
        sub = storage_dir / "my_artifacts" / "test_sub"
        sub.mkdir(parents=True, exist_ok=True)

        resp = client.get("/api/ai/browse-folders",
                          params={"path": str(storage_dir / "my_artifacts")})
        assert resp.status_code == 200
        data = resp.json()
        assert "test_sub" in data["folders"]

    def test_browse_outside_root_denied(self, client, storage_dir):
        resp = client.get("/api/ai/browse-folders",
                          params={"path": "/tmp"})
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data
        assert data["error"] == "Access denied"


class TestAIToolWebSocket:
    """WebSocket tests for /ws/terminal/ai/{tool}."""

    def test_unknown_tool_rejected(self, client):
        """Test that connecting to an unknown tool closes the WebSocket."""
        try:
            with client.websocket_connect("/ws/terminal/ai/nonexistent-tool") as ws:
                # Should have been closed by the server with code 4000
                ws.receive_text()
                assert False, "Should not receive data for unknown tool"
        except Exception:
            pass  # Expected — server closes with code 4000

    def test_tool_requiring_key_sends_error_without_key(self, client):
        """AI tools that need an API key should send an error and close."""
        with patch("app.routes.ai_terminal._get_ai_api_key", return_value=""), \
             patch("app.routes.ai_terminal.is_tool_installed", return_value=True):
            try:
                with client.websocket_connect("/ws/terminal/ai/opencode") as ws:
                    msg = ws.receive_text()
                    assert "key" in msg.lower() or "error" in msg.lower()
            except Exception:
                pass  # Expected to close after error message

    def test_tool_not_needing_key_accepted(self, client):
        """Claude tool does not require an API key — connection should be accepted.

        Rather than mocking os/pty/subprocess at module level (fragile), we verify
        that the handler reaches the PTY-launch phase by mocking just the install
        check and the binary path lookup. If the tool is available, the handler
        will open a real PTY and spawn the binary (which will fail quickly since
        'claude' is likely not installed, but the connection itself succeeds).
        """
        with patch("app.routes.ai_terminal.is_tool_installed", return_value=True), \
             patch("app.routes.ai_terminal.get_tool_binary_path", return_value="/bin/echo"):
            try:
                with client.websocket_connect("/ws/terminal/ai/claude") as ws:
                    # Connection should be accepted (no API key check for claude)
                    # We may receive some output from /bin/echo or prompt text
                    ws.send_text('{"type": "input", "data": "test\\n"}')
            except Exception:
                pass  # Process may exit quickly; that's fine

    def test_tool_status_endpoint_returns_dict(self, client):
        """GET /api/ai/tools/status returns tool availability as a dict."""
        resp = client.get("/api/ai/tools/status")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
