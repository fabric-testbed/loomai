"""Multi-user registry management.

Manages ``user_registry.json`` at ``{FABRIC_STORAGE_DIR}/.loomai/``
to support multiple FABRIC user identities with isolated storage.

When no registry exists, the system operates in legacy single-user mode.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import shutil
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

_REGISTRY_FILE = "user_registry.json"
# Folder names under .loomai/users/ that are treated as a user (UUID-shaped).
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-?[0-9a-fA-F-]{4,}$")


def _registry_path() -> str:
    """Return the path to user_registry.json."""
    storage = os.environ.get("FABRIC_STORAGE_DIR", "/home/fabric/work")
    return os.path.join(storage, ".loomai", _REGISTRY_FILE)


def _atomic_write_json(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------

def load_registry() -> Optional[dict]:
    """Load the user registry from disk. Returns None if no registry exists."""
    path = _registry_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        logger.warning("Failed to read %s", path, exc_info=True)
        return None


def save_registry(registry: dict) -> None:
    """Write the registry to disk atomically."""
    _atomic_write_json(_registry_path(), registry)


def _new_registry() -> dict:
    """Create an empty registry structure."""
    return {
        "schema_version": 1,
        "active_user": None,
        "users": [],
    }


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def _decode_jwt_payload(token: str) -> dict:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


def _user_meta_path(uuid: str) -> str:
    return os.path.join(users_base_dir(), uuid, "user.json")


def _read_user_meta(uuid: str) -> dict:
    """Best-effort display metadata for a user folder: user.json → token → uuid."""
    path = _user_meta_path(uuid)
    if os.path.isfile(path):
        try:
            with open(path) as f:
                m = json.load(f)
            return {"uuid": uuid, "name": m.get("name", ""),
                    "email": m.get("email", ""), "added_at": m.get("added_at", "")}
        except Exception:
            pass
    tok = os.path.join(users_base_dir(), uuid, "fabric_config", "id_token.json")
    if os.path.isfile(tok):
        try:
            with open(tok) as f:
                data = json.load(f)
            p = _decode_jwt_payload(data.get("id_token", ""))
            return {"uuid": uuid, "name": p.get("name", ""), "email": p.get("email", ""), "added_at": ""}
        except Exception:
            pass
    return {"uuid": uuid, "name": "", "email": "", "added_at": ""}


def _write_user_meta(uuid: str, name: str, email: str) -> None:
    """Persist a user's display metadata into their folder (creating it)."""
    os.makedirs(os.path.join(users_base_dir(), uuid), exist_ok=True)
    existing = _read_user_meta(uuid)
    meta = {
        "uuid": uuid,
        "name": name or existing.get("name", ""),
        "email": email or existing.get("email", ""),
        "added_at": existing.get("added_at") or datetime.now(timezone.utc).isoformat(),
    }
    _atomic_write_json(_user_meta_path(uuid), meta)


def get_active_user_uuid() -> Optional[str]:
    """Active user UUID. Folders are ground truth: if the stored active user's
    folder is gone, fall back to the first existing user (and persist)."""
    existing = [u["uuid"] for u in list_users()]
    reg = load_registry()
    active = reg.get("active_user") if reg else None
    if active in existing:
        return active
    new_active = existing[0] if existing else None
    # Only PERSIST a reassignment to a real user. Never auto-null a configured
    # active user just because the scan came back empty (e.g. a transient/path
    # glitch) — that would silently wipe the registry's active pointer.
    if new_active and new_active != active:
        reg = reg or _new_registry()
        reg["active_user"] = new_active
        save_registry(reg)
    return new_active


def list_users() -> list[dict]:
    """Ground truth: every UUID-named folder under ``.loomai/users/`` is a user.
    Manually creating/deleting a folder adds/removes a user."""
    base = users_base_dir()
    if not os.path.isdir(base):
        return []
    out = []
    for name in sorted(os.listdir(base)):
        if os.path.isdir(os.path.join(base, name)) and _UUID_RE.match(name):
            out.append(_read_user_meta(name))
    return out


def _find_user(registry: dict, uuid: str) -> Optional[dict]:
    """Find a user entry by UUID in the registry."""
    for u in registry.get("users", []):
        if u["uuid"] == uuid:
            return u
    return None


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------

def add_user(uuid: str, name: str, email: str) -> dict:
    """Register a user: create their folder + user.json (ground truth) and
    update the registry (active pointer + metadata cache)."""
    _write_user_meta(uuid, name, email)            # folder + user.json

    reg = load_registry()
    if reg is None:
        reg = _new_registry()
    existing = _find_user(reg, uuid)
    if existing:
        existing["name"] = name
        existing["email"] = email
    else:
        reg["users"].append({
            "uuid": uuid,
            "name": name,
            "email": email,
            "added_at": datetime.now(timezone.utc).isoformat(),
        })
    if not reg.get("active_user"):
        reg["active_user"] = uuid
    save_registry(reg)
    return reg


def remove_user(uuid: str) -> dict:
    """Delete a user: removes their folder (ground truth) and registry entry.
    If they were the active user, reassigns to a remaining user (or None)."""
    user_dir = os.path.join(users_base_dir(), uuid)
    if os.path.isdir(user_dir):
        shutil.rmtree(user_dir, ignore_errors=True)

    reg = load_registry() or _new_registry()
    reg["users"] = [u for u in reg.get("users", []) if u["uuid"] != uuid]
    if reg.get("active_user") == uuid:
        remaining = [u["uuid"] for u in list_users()]
        reg["active_user"] = remaining[0] if remaining else None
    save_registry(reg)
    return reg


def set_active_user(uuid: str) -> dict:
    """Switch the active user. Raises KeyError if the user's folder doesn't exist."""
    if uuid not in [u["uuid"] for u in list_users()]:
        raise KeyError(f"User {uuid} not found")

    reg = load_registry() or _new_registry()
    reg["active_user"] = uuid
    save_registry(reg)
    return reg


# ---------------------------------------------------------------------------
# Storage directory
# ---------------------------------------------------------------------------

def users_base_dir() -> str:
    """Return the base dir holding all per-user storage: ``{storage}/.loomai/users``."""
    storage = os.environ.get("FABRIC_STORAGE_DIR", "/home/fabric/work")
    return os.path.join(storage, ".loomai", "users")


def get_user_storage_dir(uuid: Optional[str] = None) -> Optional[str]:
    """Return the storage directory for a user, or None if legacy mode.

    If *uuid* is None, uses the active user from the registry.
    Returns None if no registry exists (legacy single-user mode).
    """
    if uuid is None:
        uuid = get_active_user_uuid()
    if uuid is None:
        return None

    return os.path.join(users_base_dir(), uuid)


def ensure_user_dir(uuid: str) -> str:
    """Create and return the storage directory for a user."""
    d = get_user_storage_dir(uuid)
    if d is None:
        raise ValueError("Cannot create user dir without a UUID")
    os.makedirs(d, exist_ok=True)
    # Create standard subdirs
    for sub in ["fabric_config", "my_artifacts", "my_slices"]:
        os.makedirs(os.path.join(d, sub), exist_ok=True)
    return d
