"""Unit tests for the tool installer (lazy-install manager).

Tests tool binary detection, tool status reporting, env setup,
manifest updates, lock management, and config helpers — all without
actually installing anything.
"""

import json
import os
import shutil
import tempfile
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

import app.tool_installer as ti


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def clean_dirs(tmp_path):
    """Set up temporary AI tools directories."""
    old_ai = ti.AI_TOOLS_DIR
    old_venv = ti._VENV_DIR
    old_npm = ti._NPM_DIR
    old_manifest = ti._MANIFEST_PATH
    old_lock = ti._LOCK_DIR

    ai_dir = str(tmp_path / "ai-tools")
    ti.AI_TOOLS_DIR = ai_dir
    ti._VENV_DIR = os.path.join(ai_dir, "venv")
    ti._NPM_DIR = os.path.join(ai_dir, "npm")
    ti._MANIFEST_PATH = os.path.join(ai_dir, ".installed.json")
    ti._LOCK_DIR = os.path.join(ai_dir, ".locks")

    yield tmp_path

    ti.AI_TOOLS_DIR = old_ai
    ti._VENV_DIR = old_venv
    ti._NPM_DIR = old_npm
    ti._MANIFEST_PATH = old_manifest
    ti._LOCK_DIR = old_lock


# ---------------------------------------------------------------------------
# Tool binary path
# ---------------------------------------------------------------------------

class TestGetToolBinaryPath:
    def test_unknown_tool_returns_none(self, clean_dirs):
        assert ti.get_tool_binary_path("nonexistent_tool") is None

    def test_pip_tool_found_in_venv(self, clean_dirs):
        """If the binary exists in the venv bin, return its path."""
        venv_bin = os.path.join(ti._VENV_DIR, "bin")
        os.makedirs(venv_bin, exist_ok=True)
        aider_path = os.path.join(venv_bin, "aider")
        with open(aider_path, "w") as f:
            f.write("#!/bin/bash\n")
        assert ti.get_tool_binary_path("aider") == aider_path

    def test_npm_tool_found_in_npm_bin(self, clean_dirs):
        npm_bin = os.path.join(ti._NPM_DIR, "bin")
        os.makedirs(npm_bin, exist_ok=True)
        opencode_path = os.path.join(npm_bin, "opencode")
        with open(opencode_path, "w") as f:
            f.write("#!/bin/bash\n")
        assert ti.get_tool_binary_path("opencode") == opencode_path

    def test_falls_back_to_system(self, clean_dirs):
        """If not in venv/npm, fall back to shutil.which."""
        with patch("shutil.which", return_value="/usr/bin/aider"):
            assert ti.get_tool_binary_path("aider") == "/usr/bin/aider"

    def test_not_found_anywhere(self, clean_dirs):
        with patch("shutil.which", return_value=None):
            assert ti.get_tool_binary_path("aider") is None


# ---------------------------------------------------------------------------
# Is tool installed
# ---------------------------------------------------------------------------

class TestIsToolInstalled:
    def test_installed_when_binary_exists(self, clean_dirs):
        venv_bin = os.path.join(ti._VENV_DIR, "bin")
        os.makedirs(venv_bin, exist_ok=True)
        with open(os.path.join(venv_bin, "aider"), "w") as f:
            f.write("#!/bin/bash\n")
        assert ti.is_tool_installed("aider") is True

    def test_not_installed(self, clean_dirs):
        with patch("shutil.which", return_value=None):
            assert ti.is_tool_installed("aider") is False


# ---------------------------------------------------------------------------
# Get tool env
# ---------------------------------------------------------------------------

class TestGetToolEnv:
    def test_env_has_extended_path(self, clean_dirs):
        """PATH should include venv/bin and npm/bin if they exist."""
        venv_bin = os.path.join(ti._VENV_DIR, "bin")
        npm_bin = os.path.join(ti._NPM_DIR, "bin")
        os.makedirs(venv_bin, exist_ok=True)
        os.makedirs(npm_bin, exist_ok=True)

        env = ti.get_tool_env()
        assert venv_bin in env["PATH"]
        assert npm_bin in env["PATH"]

    def test_env_without_dirs(self, clean_dirs):
        """If dirs don't exist, PATH should be unchanged."""
        env = ti.get_tool_env()
        # Just verify it has a PATH at all
        assert "PATH" in env


