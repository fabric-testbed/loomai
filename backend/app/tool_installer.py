"""Lazy-install manager for AI tools — installs into persistent volume on first use."""
from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Base directory for lazy-installed tools (inside the Docker volume)
def _get_ai_tools_dir() -> str:
    from app.settings_manager import get_ai_tools_dir
    return get_ai_tools_dir()

# Module-level constants — computed lazily to avoid circular imports at import time.
# Callers that need the current value should call _get_ai_tools_dir() directly.
# These are set at import time for backward compatibility with direct importers.
_STORAGE_DIR = os.environ.get("FABRIC_STORAGE_DIR", "/home/fabric/work")
AI_TOOLS_DIR = os.path.join(_STORAGE_DIR, ".ai-tools")
_VENV_DIR = os.path.join(AI_TOOLS_DIR, "venv")
_NPM_DIR = os.path.join(AI_TOOLS_DIR, "npm")
_MANIFEST_PATH = os.path.join(AI_TOOLS_DIR, ".installed.json")
_LOCK_DIR = os.path.join(AI_TOOLS_DIR, ".locks")

# Tool registry — defines what to install for each tool
TOOL_REGISTRY: dict[str, dict] = {
    "aider": {
        "type": "pip",
        "packages": ["aider-chat", "streamlit"],
        "binary": "aider",
        "display_name": "Aider",
        "size_estimate": "~900 MB",
    },
    "opencode": {
        "type": "npm",
        "packages": ["opencode-ai"],
        "binary": "opencode",
        "display_name": "OpenCode",
        "size_estimate": "~200 MB",
    },
    "crush": {
        "type": "npm",
        "packages": ["@charmland/crush"],
        "binary": "crush",
        "display_name": "Crush",
        "size_estimate": "~150 MB",
    },
    "claude": {
        "type": "npm",
        "packages": ["@anthropic-ai/claude-code"],
        "binary": "claude",
        "display_name": "Claude Code",
        "size_estimate": "~1 GB",
    },
    "deepagents": {
        "type": "pip",
        "packages": ["deepagents-cli[anthropic]"],
        "binary": "deepagents",
        "display_name": "Deep Agents",
        "size_estimate": "~500 MB",
    },
    "jupyterlab": {
        "type": "pip",
        "packages": ["jupyterlab", "ipykernel", "pandas", "matplotlib", "numpy"],
        "binary": "jupyter",
        "display_name": "JupyterLab",
        "size_estimate": "~250 MB",
    },
}


def _ensure_dirs() -> None:
    """Create the AI tools directory structure."""
    os.makedirs(AI_TOOLS_DIR, exist_ok=True)
    os.makedirs(_LOCK_DIR, exist_ok=True)


def _venv_bin() -> str:
    return os.path.join(_VENV_DIR, "bin")


def _npm_bin() -> str:
    return os.path.join(_NPM_DIR, "bin")


def _ensure_venv() -> None:
    """Create the virtualenv if it doesn't exist."""
    if os.path.isfile(os.path.join(_venv_bin(), "python")):
        return
    logger.info("Creating AI tools virtualenv at %s", _VENV_DIR)
    subprocess.run(
        [sys.executable, "-m", "venv", _VENV_DIR],
        check=True,
        capture_output=True,
    )
    # Upgrade pip in the venv
    subprocess.run(
        [os.path.join(_venv_bin(), "pip"), "install", "--upgrade", "pip"],
        capture_output=True,
    )


def _ensure_npm_prefix() -> None:
    """Create the npm prefix directory."""
    os.makedirs(_NPM_DIR, exist_ok=True)


def get_tool_binary_path(tool_id: str) -> str | None:
    """Return the full path to a tool's binary, or None if not found."""
    info = TOOL_REGISTRY.get(tool_id)
    if not info:
        return None
    binary = info["binary"]
    if info["type"] == "pip":
        path = os.path.join(_venv_bin(), binary)
    else:
        path = os.path.join(_npm_bin(), binary)
    return path if os.path.isfile(path) else None


def is_tool_installed(tool_id: str) -> bool:
    """Check if a tool's binary exists on disk."""
    return get_tool_binary_path(tool_id) is not None


