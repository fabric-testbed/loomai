"""Multi-user registry management.

Manages ``user_registry.json`` at ``{FABRIC_STORAGE_DIR}/.loomai/``
to support multiple FABRIC user identities with isolated storage.

When no registry exists, the system operates in legacy single-user mode.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

_REGISTRY_FILE = "user_registry.json"


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

def get_active_user_uuid() -> Optional[str]:
    """Return the active user UUID, or None if no registry (legacy mode)."""
    reg = load_registry()
    if reg is None:
        return None
    return reg.get("active_user")


def list_users() -> list[dict]:
    """Return the list of registered users."""
    reg = load_registry()
    if reg is None:
        return []
    return reg.get("users", [])


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
    """Add or update a user in the registry. Returns the updated registry."""
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

    # If no active user, set this one
    if not reg.get("active_user"):
        reg["active_user"] = uuid

    save_registry(reg)
    return reg


def remove_user(uuid: str) -> dict:
    """Remove a user from the registry. Cannot remove the active user.

    Returns the updated registry.
    Raises ValueError if trying to remove the active user.
    Raises KeyError if the user is not found.
    """
    reg = load_registry()
    if reg is None:
        raise KeyError(f"No registry exists")

    if reg.get("active_user") == uuid:
        raise ValueError("Cannot remove the active user. Switch to another user first.")

    if not _find_user(reg, uuid):
        raise KeyError(f"User {uuid} not found in registry")

    reg["users"] = [u for u in reg["users"] if u["uuid"] != uuid]
    save_registry(reg)
    return reg


def set_active_user(uuid: str) -> dict:
    """Switch the active user. Returns the updated registry.

    Raises KeyError if the user is not found.
    """
    reg = load_registry()
    if reg is None:
        raise KeyError("No registry exists")

    if not _find_user(reg, uuid):
        raise KeyError(f"User {uuid} not found in registry")

    reg["active_user"] = uuid
    save_registry(reg)
    return reg


# ---------------------------------------------------------------------------
# Storage directory
# ---------------------------------------------------------------------------

def get_user_storage_dir(uuid: Optional[str] = None) -> Optional[str]:
    """Return the storage directory for a user, or None if legacy mode.

    If *uuid* is None, uses the active user from the registry.
    Returns None if no registry exists (legacy single-user mode).
    """
    if uuid is None:
        uuid = get_active_user_uuid()
    if uuid is None:
        return None

    storage = os.environ.get("FABRIC_STORAGE_DIR", "/home/fabric/work")
    return os.path.join(storage, "users", uuid)


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
