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


def _write_npm_package(package_name: str, version: str) -> None:
    package_dir = ti._npm_package_path(package_name)
    os.makedirs(package_dir, exist_ok=True)
    with open(os.path.join(package_dir, "package.json"), "w", encoding="utf-8") as f:
        json.dump({"name": package_name, "version": version}, f)


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

    def test_surfaces_npm_version_drift(self, clean_dirs):
        npm_bin = os.path.join(ti._NPM_DIR, "bin")
        os.makedirs(npm_bin, exist_ok=True)
        with open(os.path.join(npm_bin, "claude"), "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n")
        _write_npm_package("@anthropic-ai/claude-code", "2.1.170")

        with patch("shutil.which", return_value=None):
            status = ti.get_all_tool_status()

        claude = status["claude"]
        assert claude["installed"] is True
        assert claude["installed_version"] == "2.1.170"
        assert claude["pinned_version"] == "2.1.202"
        assert claude["version_drift"] is True
        assert claude["package_versions"]["@anthropic-ai/claude-code"] == {
            "installed": "2.1.170",
            "pinned": "2.1.202",
            "drift": True,
        }


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

    def test_removes_active_lock_on_startup(self, clean_dirs):
        os.makedirs(ti._LOCK_DIR, exist_ok=True)
        lock_path = os.path.join(ti._LOCK_DIR, "active.lock")
        with open(lock_path, "w") as f:
            f.write(str(os.getpid()))  # Startup cleanup removes all locks, even live PIDs
        ti.clean_stale_locks()
        assert not os.path.isfile(lock_path)

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
        with patch("app.settings_manager.get_storage_dir", return_value=str(clean_dirs / "work")), \
             patch("app.harness_config.sync_harness_defaults") as sync:
            result = await ti.install_tool("aider", progress_callback=AsyncMock(side_effect=lambda msg: logs.append(msg)))
        assert result is True
        sync.assert_called_once()
        assert sync.call_args.kwargs["harnesses"] == ["aider"]
        assert any("already installed" in l for l in logs)

    @pytest.mark.asyncio
    async def test_install_already_installed_opencode_syncs_defaults(self, clean_dirs, tmp_path):
        npm_bin = os.path.join(ti._NPM_DIR, "bin")
        os.makedirs(npm_bin, exist_ok=True)
        with open(os.path.join(npm_bin, "opencode"), "w") as f:
            f.write("#!/bin/bash\n")
        logs = []
        with patch("app.settings_manager.get_storage_dir", return_value=str(tmp_path / "work")), \
             patch("app.harness_config.sync_harness_defaults") as sync:
            result = await ti.install_tool("opencode", progress_callback=AsyncMock(side_effect=lambda msg: logs.append(msg)))
        assert result is True
        sync.assert_called_once()
        assert sync.call_args.kwargs["harnesses"] == ["opencode"]
        assert any("already installed" in l for l in logs)
        assert any("harness defaults synchronized" in l for l in logs)

    @pytest.mark.asyncio
    async def test_install_already_installed_pi_syncs_defaults(self, clean_dirs, tmp_path):
        npm_bin = os.path.join(ti._NPM_DIR, "bin")
        os.makedirs(npm_bin, exist_ok=True)
        with open(os.path.join(npm_bin, "pi"), "w") as f:
            f.write("#!/bin/bash\n")
        _write_npm_package("@earendil-works/pi-coding-agent", "0.80.3")
        _write_npm_package("pi-mcp-adapter", "2.10.0")
        _write_npm_package("@gotgenes/pi-permission-system", "16.0.1")
        _write_npm_package("pi-subagents", "0.33.1")
        _write_npm_package("pi-web-access", "0.10.7")
        _write_npm_package("@lebronj/pi-lsp", "0.0.3")
        _write_npm_package("pyright", "1.1.411")
        logs = []
        with patch("app.settings_manager.get_storage_dir", return_value=str(tmp_path / "work")), \
             patch("app.harness_config.sync_harness_defaults") as sync:
            result = await ti.install_tool("pi", progress_callback=AsyncMock(side_effect=lambda msg: logs.append(msg)))
        assert result is True
        sync.assert_called_once()
        assert sync.call_args.kwargs["harnesses"] == ["pi"]
        assert any("already installed" in l for l in logs)
        assert any("harness defaults synchronized" in l for l in logs)

    @pytest.mark.asyncio
    async def test_install_already_installed_goose_syncs_defaults(self, clean_dirs, tmp_path):
        local_bin = tmp_path / ".local" / "bin"
        local_bin.mkdir(parents=True)
        (local_bin / "goose").write_text("#!/bin/bash\n", encoding="utf-8")
        logs = []
        with patch.dict(os.environ, {"HOME": str(tmp_path)}), \
             patch("app.settings_manager.get_storage_dir", return_value=str(tmp_path / "work")), \
             patch("app.harness_config.sync_harness_defaults") as sync:
            result = await ti.install_tool("goose", progress_callback=AsyncMock(side_effect=lambda msg: logs.append(msg)))
        assert result is True
        sync.assert_called_once()
        assert sync.call_args.kwargs["harnesses"] == ["goose"]
        assert any("already installed" in l for l in logs)
        assert any("harness defaults synchronized" in l for l in logs)

    @pytest.mark.asyncio
    async def test_install_already_installed_claude_syncs_defaults(self, clean_dirs, tmp_path):
        npm_bin = os.path.join(ti._NPM_DIR, "bin")
        os.makedirs(npm_bin, exist_ok=True)
        with open(os.path.join(npm_bin, "claude"), "w") as f:
            f.write("#!/bin/bash\n")
        _write_npm_package("@anthropic-ai/claude-code", "2.1.202")
        logs = []
        with patch("app.settings_manager.get_storage_dir", return_value=str(tmp_path / "work")), \
             patch("app.harness_config.sync_harness_defaults") as sync:
            result = await ti.install_tool("claude", progress_callback=AsyncMock(side_effect=lambda msg: logs.append(msg)))
        assert result is True
        sync.assert_called_once()
        assert sync.call_args.kwargs["harnesses"] == ["claude"]
        assert any("already installed" in l for l in logs)
        assert any("harness defaults synchronized" in l for l in logs)

    @pytest.mark.asyncio
    async def test_install_existing_claude_with_version_drift_upgrades(self, clean_dirs, tmp_path):
        npm_bin = os.path.join(ti._NPM_DIR, "bin")
        os.makedirs(npm_bin, exist_ok=True)
        with open(os.path.join(npm_bin, "claude"), "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n")
        _write_npm_package("@anthropic-ai/claude-code", "2.1.170")
        logs = []

        async def fake_install_npm(packages, progress_callback=None):
            _write_npm_package("@anthropic-ai/claude-code", "2.1.202")
            return True

        with patch("app.tool_installer._install_npm", side_effect=fake_install_npm) as install_npm, \
             patch("app.tool_installer._run_post_install_hook", new_callable=AsyncMock) as post_hook:
            result = await ti.install_tool(
                "claude",
                progress_callback=AsyncMock(side_effect=lambda msg: logs.append(msg)),
            )

        assert result is True
        install_npm.assert_called_once()
        assert install_npm.call_args.args[0] == ["@anthropic-ai/claude-code@2.1.202"]
        post_hook.assert_awaited_once()
        assert any("does not match the pinned version; upgrading" in line for line in logs)


