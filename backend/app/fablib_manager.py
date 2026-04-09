"""Singleton FABlib manager for the backend."""
from __future__ import annotations

import json
import os
import shutil
import threading
from typing import Optional, Tuple
from fabrictestbed_extensions.fablib.fablib import FablibManager

_lock = threading.Lock()
_fablib: Optional[FablibManager] = None

def _default_config_dir() -> str:
    from app.settings_manager import get_config_dir
    return get_config_dir()

# Keep a string constant for backward compat with imports
DEFAULT_CONFIG_DIR = "/home/fabric/work/fabric_config"


def _load_fabric_rc(path: str) -> None:
    """Parse a fabric_rc file and load its exports into os.environ."""
    if not os.path.isfile(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("export ") and "=" in line:
                kv = line[len("export "):]
                key, _, value = kv.partition("=")
                os.environ[key.strip()] = value.strip()


def _keys_json_path(config_dir: str) -> str:
    return os.path.join(config_dir, "slice_keys", "keys.json")


def _load_keys_json(config_dir: str) -> dict:
    """Load the slice keys registry, returning {"default": "default", "keys": ["default"]}."""
    path = _keys_json_path(config_dir)
    if os.path.isfile(path):
        with open(path) as f:
            return json.load(f)
    return {"default": "default", "keys": ["default"]}


def _save_keys_json(config_dir: str, data: dict) -> None:
    keys_dir = os.path.join(config_dir, "slice_keys")
    os.makedirs(keys_dir, exist_ok=True)
    with open(_keys_json_path(config_dir), "w") as f:
        json.dump(data, f, indent=2)


def _migrate_legacy_keys(config_dir: str) -> None:
    """On first access, move flat slice_key/slice_key.pub into slice_keys/default/."""
    keys_dir = os.path.join(config_dir, "slice_keys")
    default_dir = os.path.join(keys_dir, "default")
    keys_json = _keys_json_path(config_dir)

    # Already migrated
    if os.path.isfile(keys_json):
        return

    old_priv = os.path.join(config_dir, "slice_key")
    old_pub = os.path.join(config_dir, "slice_key.pub")

    if os.path.isfile(old_priv) or os.path.isfile(old_pub):
        os.makedirs(default_dir, exist_ok=True)
        if os.path.isfile(old_priv):
            shutil.copy2(old_priv, os.path.join(default_dir, "slice_key"))
        if os.path.isfile(old_pub):
            shutil.copy2(old_pub, os.path.join(default_dir, "slice_key.pub"))
        _save_keys_json(config_dir, {"default": "default", "keys": ["default"]})


def get_default_slice_key_path(config_dir: str) -> Tuple[str, str]:
    """Return (private_key_path, public_key_path) for the default key set.

    Validates that the default key directory actually exists.  If it doesn't,
    falls back to the first key set that does exist and updates keys.json.
    """
    _migrate_legacy_keys(config_dir)
    data = _load_keys_json(config_dir)
    default_name = data.get("default", "default")

    # Check if the default key set directory exists
    default_dir = os.path.join(config_dir, "slice_keys", default_name)
    if os.path.isdir(default_dir):
        return (
            os.path.join(default_dir, "slice_key"),
            os.path.join(default_dir, "slice_key.pub"),
        )

    # Default key set missing — find the first key set that actually exists
    for key_name in data.get("keys", []):
        candidate = os.path.join(config_dir, "slice_keys", key_name)
        if os.path.isdir(candidate) and os.path.isfile(os.path.join(candidate, "slice_key")):
            # Update keys.json to point to this working key set
            data["default"] = key_name
            _save_keys_json(config_dir, data)
            return (
                os.path.join(candidate, "slice_key"),
                os.path.join(candidate, "slice_key.pub"),
            )

    # Scan the slice_keys directory for any key set not listed in keys.json
    keys_dir = os.path.join(config_dir, "slice_keys")
    if os.path.isdir(keys_dir):
        for entry in sorted(os.listdir(keys_dir)):
            candidate = os.path.join(keys_dir, entry)
            if os.path.isdir(candidate) and os.path.isfile(os.path.join(candidate, "slice_key")):
                data["default"] = entry
                if entry not in data.get("keys", []):
                    data.setdefault("keys", []).append(entry)
                _save_keys_json(config_dir, data)
                return (
                    os.path.join(candidate, "slice_key"),
                    os.path.join(candidate, "slice_key.pub"),
                )

    # Last resort: return the nominal path (will fail at SSH time with a clear error)
    return (
        os.path.join(default_dir, "slice_key"),
        os.path.join(default_dir, "slice_key.pub"),
    )


def get_slice_key_path(config_dir: str, key_name: str) -> Tuple[str, str]:
    """Return (private_key_path, public_key_path) for a named key set."""
    base = os.path.join(config_dir, "slice_keys", key_name)
    return (
        os.path.join(base, "slice_key"),
        os.path.join(base, "slice_key.pub"),
    )


def is_configured() -> bool:
    """Check whether minimum FABRIC config files exist."""
    from app.settings_manager import get_token_path, get_config_dir
    config_dir = get_config_dir()
    rc_path = os.path.join(config_dir, "fabric_rc")
    return os.path.isfile(rc_path) and os.path.isfile(get_token_path())


def reset_fablib() -> None:
    """Reset the FABlib singleton so it will be re-created on next access."""
    global _fablib
    with _lock:
        _fablib = None
    # Re-load fabric_rc env vars so FABlib picks up new settings
    from app.settings_manager import get_config_dir
    config_dir = get_config_dir()
    rc_path = os.path.join(config_dir, "fabric_rc")
    _load_fabric_rc(rc_path)
    # Also force-correct the slice key paths in case fabric_rc has stale ones
    _migrate_legacy_keys(config_dir)
    priv_path, pub_path = get_default_slice_key_path(config_dir)
    os.environ["FABRIC_SLICE_PRIVATE_KEY_FILE"] = priv_path
    os.environ["FABRIC_SLICE_PUBLIC_KEY_FILE"] = pub_path
    # Invalidate all cached API call results — the token/project may have
    # changed, so stale data (e.g. empty slice list) must not be served.
    try:
        from app.fabric_call_manager import get_call_manager
        mgr = get_call_manager()
        for key in list(mgr._cache.keys()):
            mgr.invalidate(key)
    except Exception:
        pass


def get_fablib() -> FablibManager:
    """Get or create the FABlib manager singleton.

    Raises RuntimeError if FABRIC is not yet configured.
    """
    global _fablib
    if _fablib is None:
        with _lock:
            if _fablib is None:
                from app.settings_manager import get_config_dir as _get_config
                config_dir = _get_config()
                rc_path = os.path.join(config_dir, "fabric_rc")
                if not os.path.isfile(rc_path):
                    raise RuntimeError(
                        "FABRIC is not configured. Please complete setup in the Configure view."
                    )
                # Load fabric_rc into environment
                _load_fabric_rc(rc_path)
                # Override path-based env vars to use the container config dir.
                # fabric_rc may have hardcoded host paths that don't exist inside
                # the container, so we rewrite simple file vars (token, bastion
                # key, ssh_config) using basename lookup.  Slice key vars are
                # handled separately below because they live in a subdirectory
                # structure (slice_keys/{name}/slice_key).
                _SIMPLE_PATH_KEYS = [
                    "FABRIC_BASTION_KEY_LOCATION",
                    "FABRIC_BASTION_SSH_CONFIG_FILE",
                ]
                for key in _SIMPLE_PATH_KEYS:
                    val = os.environ.get(key, "")
                    if val:
                        basename = os.path.basename(val)
                        container_path = os.path.join(config_dir, basename)
                        if os.path.exists(container_path):
                            os.environ[key] = container_path
                # Token location: use get_token_path() which checks
                # ~/.tokens.json (JupyterHub) before falling back to
                # {config_dir}/id_token.json.
                from app.user_context import get_token_path
                os.environ["FABRIC_TOKEN_LOCATION"] = get_token_path()
                # Also fix SSH command line if it references a config path
                ssh_cmd = os.environ.get("FABRIC_SSH_COMMAND_LINE", "")
                if ssh_cmd:
                    import re
                    os.environ["FABRIC_SSH_COMMAND_LINE"] = re.sub(
                        r'/[^\s}]+/\.?fabric_config/',
                        config_dir.rstrip('/') + '/',
                        ssh_cmd,
                    )
                # Set defaults FABlib expects
                os.environ["FABRIC_RC"] = rc_path
                os.environ.setdefault(
                    "FABRIC_BASTION_KEY_LOCATION",
                    os.path.join(config_dir, "fabric_bastion_key"),
                )
                # Resolve the actual default slice key set — this validates that
                # the directory exists and auto-corrects keys.json if needed.
                _migrate_legacy_keys(config_dir)
                priv_path, pub_path = get_default_slice_key_path(config_dir)
                # Force-set (not setdefault) to override stale paths in fabric_rc
                # that may point to a deleted key set directory.
                os.environ["FABRIC_SLICE_PRIVATE_KEY_FILE"] = priv_path
                os.environ["FABRIC_SLICE_PUBLIC_KEY_FILE"] = pub_path
                _fablib = FablibManager()
                # Ensure the token is scoped to the configured project.
                # The token on disk may be stale (from a previous session or
                # different project).  If the configured FABRIC_PROJECT_ID
                # differs from what the token contains, refresh the token
                # and recreate the singleton so it uses the new token.
                if _sync_token_project(_fablib):
                    _fablib = FablibManager()
    return _fablib


def _sync_token_project(fablib: FablibManager) -> bool:
    """If the token's project doesn't match FABRIC_PROJECT_ID, refresh it.

    Returns True if the token was refreshed (caller should recreate the
    FablibManager so it picks up the new token).
    """
    import json
    import base64
    import logging
    log = logging.getLogger(__name__)
    configured_pid = os.environ.get("FABRIC_PROJECT_ID", "")
    if not configured_pid:
        return False
    try:
        # Read the actual project UUID from the JWT on disk
        token_path = os.environ.get("FABRIC_TOKEN_LOCATION", "")
        if not token_path or not os.path.isfile(token_path):
            return False
        with open(token_path) as f:
            token_data = json.load(f)
        id_token = token_data.get("id_token", "")
        if not id_token:
            return False
        # Decode JWT payload (no verification — we just need the claims)
        parts = id_token.split(".")
        if len(parts) < 2:
            return False
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=="))
        token_projects = payload.get("projects", [])
        token_pids = {p.get("uuid", "") for p in token_projects}

        if configured_pid in token_pids:
            return False  # Token already scoped to the right project

        log.info("Token scoped to project(s) %s, but configured project is %s — refreshing...",
                 token_pids, configured_pid)
        mgr = fablib.get_manager()
        mgr.project_id = configured_pid
        refresh_token = mgr.get_refresh_token()
        if refresh_token:
            mgr.refresh_tokens(refresh_token=refresh_token)
            log.info("Token refreshed for project %s", configured_pid)
            return True
        else:
            log.warning("No refresh token available — cannot auto-refresh for project %s",
                        configured_pid)
            return False
    except Exception as e:
        log.warning("Failed to sync token project: %s", e)
        return False
