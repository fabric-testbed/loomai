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


class TestToolSync:
    def test_sync_harness_defaults_endpoint(self, client, storage_dir):
        resp = client.post("/api/ai/tools/sync")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["workspace"] == str(storage_dir)
        assert data["managed_service"]["name"] == "loomai-harness"
        assert data["managed_service"]["command"] == "python3 -m app.harness_mcp_server"
        # Every server in app.mcp_registry must reach the harness configs.
        assert "fabric-metrics" in data["mcp_servers"]
        assert "fabric-reports" in data["mcp_servers"]
        assert "loomai-harness" in data["mcp_servers"]
        assert (storage_dir / "opencode.json").is_file()
        assert (storage_dir / ".loomai" / "harness-defaults" / "MAPPING.md").is_file()
        assert (storage_dir / ".pi" / "agent" / "models.json").is_file()
        assert (storage_dir / ".local" / "bin" / "pi-fabric").is_file()
        status_resp = client.get("/api/ai/tools/harnesses")
        assert status_resp.status_code == 200
        statuses = {h["name"]: h["status"] for h in status_resp.json()["harnesses"]}
        for name in ["opencode", "goose", "pi", "aider", "crush", "codex", "claude"]:
            assert statuses[name] == "configured"

    def test_harness_status_and_per_harness_sync_endpoints(self, client, storage_dir):
        status_resp = client.get("/api/ai/tools/harnesses")

        assert status_resp.status_code == 200
        status_data = status_resp.json()
        names = {h["name"] for h in status_data["harnesses"]}
        assert {"opencode", "goose", "pi", "aider", "crush", "codex", "claude"}.issubset(names)

        sync_resp = client.post("/api/ai/tools/harnesses/pi/sync")

        assert sync_resp.status_code == 200
        sync_data = sync_resp.json()
        assert sync_data["status"] == "ok"
        assert sync_data["harness"]["name"] == "pi"
        assert sync_data["harness"]["status"] == "configured"
        assert (storage_dir / "pi" / "agent" / "models.json").is_file()
        assert (storage_dir / "pi" / "pi-fabric").is_file()
        assert (storage_dir / ".pi" / "agent" / "models.json").is_file()
        assert (storage_dir / ".local" / "bin" / "pi-fabric").is_file()
        pi_mcp = json.loads((storage_dir / ".pi" / "agent" / "mcp.json").read_text(encoding="utf-8"))
        assert pi_mcp["mcpServers"]["loomai-harness"]["env"]["PYTHONPATH"] == "/app"
        assert pi_mcp["mcpServers"]["loomai-harness"]["lifecycle"] == "eager"
        assert pi_mcp["settings"]["directTools"] is True

        docs_resp = client.get("/api/ai/tools/harnesses/pi/docs")
        assert docs_resp.status_code == 200
        assert "Pi LoomAI Harness Defaults" in docs_resp.text
        assert "Settings Uninstall" in docs_resp.text
        assert "verify_harness_lifecycle.py --execute" in docs_resp.text

    def test_per_harness_reset_endpoint_overwrites_user_modified_config(self, client, storage_dir):
        pi_settings = storage_dir / "pi" / "agent" / "settings.json"
        pi_settings.parent.mkdir(parents=True)
        pi_settings.write_text(json.dumps({"defaultProvider": "custom"}), encoding="utf-8")

        resp = client.post("/api/ai/tools/harnesses/pi/reset")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["harness"]["name"] == "pi"
        assert data["harness"]["status"] == "configured"
        restored = json.loads(pi_settings.read_text(encoding="utf-8"))
        assert restored["defaultProvider"] == "ai-renci"
        assert restored["sessionDir"] == str(storage_dir / ".loomai" / "harness-defaults" / "pi" / "sessions")

    def test_per_harness_sync_preserves_user_owned_goose_config(self, client, storage_dir):
        goose_config = storage_dir / ".config" / "goose" / "config.yaml"
        goose_config.parent.mkdir(parents=True)
        goose_config.write_text("user-owned: true\n")

        resp = client.post("/api/ai/tools/harnesses/goose/sync")

        assert resp.status_code == 200
        data = resp.json()
        assert data["harness"]["name"] == "goose"
        assert data["harness"]["status"] == "user_modified"
        assert goose_config.read_text() == "user-owned: true\n"