# ---------------------------------------------------------------------------
# Archive installer
# ---------------------------------------------------------------------------

class TestArchiveInstaller:
    @pytest.mark.asyncio
    async def test_archive_binary_downloads_extracts_and_installs_executable(self, clean_dirs, tmp_path):
        logs = []
        commands = []

        async def fake_run(cmd, progress_callback=None, extra_env=None):
            commands.append(cmd)
            if cmd[0] == "curl":
                if progress_callback:
                    await progress_callback("curl ok\r\n")
                return True
            if cmd[0] == "tar":
                extract_dir = cmd[cmd.index("-C") + 1]
                os.makedirs(extract_dir, exist_ok=True)
                source = os.path.join(extract_dir, "goose")
                with open(source, "w", encoding="utf-8") as f:
                    f.write("#!/bin/sh\n")
                return True
            raise AssertionError(f"unexpected command: {cmd}")

        url = "https://example.test/goose.tar.bz2"
        with patch.dict(os.environ, {"HOME": str(tmp_path)}), \
             patch("app.tool_installer._run_install_cmd", side_effect=fake_run):
            result = await ti._install_archive_binary(
                url,
                "goose",
                "goose",
                progress_callback=AsyncMock(side_effect=lambda msg: logs.append(msg)),
            )

        installed = tmp_path / ".local" / "bin" / "goose"
        assert result is True
        assert installed.is_file()
        assert os.access(installed, os.X_OK)
        assert commands[0][:5] == ["curl", "-fL", "--show-error", "--silent", "--output"]
        assert commands[0][-1] == url
        assert commands[1][0] == "tar"
        assert "-xjf" in commands[1]
        assert any("Binary found at:" in line for line in logs)

    @pytest.mark.asyncio
    async def test_archive_binary_reports_underlying_curl_error(self, clean_dirs, tmp_path):
        logs = []
        commands = []

        async def fake_run(cmd, progress_callback=None, extra_env=None):
            commands.append(cmd)
            if progress_callback:
                await progress_callback("curl: (22) The requested URL returned error: 404\r\n")
            return False

        with patch.dict(os.environ, {"HOME": str(tmp_path)}), \
             patch("app.tool_installer._run_install_cmd", side_effect=fake_run):
            result = await ti._install_archive_binary(
                "https://example.test/missing.tar.bz2",
                "goose",
                "goose",
                progress_callback=AsyncMock(side_effect=lambda msg: logs.append(msg)),
            )

        assert result is False
        assert [cmd[0] for cmd in commands] == ["curl"]
        assert any("curl: (22)" in line for line in logs)
        assert any("Download failed" in line for line in logs)

    @pytest.mark.asyncio
    async def test_archive_binary_reports_underlying_tar_error(self, clean_dirs, tmp_path):
        logs = []
        commands = []

        async def fake_run(cmd, progress_callback=None, extra_env=None):
            commands.append(cmd)
            if cmd[0] == "curl":
                return True
            if progress_callback:
                await progress_callback("tar: This does not look like a tar archive\r\n")
            return False

        with patch.dict(os.environ, {"HOME": str(tmp_path)}), \
             patch("app.tool_installer._run_install_cmd", side_effect=fake_run):
            result = await ti._install_archive_binary(
                "https://example.test/bad.tar.bz2",
                "goose",
                "goose",
                progress_callback=AsyncMock(side_effect=lambda msg: logs.append(msg)),
            )

        assert result is False
        assert [cmd[0] for cmd in commands] == ["curl", "tar"]
        assert any("tar:" in line for line in logs)
        assert any("Extraction failed" in line for line in logs)


