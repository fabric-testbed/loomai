"""Persistent slice registry — maps slice names to UUIDs, tracks state, supports archiving.

Registry file: ``FABRIC_STORAGE_DIR/my_slices/registry.json``
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any

from app.user_context import get_user_storage, get_slices_dir

logger = logging.getLogger(__name__)

TERMINAL_STATES = {"Dead", "Closing", "StableError"}

_lock = threading.Lock()


def _archive_slice_workdir(name: str, uuid: str) -> None:
    """Rename <name> to <name>-<uuid> on terminal state."""
    if not uuid:
        return
    storage = get_user_storage()
    src = os.path.join(storage, name)
    dst = os.path.join(storage, f"{name}-{uuid}")
    if os.path.isdir(src) and not os.path.exists(dst):
        try:
            os.rename(src, dst)
            logger.info("Archived slice workdir %s -> %s", src, dst)
        except Exception:
            logger.warning("Could not archive slice workdir %s", src, exc_info=True)


def _registry_path() -> str:
    d = get_slices_dir()
    return os.path.join(d, "registry.json")


def _load() -> dict[str, Any]:
    path = _registry_path()
    if not os.path.isfile(path):
        return {"slices": {}}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        logger.warning("Could not read slice registry; starting fresh")
        return {"slices": {}}


def _save(data: dict[str, Any]) -> None:
    path = _registry_path()
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- Public API ---

def _current_project_id() -> str:
    """Return the current FABRIC_PROJECT_ID from environment."""
    return os.environ.get("FABRIC_PROJECT_ID", "")


def register_slice(name: str, uuid: str = "", state: str = "Draft", has_errors: bool | None = None, project_id: str = "") -> None:
    """Add or update a slice entry in the registry."""
    with _lock:
        reg = _load()
        now = _now()
        existing = reg["slices"].get(name)
        pid = project_id or (existing.get("project_id", "") if existing else "") or _current_project_id()
        entry = {
            "uuid": uuid or (existing["uuid"] if existing else ""),
            "name": name,
            "state": state,
            "archived": False,
            "has_errors": has_errors if has_errors is not None else (existing.get("has_errors", False) if existing else False),
            "project_id": pid,
            "created_at": existing["created_at"] if existing else now,
            "updated_at": now,
        }
        reg["slices"][name] = entry
        _save(reg)


def update_slice_state(name: str, state: str, uuid: str = "", has_errors: bool | None = None, project_id: str = "") -> None:
    """Update state (and optionally UUID / has_errors) for a registered slice."""
    with _lock:
        reg = _load()
        entry = reg["slices"].get(name)
        if entry is None:
            entry = {
                "uuid": uuid,
                "name": name,
                "state": state,
                "archived": False,
                "has_errors": has_errors or False,
                "project_id": project_id or _current_project_id(),
                "created_at": _now(),
                "updated_at": _now(),
            }
        else:
            old_state = entry.get("state", "")
            entry["state"] = state
            entry["updated_at"] = _now()
            if uuid:
                # New UUID means a fresh submission — unarchive so it
                # appears in the list again even if an older slice with
                # the same name was previously archived.
                if uuid != entry.get("uuid"):
                    entry["archived"] = False
                entry["uuid"] = uuid
            if has_errors is not None:
                entry["has_errors"] = has_errors
            # Backfill project_id for entries created before this field existed
            if project_id:
                entry["project_id"] = project_id
            elif not entry.get("project_id"):
                entry["project_id"] = _current_project_id()
            # Rename workdir when slice reaches a terminal state
            if state in TERMINAL_STATES and old_state not in TERMINAL_STATES:
                _archive_slice_workdir(name, entry.get("uuid", ""))
        reg["slices"][name] = entry
        _save(reg)


def get_slice_uuid(name: str) -> str:
    """Return the UUID for a slice name, or empty string."""
    with _lock:
        reg = _load()
        entry = reg["slices"].get(name)
        return entry["uuid"] if entry else ""


def resolve_slice_id(slice_id: str) -> str | None:
    """Resolve a slice ID (UUID or draft ID) to its registry name.

    Returns the slice name if found, or None.
    """
    if not slice_id:
        return None
    with _lock:
        reg = _load()
        for name, entry in reg["slices"].items():
            if entry.get("uuid") == slice_id:
                return name
        return None


def resolve_slice_name(slice_id: str) -> str:
    """Resolve a slice ID to its name, falling back to the input string.

    Use this at the top of route handlers to accept both UUIDs and names.
    """
    if not slice_id:
        return slice_id
    name = resolve_slice_id(slice_id)
    return name if name else slice_id


def archive_slice(name: str) -> None:
    """Mark a slice as archived."""
    with _lock:
        reg = _load()
        entry = reg["slices"].get(name)
        if entry:
            entry["archived"] = True
            entry["updated_at"] = _now()
            _save(reg)


def archive_all_terminal() -> list[str]:
    """Archive all slices in terminal states. Returns list of archived names."""
    with _lock:
        reg = _load()
        archived = []
        for name, entry in reg["slices"].items():
            if not entry.get("archived") and entry.get("state") in TERMINAL_STATES:
                entry["archived"] = True
                entry["updated_at"] = _now()
                archived.append(name)
        if archived:
            _save(reg)
        return archived


def unregister_slice(name: str) -> None:
    """Remove a slice entry entirely (for draft deletion)."""
    with _lock:
        reg = _load()
        if name in reg["slices"]:
            del reg["slices"][name]
            _save(reg)


def get_all_entries(include_archived: bool = False, project_id: str = "") -> dict[str, dict[str, Any]]:
    """Return all registry entries, optionally including archived ones.

    If *project_id* is given, only entries whose project_id matches are
    returned.  Entries with no project_id are excluded when filtering (they
    belong to an unknown project and should be reconciled first).
    """
    with _lock:
        reg = _load()
        result = {}
        for k, v in reg["slices"].items():
            if not include_archived and v.get("archived"):
                continue
            if project_id:
                entry_pid = v.get("project_id", "")
                if entry_pid != project_id:
                    continue
            result[k] = v
        return result


def bulk_tag_project(uuid_to_project: dict[str, str]) -> int:
    """Tag registry entries with their project_id based on UUID matching.

    *uuid_to_project* maps slice UUID → project_id.
    Returns the number of entries updated.
    """
    with _lock:
        reg = _load()
        updated = 0
        for name, entry in reg["slices"].items():
            uuid = entry.get("uuid", "")
            if uuid and uuid in uuid_to_project:
                pid = uuid_to_project[uuid]
                if entry.get("project_id") != pid:
                    entry["project_id"] = pid
                    entry["updated_at"] = _now()
                    updated += 1
        if updated:
            _save(reg)
        return updated


def bulk_register(entries: list[dict[str, Any]], project_id: str = "") -> None:
    """Register many slices at once (single read/write cycle).

    Each entry dict should have: name, uuid, state, and optionally has_errors.
    """
    pid = project_id or _current_project_id()
    with _lock:
        reg = _load()
        now = _now()
        for e in entries:
            name = e["name"]
            existing = reg["slices"].get(name)
            reg["slices"][name] = {
                "uuid": e.get("uuid", "") or (existing["uuid"] if existing else ""),
                "name": name,
                "state": e.get("state", ""),
                "archived": existing.get("archived", False) if existing else False,
                "has_errors": e.get("has_errors", existing.get("has_errors", False) if existing else False),
                "project_id": e.get("project_id", "") or (existing.get("project_id", "") if existing else "") or pid,
                "created_at": existing["created_at"] if existing else now,
                "updated_at": now,
            }
        _save(reg)