def get_tool_env() -> dict[str, str]:
    """Return env dict with PATH extended for lazy-installed tools."""
    env = dict(os.environ)
    extra_paths = []
    if os.path.isdir(_venv_bin()):
        extra_paths.append(_venv_bin())
    if os.path.isdir(_npm_bin()):
        extra_paths.append(_npm_bin())
    if extra_paths:
        env["PATH"] = ":".join(extra_paths) + ":" + env.get("PATH", "")
    return env


def get_all_tool_status() -> dict[str, dict]:
    """Return install status for all tools."""
    result = {}
    for tool_id, info in TOOL_REGISTRY.items():
        result[tool_id] = {
            "installed": is_tool_installed(tool_id),
            "display_name": info["display_name"],
            "size_estimate": info["size_estimate"],
            "type": info["type"],
        }
    return result


class _ToolLock:
    """File-based lock to prevent concurrent installs of the same tool."""

    def __init__(self, tool_id: str):
        _ensure_dirs()
        self._path = os.path.join(_LOCK_DIR, f"{tool_id}.lock")
        self._fd: int | None = None

    def acquire(self) -> bool:
        self._fd = os.open(self._path, os.O_CREAT | os.O_WRONLY)
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Write our PID for diagnostics
            os.ftruncate(self._fd, 0)
            os.write(self._fd, str(os.getpid()).encode())
            return True
        except OSError:
            os.close(self._fd)
            self._fd = None
            return False

    def release(self) -> None:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
            try:
                os.unlink(self._path)
            except OSError:
                pass


async def install_tool(
    tool_id: str,
    progress_callback=None,
) -> bool:
    """Install a tool. Streams progress via optional callback.

    progress_callback(line: str) is called for each line of install output.
    Returns True on success.
    """
    info = TOOL_REGISTRY.get(tool_id)
    if not info:
        if progress_callback:
            await progress_callback(f"Unknown tool: {tool_id}\r\n")
        return False

    if is_tool_installed(tool_id):
        if progress_callback:
            await progress_callback(f"{info['display_name']} is already installed.\r\n")
        return True

    lock = _ToolLock(tool_id)
    if not lock.acquire():
        if progress_callback:
            await progress_callback(
                f"{info['display_name']} is being installed by another process. Please wait...\r\n"
            )
        # Wait for the other install to finish
        for _ in range(300):  # up to 5 minutes
            await asyncio.sleep(1)
            if is_tool_installed(tool_id):
                if progress_callback:
                    await progress_callback(f"{info['display_name']} is now available.\r\n")
                return True
        if progress_callback:
            await progress_callback("Timed out waiting for install.\r\n")
        return False

    try:
        _ensure_dirs()
        if progress_callback:
            await progress_callback(
                f"\x1b[36mInstalling {info['display_name']} ({info['size_estimate']})...\x1b[0m\r\n"
            )

        if info["type"] == "pip":
            success = await _install_pip(info["packages"], progress_callback)
        else:
            success = await _install_npm(info["packages"], progress_callback)

        if success:
            _update_manifest(tool_id, info)
            if progress_callback:
                await progress_callback(
                    f"\x1b[32m{info['display_name']} installed successfully.\x1b[0m\r\n"
                )

            # Post-install hooks
            if tool_id == "jupyterlab":
                _setup_jupyter_config()
        else:
            if progress_callback:
                await progress_callback(
                    f"\x1b[31mFailed to install {info['display_name']}.\x1b[0m\r\n"
                )
        return success
    finally:
        lock.release()


async def _install_pip(packages: list[str], progress_callback=None) -> bool:
    """Install pip packages into the venv."""
    _ensure_venv()
    pip = os.path.join(_venv_bin(), "pip")
    cmd = [pip, "install", "--no-cache-dir"] + packages
    return await _run_install_cmd(cmd, progress_callback)


async def _install_npm(packages: list[str], progress_callback=None) -> bool:
    """Install npm packages globally into our prefix."""
    _ensure_npm_prefix()
    cmd = ["npm", "install", "-g", f"--prefix={_NPM_DIR}"] + packages
    return await _run_install_cmd(cmd, progress_callback)