# ---------------------------------------------------------------------------
# Get all tool status
# ---------------------------------------------------------------------------

class TestGetAllToolStatus:
    def test_returns_all_tools(self, clean_dirs):
        with patch("shutil.which", return_value=None):
            status = ti.get_all_tool_status()
        assert "aider" in status
        assert "opencode" in status
        assert "crush" in status
        assert "claude" in status
        assert "jupyterlab" in status
        for tool_id, info in status.items():
            assert "installed" in info
            assert "display_name" in info
            assert "size_estimate" in info
            assert "type" in info

    def test_marks_installed_correctly(self, clean_dirs):
        venv_bin = os.path.join(ti._VENV_DIR, "bin")
        os.makedirs(venv_bin, exist_ok=True)
        with open(os.path.join(venv_bin, "aider"), "w") as f:
            f.write("#!/bin/bash\n")
        with patch("shutil.which", return_value=None):
            status = ti.get_all_tool_status()
        assert status["aider"]["installed"] is True
        assert status["opencode"]["installed"] is False


# ---------------------------------------------------------------------------
# Manifest management
# ---------------------------------------------------------------------------

class TestUpdateManifest:
    def test_creates_manifest_file(self, clean_dirs):
        os.makedirs(ti.AI_TOOLS_DIR, exist_ok=True)
        ti._update_manifest("aider", {"packages": ["aider-chat"], "type": "pip"})
        assert os.path.isfile(ti._MANIFEST_PATH)
        with open(ti._MANIFEST_PATH) as f:
            data = json.load(f)
        assert "aider" in data
        assert data["aider"]["type"] == "pip"
        assert "installed_at" in data["aider"]

    def test_updates_existing_manifest(self, clean_dirs):
        os.makedirs(ti.AI_TOOLS_DIR, exist_ok=True)
        # Write initial entry
        ti._update_manifest("aider", {"packages": ["aider-chat"], "type": "pip"})
        # Add another
        ti._update_manifest("crush", {"packages": ["@charmland/crush"], "type": "npm"})
        with open(ti._MANIFEST_PATH) as f:
            data = json.load(f)
        assert "aider" in data
        assert "crush" in data


# ---------------------------------------------------------------------------
# Tool lock
# ---------------------------------------------------------------------------

class TestToolLock:
    def test_acquire_and_release(self, clean_dirs):
        os.makedirs(ti.AI_TOOLS_DIR, exist_ok=True)
        os.makedirs(ti._LOCK_DIR, exist_ok=True)
        lock = ti._ToolLock("test_tool")
        assert lock.acquire() is True
        lock.release()

    def test_double_acquire_fails(self, clean_dirs):
        os.makedirs(ti.AI_TOOLS_DIR, exist_ok=True)
        os.makedirs(ti._LOCK_DIR, exist_ok=True)
        lock1 = ti._ToolLock("test_tool2")
        lock2 = ti._ToolLock("test_tool2")
        assert lock1.acquire() is True
        assert lock2.acquire() is False
        lock1.release()

    def test_release_without_acquire(self, clean_dirs):
        """Release without acquire should not crash."""
        lock = ti._ToolLock("unacquired")
        lock.release()  # Should be a no-op


# ---------------------------------------------------------------------------
# Clean stale locks
# ---------------------------------------------------------------------------

