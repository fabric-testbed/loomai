"""Central settings management for Loomai / fabric-webgui.

All application settings are stored in a single ``settings.json`` file
inside ``{FABRIC_STORAGE_DIR}/.loomai/``.  Legacy ``fabric_rc`` and
``.ai_tools.json`` files are migrated automatically on first load.

Public API
----------
- ``load_settings()`` / ``save_settings(settings)`` — read/write the full dict
- ``get_*`` / ``set_*`` accessors — typed convenience for individual settings
- ``generate_fabric_rc(settings)`` / ``generate_ssh_config(settings)`` — derived files
- ``migrate_from_legacy()`` — one-time import of fabric_rc + .ai_tools.json
- Tool-config helpers: ``seed_tool_configs``, ``reset_tool_config``, ``get_tool_config_status``
"""
from __future__ import annotations

import copy
import json
import logging
import os
import shutil
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SETTINGS_SUBDIR = ".loomai"
_SETTINGS_FILE = "settings.json"
_TOOLS_SUBDIR = "tools"
_DOCKER_AI_TOOLS_DIR = "/app/ai-tools"

# ---------------------------------------------------------------------------
# Module-level cache
# ---------------------------------------------------------------------------

_cached_settings: Optional[dict] = None

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge *overlay* into a copy of *base*.

    Keys present in *base* but missing from *overlay* are preserved.
    Keys in *overlay* override *base* at the leaf level.
    """
    merged = copy.deepcopy(base)
    for key, value in overlay.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _atomic_write_json(path: str, data: dict) -> None:
    """Write *data* as JSON to *path* atomically (tmp + os.replace)."""
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp_path, path)


def _atomic_write_text(path: str, text: str) -> None:
    """Write *text* to *path* atomically (tmp + os.replace)."""
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        f.write(text)
    os.replace(tmp_path, path)


# ---------------------------------------------------------------------------
# Core directory / path helpers
# ---------------------------------------------------------------------------


def get_storage_dir() -> str:
    """Return the effective storage directory.

    When a user registry exists and an active user is set, returns the
    per-user directory ``users/{uuid}/``. Otherwise returns the flat
    ``FABRIC_STORAGE_DIR`` root (legacy single-user mode).
    """
    from app.user_registry import get_user_storage_dir
    user_dir = get_user_storage_dir()
    if user_dir is not None:
        return user_dir
    return os.environ.get("FABRIC_STORAGE_DIR", "/home/fabric/work")


def get_root_storage_dir() -> str:
    """Return the raw FABRIC_STORAGE_DIR (never user-scoped)."""
    return os.environ.get("FABRIC_STORAGE_DIR", "/home/fabric/work")


def get_settings_dir() -> str:
    """Return the ``.loomai/`` directory, creating it if necessary."""
    d = os.path.join(get_storage_dir(), _SETTINGS_SUBDIR)
    os.makedirs(d, exist_ok=True)
    return d


def get_settings_path() -> str:
    """Return the full path to ``settings.json``."""
    return os.path.join(get_settings_dir(), _SETTINGS_FILE)


# ---------------------------------------------------------------------------
# Default settings schema
# ---------------------------------------------------------------------------


def get_default_settings() -> dict:
    """Return a fresh copy of the full default settings dict."""
    storage_dir = get_storage_dir()
    config_dir = os.path.join(storage_dir, "fabric_config")
    return {
        "schema_version": 1,
        "paths": {
            "storage_dir": storage_dir,
            "config_dir": config_dir,
            "artifacts_dir": os.path.join(storage_dir, "my_artifacts"),
            "slices_dir": os.path.join(storage_dir, "my_slices"),
            "notebooks_dir": os.path.join(storage_dir, "notebooks"),
            "ai_tools_dir": os.path.join(storage_dir, ".ai-tools"),
            "token_file": os.path.join(config_dir, "id_token.json"),
            "bastion_key_file": os.path.join(config_dir, "fabric_bastion_key"),
            "slice_keys_dir": os.path.join(config_dir, "slice_keys"),
            "ssh_config_file": os.path.join(config_dir, "ssh_config"),
            "log_file": "/tmp/fablib/fablib.log",
        },
        "fabric": {
            "project_id": "",
            "bastion_username": "",
            "hosts": {
                "credmgr": "cm.fabric-testbed.net",
                "orchestrator": "orchestrator.fabric-testbed.net",
                "core_api": "uis.fabric-testbed.net",
                "bastion": "bastion.fabric-testbed.net",
                "artifact_manager": "artifacts.fabric-testbed.net",
            },
            "logging": {"level": "INFO"},
            "avoid_sites": [],
            "ssh_command_line": (
                "ssh -i {{ _self_.private_ssh_key_file }} "
                "-F {config_dir}/ssh_config "
                "{{ _self_.username }}@{{ _self_.management_ip }}"
            ),
        },
        "ai": {
            "fabric_api_key": "",
            "nrp_api_key": "",
            "ai_server_url": "https://ai.fabric-testbed.net",
            "nrp_server_url": "https://ellm.nrp-nautilus.io",
            "tools": {
                "aider": True,
                "opencode": True,
                "crush": True,
                "claude": True,
                "deepagents": True,
            },
        },
        "services": {
            "jupyter_port": 8889,
            "model_proxy_port": 9199,
        },
        "tool_configs": {},
    }


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------


def load_settings() -> dict:
    """Load settings from disk, deep-merging with defaults for any missing keys.

    The result is cached in ``_cached_settings`` for subsequent accessor calls.
    """
    global _cached_settings

    defaults = get_default_settings()
    path = get_settings_path()

    if os.path.isfile(path):
        try:
            with open(path) as f:
                on_disk = json.load(f)
            settings = _deep_merge(defaults, on_disk)
        except Exception:
            logger.warning("Failed to read %s — using defaults", path, exc_info=True)
            settings = defaults
    else:
        settings = defaults

    _cached_settings = settings
    return settings


def save_settings(settings: dict) -> None:
    """Persist *settings* to disk (atomic write), regenerate derived files, and invalidate cache."""
    global _cached_settings

    path = get_settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _atomic_write_json(path, settings)

    _cached_settings = settings

    # Regenerate derived config files
    try:
        generate_fabric_rc(settings)
    except Exception:
        logger.warning("Failed to regenerate fabric_rc", exc_info=True)
    try:
        generate_ssh_config(settings)
    except Exception:
        logger.warning("Failed to regenerate ssh_config", exc_info=True)


def _get_settings() -> dict:
    """Return cached settings, loading from disk if necessary."""
    global _cached_settings
    if _cached_settings is None:
        return load_settings()
    return _cached_settings


def invalidate_settings_cache() -> None:
    """Clear the cached settings so the next access reloads from disk."""
    global _cached_settings
    _cached_settings = None


# ---------------------------------------------------------------------------
# Path accessors
# ---------------------------------------------------------------------------


def get_config_dir() -> str:
    """Return ``paths.config_dir``, creating it if needed."""
    d: str = _get_settings()["paths"]["config_dir"]
    os.makedirs(d, exist_ok=True)
    return d


def get_artifacts_dir() -> str:
    """Return ``paths.artifacts_dir``, creating it if needed."""
    d: str = _get_settings()["paths"]["artifacts_dir"]
    os.makedirs(d, exist_ok=True)
    return d


def get_slices_dir() -> str:
    """Return ``paths.slices_dir``, creating it if needed."""
    d: str = _get_settings()["paths"]["slices_dir"]
    os.makedirs(d, exist_ok=True)
    return d


def get_notebooks_dir() -> str:
    """Return ``paths.notebooks_dir``, creating it if needed."""
    d: str = _get_settings()["paths"]["notebooks_dir"]
    os.makedirs(d, exist_ok=True)
    return d


def get_ai_tools_dir() -> str:
    """Return ``paths.ai_tools_dir``."""
    return _get_settings()["paths"]["ai_tools_dir"]


def get_token_path() -> str:
    """Return the path to the FABRIC id_token JSON file.

    Resolution order:
    1. ``FABRIC_TOKEN_FILE`` env var (explicit override)
    2. ``~/.tokens.json`` if it exists (JupyterHub convention)
    3. ``paths.token_file`` from settings (config_dir/id_token.json)
    """
    explicit = os.environ.get("FABRIC_TOKEN_FILE")
    if explicit:
        return explicit

    home_tokens = os.path.join(os.path.expanduser("~"), ".tokens.json")
    if os.path.isfile(home_tokens):
        return home_tokens

    return _get_settings()["paths"]["token_file"]


def get_bastion_key_path() -> str:
    """Return ``paths.bastion_key_file``."""
    return _get_settings()["paths"]["bastion_key_file"]


def get_slice_keys_dir() -> str:
    """Return ``paths.slice_keys_dir``."""
    return _get_settings()["paths"]["slice_keys_dir"]


def get_ssh_config_path() -> str:
    """Return ``paths.ssh_config_file``."""
    return _get_settings()["paths"]["ssh_config_file"]


def get_log_file() -> str:
    """Return ``paths.log_file``."""
    return _get_settings()["paths"]["log_file"]


# ---------------------------------------------------------------------------
# Setting accessors
# ---------------------------------------------------------------------------


def get_fabric_api_key() -> str:
    """Return ``ai.fabric_api_key``."""
    return _get_settings()["ai"]["fabric_api_key"]


def get_nrp_api_key() -> str:
    """Return ``ai.nrp_api_key``."""
    return _get_settings()["ai"]["nrp_api_key"]


def get_project_id() -> str:
    """Return ``fabric.project_id``."""
    return _get_settings()["fabric"]["project_id"]


def get_bastion_username() -> str:
    """Return ``fabric.bastion_username``."""
    return _get_settings()["fabric"]["bastion_username"]


def get_avoid_sites() -> List[str]:
    """Return ``fabric.avoid_sites`` (list of site name strings)."""
    return _get_settings()["fabric"]["avoid_sites"]


def get_host(name: str) -> str:
    """Return ``fabric.hosts.{name}``."""
    return _get_settings()["fabric"]["hosts"].get(name, "")


def get_log_level() -> str:
    """Return ``fabric.logging.level``."""
    return _get_settings()["fabric"]["logging"]["level"]


def get_ai_tools() -> Dict[str, bool]:
    """Return ``ai.tools`` (dict of tool name to enabled bool)."""
    return _get_settings()["ai"]["tools"]


def set_ai_tools(tools: dict) -> None:
    """Update ``ai.tools`` in settings and persist to disk."""
    settings = _get_settings()
    current_tools = settings["ai"]["tools"]
    for k in current_tools:
        if k in tools:
            current_tools[k] = bool(tools[k])
    save_settings(settings)


def get_ai_server_url() -> str:
    """Return ``ai.ai_server_url``."""
    return _get_settings()["ai"]["ai_server_url"]


def get_nrp_server_url() -> str:
    """Return ``ai.nrp_server_url``."""
    return _get_settings()["ai"]["nrp_server_url"]


def get_jupyter_port() -> int:
    """Return ``services.jupyter_port``."""
    return _get_settings()["services"]["jupyter_port"]


def get_model_proxy_port() -> int:
    """Return ``services.model_proxy_port``."""
    return _get_settings()["services"]["model_proxy_port"]


def get_ssh_command_line() -> str:
    """Return ``fabric.ssh_command_line``."""
    return _get_settings()["fabric"]["ssh_command_line"]


# ---------------------------------------------------------------------------
# Derived file generation
# ---------------------------------------------------------------------------


def generate_fabric_rc(settings: dict) -> None:
    """Write ``fabric_rc`` into the config directory from *settings*."""
    from app.fablib_manager import get_default_slice_key_path

    paths = settings["paths"]
    fabric = settings["fabric"]
    hosts = fabric["hosts"]
    ai = settings["ai"]
    config_dir = paths["config_dir"]

    # Resolve actual default slice key paths (handles key set default logic)
    try:
        priv_key_path, pub_key_path = get_default_slice_key_path(config_dir)
    except Exception:
        # Fallback to nominal paths if key resolution fails
        slice_keys_dir = paths["slice_keys_dir"]
        priv_key_path = os.path.join(slice_keys_dir, "default", "slice_key")
        pub_key_path = os.path.join(slice_keys_dir, "default", "slice_key.pub")

    avoid_str = ",".join(fabric.get("avoid_sites", []))

    # Resolve {config_dir} placeholder in ssh_command_line
    ssh_cmd = fabric.get("ssh_command_line", "").replace("{config_dir}", config_dir)

    lines = [
        f"export FABRIC_CREDMGR_HOST={hosts.get('credmgr', 'cm.fabric-testbed.net')}",
        f"export FABRIC_ORCHESTRATOR_HOST={hosts.get('orchestrator', 'orchestrator.fabric-testbed.net')}",
        f"export FABRIC_CORE_API_HOST={hosts.get('core_api', 'uis.fabric-testbed.net')}",
        f"export FABRIC_AM_HOST={hosts.get('artifact_manager', 'artifacts.fabric-testbed.net')}",
        f"export FABRIC_TOKEN_LOCATION={paths['token_file']}",
        f"export FABRIC_BASTION_HOST={hosts.get('bastion', 'bastion.fabric-testbed.net')}",
        f"export FABRIC_BASTION_USERNAME={fabric.get('bastion_username', '')}",
        f"export FABRIC_BASTION_KEY_LOCATION={paths['bastion_key_file']}",
        f"export FABRIC_BASTION_SSH_CONFIG_FILE={paths['ssh_config_file']}",
        f"export FABRIC_SLICE_PUBLIC_KEY_FILE={pub_key_path}",
        f"export FABRIC_SLICE_PRIVATE_KEY_FILE={priv_key_path}",
        f"export FABRIC_PROJECT_ID={fabric.get('project_id', '')}",
        f"export FABRIC_LOG_LEVEL={fabric.get('logging', {}).get('level', 'INFO')}",
        f"export FABRIC_LOG_FILE={paths.get('log_file', '/tmp/fablib/fablib.log')}",
        f"export FABRIC_AVOID={avoid_str}",
        f'export FABRIC_SSH_COMMAND_LINE="{ssh_cmd}"',
        f"export FABRIC_AI_API_KEY={ai.get('fabric_api_key', '')}",
        f"export NRP_API_KEY={ai.get('nrp_api_key', '')}",
    ]

    rc_content = "\n".join(lines) + "\n"
    rc_path = os.path.join(config_dir, "fabric_rc")
    os.makedirs(config_dir, exist_ok=True)
    _atomic_write_text(rc_path, rc_content)
    logger.debug("Wrote fabric_rc to %s", rc_path)


def generate_ssh_config(settings: dict) -> None:
    """Write ``ssh_config`` into the config directory from *settings*."""
    paths = settings["paths"]
    fabric = settings["fabric"]
    config_dir = paths["config_dir"]
    bastion_username = fabric.get("bastion_username", "")
    bastion_key_file = paths["bastion_key_file"]

    content = f"""\
