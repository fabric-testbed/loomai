"""Unit tests for FABRIC LLM key creation/recreation in app.routes.config."""

import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.settings_manager as sm
from app.routes import config as config_routes


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path):
    """Redirect settings_manager to an isolated temp directory."""
    storage = tmp_path / "fabric_work"
    storage.mkdir()
    config_dir = storage / "fabric_config"
    config_dir.mkdir()

    env_vars = {
        "FABRIC_STORAGE_DIR": str(storage),
        "FABRIC_CONFIG_DIR": str(config_dir),
    }
    with patch.dict(os.environ, env_vars):
        with patch("app.user_registry.get_user_storage_dir", return_value=None):
            old_cache = sm._cached_settings
            sm._cached_settings = None
            yield storage
            sm._cached_settings = old_cache


def _response(status_code=200, payload=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload if payload is not None else {}
    resp.text = text
    return resp


# ---------------------------------------------------------------------------
# _create_fabric_llm_key
# ---------------------------------------------------------------------------


class TestCreateFabricLlmKey:
    def test_success_parses_key_and_normalizes_expiry(self):
        payload = {"data": [{"details": {
            "api_key": "sk-new-key",
            "key_name": "loomai-abcd1234",
            "expires_at": "2026-09-23 12:00:00 +0000",
        }}]}
        with patch.object(config_routes.httpx, "post", return_value=_response(200, payload)) as post:
            info = config_routes._create_fabric_llm_key("tok", comment="test")
        assert info["api_key"] == "sk-new-key"
        assert info["key_name"] == "loomai-abcd1234"
        assert info["expires_at"] == "2026-09-23T12:00:00+00:00"
        params = post.call_args.kwargs["params"]
        assert params["key_name"].startswith("loomai-")
        assert params["duration"] == 30

    def test_cm_error_detail_is_surfaced(self):
        payload = {"errors": [{"details": "User already has 10 active LLM keys"}]}
        with patch.object(config_routes.httpx, "post", return_value=_response(500, payload)):
            with pytest.raises(RuntimeError, match="10 active LLM keys"):
                config_routes._create_fabric_llm_key("tok", comment="test")

    def test_missing_api_key_raises(self):
        payload = {"data": [{"details": {}}]}
        with patch.object(config_routes.httpx, "post", return_value=_response(200, payload)):
            with pytest.raises(RuntimeError, match="did not return an API key"):
                config_routes._create_fabric_llm_key("tok", comment="test")


# ---------------------------------------------------------------------------
# _save_fabric_llm_key
# ---------------------------------------------------------------------------


class TestSaveFabricLlmKey:
    def test_persists_key_and_metadata(self):
        config_routes._save_fabric_llm_key(
            api_key="sk-abc", key_name="loomai-x", expires_at="2026-09-23T12:00:00+00:00")
        assert sm.get_fabric_api_key() == "sk-abc"
        name, expires = sm.get_fabric_api_key_meta()
        assert name == "loomai-x"
        assert expires == "2026-09-23T12:00:00+00:00"


# ---------------------------------------------------------------------------
# _delete_replaced_llm_key
# ---------------------------------------------------------------------------


class TestDeleteReplacedLlmKey:
    def test_deletes_only_the_replaced_key(self):
        # CM nests the key list one level deep: data[0].details is the list.
        # Other loomai-* keys may belong to other LoomAI installations and
        # must never be revoked.
        payload = {"data": [{"details": [
            {"key_alias": "loomai-other-install", "token": "hash-other"},
            {"key_alias": "loomai-replaced", "token": "hash-replaced"},
            {"key_alias": "my-manual-key", "token": "hash-manual"},
        ]}]}
        with patch.object(config_routes.httpx, "get", return_value=_response(200, payload)), \
             patch.object(config_routes.httpx, "delete", return_value=_response(200)) as delete:
            config_routes._delete_replaced_llm_key("tok", old_key_name="loomai-replaced")
        deleted_urls = [c.args[0] for c in delete.call_args_list]
        assert deleted_urls == [
            "https://cm.fabric-testbed.net/credmgr/tokens/delete_llm/hash-replaced"]

    def test_no_stored_name_is_a_noop(self):
        with patch.object(config_routes.httpx, "get") as get:
            config_routes._delete_replaced_llm_key("tok", old_key_name="")
        get.assert_not_called()

    def test_listing_failure_is_swallowed(self):
        with patch.object(config_routes.httpx, "get", side_effect=Exception("boom")):
            config_routes._delete_replaced_llm_key("tok", old_key_name="loomai-x")  # no raise


# ---------------------------------------------------------------------------
# POST /api/config/llm-key endpoint
# ---------------------------------------------------------------------------


class TestCreateLlmKeyEndpoint:
    @pytest.mark.asyncio
    async def test_recreates_even_when_key_already_configured(self):
        from fastapi import BackgroundTasks
        settings = sm.load_settings()
        settings["ai"]["fabric_api_key"] = "sk-old"
        settings["ai"]["fabric_api_key_name"] = "loomai-old"
        sm.save_settings(settings)

        key_info = {"api_key": "sk-fresh", "key_name": "loomai-fresh",
                    "expires_at": "2026-09-23T12:00:00+00:00"}
        tasks = BackgroundTasks()
        with patch.object(config_routes, "_read_token", return_value={"id_token": "tok"}), \
             patch.object(config_routes, "_decode_jwt_payload",
                          return_value={"exp": time.time() + 3600}), \
             patch.object(config_routes, "_create_fabric_llm_key", return_value=key_info), \
             patch.object(config_routes, "_delete_replaced_llm_key") as delete_old:
            result = await config_routes.create_llm_key(tasks)

        assert result["status"] == "ok"
        assert result["created"] is True
        assert result["key_name"] == "loomai-fresh"
        assert result["expires_at"] == "2026-09-23T12:00:00+00:00"
        assert sm.get_fabric_api_key() == "sk-fresh"
        # Only the key this instance previously created is deleted
        delete_old.assert_called_once_with("tok", "loomai-old")
        # Tool workspaces are re-synced and live processes holding the old
        # key in env are stopped, so nothing keeps using the replaced key
        from app.routes.ai_terminal import propagate_ai_configs, refresh_live_ai_tools
        task_funcs = [t.func for t in tasks.tasks]
        assert propagate_ai_configs in task_funcs
        assert refresh_live_ai_tools in task_funcs

    @pytest.mark.asyncio
    async def test_first_create_deletes_nothing(self):
        from fastapi import BackgroundTasks
        key_info = {"api_key": "sk-first", "key_name": "loomai-first", "expires_at": ""}
        with patch.object(config_routes, "_read_token", return_value={"id_token": "tok"}), \
             patch.object(config_routes, "_decode_jwt_payload",
                          return_value={"exp": time.time() + 3600}), \
             patch.object(config_routes, "_create_fabric_llm_key", return_value=key_info), \
             patch.object(config_routes, "_delete_replaced_llm_key") as delete_old:
            result = await config_routes.create_llm_key(BackgroundTasks())
        assert result["status"] == "ok"
        delete_old.assert_not_called()

    @pytest.mark.asyncio
    async def test_refresh_live_ai_tools_stops_processes_with_stale_env(self):
        from app.routes import ai_terminal, jupyter

        def _fake_proc():
            proc = MagicMock()
            proc.poll.return_value = None  # still running
            proc.pid = 4242
            return proc

        live = _fake_proc()
        # Every ai-* session gets the FABRIC key in env at launch (even
        # needs_key=False tools like codex), so all are killed; plain shell
        # terminals are never touched.
        sessions = [
            {"id": "s-oc", "type": "ai-opencode"},
            {"id": "s-cx", "type": "ai-codex"},
            {"id": "s-sh", "type": "local"},
        ]
        with patch.object(ai_terminal, "_opencode_web_proc", live), \
             patch.object(ai_terminal, "_aider_web_proc", None), \
             patch.object(ai_terminal, "_opencode_web_proxy", None), \
             patch.object(ai_terminal, "_terminal_model_proxy", None), \
             patch.object(ai_terminal._term_sessions, "list_sessions", return_value=sessions), \
             patch.object(ai_terminal._term_sessions, "kill", return_value=True) as kill_session, \
             patch.object(jupyter, "stop_jupyter_sync", return_value=True) as stop_jupyter, \
             patch.object(jupyter, "wait_jupyter_port_free", return_value=True), \
             patch.object(jupyter, "start_jupyter", AsyncMock(return_value={"status": "running"})), \
             patch.object(ai_terminal.os, "getpgid", return_value=4242), \
             patch.object(ai_terminal.os, "killpg") as killpg:
            results = ai_terminal.refresh_live_ai_tools()
            # Global cleared so the next launch starts fresh with the new key
            assert ai_terminal._opencode_web_proc is None

        assert results["opencode-web"] == "stopped"
        assert results["aider-web"] == "not_running"
        assert results["model-proxy"] == "not_running"
        assert results["ai-terminals"] == "stopped 2"
        # JupyterLab captured OPENAI_API_KEY in env at launch — the managed
        # instance is stopped and relaunched with the new key
        assert results["jupyterlab"] == "restarted (running)"
        stop_jupyter.assert_called_once()
        killpg.assert_called_once()
        assert [c.args[0] for c in kill_session.call_args_list] == ["s-oc", "s-cx"]

    @pytest.mark.asyncio
    async def test_restart_external_jupyter_deployment_modes(self, tmp_path):
        from app.routes import ai_terminal, jupyter

        def _proc_entry(pid, cmdline, ppid=None):
            d = tmp_path / str(pid)
            d.mkdir()
            (d / "cmdline").write_bytes(cmdline)
            if ppid is not None:
                (d / "status").write_text(f"Name:\tx\nPPid:\t{ppid}\n")

        jl_cmd = b"/usr/local/bin/python\x00/usr/local/bin/jupyter-lab\x00--no-browser\x00--port=8889\x00"
        # supervisord (pid 1) → supervised JupyterLab (pid 321): signalled,
        # supervisor respawns it. A user's own Jupyter on another port
        # (pid 700) must never be touched.
        _proc_entry(1, b"/usr/bin/python3\x00/usr/bin/supervisord\x00")
        _proc_entry(321, jl_cmd, ppid=1)
        _proc_entry(654, b"nginx\x00-g\x00daemon off;\x00", ppid=1)
        _proc_entry(700, b"python\x00/usr/local/bin/jupyter-lab\x00--port=9999\x00", ppid=1)

        with patch.object(jupyter, "_is_jupyter_listening", return_value=True), \
             patch.object(jupyter, "_jupyter_port", return_value=8889), \
             patch.object(jupyter.os, "kill") as kill:
            assert jupyter.restart_external_jupyter(proc_root=str(tmp_path)) == "supervised"
        kill.assert_called_once()
        assert kill.call_args.args[0] == 321

        # Split-image mode: entrypoint-started JupyterLab (parent bash, no
        # supervisor) → killed, reported unsupervised so the caller starts a
        # managed replacement.
        import shutil as _shutil
        _shutil.rmtree(tmp_path / "321")
        _proc_entry(99, b"/bin/bash\x00/app/entrypoint.sh\x00")
        _proc_entry(500, jl_cmd, ppid=99)
        with patch.object(jupyter, "_is_jupyter_listening", side_effect=[True, False]), \
             patch.object(jupyter, "_jupyter_port", return_value=8889), \
             patch.object(jupyter.os, "kill") as kill:
            assert jupyter.restart_external_jupyter(proc_root=str(tmp_path)) == "unsupervised"
        kill.assert_called_once()
        assert kill.call_args.args[0] == 500

        # In refresh: supervised bounce needs no takeover...
        base_patches = dict(
            _opencode_web_proc=None, _aider_web_proc=None,
            _opencode_web_proxy=None, _terminal_model_proxy=None)
        with patch.multiple(ai_terminal, **base_patches), \
             patch.object(ai_terminal._term_sessions, "list_sessions", return_value=[]), \
             patch.object(jupyter, "stop_jupyter_sync", return_value=False), \
             patch.object(jupyter, "restart_external_jupyter", return_value="supervised"), \
             patch.object(jupyter, "start_jupyter", AsyncMock()) as start:
            results = ai_terminal.refresh_live_ai_tools()
        assert results["jupyterlab"] == "restarted"
        start.assert_not_called()

        # ...but the split-image kill is followed by a managed takeover so
        # Jupyter AI comes back with the new key.
        with patch.multiple(ai_terminal, **base_patches), \
             patch.object(ai_terminal._term_sessions, "list_sessions", return_value=[]), \
             patch.object(jupyter, "stop_jupyter_sync", return_value=False), \
             patch.object(jupyter, "restart_external_jupyter", return_value="unsupervised"), \
             patch.object(jupyter, "start_jupyter",
                          AsyncMock(return_value={"status": "running"})) as start:
            results = ai_terminal.refresh_live_ai_tools()
        assert results["jupyterlab"] == "restarted (running)"
        start.assert_called_once()

    @pytest.mark.asyncio
    async def test_takeover_failures_are_reported_not_masked(self, tmp_path):
        from app.routes import ai_terminal, jupyter

        # Old instance never releases the port: SIGTERM, then SIGKILL, then
        # an honest "stuck" — never a false "restarted".
        d = tmp_path / "500"
        d.mkdir()
        (d / "cmdline").write_bytes(
            b"/usr/local/bin/python\x00/usr/local/bin/jupyter-lab\x00--port=8889\x00")
        (d / "status").write_text("Name:\tx\nPPid:\t99\n")
        p = tmp_path / "99"
        p.mkdir()
        (p / "cmdline").write_bytes(b"/bin/bash\x00/app/entrypoint.sh\x00")
        with patch.object(jupyter, "_is_jupyter_listening", return_value=True), \
             patch.object(jupyter, "_jupyter_port", return_value=8889), \
             patch.object(jupyter.time, "sleep"), \
             patch.object(jupyter.os, "kill") as kill:
            assert jupyter.restart_external_jupyter(proc_root=str(tmp_path)) == "stuck"
        import signal as _signal
        assert [c.args for c in kill.call_args_list] == [
            (500, _signal.SIGTERM), (500, _signal.SIGKILL)]

        base_patches = dict(
            _opencode_web_proc=None, _aider_web_proc=None,
            _opencode_web_proxy=None, _terminal_model_proxy=None)
        # Stuck port → error, and no takeover attempt
        with patch.multiple(ai_terminal, **base_patches), \
             patch.object(ai_terminal._term_sessions, "list_sessions", return_value=[]), \
             patch.object(jupyter, "stop_jupyter_sync", return_value=False), \
             patch.object(jupyter, "restart_external_jupyter", return_value="stuck"), \
             patch.object(jupyter, "start_jupyter", AsyncMock()) as start:
            results = ai_terminal.refresh_live_ai_tools()
        assert results["jupyterlab"].startswith("error:")
        start.assert_not_called()

        # start_jupyter didn't actually start a server → error, not success
        with patch.multiple(ai_terminal, **base_patches), \
             patch.object(ai_terminal._term_sessions, "list_sessions", return_value=[]), \
             patch.object(jupyter, "stop_jupyter_sync", return_value=False), \
             patch.object(jupyter, "restart_external_jupyter", return_value="unsupervised"), \
             patch.object(jupyter, "start_jupyter",
                          AsyncMock(return_value={"status": "not_installed",
                                                  "install_required": True})):
            results = ai_terminal.refresh_live_ai_tools()
        assert results["jupyterlab"] == "error: takeover failed (not_installed)"

        # Managed stop whose socket never frees → error, and no start attempt
        # (start_jupyter would see the occupied port and fake success)
        with patch.multiple(ai_terminal, **base_patches), \
             patch.object(ai_terminal._term_sessions, "list_sessions", return_value=[]), \
             patch.object(jupyter, "stop_jupyter_sync", return_value=True), \
             patch.object(jupyter, "wait_jupyter_port_free", return_value=False), \
             patch.object(jupyter, "start_jupyter", AsyncMock()) as start:
            results = ai_terminal.refresh_live_ai_tools()
        assert results["jupyterlab"] == "error: old instance did not release the port"
        start.assert_not_called()

        # Spawned but readiness poll timed out → failure, never success
        with patch.multiple(ai_terminal, **base_patches), \
             patch.object(ai_terminal._term_sessions, "list_sessions", return_value=[]), \
             patch.object(jupyter, "stop_jupyter_sync", return_value=False), \
             patch.object(jupyter, "restart_external_jupyter", return_value="unsupervised"), \
             patch.object(jupyter, "start_jupyter",
                          AsyncMock(return_value={"status": "running", "ready": False})):
            results = ai_terminal.refresh_live_ai_tools()
        assert results["jupyterlab"] == "error: replacement started but not responding"

    @pytest.mark.asyncio
    async def test_launch_notebook_reports_starting_when_not_ready(self, isolated_storage):
        from app.routes import jupyter

        artifacts = isolated_storage / "my_artifacts" / "nb1"
        artifacts.mkdir(parents=True)
        (artifacts / "demo.ipynb").write_text("{}")

        with patch.object(jupyter, "start_jupyter",
                          AsyncMock(return_value={"status": "running", "ready": False})):
            result = await jupyter.launch_notebook("nb1")
        assert result["status"] == "starting"
        assert result["ready"] is False
        assert result["jupyter_path"]  # path still returned for retry flows

        with patch.object(jupyter, "start_jupyter",
                          AsyncMock(return_value={"status": "running", "ready": True})):
            result = await jupyter.launch_notebook("nb1")
        assert result["status"] == "running"
        assert result["ready"] is True

    @pytest.mark.asyncio
    async def test_start_jupyter_ready_tracks_port_state(self):
        from app.routes import jupyter
        # A live-but-never-ready process must not turn into ready=True on the
        # next start_jupyter() call — ready reflects the actual port state.
        alive = MagicMock()
        alive.poll.return_value = None
        with patch.object(jupyter, "_jupyter_proc", alive), \
             patch.object(jupyter, "_is_jupyter_listening", return_value=False):
            result = await jupyter.start_jupyter()
        assert result["status"] == "running"
        assert result["ready"] is False
        with patch.object(jupyter, "_jupyter_proc", alive), \
             patch.object(jupyter, "_is_jupyter_listening", return_value=True):
            result = await jupyter.start_jupyter()
        assert result["ready"] is True

    @pytest.mark.asyncio
    async def test_expired_login_token_rejected(self):
        from fastapi import BackgroundTasks, HTTPException
        with patch.object(config_routes, "_read_token", return_value={"id_token": "tok"}), \
             patch.object(config_routes, "_decode_jwt_payload",
                          return_value={"exp": time.time() - 10}):
            with pytest.raises(HTTPException) as exc:
                await config_routes.create_llm_key(BackgroundTasks())
        assert exc.value.status_code == 401