class TestCleanStaleLocks:
    def test_removes_stale_lock(self, clean_dirs):
        os.makedirs(ti._LOCK_DIR, exist_ok=True)
        lock_path = os.path.join(ti._LOCK_DIR, "test.lock")
        with open(lock_path, "w") as f:
            f.write("99999999")  # PID that doesn't exist
        ti.clean_stale_locks()
        assert not os.path.isfile(lock_path)

    def test_keeps_active_lock(self, clean_dirs):
        os.makedirs(ti._LOCK_DIR, exist_ok=True)
        lock_path = os.path.join(ti._LOCK_DIR, "active.lock")
        with open(lock_path, "w") as f:
            f.write(str(os.getpid()))  # Our own PID — still alive
        ti.clean_stale_locks()
        assert os.path.isfile(lock_path)

    def test_handles_corrupt_lock_file(self, clean_dirs):
        os.makedirs(ti._LOCK_DIR, exist_ok=True)
        lock_path = os.path.join(ti._LOCK_DIR, "corrupt.lock")
        with open(lock_path, "w") as f:
            f.write("not-a-pid")
        ti.clean_stale_locks()
        assert not os.path.isfile(lock_path)

    def test_no_lock_dir(self, clean_dirs):
        """If lock dir doesn't exist, no crash."""
        ti.clean_stale_locks()


# ---------------------------------------------------------------------------
# Install tool (mock subprocess)
# ---------------------------------------------------------------------------

class TestInstallTool:
    @pytest.mark.asyncio
    async def test_install_unknown_tool(self, clean_dirs):
        logs = []
        result = await ti.install_tool("fake_tool", progress_callback=AsyncMock(side_effect=lambda msg: logs.append(msg)))
        assert result is False
        assert any("Unknown tool" in l for l in logs)

    @pytest.mark.asyncio
    async def test_install_already_installed(self, clean_dirs):
        venv_bin = os.path.join(ti._VENV_DIR, "bin")
        os.makedirs(venv_bin, exist_ok=True)
        with open(os.path.join(venv_bin, "aider"), "w") as f:
            f.write("#!/bin/bash\n")
        logs = []
        result = await ti.install_tool("aider", progress_callback=AsyncMock(side_effect=lambda msg: logs.append(msg)))
        assert result is True
        assert any("already installed" in l for l in logs)


# ---------------------------------------------------------------------------
# Jupyter config helper
# ---------------------------------------------------------------------------

class TestSetupJupyterConfig:
    def test_creates_config(self, clean_dirs, tmp_path):
        jupyter_dir = str(tmp_path / ".jupyter")
        with patch.dict(os.environ, {"HOME": str(tmp_path)}):
            ti._setup_jupyter_config()
        config_path = os.path.join(jupyter_dir, "jupyter_server_config.py")
        assert os.path.isfile(config_path)
        with open(config_path) as f:
            content = f.read()
        assert "terminado_settings" in content

    def test_appends_to_existing_config(self, clean_dirs, tmp_path):
        jupyter_dir = tmp_path / ".jupyter"
        jupyter_dir.mkdir()
        config_path = jupyter_dir / "jupyter_server_config.py"
        config_path.write_text("# existing config\n")
        with patch.dict(os.environ, {"HOME": str(tmp_path)}):
            ti._setup_jupyter_config()
        content = config_path.read_text()
        assert "# existing config" in content
        assert "terminado_settings" in content

    def test_does_not_duplicate_config(self, clean_dirs, tmp_path):
        jupyter_dir = tmp_path / ".jupyter"
        jupyter_dir.mkdir()
        config_path = jupyter_dir / "jupyter_server_config.py"
        config_path.write_text("c.ServerApp.terminado_settings = {'shell_command': ['/bin/bash']}\n")
        with patch.dict(os.environ, {"HOME": str(tmp_path)}):
            ti._setup_jupyter_config()
        content = config_path.read_text()
        assert content.count("terminado_settings") == 1


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

class TestToolRegistry:
    def test_all_tools_have_required_fields(self):
        for tool_id, info in ti.TOOL_REGISTRY.items():
            assert "type" in info, f"{tool_id} missing type"
            assert "packages" in info, f"{tool_id} missing packages"
            assert "binary" in info, f"{tool_id} missing binary"
            assert "display_name" in info, f"{tool_id} missing display_name"
            assert info["type"] in ("pip", "npm"), f"{tool_id} has invalid type"

    def test_known_tools_exist(self):
        assert "aider" in ti.TOOL_REGISTRY
        assert "opencode" in ti.TOOL_REGISTRY
        assert "claude" in ti.TOOL_REGISTRY
        assert "jupyterlab" in ti.TOOL_REGISTRY