UserKnownHostsFile /dev/null
StrictHostKeyChecking no
ServerAliveInterval 120

Host bastion.fabric-testbed.net
    User {bastion_username}
    ForwardAgent yes
    Hostname %h
    IdentityFile {bastion_key_file}
    IdentitiesOnly yes

Host * !bastion.fabric-testbed.net
    ProxyJump {bastion_username}@bastion.fabric-testbed.net:22
"""

    ssh_config_path = os.path.join(config_dir, "ssh_config")
    os.makedirs(config_dir, exist_ok=True)
    _atomic_write_text(ssh_config_path, content)
    logger.debug("Wrote ssh_config to %s", ssh_config_path)


def apply_env_vars(settings: dict) -> None:
    """Set ``os.environ`` entries from *settings* so FABlib and subprocesses inherit them."""
    paths = settings["paths"]
    fabric = settings["fabric"]
    ai = settings["ai"]

    env_map = {
        "FABRIC_STORAGE_DIR": paths.get("storage_dir", ""),
        "FABRIC_CONFIG_DIR": paths.get("config_dir", ""),
        "FABRIC_PROJECT_ID": fabric.get("project_id", ""),
        "FABRIC_BASTION_USERNAME": fabric.get("bastion_username", ""),
        "FABRIC_BASTION_HOST": fabric.get("hosts", {}).get("bastion", ""),
        "FABRIC_CREDMGR_HOST": fabric.get("hosts", {}).get("credmgr", ""),
        "FABRIC_ORCHESTRATOR_HOST": fabric.get("hosts", {}).get("orchestrator", ""),
        "FABRIC_CORE_API_HOST": fabric.get("hosts", {}).get("core_api", ""),
        "FABRIC_AM_HOST": fabric.get("hosts", {}).get("artifact_manager", ""),
        "FABRIC_TOKEN_LOCATION": paths.get("token_file", ""),
        "FABRIC_BASTION_KEY_LOCATION": paths.get("bastion_key_file", ""),
        "FABRIC_BASTION_SSH_CONFIG_FILE": paths.get("ssh_config_file", ""),
        "FABRIC_LOG_LEVEL": fabric.get("logging", {}).get("level", "INFO"),
        "FABRIC_LOG_FILE": paths.get("log_file", ""),
        "FABRIC_AVOID": ",".join(fabric.get("avoid_sites", [])),
        "FABRIC_AI_API_KEY": ai.get("fabric_api_key", ""),
        "NRP_API_KEY": ai.get("nrp_api_key", ""),
    }

    ssh_cmd = fabric.get("ssh_command_line", "")
    if ssh_cmd:
        config_dir = paths.get("config_dir", "")
        env_map["FABRIC_SSH_COMMAND_LINE"] = ssh_cmd.replace("{config_dir}", config_dir)

    for key, value in env_map.items():
        if value:
            os.environ[key] = str(value)


# ---------------------------------------------------------------------------
# Legacy migration
# ---------------------------------------------------------------------------


def migrate_from_legacy() -> dict:
    """Parse existing ``fabric_rc`` and ``.ai_tools.json`` into a new ``settings.json``.

    Returns the migrated settings dict (also saved to disk).
    """
    settings = get_default_settings()
    storage_dir = get_storage_dir()
    config_dir = os.path.join(storage_dir, "fabric_config")

    # --- Parse fabric_rc ---
    rc_path = os.path.join(config_dir, "fabric_rc")
    if os.path.isfile(rc_path):
        logger.info("Migrating settings from %s", rc_path)
        rc_vars: Dict[str, str] = {}
        with open(rc_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("export ") and "=" in line:
                    kv = line[len("export "):]
                    key, _, value = kv.partition("=")
                    rc_vars[key.strip()] = value.strip()

        # Map fabric_rc keys to settings paths
        _rc_host_map = {
            "FABRIC_CREDMGR_HOST": "credmgr",
            "FABRIC_ORCHESTRATOR_HOST": "orchestrator",
            "FABRIC_CORE_API_HOST": "core_api",
            "FABRIC_AM_HOST": "artifact_manager",
            "FABRIC_BASTION_HOST": "bastion",
        }
        for env_key, host_key in _rc_host_map.items():
            if env_key in rc_vars:
                settings["fabric"]["hosts"][host_key] = rc_vars[env_key]

        if "FABRIC_BASTION_USERNAME" in rc_vars:
            settings["fabric"]["bastion_username"] = rc_vars["FABRIC_BASTION_USERNAME"]

        if "FABRIC_PROJECT_ID" in rc_vars:
            settings["fabric"]["project_id"] = rc_vars["FABRIC_PROJECT_ID"]

        if "FABRIC_LOG_LEVEL" in rc_vars:
            settings["fabric"]["logging"]["level"] = rc_vars["FABRIC_LOG_LEVEL"]

        if "FABRIC_LOG_FILE" in rc_vars:
            settings["paths"]["log_file"] = rc_vars["FABRIC_LOG_FILE"]

        if "FABRIC_AVOID" in rc_vars:
            avoid_str = rc_vars["FABRIC_AVOID"]
            if avoid_str:
                settings["fabric"]["avoid_sites"] = [
                    s.strip() for s in avoid_str.split(",") if s.strip()
                ]
            else:
                settings["fabric"]["avoid_sites"] = []

        if "FABRIC_SSH_COMMAND_LINE" in rc_vars:
            ssh_val = rc_vars["FABRIC_SSH_COMMAND_LINE"]
            # Strip surrounding quotes if present
            if (ssh_val.startswith('"') and ssh_val.endswith('"')) or \
               (ssh_val.startswith("'") and ssh_val.endswith("'")):
                ssh_val = ssh_val[1:-1]
            settings["fabric"]["ssh_command_line"] = ssh_val

        if "FABRIC_AI_API_KEY" in rc_vars:
            settings["ai"]["fabric_api_key"] = rc_vars["FABRIC_AI_API_KEY"]

        if "NRP_API_KEY" in rc_vars:
            settings["ai"]["nrp_api_key"] = rc_vars["NRP_API_KEY"]

    # --- Parse .ai_tools.json ---
    ai_tools_path = os.path.join(storage_dir, ".ai_tools.json")
    if os.path.isfile(ai_tools_path):
        logger.info("Migrating AI tool toggles from %s", ai_tools_path)
        try:
            with open(ai_tools_path) as f:
                tools_data = json.load(f)
            if isinstance(tools_data, dict):
                default_tools = settings["ai"]["tools"]
                for k in default_tools:
                    if k in tools_data:
                        default_tools[k] = bool(tools_data[k])
        except Exception:
            logger.warning("Failed to parse %s", ai_tools_path, exc_info=True)

    # Write the migrated settings
    save_settings(settings)
    logger.info("Legacy migration complete — settings.json written to %s", get_settings_path())
    return settings


# ---------------------------------------------------------------------------
# Tool config management
# ---------------------------------------------------------------------------


def get_tool_config_dir(tool: str) -> str:
    """Return ``{settings_dir}/tools/{tool}/``, creating it if needed."""
    d = os.path.join(get_settings_dir(), _TOOLS_SUBDIR, tool)
    os.makedirs(d, exist_ok=True)
    return d


def seed_tool_configs() -> None:
    """Copy default tool configs from the Docker image to ``.loomai/tools/``.

    For each tool directory in ``_DOCKER_AI_TOOLS_DIR``, copies its contents
    to ``.loomai/tools/{tool}/`` only if that target directory does not
    already exist (preserves user customizations).
    """
    if not os.path.isdir(_DOCKER_AI_TOOLS_DIR):
        logger.debug("Docker AI tools dir %s not found — skipping seed", _DOCKER_AI_TOOLS_DIR)
        return

    for entry in os.listdir(_DOCKER_AI_TOOLS_DIR):
        src = os.path.join(_DOCKER_AI_TOOLS_DIR, entry)
        if not os.path.isdir(src):
            continue
        dst = os.path.join(get_settings_dir(), _TOOLS_SUBDIR, entry)
        if os.path.exists(dst):
            logger.debug("Tool config for %s already exists — skipping", entry)
            continue
        try:
            shutil.copytree(src, dst)
            logger.info("Seeded tool config for %s from %s", entry, src)
        except Exception:
            logger.warning("Failed to seed tool config for %s", entry, exc_info=True)


def reset_tool_config(tool: str) -> None:
    """Delete ``.loomai/tools/{tool}/`` and re-copy from the Docker image.

    Raises ``FileNotFoundError`` if the tool has no default config in the
    Docker image.
    """
    src = os.path.join(_DOCKER_AI_TOOLS_DIR, tool)
    if not os.path.isdir(src):
        raise FileNotFoundError(
            f"No default config for tool '{tool}' in {_DOCKER_AI_TOOLS_DIR}"
        )

    dst = os.path.join(get_settings_dir(), _TOOLS_SUBDIR, tool)
    if os.path.exists(dst):
        shutil.rmtree(dst)

    shutil.copytree(src, dst)
    logger.info("Reset tool config for %s from %s", tool, src)


def get_tool_config_status() -> List[Dict[str, Any]]:
    """Return a list of dicts describing each tool's config status.

    Each dict contains:
    - ``tool`` (str): tool name
    - ``has_config`` (bool): whether a config directory exists in ``.loomai/tools/``
    - ``files`` (list[str]): list of filenames in the config directory
    """
    tools_dir = os.path.join(get_settings_dir(), _TOOLS_SUBDIR)
    result: List[Dict[str, Any]] = []

    # Collect tool names from both Docker defaults and user configs
    tool_names: set[str] = set()
    if os.path.isdir(_DOCKER_AI_TOOLS_DIR):
        for entry in os.listdir(_DOCKER_AI_TOOLS_DIR):
            if os.path.isdir(os.path.join(_DOCKER_AI_TOOLS_DIR, entry)):
                tool_names.add(entry)
    if os.path.isdir(tools_dir):
        for entry in os.listdir(tools_dir):
            if os.path.isdir(os.path.join(tools_dir, entry)):
                tool_names.add(entry)

    for name in sorted(tool_names):
        tool_dir = os.path.join(tools_dir, name)
        has_config = os.path.isdir(tool_dir)
        files: List[str] = []
        if has_config:
            try:
                files = sorted(os.listdir(tool_dir))
            except OSError:
                pass
        result.append({
            "tool": name,
            "has_config": has_config,
            "files": files,
        })

    return result