async def _run_install_cmd(cmd: list[str], progress_callback=None) -> bool:
    """Run an install command, streaming output line-by-line."""
    logger.info("Running install: %s", " ".join(cmd))
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=get_tool_env(),
        )
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace")
            if progress_callback:
                await progress_callback(text.rstrip("\n") + "\r\n")
        await proc.wait()
        success = proc.returncode == 0
        if not success:
            logger.error("Install failed (rc=%d): %s", proc.returncode, " ".join(cmd))
        return success
    except Exception as e:
        logger.exception("Install command failed: %s", e)
        if progress_callback:
            await progress_callback(f"\x1b[31mError: {e}\x1b[0m\r\n")
        return False


def _update_manifest(tool_id: str, info: dict) -> None:
    """Update the installed tools manifest."""
    manifest = {}
    if os.path.isfile(_MANIFEST_PATH):
        try:
            with open(_MANIFEST_PATH) as f:
                manifest = json.load(f)
        except Exception:
            pass
    manifest[tool_id] = {
        "packages": info["packages"],
        "type": info["type"],
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with open(_MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)


def _setup_jupyter_config() -> None:
    """Configure JupyterLab terminals and kernel (post-install hook)."""
    # Terminal config
    jupyter_dir = os.path.expanduser("~/.jupyter")
    os.makedirs(jupyter_dir, exist_ok=True)
    config_path = os.path.join(jupyter_dir, "jupyter_server_config.py")
    config_line = "c.ServerApp.terminado_settings = {'shell_command': ['/bin/bash']}\n"
    if os.path.isfile(config_path):
        with open(config_path) as f:
            if "terminado_settings" not in f.read():
                with open(config_path, "a") as f2:
                    f2.write(config_line)
    else:
        with open(config_path, "w") as f:
            f.write(config_line)

    # Register kernel spec pointing to venv Python explicitly
    kernel_dir = os.path.join(_VENV_DIR, "share", "jupyter", "kernels", "python3")
    os.makedirs(kernel_dir, exist_ok=True)
    kernel_spec = {
        "argv": [os.path.join(_venv_bin(), "python"), "-m", "ipykernel_launcher", "-f", "{connection_file}"],
        "display_name": "Python 3",
        "language": "python",
    }
    with open(os.path.join(kernel_dir, "kernel.json"), "w") as f:
        json.dump(kernel_spec, f, indent=2)


def fixup_jupyter_kernel() -> None:
    """Ensure JupyterLab kernel has data science packages (handles pre-existing installs)."""
    if not is_tool_installed("jupyterlab"):
        return
    venv_python = os.path.join(_venv_bin(), "python")
    kernel_json = os.path.join(_VENV_DIR, "share", "jupyter", "kernels", "python3", "kernel.json")

    # Check if kernel spec needs fixing (uses relative "python" instead of absolute path)
    needs_fix = False
    if os.path.isfile(kernel_json):
        try:
            with open(kernel_json) as f:
                spec = json.load(f)
            if spec.get("argv", [None])[0] != venv_python:
                needs_fix = True
        except Exception:
            needs_fix = True
    else:
        needs_fix = True

    if needs_fix:
        # Install missing packages
        pip = os.path.join(_venv_bin(), "pip")
        subprocess.run(
            [pip, "install", "--no-cache-dir", "ipykernel", "pandas", "matplotlib", "numpy"],
            capture_output=True,
        )
        _setup_jupyter_config()
        logger.info("Fixed JupyterLab kernel spec and installed data science packages")


def clean_stale_locks() -> None:
    """Remove stale lock files on startup (from crashed installs)."""
    if not os.path.isdir(_LOCK_DIR):
        return
    for fname in os.listdir(_LOCK_DIR):
        if not fname.endswith(".lock"):
            continue
        path = os.path.join(_LOCK_DIR, fname)
        try:
            with open(path) as f:
                pid = int(f.read().strip())
            # Check if the PID is still alive
            os.kill(pid, 0)
        except (ValueError, OSError):
            # PID is dead or file is corrupt — remove the lock
            try:
                os.unlink(path)
                logger.info("Cleaned stale lock: %s", fname)
            except OSError:
                pass