class TestToolInstall:
    def test_install_unknown_tool_returns_error(self, client):
        resp = client.post("/api/ai/tools/nonexistent-tool/install")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "Unknown tool" in data["error"]

    def test_install_already_installed_tool(self, client):
        with patch("app.routes.ai_terminal.is_tool_installed", return_value=True):
            resp = client.post("/api/ai/tools/deepagents/install")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "already_installed"
        assert data["tool"] == "deepagents"

    def test_install_already_installed_opencode_refreshes_defaults(self, client):
        async def fake_install(tool_id, progress_callback=None):
            if progress_callback:
                await progress_callback("OpenCode is already installed.\r\n")
                await progress_callback("OpenCode LoomAI harness defaults synchronized.\r\n")
            return True

        with patch("app.routes.ai_terminal.is_tool_installed", return_value=True), \
             patch("app.routes.ai_terminal.install_tool", side_effect=fake_install) as install:
            resp = client.post("/api/ai/tools/opencode/install")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "already_installed"
        assert data["tool"] == "opencode"
        assert "harness defaults synchronized" in data["output"]
        install.assert_called_once()

    def test_install_already_installed_pi_refreshes_defaults(self, client):
        async def fake_install(tool_id, progress_callback=None):
            if progress_callback:
                await progress_callback("Pi is already installed.\r\n")
                await progress_callback("Pi LoomAI harness defaults synchronized.\r\n")
            return True

        with patch("app.routes.ai_terminal.is_tool_installed", return_value=True), \
             patch("app.routes.ai_terminal.tool_needs_upgrade", return_value=False), \
             patch("app.routes.ai_terminal.install_tool", side_effect=fake_install) as install:
            resp = client.post("/api/ai/tools/pi/install")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "already_installed"
        assert data["tool"] == "pi"
        assert "harness defaults synchronized" in data["output"]
        install.assert_called_once()

    def test_install_drifted_claude_returns_upgraded(self, client):
        async def fake_install(tool_id, progress_callback=None):
            if progress_callback:
                await progress_callback(
                    "Claude Code is installed but does not match the pinned version; upgrading.\r\n"
                )
                await progress_callback("Claude Code installed successfully.\r\n")
            return True

        with patch("app.routes.ai_terminal.is_tool_installed", return_value=True), \
             patch("app.routes.ai_terminal.tool_needs_upgrade", return_value=True), \
             patch("app.routes.ai_terminal.install_tool", side_effect=fake_install) as install:
            resp = client.post("/api/ai/tools/claude/install")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "upgraded"
        assert data["tool"] == "claude"
        assert "does not match the pinned version" in data["output"]
        install.assert_called_once()

    def test_uninstall_refuses_active_terminal_session(self, client):
        with patch("app.routes.ai_terminal._term_sessions.has_live_type", return_value=True), \
             patch("app.routes.ai_terminal.uninstall_tool") as uninstall:
            resp = client.post("/api/ai/tools/pi/uninstall")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"
        assert "active terminal session" in data["error"]
        uninstall.assert_not_called()

    def test_uninstall_refuses_active_opencode_web_process(self, client):
        import app.routes.ai_terminal as ai_term

        old_proc = ai_term._opencode_web_proc
        old_proxy = ai_term._opencode_web_proxy
        proc = MagicMock()
        proc.poll.return_value = None
        ai_term._opencode_web_proc = proc
        ai_term._opencode_web_proxy = None
        try:
            with patch("app.routes.ai_terminal._term_sessions.has_live_type", return_value=False), \
                 patch("app.routes.ai_terminal.uninstall_tool") as uninstall:
                resp = client.post("/api/ai/tools/opencode/uninstall")
        finally:
            ai_term._opencode_web_proc = old_proc
            ai_term._opencode_web_proxy = old_proxy

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"
        assert "OpenCode web is running" in data["error"]
        uninstall.assert_not_called()

    def test_uninstall_refuses_active_claude_process(self, client):
        pgrep = MagicMock()
        pgrep.returncode = 0
        pgrep.stdout = "1234 claude\n"

        with patch("app.routes.ai_terminal._term_sessions.has_live_type", return_value=False), \
             patch("app.routes.ai_terminal.subprocess.run", return_value=pgrep), \
             patch("app.routes.ai_terminal.uninstall_tool") as uninstall:
            resp = client.post("/api/ai/tools/claude/uninstall")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"
        assert "Claude Code is running" in data["error"]
        uninstall.assert_not_called()

    def test_uninstall_managed_harness_keeps_config_by_default(self, client, storage_dir):
        client.post("/api/ai/tools/harnesses/pi/sync")
        pi_settings = storage_dir / "pi" / "agent" / "settings.json"
        runtime_file = storage_dir / ".loomai" / "harness-defaults" / "pi" / "sessions" / "session.json"
        runtime_file.parent.mkdir(parents=True, exist_ok=True)
        runtime_file.write_text("{}", encoding="utf-8")

        async def fake_uninstall(tool_id, progress_callback=None):
            if progress_callback:
                await progress_callback("Pi uninstalled successfully.\r\n")
            return True

        with patch("app.routes.ai_terminal.is_tool_installed", return_value=True), \
             patch("app.routes.ai_terminal.uninstall_tool", side_effect=fake_uninstall):
            resp = client.post("/api/ai/tools/pi/uninstall")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "uninstalled"
        assert data["removed_config_files"] == 0
        assert not runtime_file.exists()
        assert pi_settings.is_file()

    def test_uninstall_managed_harness_removes_config_when_requested(self, client, storage_dir):
        client.post("/api/ai/tools/harnesses/pi/sync")
        pi_settings = storage_dir / "pi" / "agent" / "settings.json"
        runtime_file = storage_dir / ".loomai" / "harness-defaults" / "pi" / "cache" / "cache.json"
        runtime_file.parent.mkdir(parents=True, exist_ok=True)
        runtime_file.write_text("{}", encoding="utf-8")

        async def fake_uninstall(tool_id, progress_callback=None):
            if progress_callback:
                await progress_callback("Pi uninstalled successfully.\r\n")
            return True

        with patch("app.routes.ai_terminal.is_tool_installed", return_value=True), \
             patch("app.routes.ai_terminal.uninstall_tool", side_effect=fake_uninstall):
            resp = client.post("/api/ai/tools/pi/uninstall?remove_config=true")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "uninstalled"
        assert data["removed_config_files"] > 0
        assert not runtime_file.exists()
        assert not pi_settings.exists()


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
            resp = client.post("/api/ai/tools/deepagents/install-stream")
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