# ---------------------------------------------------------------------------
# Pip uninstall
# ---------------------------------------------------------------------------

class TestPipUninstall:
    @pytest.mark.asyncio
    async def test_uninstall_pip_uses_venv_python_with_local_offline_env(self, clean_dirs):
        venv_bin = os.path.join(ti._VENV_DIR, "bin")
        os.makedirs(venv_bin, exist_ok=True)
        python = os.path.join(venv_bin, "python")
        with open(python, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n")
        with open(os.path.join(venv_bin, "aider"), "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n")

        commands = []
        envs = []

        async def fake_run(cmd, progress_callback=None, extra_env=None):
            commands.append(cmd)
            envs.append(extra_env)
            return True

        with patch("app.tool_installer._run_install_cmd", side_effect=fake_run):
            result = await ti.uninstall_tool("aider")

        assert result is True
        assert commands == [
            [
                python,
                "-m",
                "pip",
                "--disable-pip-version-check",
                "uninstall",
                "-y",
                "aider-chat",
                "streamlit",
            ]
        ]
        assert envs[0]["PIP_DISABLE_PIP_VERSION_CHECK"] == "1"
        assert envs[0]["PIP_NO_INPUT"] == "1"
        assert envs[0]["PIP_NO_INDEX"] == "1"

    @pytest.mark.asyncio
    async def test_uninstall_pip_repairs_and_retries_after_pip_crash(self, clean_dirs):
        venv_bin = os.path.join(ti._VENV_DIR, "bin")
        os.makedirs(venv_bin, exist_ok=True)
        python = os.path.join(venv_bin, "python")
        with open(python, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n")
        with open(os.path.join(venv_bin, "aider"), "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n")

        commands = []
        logs = []

        async def fake_run(cmd, progress_callback=None, extra_env=None):
            commands.append(cmd)
            if len(commands) == 1:
                if progress_callback:
                    await progress_callback("FileNotFoundError: certifi/cacert.pem\r\n")
                return False
            return True

        with patch("app.tool_installer._run_install_cmd", side_effect=fake_run):
            result = await ti.uninstall_tool(
                "aider",
                progress_callback=AsyncMock(side_effect=lambda msg: logs.append(msg)),
            )

        assert result is True
        assert commands[0][2:6] == ["pip", "--disable-pip-version-check", "uninstall", "-y"]
        assert commands[1] == [python, "-m", "ensurepip", "--upgrade"]
        assert commands[2][2:6] == ["pip", "--disable-pip-version-check", "uninstall", "-y"]
        assert any("FileNotFoundError" in line for line in logs)
        assert any("attempting local pip repair" in line for line in logs)
        assert any("Repairing virtualenv pip" in line for line in logs)

    @pytest.mark.asyncio
    async def test_uninstall_pip_restores_missing_vendored_certifi(self, clean_dirs):
        venv_bin = os.path.join(ti._VENV_DIR, "bin")
        os.makedirs(venv_bin, exist_ok=True)
        python = os.path.join(venv_bin, "python")
        with open(python, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n")
        with open(os.path.join(venv_bin, "aider"), "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n")

        site_packages = os.path.join(ti._VENV_DIR, "lib", "python3.11", "site-packages")
        vendored_certifi = os.path.join(site_packages, "pip", "_vendor", "certifi")
        top_level_certifi = os.path.join(site_packages, "certifi")
        os.makedirs(vendored_certifi, exist_ok=True)
        os.makedirs(top_level_certifi, exist_ok=True)
        with open(os.path.join(top_level_certifi, "cacert.pem"), "w", encoding="utf-8") as f:
            f.write("CERT-BUNDLE")

        commands = []
        logs = []

        async def fake_run(cmd, progress_callback=None, extra_env=None):
            commands.append(cmd)
            if len(commands) == 1:
                if progress_callback:
                    await progress_callback("FileNotFoundError: pip/_vendor/certifi/cacert.pem\r\n")
                return False
            return True

        with patch("app.tool_installer._run_install_cmd", side_effect=fake_run):
            result = await ti.uninstall_tool(
                "aider",
                progress_callback=AsyncMock(side_effect=lambda msg: logs.append(msg)),
            )

        assert result is True
        assert commands[1] == [python, "-m", "ensurepip", "--upgrade"]
        restored = os.path.join(vendored_certifi, "cacert.pem")
        assert os.path.isfile(restored)
        with open(restored, encoding="utf-8") as f:
            assert f.read() == "CERT-BUNDLE"
        assert any("Restored pip vendored certifi bundle" in line for line in logs)

    @pytest.mark.asyncio
    async def test_uninstall_pip_reports_repair_failure(self, clean_dirs):
        venv_bin = os.path.join(ti._VENV_DIR, "bin")
        os.makedirs(venv_bin, exist_ok=True)
        with open(os.path.join(venv_bin, "python"), "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n")
        with open(os.path.join(venv_bin, "aider"), "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n")

        async def fake_run(cmd, progress_callback=None, extra_env=None):
            if progress_callback:
                await progress_callback("pip traceback on stderr\r\n")
            return False

        logs = []
        with patch("app.tool_installer._run_install_cmd", side_effect=fake_run):
            result = await ti.uninstall_tool(
                "aider",
                progress_callback=AsyncMock(side_effect=lambda msg: logs.append(msg)),
            )

        assert result is False
        assert any("pip traceback on stderr" in line for line in logs)
        assert any("Pip repair failed" in line for line in logs)
        assert any("Failed to uninstall Aider" in line for line in logs)


# ---------------------------------------------------------------------------
# Npm uninstall
# ---------------------------------------------------------------------------

class TestNpmUninstall:
    def test_npm_package_name_strips_versions(self):
        assert (
            ti._npm_package_name("@earendil-works/pi-coding-agent@0.80.3")
            == "@earendil-works/pi-coding-agent"
        )
        assert (
            ti._npm_package_name("@gotgenes/pi-permission-system")
            == "@gotgenes/pi-permission-system"
        )
        assert ti._npm_package_name("pyright@1.1.411") == "pyright"
        assert ti._npm_package_name("opencode-ai") == "opencode-ai"
        assert (
            ti._npm_package_version("@anthropic-ai/claude-code@2.1.202")
            == "2.1.202"
        )
        assert ti._npm_package_version("@openai/codex") is None
        assert ti._npm_package_version("pyright@1.1.411") == "1.1.411"

    @pytest.mark.asyncio
    async def test_uninstall_npm_uses_unversioned_package_names_and_verifies_absence(self, clean_dirs):
        npm_bin = os.path.join(ti._NPM_DIR, "bin")
        os.makedirs(npm_bin, exist_ok=True)
        pi_bin = os.path.join(npm_bin, "pi")
        with open(pi_bin, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n")

        package_dir = ti._npm_package_path("@earendil-works/pi-coding-agent")
        os.makedirs(package_dir, exist_ok=True)
        commands = []

        async def fake_run(cmd, progress_callback=None, extra_env=None):
            commands.append(cmd)
            shutil.rmtree(package_dir)
            os.remove(pi_bin)
            return True

        logs = []
        with patch("app.tool_installer._run_install_cmd", side_effect=fake_run):
            result = await ti.uninstall_tool(
                "pi",
                progress_callback=AsyncMock(side_effect=lambda msg: logs.append(msg)),
            )

        assert result is True
        uninstall_cmd = commands[0]
        assert uninstall_cmd[:4] == ["npm", "uninstall", "-g", f"--prefix={ti._NPM_DIR}"]
        assert "@earendil-works/pi-coding-agent" in uninstall_cmd
        assert "@earendil-works/pi-coding-agent@0.80.3" not in uninstall_cmd
        assert "@gotgenes/pi-permission-system" in uninstall_cmd
        assert "@gotgenes/pi-permission-system@16.0.1" not in uninstall_cmd
        assert "pyright" in uninstall_cmd
        assert "pyright@1.1.411" not in uninstall_cmd
        assert any("uninstalled successfully" in line for line in logs)

    @pytest.mark.asyncio
    async def test_uninstall_npm_fails_when_package_or_binary_remains(self, clean_dirs):
        npm_bin = os.path.join(ti._NPM_DIR, "bin")
        os.makedirs(npm_bin, exist_ok=True)
        with open(os.path.join(npm_bin, "pi"), "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n")

        package_dir = ti._npm_package_path("@earendil-works/pi-coding-agent")
        os.makedirs(package_dir, exist_ok=True)

        async def fake_run(cmd, progress_callback=None, extra_env=None):
            return True

        logs = []
        with patch("app.tool_installer._run_install_cmd", side_effect=fake_run):
            result = await ti.uninstall_tool(
                "pi",
                progress_callback=AsyncMock(side_effect=lambda msg: logs.append(msg)),
            )

        assert result is False
        assert any("Npm uninstall left managed files behind" in line for line in logs)
        assert any("@earendil-works/pi-coding-agent" in line for line in logs)
        assert any("pi binary" in line for line in logs)
        assert any("Failed to uninstall Pi" in line for line in logs)


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
            assert "binary" in info, f"{tool_id} missing binary"
            assert "display_name" in info, f"{tool_id} missing display_name"
            assert info["type"] in ("pip", "npm", "shell", "archive"), f"{tool_id} has invalid type"
            if info["type"] == "shell":
                assert "install_cmd" in info, f"{tool_id} missing install_cmd"
            elif info["type"] == "archive":
                assert "archive_url" in info, f"{tool_id} missing archive_url"
                assert "archive_member" in info, f"{tool_id} missing archive_member"
            else:
                assert "packages" in info, f"{tool_id} missing packages"

    def test_known_tools_exist(self):
        assert "aider" in ti.TOOL_REGISTRY
        assert "opencode" in ti.TOOL_REGISTRY
        assert "goose" in ti.TOOL_REGISTRY
        assert "claude" in ti.TOOL_REGISTRY
        assert "jupyterlab" in ti.TOOL_REGISTRY
        assert "antigravity" in ti.TOOL_REGISTRY
        assert "codex" in ti.TOOL_REGISTRY

    def test_pi_registry_installs_pinned_extension_stack(self):
        packages = ti.TOOL_REGISTRY["pi"]["packages"]
        assert packages == [
            "@earendil-works/pi-coding-agent@0.80.3",
            "pi-mcp-adapter@2.10.0",
            "@gotgenes/pi-permission-system@16.0.1",
            "pi-subagents@0.33.1",
            "pi-web-access@0.10.7",
            "@lebronj/pi-lsp@0.0.3",
            "pyright@1.1.411",
        ]
        assert ti._SIZE_MB["pi"] == 700

    def test_goose_registry_installs_pinned_cli(self):
        info = ti.TOOL_REGISTRY["goose"]
        assert info["type"] == "archive"
        assert info["binary"] == "goose"
        assert info["archive_url"] == (
            "https://github.com/aaif-goose/goose/releases/download/v1.41.0/"
            "goose-x86_64-unknown-linux-gnu.tar.bz2"
        )
        assert info["archive_member"] == "goose"
        assert ti._SIZE_MB["goose"] == 200

    def test_claude_registry_installs_pinned_cli(self):
        assert ti.TOOL_REGISTRY["claude"]["packages"] == ["@anthropic-ai/claude-code@2.1.202"]


def test_tool_installer_paths_are_isolated_by_storage_dir(storage_dir):
    """tool_installer must never touch the production storage path in tests.

    Its path constants are resolved at module import time, and this module
    imports app.tool_installer at module scope -- so pytest freezes them at
    COLLECTION, before any fixture sets FABRIC_STORAGE_DIR. Without the
    redirect in the storage_dir fixture they stay at /home/fabric/work, and
    any test reaching the install path calls os.makedirs on it: that fails
    outright on a bare CI runner (PermissionError: '/home/fabric') and writes
    outside tmp_path anywhere it succeeds.
    """
    from app import tool_installer as ti

    for name in ("AI_TOOLS_DIR", "_VENV_DIR", "_NPM_DIR", "_MANIFEST_PATH", "_LOCK_DIR"):
        value = getattr(ti, name)
        assert str(storage_dir) in value, f"{name} leaked outside tmp storage: {value}"

    ti._ensure_dirs()
    assert os.path.isdir(ti.AI_TOOLS_DIR)
    assert os.path.isdir(ti._LOCK_DIR)
