"""Slice management API routes."""

from __future__ import annotations
import asyncio
import json
import logging
import os
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.fablib_manager import get_fablib
from app.fablib_executor import run_in_fablib_pool
from app.user_context import get_user_storage
from app.slice_serializer import slice_to_dict, slice_summary, check_has_errors
from app.graph_builder import build_graph
from app.site_resolver import resolve_sites
from app.routes.resources import get_cached_sites, get_fresh_sites
from app.slice_registry import (
    register_slice, update_slice_state, get_slice_uuid,
    resolve_slice_id,
    archive_slice as registry_archive_slice,
    archive_all_terminal as registry_archive_all_terminal,
    unregister_slice, get_all_entries, bulk_register, bulk_tag_project,
    TERMINAL_STATES,
)

router = APIRouter(tags=["slices"])


def _resolve_slice_name(slice_id: str) -> str:
    """Resolve a slice_id (FABRIC UUID or draft-UUID) to a slice name.

    The frontend always passes a slice ID. This maps it back to the name
    used internally. Falls back to treating the value as a name for
    backward compatibility.
    """
    # Try registry UUID lookup first
    name = resolve_slice_id(slice_id)
    if name:
        return name
    # Check if it matches a draft in memory (drafts also use UUIDs)
    with _draft_lock:
        for draft_name, _obj in _draft_slices.items():
            draft_uuid = get_slice_uuid(draft_name)
            if draft_uuid == slice_id:
                return draft_name
    # Backward compat: treat as literal name
    return slice_id


def _resolve_vm_template(name: str) -> dict | None:
    """Look up a VM template by name and return its data dict (or None).

    Ensures the storage dir exists, then reads the template JSON from
    disk.  If the template has a ``tools/`` directory, an extra
    ``_tools_source`` key is added with its path.
    """
    from app.routes.vm_templates import _ensure_dir, _sanitize_name, _vm_templates_dir
    import json as _json

    _ensure_dir()
    try:
        safe = _sanitize_name(name)
    except Exception:
        return None
    tdir = _vm_templates_dir()
    tmpl_dir = os.path.join(tdir, safe)
    tmpl_path = os.path.join(tmpl_dir, "vm-template.json")
    if not os.path.isfile(tmpl_path):
        return None
    try:
        with open(tmpl_path) as f:
            data = _json.load(f)
    except Exception:
        return None
    # Check for tools directory
    tools_dir = os.path.join(tmpl_dir, "tools")
    if os.path.isdir(tools_dir) and os.listdir(tools_dir):
        data["_tools_source"] = tools_dir
    return data

# ---------------------------------------------------------------------------
# Draft slice store — holds slices that are being edited locally.
# For new slices: created with new_slice() but not yet submitted.
# For existing slices: loaded from FABRIC and being modified locally.
# Keyed by slice name.
#
# New drafts are also persisted to disk so they survive container restarts.
# Disk path: FABRIC_STORAGE_DIR/my_slices/<safe_name>/topology.graphml
# ---------------------------------------------------------------------------
_draft_lock = threading.Lock()
_draft_slices: dict[str, Any] = {}
# Track which drafts are "new" (never submitted) vs "loaded" (existing slice)
_draft_is_new: dict[str, bool] = {}
# Track site group membership: slice_name -> {node_name: "@group"}
_draft_site_groups: dict[str, dict[str, str]] = {}
# Track IP hints for L3 networks: slice_name -> {net_name -> {iface_name -> hint}}
_draft_ip_hints: dict[str, dict[str, dict[str, dict]]] = {}
# Track L3 config for FABNet networks: slice_name -> {net_name -> config_dict}
_draft_l3_config: dict[str, dict[str, dict]] = {}
# Track which project a draft belongs to
_draft_project_id: dict[str, str] = {}


def _drafts_dir() -> str:
    from app.user_context import get_slices_dir
    return get_slices_dir()


def _safe_dir_name(name: str) -> str:
    """Convert a slice name to a safe directory name."""
    import re
    return re.sub(r'[^\w\-. ]', '_', name).strip()


def _persist_draft(name: str, slice_obj: Any) -> None:
    """Save a new draft to disk so it survives restarts."""
    try:
        safe = _safe_dir_name(name)
        d = os.path.join(_drafts_dir(), safe)
        os.makedirs(d, exist_ok=True)
        # Save topology
        topo_path = os.path.join(d, "topology.graphml")
        slice_obj.save(topo_path)
        # Save metadata (original name, site groups, project)
        meta = {"name": name}
        groups = _draft_site_groups.get(name, {})
        if groups:
            meta["site_groups"] = groups
        ip_hints = _draft_ip_hints.get(name, {})
        if ip_hints:
            meta["ip_hints"] = ip_hints
        l3_config = _draft_l3_config.get(name, {})
        if l3_config:
            meta["l3_config"] = l3_config
        pid = _draft_project_id.get(name, os.environ.get("FABRIC_PROJECT_ID", ""))
        if pid:
            meta["project_id"] = pid
        meta_path = os.path.join(d, "meta.json")
        with open(meta_path, "w") as f:
            json.dump(meta, f)
        logger.debug("Persisted draft '%s' to disk", name)
    except Exception:
        logger.warning("Could not persist draft '%s' to disk", name, exc_info=True)


def _delete_persistent_draft(name: str) -> None:
    """Remove a draft's persistent files from disk."""
    try:
        import shutil
        safe = _safe_dir_name(name)
        d = os.path.join(_drafts_dir(), safe)
        if os.path.isdir(d):
            shutil.rmtree(d)
            logger.debug("Deleted persistent draft '%s'", name)
    except Exception:
        logger.warning("Could not delete persistent draft '%s'", name, exc_info=True)


def _load_persistent_drafts() -> None:
    """Scan drafts dir and load any new drafts not yet in memory."""
    try:
        fablib = get_fablib()
    except Exception:
        logger.warning("Cannot load persistent drafts: fablib not available yet")
        return
    drafts_root = _drafts_dir()
    if not os.path.isdir(drafts_root):
        return
    for entry in os.listdir(drafts_root):
        d = os.path.join(drafts_root, entry)
        if not os.path.isdir(d):
            continue
        topo_path = os.path.join(d, "topology.graphml")
        meta_path = os.path.join(d, "meta.json")
        if not os.path.isfile(topo_path):
            continue
        # Read metadata
        name = entry  # fallback to dir name
        groups: dict[str, str] = {}
        ip_hints: dict[str, dict[str, dict]] = {}
        l3_config: dict[str, dict] = {}
        draft_pid = ""
        if os.path.isfile(meta_path):
            try:
                with open(meta_path) as f:
                    meta = json.load(f)
                name = meta.get("name", entry)
                groups = meta.get("site_groups", {})
                ip_hints = meta.get("ip_hints", {})
                l3_config = meta.get("l3_config", {})
                draft_pid = meta.get("project_id", "")
            except Exception:
                pass
        # Skip if already in memory
        if name in _draft_slices:
            continue
        # Skip if registry has a non-draft UUID — this draft was submitted
        existing_uuid = get_slice_uuid(name)
        if existing_uuid and not existing_uuid.startswith("draft-"):
            logger.info("Skipping persistent draft '%s' — already submitted (uuid=%s), cleaning up", name, existing_uuid)
            _delete_persistent_draft(name)
            continue
        try:
            import uuid as _uuid_mod
            slice_obj = fablib.new_slice(name=name)
            slice_obj.load(topo_path)
            _draft_slices[name] = slice_obj
            _draft_is_new[name] = True
            if groups:
                _draft_site_groups[name] = groups
            if ip_hints:
                _draft_ip_hints[name] = ip_hints
            if l3_config:
                _draft_l3_config[name] = l3_config
            if draft_pid:
                _draft_project_id[name] = draft_pid
            # Reuse existing draft UUID if present, otherwise generate one
            draft_uuid = existing_uuid if existing_uuid and existing_uuid.startswith("draft-") else f"draft-{_uuid_mod.uuid4()}"
            register_slice(name, uuid=draft_uuid, state="Draft", project_id=draft_pid)
            logger.info("Restored persistent draft '%s' from disk (id=%s)", name, draft_uuid)
        except Exception:
            logger.warning("Could not restore draft '%s' from disk", name, exc_info=True)


def _store_draft(name: str, slice_obj: Any, is_new: bool = True) -> None:
    with _draft_lock:
        _draft_slices[name] = slice_obj
        _draft_is_new[name] = is_new
        if name not in _draft_project_id:
            _draft_project_id[name] = os.environ.get("FABRIC_PROJECT_ID", "")
    # Persist new drafts to disk
    if is_new:
        _persist_draft(name, slice_obj)


def _pop_draft(name: str) -> tuple[Any | None, bool]:
    with _draft_lock:
        obj = _draft_slices.pop(name, None)
        is_new = _draft_is_new.pop(name, True)
        _draft_site_groups.pop(name, None)
        _draft_ip_hints.pop(name, None)
        _draft_l3_config.pop(name, None)
        _draft_project_id.pop(name, None)
        return obj, is_new


def _get_draft(name: str) -> Any | None:
    with _draft_lock:
        return _draft_slices.get(name)


def _is_draft(name: str) -> bool:
    with _draft_lock:
        return name in _draft_slices


def _is_new_draft(name: str) -> bool:
    with _draft_lock:
        return _draft_is_new.get(name, True)


def is_site_group(site: str) -> bool:
    """Return True if a site value is a group reference (starts with @)."""
    return isinstance(site, str) and site.startswith("@")


def _store_site_groups(name: str, groups: dict[str, str]) -> None:
    """Store node→group mapping for a slice."""
    with _draft_lock:
        _draft_site_groups[name] = groups


def _get_site_groups(name: str) -> dict[str, str]:
    """Get node→group mapping for a slice (empty dict if none)."""
    with _draft_lock:
        return dict(_draft_site_groups.get(name, {}))


def _store_ip_hints(name: str, net_name: str, hints: dict[str, dict]) -> None:
    """Store IP hints for a specific network in a slice."""
    with _draft_lock:
        if name not in _draft_ip_hints:
            _draft_ip_hints[name] = {}
        _draft_ip_hints[name][net_name] = hints


def _get_ip_hints(name: str, net_name: str) -> dict[str, dict]:
    """Get IP hints for a specific network (empty dict if none)."""
    with _draft_lock:
        return dict(_draft_ip_hints.get(name, {}).get(net_name, {}))


def _get_all_ip_hints(name: str) -> dict[str, dict[str, dict]]:
    """Get all IP hints for a slice (net_name → {iface → hint})."""
    with _draft_lock:
        return {k: dict(v) for k, v in _draft_ip_hints.get(name, {}).items()}


def _store_l3_config(name: str, net_name: str, config: dict) -> None:
    """Store L3 config for a specific network in a slice."""
    with _draft_lock:
        if name not in _draft_l3_config:
            _draft_l3_config[name] = {}
        _draft_l3_config[name][net_name] = config


def _get_l3_config(name: str, net_name: str) -> dict:
    """Get L3 config for a specific network (empty dict if none)."""
    with _draft_lock:
        return dict(_draft_l3_config.get(name, {}).get(net_name, {}))


def _get_all_l3_configs(name: str) -> dict[str, dict]:
    """Get all L3 configs for a slice (net_name → config)."""
    with _draft_lock:
        return {k: dict(v) for k, v in _draft_l3_config.get(name, {}).items()}


def _get_slice_obj(name: str):
    """Return the slice object — draft first, then UUID lookup, then name."""
    draft = _get_draft(name)
    if draft is not None:
        return draft
    fablib = get_fablib()
    uuid = get_slice_uuid(name)
    if uuid:
        try:
            return fablib.get_slice(slice_id=uuid)
        except Exception:
            logger.debug("UUID lookup failed for '%s' (uuid=%s), falling back to name", name, uuid)
    return fablib.get_slice(name=name)


# Serialization cache: keyed on (slice_name, state), stores serialized dict.
# Invalidated on any mutation (add/remove node, submit, modify).
_serialize_cache: dict[str, tuple[str, dict[str, Any]]] = {}  # name -> (state, data)


def _invalidate_serialize_cache(name: str):
    """Invalidate the serialization cache for a slice after mutations."""
    _serialize_cache.pop(name, None)


def _serialize(slice_obj, dirty: bool = False) -> dict[str, Any]:
    data = slice_to_dict(slice_obj)
    name = data.get("name", "")
    state = data.get("state", "")
    is_new = _is_new_draft(name) if _is_draft(name) else False

    # Check serialization cache for stable, non-dirty slices
    if not dirty and not is_new:
        cached = _serialize_cache.get(name)
        if cached and cached[0] == state:
            return cached[1]

    # Only mark as "Draft" if it's a genuinely new local slice with no UUID.
    # A slice that has a UUID was submitted to FABRIC and must show its real state.
    if is_new and not data.get("id"):
        data["state"] = "Draft"
    # Always inject the ID from the registry (draft-UUID or FABRIC UUID)
    # so the frontend can identify this slice by ID.
    if not data.get("id"):
        reg_uuid = get_slice_uuid(name)
        if reg_uuid:
            data["id"] = reg_uuid
    # Keep real state for loaded slices
    data["dirty"] = dirty
    # Annotate nodes with site group info
    site_groups = _get_site_groups(name)
    if site_groups:
        for node in data.get("nodes", []):
            grp = site_groups.get(node["name"])
            if grp:
                node["site_group"] = grp
    # Annotate networks with IP hints
    all_hints = _get_all_ip_hints(name)
    if all_hints:
        for net in data.get("networks", []):
            net_hints = all_hints.get(net["name"])
            if net_hints:
                net["ip_hints"] = net_hints
    # Re-persist new drafts to disk when modified
    if dirty and is_new:
        _persist_draft(name, slice_obj)
    graph = build_graph(data)
    result = {**data, "graph": graph}

    # Cache the result for stable, non-dirty slices
    if not dirty and not is_new:
        _serialize_cache[name] = (state, result)

    return result


# --- Request models ---

class CreateNodeRequest(BaseModel):
    name: str
    site: str = "auto"
    cores: int = 2
    ram: int = 8
    disk: int = 10
    image: str = "default_ubuntu_22"
    host: Optional[str] = None
    image_type: Optional[str] = None
    username: Optional[str] = None
    instance_type: Optional[str] = None
    components: Optional[List[Dict[str, Any]]] = None


class CreateComponentRequest(BaseModel):
    name: str
    model: str  # e.g. NIC_Basic, GPU_TeslaT4


class CreateNetworkRequest(BaseModel):
    name: str
    type: str = "L2Bridge"  # L2Bridge, L2STS, L2PTP, IPv4, IPv6, etc.
    interfaces: List[str] = []  # list of interface names to attach
    subnet: Optional[str] = None      # e.g. "192.168.1.0/24"
    gateway: Optional[str] = None     # e.g. "192.168.1.1"
    ip_mode: str = "none"             # "auto" | "config" | "none"
    interface_ips: Dict[str, str] = {} # {"node1-nic1-p1": "10.0.0.1"}


class PostBootConfigRequest(BaseModel):
    script: str  # bash script content


class SliceModelImport(BaseModel):
    format: str = "fabric-webgui-v1"
    name: str
    nodes: List[Dict[str, Any]] = []
    networks: List[Dict[str, Any]] = []
    facility_ports: List[Dict[str, Any]] = []
    port_mirrors: List[Dict[str, Any]] = []


class UpdateNodeRequest(BaseModel):
    site: Optional[str] = None
    host: Optional[str] = None
    cores: Optional[int] = None
    ram: Optional[int] = None
    disk: Optional[int] = None
    image: Optional[str] = None


class CreateFacilityPortRequest(BaseModel):
    name: str
    site: str
    vlan: str = ""
    bandwidth: int = 10


class CreatePortMirrorRequest(BaseModel):
    name: str
    mirror_interface_name: str       # interface to mirror (string name)
    receive_interface_name: str      # interface to receive capture (string name)
    mirror_direction: str = "both"   # "both" | "ingress" | "egress"


class ResolveSitesRequest(BaseModel):
    group_overrides: Dict[str, str] = {}  # "@group" -> "SITE_NAME"
    resolve_all: bool = False  # When True, re-resolve ALL nodes (not just grouped ones)


# --- Routes ---
# Heavy FABlib calls use async + asyncio.to_thread() so they don't block
# the event loop or exhaust the default threadpool for other requests.

# Request deduplication for list_slices: avoid concurrent FABlib calls
# from overlapping poll requests.
_list_slices_lock = asyncio.Lock()
_list_slices_cache: tuple[float, list[dict[str, Any]]] | None = None
_LIST_SLICES_CACHE_TTL = 5  # seconds


def _invalidate_list_cache():
    """Invalidate the list_slices dedup cache after mutations."""
    global _list_slices_cache
    _list_slices_cache = None

@router.get("/slices")
async def list_slices() -> list[dict[str, Any]]:
    """List all slices visible to the current user.

    1. Fast ``fablib.get_slices()`` — returns only active/non-terminal slices.
    2. Bulk-register results into the registry.
    3. For each non-archived registry entry with a UUID that was NOT in the
       fast results, individually query by UUID to get its current state and
       ``has_errors``.  This catches slices that transitioned to terminal
       states (Dead, Closing, StableError) since the last list.
    4. Scan drafts dir on disk for new drafts (e.g. created externally).
    5. Append new (never-submitted) draft slices.

    Uses a 5-second result cache + async lock to deduplicate concurrent polls.
    """
    import time as _time
    global _list_slices_cache

    # Fast path: return cached result if still fresh (no lock needed)
    cached = _list_slices_cache
    if cached and _time.time() - cached[0] < _LIST_SLICES_CACHE_TTL:
        return cached[1]

    # Acquire lock to prevent concurrent FABlib calls from overlapping polls
    async with _list_slices_lock:
        # Double-check after acquiring lock (another request may have filled cache)
        cached = _list_slices_cache
        if cached and _time.time() - cached[0] < _LIST_SLICES_CACHE_TTL:
            return cached[1]

        result = await _list_slices_impl()
        _list_slices_cache = (_time.time(), result)
        return result


async def _list_slices_impl() -> list[dict[str, Any]]:
    """Core implementation of list_slices (extracted for dedup caching)."""
    # Scan drafts dir for any new drafts not yet in memory
    try:
        await asyncio.to_thread(_load_persistent_drafts)
    except Exception:
        logger.warning("Failed to load persistent drafts", exc_info=True)

    current_pid = os.environ.get("FABRIC_PROJECT_ID", "")

    def _fast_query():
        fablib = get_fablib()
        slices = fablib.get_slices()
        # Filter to current project — get_slices() returns all accessible slices
        if current_pid:
            slices = [s for s in slices
                      if (getattr(s, 'get_project_id', lambda: '')() or '') == current_pid]
        return [slice_summary(s) for s in slices]
    try:
        fabric_results = await run_in_fablib_pool(_fast_query)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Load non-archived registry entries for the current project
    registry = get_all_entries(include_archived=False, project_id=current_pid)

    # Trust get_slices() results directly for state — no per-slice UUID
    # confirmation needed. This reduces list_slices from O(N) to O(1) FABlib
    # calls (single biggest backend performance win).
    all_entries: list[dict] = []
    for r in fabric_results:
        name = r["name"]
        uuid = r.get("id", "")
        fast_state = r.get("state", "")
        entry = registry.get(name)
        if entry is None:
            # New slice — register it
            all_entries.append({
                "name": name, "uuid": uuid,
                "state": fast_state, "has_errors": False,
            })
        elif entry.get("state") != fast_state:
            # State changed — trust get_slices() result and update registry
            update_slice_state(name, fast_state, uuid=uuid,
                               has_errors=entry.get("has_errors", False))
            logger.info("State change for '%s': %s → %s (trusted from get_slices)",
                        name, entry.get("state"), fast_state)
        else:
            # Unchanged — bulk register to keep registry fresh
            all_entries.append({
                "name": name, "uuid": uuid,
                "state": fast_state, "has_errors": entry.get("has_errors", False),
            })

    if all_entries:
        bulk_register(all_entries)

    # Build set of names returned by the fast query
    fast_names: set[str] = {r["name"] for r in fabric_results}

    # For registry entries NOT in fast results (stale), use the registry's
    # last known state. Only query by UUID lazily when the user selects
    # the slice (via refresh endpoint), not on every poll.
    stale_results: list[dict[str, Any]] = []
    for name, entry in registry.items():
        if name in fast_names:
            continue
        if entry.get("uuid"):
            uuid = entry["uuid"]
            state = entry.get("state", "Dead")
            # If the state is not terminal, it likely transitioned to Dead
            # since get_slices() didn't return it. Mark as Dead.
            if state not in TERMINAL_STATES:
                update_slice_state(name, "Dead", uuid=uuid, has_errors=False)
                state = "Dead"
            stale_results.append({
                "name": name, "id": uuid,
                "state": state,
                "has_errors": entry.get("has_errors", False),
            })

    results: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    # Add all FABRIC results directly (already authoritative)
    for r in fabric_results:
        name = r["name"]
        seen_names.add(name)
        entry = registry.get(name)
        r["has_errors"] = entry.get("has_errors", False) if entry else False
        results.append(r)

    # Add stale results
    for r in stale_results:
        name = r["name"]
        if name not in seen_names:
            results.append(r)
            seen_names.add(name)

    # Append new (never-submitted) draft slices for the current project.
    # A draft with a UUID in the registry was already submitted — skip it
    # (the stale query above should have picked it up with its real state).
    # Check ALL registry entries (including archived) to avoid resurrecting
    # archived slices as drafts.
    all_registry = get_all_entries(include_archived=True)
    with _draft_lock:
        for name in list(_draft_slices.keys()):
            if name not in seen_names and _draft_is_new.get(name, True):
                # Skip drafts from other projects
                draft_pid = _draft_project_id.get(name, "")
                if draft_pid and current_pid and draft_pid != current_pid:
                    continue
                # Double-check: if registry has a non-draft UUID, this was submitted
                reg_entry = all_registry.get(name)
                reg_uuid = reg_entry.get("uuid", "") if reg_entry else ""
                if reg_uuid and not reg_uuid.startswith("draft-"):
                    # Submitted slice stuck in draft store — clean it up
                    _draft_slices.pop(name, None)
                    _draft_is_new.pop(name, None)
                    _draft_project_id.pop(name, None)
                    _delete_persistent_draft(name)
                    continue
                # Use draft UUID from registry, or generate one if missing
                draft_id = reg_uuid or ""
                if not draft_id:
                    import uuid as _uuid_mod
                    draft_id = f"draft-{_uuid_mod.uuid4()}"
                    register_slice(name, uuid=draft_id, state="Draft", project_id=draft_pid)
                results.append({"name": name, "id": draft_id, "state": "Draft", "has_errors": False})
    return results


@router.post("/slices/archive-terminal")
async def archive_terminal_slices() -> dict[str, Any]:
    """Archive all slices in terminal states (Dead, Closing, StableError)."""
    _invalidate_list_cache()
    archived = registry_archive_all_terminal()
    return {"archived": archived, "count": len(archived)}


@router.post("/slices/reconcile-projects")
async def reconcile_projects() -> dict[str, Any]:
    """Scan all user projects and tag every known slice with its project_id.

    For each project the user belongs to, temporarily switches to that project,
    queries its slices, and tags the UUIDs in the registry.  Restores the
    original project when done.
    """
    def _reconcile():
        fablib = get_fablib()
        mgr = fablib.get_manager()
        original_pid = os.environ.get("FABRIC_PROJECT_ID", "")

        # Get all projects
        try:
            projects = mgr.get_project_info()
        except Exception as e:
            logger.warning("reconcile-projects: could not get project list: %s", e)
            return {"tagged": 0, "projects_scanned": 0, "error": str(e)}

        uuid_to_project: dict[str, str] = {}
        projects_scanned = 0

        try:
            for proj in projects:
                pid = proj.get("uuid", "")
                if not pid:
                    continue
                try:
                    fablib.set_project_id(pid)
                    os.environ["FABRIC_PROJECT_ID"] = pid
                    slices = fablib.get_slices()
                    for s in slices:
                        sid = str(s.get_slice_id()) if s.get_slice_id() else ""
                        if sid:
                            uuid_to_project[sid] = pid
                    projects_scanned += 1
                except Exception as e:
                    logger.warning("reconcile-projects: failed for project %s (%s): %s",
                                   proj.get("name", "?"), pid, e)
        finally:
            # Always restore original project, even if an exception occurs
            if original_pid:
                fablib.set_project_id(original_pid)
                os.environ["FABRIC_PROJECT_ID"] = original_pid

        # Bulk-tag the registry
        tagged = bulk_tag_project(uuid_to_project)
        return {
            "tagged": tagged,
            "projects_scanned": projects_scanned,
            "slices_found": len(uuid_to_project),
        }

    try:
        result = await run_in_fablib_pool(_reconcile)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/slices/{slice_name}")
async def get_slice(slice_name: str) -> dict[str, Any]:
    """Get full slice data including topology graph.

    For submitted slices this always fetches a fresh copy from FABRIC
    (by UUID) so the state is up-to-date.  New drafts (never submitted)
    are served from the in-memory store.
    """
    slice_name = _resolve_slice_name(slice_name)
    def _do():
        # New drafts (never submitted) — serve from memory.
        # Safety net: if the registry already has a UUID for this name, the
        # draft was submitted externally (e.g. by an AI tool) — skip the draft
        # and fall through to the FABRIC lookup below.
        if _is_new_draft(slice_name):
            existing_uuid = get_slice_uuid(slice_name)
            if not existing_uuid:
                slice_obj = _get_draft(slice_name)
                if slice_obj is not None:
                    return _serialize(slice_obj)
            else:
                # Draft was submitted externally — clean up
                _pop_draft(slice_name)
                _delete_persistent_draft(slice_name)

        # Submitted slices — always pull fresh from FABRIC by UUID
        fablib = get_fablib()
        uuid = get_slice_uuid(slice_name)
        slice_obj = None
        if uuid:
            try:
                slice_obj = fablib.get_slice(slice_id=uuid)
            except Exception:
                logger.debug("UUID lookup failed for '%s' (uuid=%s), falling back to name", slice_name, uuid)
        if slice_obj is None:
            slice_obj = fablib.get_slice(name=slice_name)

        # Determine state before deciding whether to store as draft
        state = str(slice_obj.get_state()) if slice_obj.get_state() else ""
        # Only store as draft if NOT in a terminal state — terminal slices
        # are read-only (viewable/clonable but not editable)
        if state not in TERMINAL_STATES:
            _store_draft(slice_name, slice_obj, is_new=False)
        else:
            # Terminal slice — remove any stale draft
            _pop_draft(slice_name)

        data = _serialize(slice_obj)
        # Ensure a working directory exists for this slice
        from app.routes.jupyter import ensure_slice_workdir
        ensure_slice_workdir(slice_name)
        # Update registry with fresh state (including has_errors)
        try:
            sid = str(slice_obj.get_slice_id()) if hasattr(slice_obj, 'get_slice_id') else ""
            st = data.get("state", "")
            has_errors = bool(data.get("error_messages"))
            if sid or st:
                update_slice_state(slice_name, st, uuid=sid, has_errors=has_errors)
        except Exception:
            logger.warning("Failed to update registry state for '%s'", slice_name, exc_info=True)
        return data
    try:
        return await run_in_fablib_pool(_do)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Slice not found: {e}")


@router.post("/slices")
async def create_slice(name: str) -> dict[str, Any]:
    """Create a new empty draft slice."""
    _invalidate_list_cache()
    def _do():
        import uuid as _uuid_mod
        fablib = get_fablib()
        slice_obj = fablib.new_slice(name=name)
        # Generate a local draft UUID so the frontend can identify this slice
        draft_id = f"draft-{_uuid_mod.uuid4()}"
        _store_draft(name, slice_obj, is_new=True)
        register_slice(name, uuid=draft_id, state="Draft")
        # Create an empty working directory for this slice
        from app.routes.jupyter import ensure_slice_workdir
        ensure_slice_workdir(name)
        return _serialize(slice_obj)
    try:
        return await run_in_fablib_pool(_do)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/slices/{slice_name}/submit")
async def submit_slice(slice_name: str) -> dict[str, Any]:
    """Submit a slice — creates new slice or modifies existing one."""
    _invalidate_list_cache()
    slice_name = _resolve_slice_name(slice_name)
    # Capture site groups before popping draft (pop clears them)
    site_groups = _get_site_groups(slice_name)
    draft, is_new = _pop_draft(slice_name)
    if draft is not None:
        # Track whether submit() actually succeeded so we know whether
        # to restore the draft on error or not.
        submit_succeeded = False
        submitted_uuid = ""
        submitted_state = ""

        def _do():
            nonlocal submit_succeeded, submitted_uuid, submitted_state
            if is_new:
                # Force-refresh resource availability (including host-level)
                # and re-resolve all node site assignments before submitting.
                logger.info("Submit: refreshing resource availability for slice '%s'", slice_name)
                fresh_sites = get_fresh_sites()

                data = slice_to_dict(draft)
                # Build node defs — restore @group tags for grouped nodes,
                # keep explicit sites, mark ungrouped nodes as "auto" so
                # the resolver assigns them to sites with real capacity.
                node_defs = []
                for node in data.get("nodes", []):
                    grp = site_groups.get(node["name"])
                    current_site = node.get("site", "")

                    if current_site and not current_site.startswith("@") and current_site != "auto":
                        # User explicitly set this site (or it was resolved
                        # earlier and the user kept it) — honour it as-is.
                        site = current_site
                    elif grp:
                        # Still in a group with no concrete site — pass @group for resolution
                        site = grp
                    else:
                        # No site set — auto-resolve
                        site = "auto"
                    node_defs.append({
                        "name": node["name"],
                        "site": site,
                        "cores": node.get("cores", 2),
                        "ram": node.get("ram", 8),
                        "disk": node.get("disk", 10),
                        "components": node.get("components", []),
                    })

                resolved_defs, _ = resolve_sites(node_defs, fresh_sites)

                # Apply resolved sites to draft nodes — only if the site
                # actually changed (skip user-defined mappings).
                for nd in resolved_defs:
                    try:
                        fab_node = draft.get_node(name=nd["name"])
                        old_site = str(fab_node.get_site()) if fab_node.get_site() else ""
                        if nd["site"] and nd["site"] != old_site:
                            fab_node.set_site(nd["site"])
                            logger.info("Submit: node '%s' -> site '%s'", nd["name"], nd["site"])
                    except Exception as ex:
                        logger.warning("Submit re-resolve: could not set site for %s: %s", nd["name"], ex)

                submit_error = None
                try:
                    draft.submit(wait=False)
                except Exception as e:
                    submit_error = e
                    logger.warning("Submit: draft.submit() threw for '%s': %s", slice_name, e)
            else:
                submit_error = None
                try:
                    draft.submit(wait=False)
                except Exception as e:
                    submit_error = e
                    logger.warning("Submit: draft.submit() threw for '%s': %s", slice_name, e)

            # Once submit() has been called (even if it threw), the slice
            # may exist on FABRIC. Try to capture the UUID, retrying a few
            # times since it may not be immediately available.
            _capture_uuid_with_retry(draft, slice_name)

            if submit_succeeded:
                _delete_persistent_draft(slice_name)
                if submit_error:
                    # submit() threw but the slice exists on FABRIC (we got UUID).
                    # Return what we have — the slice will show as terminal.
                    return _serialize(draft)
                return _serialize(draft)

            # If we still don't have a UUID, re-raise the original error
            # so the draft gets restored.
            if submit_error:
                raise submit_error

            # submit() returned normally but we couldn't get a UUID (unlikely)
            submit_succeeded = True
            return _serialize(draft)

        def _capture_uuid_with_retry(d, name):
            """Try to capture UUID from the draft object, retrying with delays.

            FABlib may not populate the slice_id immediately after submit().
            We retry a few times with short delays to give it time."""
            nonlocal submit_succeeded, submitted_uuid, submitted_state
            import time
            for attempt in range(6):  # try up to 6 times (~15s total)
                try:
                    sid = str(d.get_slice_id()) if d.get_slice_id() else ""
                    if sid:
                        submitted_uuid = sid
                        try:
                            submitted_state = str(d.get_state()) if d.get_state() else "Configuring"
                        except Exception:
                            logger.debug("Could not read state after submit", exc_info=True)
                            submitted_state = "Configuring"
                        submit_succeeded = True
                        update_slice_state(name, submitted_state, uuid=submitted_uuid)
                        logger.info("Submit: slice '%s' uuid=%s, state=%s (attempt %d)",
                                    name, submitted_uuid, submitted_state, attempt + 1)
                        return
                except Exception:
                    logger.debug("UUID capture attempt failed", exc_info=True)
                if attempt < 5:
                    logger.info("Submit: no UUID yet for '%s', retrying in %ds (attempt %d/6)",
                                name, (attempt + 1), attempt + 1)
                    time.sleep(attempt + 1)  # 1, 2, 3, 4, 5 seconds
            logger.warning("Submit: could not capture UUID for '%s' after retries", name)
        try:
            return await run_in_fablib_pool(_do)
        except Exception as e:
            if submit_succeeded:
                # Submit worked but post-submit serialization failed.
                # Do NOT restore the draft — the slice is on FABRIC now.
                logger.warning("Submit succeeded for '%s' but post-submit failed: %s", slice_name, e)
                # Return minimal data so frontend knows it worked
                return {
                    "name": slice_name,
                    "id": submitted_uuid,
                    "state": submitted_state or "Configuring",
                    "dirty": False,
                    "lease_start": "",
                    "lease_end": "",
                    "error_messages": [],
                    "nodes": [],
                    "networks": [],
                    "facility_ports": [],
                    "graph": {"nodes": [], "edges": []},
                }
            # Submit itself failed — restore draft so user can retry
            _store_draft(slice_name, draft, is_new=is_new)
            if site_groups:
                _store_site_groups(slice_name, site_groups)
            raise HTTPException(status_code=500, detail=str(e))
    # Not a draft — nothing to submit
    raise HTTPException(status_code=400, detail="No pending changes to submit")


@router.post("/slices/{slice_name}/refresh")
async def refresh_slice(slice_name: str) -> dict[str, Any]:
    """Refresh slice state from FABRIC (discards local edits).

    For new drafts (never submitted, no UUID on FABRIC), just return the
    current draft without hitting FABRIC — there is nothing to refresh.
    """
    slice_name = _resolve_slice_name(slice_name)
    # Check if this is a new draft with no UUID — nothing to refresh from FABRIC
    if _is_draft(slice_name) and _is_new_draft(slice_name):
        uuid = get_slice_uuid(slice_name)
        if not uuid:
            draft = _get_draft(slice_name)
            if draft is not None:
                return _serialize(draft)

    # Drop any draft — reload fresh from FABRIC
    _invalidate_serialize_cache(slice_name)
    draft_backup, is_new_backup = _pop_draft(slice_name)
    site_groups_backup = _get_site_groups(slice_name)

    def _do():
        fablib = get_fablib()
        # Use UUID if available for reliable lookup
        uuid = get_slice_uuid(slice_name)
        if uuid:
            try:
                slice_obj = fablib.get_slice(slice_id=uuid)
            except Exception:
                slice_obj = fablib.get_slice(name=slice_name)
        else:
            slice_obj = fablib.get_slice(name=slice_name)
        slice_obj.update()
        # Update registry with current state (including has_errors)
        try:
            sid = str(slice_obj.get_slice_id())
            state = str(slice_obj.get_state())
            has_errors = check_has_errors(slice_obj)
            update_slice_state(slice_name, state, uuid=sid, has_errors=has_errors)
        except Exception:
            logger.warning("Failed to read state after refresh", exc_info=True)
            state = ""
        # Only store as draft if NOT terminal — terminal slices are read-only
        if state not in TERMINAL_STATES:
            _store_draft(slice_name, slice_obj, is_new=False)
        return _serialize(slice_obj)
    try:
        return await run_in_fablib_pool(_do)
    except Exception as e:
        # Restore draft so user doesn't lose their work
        if draft_backup is not None:
            _store_draft(slice_name, draft_backup, is_new=is_new_backup)
            if site_groups_backup:
                _store_site_groups(slice_name, site_groups_backup)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/slices/{slice_name}/state")
async def get_slice_state(slice_name: str) -> dict[str, Any]:
    """Return only slice state (lightweight, for polling)."""
    slice_name = _resolve_slice_name(slice_name)
    uuid = get_slice_uuid(slice_name)
    entry = get_all_entries(include_archived=True).get(slice_name)
    if entry:
        return {
            "name": slice_name,
            "id": entry.get("uuid", uuid or ""),
            "state": entry.get("state", ""),
            "has_errors": entry.get("has_errors", False),
        }
    raise HTTPException(status_code=404, detail="Slice not found")


@router.post("/slices/{slice_name}/resolve-sites")
async def resolve_sites_endpoint(slice_name: str, body: ResolveSitesRequest = ResolveSitesRequest()) -> dict[str, Any]:
    """Re-resolve site assignments for a draft slice.

    Optionally accepts group_overrides to pin specific groups to sites.
    Groups not overridden are re-resolved using fresh resource data.
    When resolve_all is True, all nodes (not just grouped ones) are re-resolved.
    """
    slice_name = _resolve_slice_name(slice_name)
    draft = _get_draft(slice_name)
    if draft is None:
        raise HTTPException(status_code=404, detail=f"No draft found for slice '{slice_name}'")

    site_groups = _get_site_groups(slice_name)
    if not site_groups and not body.resolve_all:
        raise HTTPException(status_code=400, detail="Slice has no site groups to resolve")

    def _do():
        data = slice_to_dict(draft)
        nodes = data.get("nodes", [])

        # Build node defs for the resolver
        node_defs = []
        for node in nodes:
            grp = (site_groups or {}).get(node["name"])
            if grp:
                # Check if this group is overridden
                if grp in body.group_overrides:
                    site = body.group_overrides[grp]
                else:
                    site = grp  # Pass @group tag for re-resolution
            elif body.resolve_all:
                site = "auto"  # Force re-resolution for all non-grouped nodes
            else:
                site = node.get("site", "")
            node_defs.append({
                "name": node["name"],
                "site": site,
                "cores": node.get("cores", 2),
                "ram": node.get("ram", 8),
                "disk": node.get("disk", 10),
                "components": node.get("components", []),
            })

        # Refresh cached sites for current availability
        sites = get_cached_sites()

        # Re-resolve — only non-overridden groups will be resolved
        resolved_defs, new_groups = resolve_sites(node_defs, sites)

        # Update FABlib draft node sites
        fablib = get_fablib()
        for nd in resolved_defs:
            try:
                fab_node = draft.get_node(name=nd["name"])
                fab_node.set_site(site=nd["site"])
            except Exception:
                logger.warning("Could not update site for node %s", nd["name"])

        # Merge: keep all original group memberships, update resolved sites
        merged_groups = dict(site_groups)
        merged_groups.update(new_groups)
        _store_site_groups(slice_name, merged_groups)

        return _serialize(draft, dirty=True)

    try:
        return await run_in_fablib_pool(_do)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/slices/{slice_name}")
async def delete_slice(slice_name: str) -> dict[str, str]:
    """Delete a slice."""
    _invalidate_list_cache()
    slice_name = _resolve_slice_name(slice_name)
    draft, is_new = _pop_draft(slice_name)
    if draft is not None and is_new:
        # Just a draft that was never submitted — discard it
        _delete_persistent_draft(slice_name)
        unregister_slice(slice_name)
        return {"status": "deleted", "name": slice_name}
    # Delete the actual slice from FABRIC
    def _do():
        fablib = get_fablib()
        # Use UUID if available for reliable lookup
        uuid = get_slice_uuid(slice_name)
        if uuid:
            try:
                slice_obj = fablib.get_slice(slice_id=uuid)
            except Exception:
                slice_obj = fablib.get_slice(name=slice_name)
        else:
            slice_obj = fablib.get_slice(name=slice_name)
        slice_obj.delete()
        update_slice_state(slice_name, "Dead")
        return {"status": "deleted", "name": slice_name}
    try:
        return await run_in_fablib_pool(_do)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class RenewRequest(BaseModel):
    end_date: str


@router.post("/slices/{slice_name}/renew")
async def renew_slice(slice_name: str, body: RenewRequest) -> dict[str, Any]:
    """Renew a slice lease to a new end date."""
    slice_name = _resolve_slice_name(slice_name)
    from datetime import datetime

    try:
        end_dt = datetime.fromisoformat(body.end_date.replace("Z", "+00:00"))
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {body.end_date}")

    def _do():
        fablib = get_fablib()
        uuid = get_slice_uuid(slice_name)
        if uuid:
            try:
                slice_obj = fablib.get_slice(slice_id=uuid)
            except Exception:
                slice_obj = fablib.get_slice(name=slice_name)
        else:
            slice_obj = fablib.get_slice(name=slice_name)
        slice_obj.renew(end_dt)
        slice_obj.update()
        return _serialize(slice_obj)

    try:
        return await run_in_fablib_pool(_do)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("renew_slice failed for %s", slice_name)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/slices/{slice_name}/archive")
async def archive_slice_endpoint(slice_name: str) -> dict[str, str]:
    """Archive a slice (hide from list without deleting)."""
    slice_name = _resolve_slice_name(slice_name)
    registry_archive_slice(slice_name)
    return {"status": "archived", "name": slice_name}


@router.get("/slices/{slice_name}/validate")
def validate_slice(slice_name: str) -> dict[str, Any]:
    """Validate a slice and return any issues."""
    slice_name = _resolve_slice_name(slice_name)
    try:
        slice_obj = _get_slice_obj(slice_name)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Slice not found: {e}")

    issues: list[dict[str, str]] = []
    data = slice_to_dict(slice_obj)
    nodes = data.get("nodes", [])
    networks = data.get("networks", [])

    # Must have at least one node
    if not nodes:
        issues.append({
            "severity": "error",
            "message": "Slice has no nodes.",
            "remedy": "Add at least one node using the editor panel.",
        })

    for node in nodes:
        name = node.get("name", "?")
        site = node.get("site", "")
        # Node needs a site
        if not site or site in ("None", "none", ""):
            issues.append({
                "severity": "error",
                "message": f"Node '{name}' has no site assigned.",
                "remedy": f"Set a site for node '{name}' in the editor panel.",
            })
        # Check resource minimums
        cores = node.get("cores", 0)
        ram = node.get("ram", 0)
        disk = node.get("disk", 0)
        if isinstance(cores, (int, float)) and cores < 1:
            issues.append({
                "severity": "error",
                "message": f"Node '{name}' has {cores} cores.",
                "remedy": f"Set at least 1 core for node '{name}'.",
            })
        if isinstance(ram, (int, float)) and ram < 1:
            issues.append({
                "severity": "error",
                "message": f"Node '{name}' has {ram} GB RAM.",
                "remedy": f"Set at least 1 GB RAM for node '{name}'.",
            })
        if isinstance(disk, (int, float)) and disk < 1:
            issues.append({
                "severity": "error",
                "message": f"Node '{name}' has {disk} GB disk.",
                "remedy": f"Set at least 1 GB disk for node '{name}'.",
            })

    for net in networks:
        net_name = net.get("name", "?")
        net_type = net.get("type", "")
        ifaces = net.get("interfaces", [])
        iface_count = len(ifaces)

        layer = net.get("layer", "L2")
        if "PTP" in net_type:
            if iface_count != 2:
                issues.append({
                    "severity": "error",
                    "message": f"Network '{net_name}' ({net_type}) has {iface_count} interface(s), needs exactly 2.",
                    "remedy": f"Connect exactly 2 interfaces to '{net_name}'.",
                })
        elif layer == "L3":
            # L3 networks have an implied gateway, so 1 interface is valid
            if iface_count < 1:
                issues.append({
                    "severity": "error",
                    "message": f"Network '{net_name}' ({net_type}) has no interfaces.",
                    "remedy": f"Connect at least 1 interface to '{net_name}'.",
                })
        else:
            if iface_count < 2:
                issues.append({
                    "severity": "error",
                    "message": f"Network '{net_name}' ({net_type}) has {iface_count} interface(s), needs at least 2.",
                    "remedy": f"Connect at least 2 interfaces to '{net_name}'.",
                })

    # Check for nodes with NICs that aren't connected to any network
    for node in nodes:
        for comp in node.get("components", []):
            for iface in comp.get("interfaces", []):
                if not iface.get("network_name"):
                    issues.append({
                        "severity": "warning",
                        "message": f"Interface '{iface.get('name', '?')}' on node '{node.get('name', '?')}' is not connected to a network.",
                        "remedy": "Connect the interface to a network, or remove the component if unused.",
                    })

    # Validate IP hints for L3 networks
    l3_net_types = {"FABNetv4", "FABNetv6", "FABNetv4Ext", "FABNetv6Ext",
                    "IPv4", "IPv6", "IPv4Ext", "IPv6Ext", "L3VPN"}
    all_hints = _get_all_ip_hints(slice_name)
    for net in networks:
        net_name = net.get("name", "?")
        net_type = net.get("type", "")
        hints = all_hints.get(net_name, {})
        if not hints:
            continue
        if net_type not in l3_net_types:
            issues.append({
                "severity": "error",
                "message": f"IP hints on '{net_name}' ({net_type}) are only valid for FABNetv4/v6 networks.",
                "remedy": f"Remove IP hints from non-L3 network '{net_name}'.",
            })
            continue
        seen_octets: dict[int, str] = {}
        for iface_name, hint in hints.items():
            octet = hint.get("last_octet")
            if octet is not None:
                if not isinstance(octet, int) or not (1 <= octet <= 254):
                    issues.append({
                        "severity": "error",
                        "message": f"IP hint for '{iface_name}' on '{net_name}': last_octet {octet} must be 1-254.",
                        "remedy": f"Fix the last octet value for '{iface_name}'.",
                    })
                elif octet in seen_octets:
                    issues.append({
                        "severity": "error",
                        "message": f"Duplicate last_octet {octet} on '{net_name}': '{seen_octets[octet]}' and '{iface_name}'.",
                        "remedy": f"Choose unique last octets for each interface on '{net_name}'.",
                    })
                else:
                    seen_octets[octet] = iface_name
            range_str = hint.get("last_octet_range", "")
            if range_str:
                try:
                    parts = range_str.split("-")
                    lo, hi = int(parts[0]), int(parts[1])
                    if not (1 <= lo <= 254 and 1 <= hi <= 254 and lo <= hi):
                        raise ValueError("out of range")
                except (ValueError, IndexError):
                    issues.append({
                        "severity": "error",
                        "message": f"IP hint for '{iface_name}' on '{net_name}': invalid range '{range_str}'.",
                        "remedy": "Use format 'LOW-HIGH' where both are 1-254 and LOW <= HIGH.",
                    })

    return {
        "valid": len([i for i in issues if i["severity"] == "error"]) == 0,
        "issues": issues,
    }


# --- Node operations ---

@router.post("/slices/{slice_name}/nodes")
def add_node(slice_name: str, req: CreateNodeRequest) -> dict[str, Any]:
    """Add a node to a slice."""
    slice_name = _resolve_slice_name(slice_name)
    try:
        slice_obj = _get_slice_obj(slice_name)
        kwargs: dict[str, Any] = {
            "name": req.name,
            "cores": req.cores,
            "ram": req.ram,
            "disk": req.disk,
            "image": req.image,
        }
        if req.site != "auto":
            kwargs["site"] = req.site
        if req.host:
            kwargs["host"] = req.host
        node = slice_obj.add_node(**kwargs)
        if req.image_type and req.image_type != "qcow2":
            node.set_image(req.image, image_type=req.image_type)
        if req.username:
            node.set_username(req.username)
        if req.instance_type:
            try:
                node.set_instance_type(req.instance_type)
            except Exception:
                pass
        if req.components:
            for comp_def in req.components:
                comp = node.add_component(
                    model=comp_def.get("model", "NIC_Basic"),
                    name=comp_def.get("name", ""),
                )
        return _serialize(slice_obj, dirty=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/slices/{slice_name}/nodes/{node_name}")
def remove_node(slice_name: str, node_name: str) -> dict[str, Any]:
    """Remove a node from a slice."""
    slice_name = _resolve_slice_name(slice_name)
    try:
        slice_obj = _get_slice_obj(slice_name)
        node = slice_obj.get_node(name=node_name)
        node.delete()
        return _serialize(slice_obj, dirty=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/slices/{slice_name}/nodes/{node_name}")
def update_node(slice_name: str, node_name: str, req: UpdateNodeRequest) -> dict[str, Any]:
    """Update node configuration."""
    slice_name = _resolve_slice_name(slice_name)
    try:
        slice_obj = _get_slice_obj(slice_name)
        node = slice_obj.get_node(name=node_name)
        if req.site is not None:
            node.set_site(req.site)
        if req.host is not None:
            node.set_host(req.host if req.host else None)
        # Call set_capacities once with all provided values to avoid overwrites
        cap_kwargs: dict[str, Any] = {}
        if req.cores is not None:
            cap_kwargs["cores"] = req.cores
        if req.ram is not None:
            cap_kwargs["ram"] = req.ram
        if req.disk is not None:
            cap_kwargs["disk"] = req.disk
        if cap_kwargs:
            node.set_capacities(**cap_kwargs)
        if req.image is not None:
            node.set_image(req.image)
        return _serialize(slice_obj, dirty=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Component operations ---

@router.post("/slices/{slice_name}/nodes/{node_name}/components")
def add_component(slice_name: str, node_name: str, req: CreateComponentRequest) -> dict[str, Any]:
    """Add a component to a node."""
    slice_name = _resolve_slice_name(slice_name)
    try:
        slice_obj = _get_slice_obj(slice_name)
        node = slice_obj.get_node(name=node_name)
        node.add_component(model=req.model, name=req.name)
        return _serialize(slice_obj, dirty=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/slices/{slice_name}/nodes/{node_name}/components/{comp_name}")
def remove_component(slice_name: str, node_name: str, comp_name: str) -> dict[str, Any]:
    """Remove a component from a node."""
    slice_name = _resolve_slice_name(slice_name)
    try:
        slice_obj = _get_slice_obj(slice_name)
        node = slice_obj.get_node(name=node_name)
        comp = node.get_component(name=comp_name)
        comp.delete()
        return _serialize(slice_obj, dirty=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Facility port operations ---

@router.post("/slices/{slice_name}/facility-ports")
def add_facility_port(slice_name: str, req: CreateFacilityPortRequest) -> dict[str, Any]:
    """Add a facility port to a slice."""
    slice_name = _resolve_slice_name(slice_name)
    try:
        slice_obj = _get_slice_obj(slice_name)
        kwargs: dict[str, Any] = {
            "name": req.name,
            "site": req.site,
        }
        if req.vlan:
            kwargs["vlan"] = req.vlan
        if req.bandwidth:
            kwargs["bandwidth"] = req.bandwidth
        slice_obj.add_facility_port(**kwargs)
        return _serialize(slice_obj, dirty=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/slices/{slice_name}/facility-ports/{fp_name}")
def remove_facility_port(slice_name: str, fp_name: str) -> dict[str, Any]:
    """Remove a facility port from a slice."""
    slice_name = _resolve_slice_name(slice_name)
    try:
        slice_obj = _get_slice_obj(slice_name)
        # Get facility port by name and delete
        for fp in slice_obj.get_facility_ports():
            if fp.get_name() == fp_name:
                fp.delete()
                return _serialize(slice_obj, dirty=True)
        raise HTTPException(status_code=404, detail=f"Facility port '{fp_name}' not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Port mirror operations ---

@router.post("/slices/{slice_name}/port-mirrors")
def add_port_mirror(slice_name: str, req: CreatePortMirrorRequest) -> dict[str, Any]:
    """Add a port mirror service to a slice."""
    slice_name = _resolve_slice_name(slice_name)
    if req.mirror_direction not in ("both", "ingress", "egress"):
        raise HTTPException(status_code=400, detail="mirror_direction must be 'both', 'ingress', or 'egress'")
    try:
        slice_obj = _get_slice_obj(slice_name)
        # Resolve the receive interface object from its name
        receive_iface = None
        for node in slice_obj.get_nodes():
            for iface in node.get_interfaces():
                if iface.get_name() == req.receive_interface_name:
                    receive_iface = iface
                    break
            if receive_iface:
                break
        if receive_iface is None:
            raise HTTPException(status_code=404, detail=f"Receive interface '{req.receive_interface_name}' not found")

        slice_obj.add_port_mirror_service(
            name=req.name,
            mirror_interface_name=req.mirror_interface_name,
            receive_interface=receive_iface,
            mirror_direction=req.mirror_direction,
        )
        return _serialize(slice_obj, dirty=True)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/slices/{slice_name}/port-mirrors/{pm_name}")
def remove_port_mirror(slice_name: str, pm_name: str) -> dict[str, Any]:
    """Remove a port mirror service from a slice."""
    slice_name = _resolve_slice_name(slice_name)
    try:
        slice_obj = _get_slice_obj(slice_name)
        # Try dedicated method first
        if hasattr(slice_obj, 'get_port_mirror_services'):
            for pm in (slice_obj.get_port_mirror_services() or []):
                if pm.get_name() == pm_name:
                    pm.delete()
                    return _serialize(slice_obj, dirty=True)
        # Fallback: try via network services
        for svc in (slice_obj.get_network_services() or []):
            if svc.get_name() == pm_name:
                try:
                    svc_type = str(svc.get_type())
                    if "PortMirror" in svc_type:
                        svc.delete()
                        return _serialize(slice_obj, dirty=True)
                except Exception:
                    pass
        raise HTTPException(status_code=404, detail=f"Port mirror '{pm_name}' not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Network operations ---

@router.post("/slices/{slice_name}/networks")
def add_network(slice_name: str, req: CreateNetworkRequest) -> dict[str, Any]:
    """Add a network to a slice."""
    slice_name = _resolve_slice_name(slice_name)
    try:
        slice_obj = _get_slice_obj(slice_name)
        # Resolve interface objects from names
        ifaces = []
        for iface_name in req.interfaces:
            for node in slice_obj.get_nodes():
                for iface in node.get_interfaces():
                    if iface.get_name() == iface_name:
                        ifaces.append(iface)

        _fabnet_to_l3 = {
            "FABNetv4": "IPv4", "FABNetv6": "IPv6",
            "FABNetv4Ext": "IPv4Ext", "FABNetv6Ext": "IPv6Ext",
        }
        l3_types = {"IPv4", "IPv6", "IPv4Ext", "IPv6Ext", "L3VPN",
                    "FABNetv4", "FABNetv6", "FABNetv4Ext", "FABNetv6Ext"}
        if req.type in l3_types:
            # L3 network — use add_l3network, auto-assign IPs
            canonical_type = _fabnet_to_l3.get(req.type, req.type)
            net = slice_obj.add_l3network(name=req.name, interfaces=ifaces, type=canonical_type)
            for iface in ifaces:
                iface.set_mode("auto")
        else:
            # L2 network
            net = slice_obj.add_l2network(name=req.name, interfaces=ifaces, type=req.type)
            if req.subnet:
                net.set_subnet(req.subnet)
            if req.gateway:
                net.set_gateway(req.gateway)
            if req.ip_mode == "auto" and req.subnet:
                for iface in ifaces:
                    iface.set_mode("auto")
            elif req.ip_mode == "config":
                for iface in ifaces:
                    iface_name = iface.get_name()
                    if iface_name in req.interface_ips:
                        iface.set_mode("config")
                        iface.set_ip_addr(addr=req.interface_ips[iface_name])

        return _serialize(slice_obj, dirty=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class UpdateNetworkRequest(BaseModel):
    subnet: Optional[str] = None
    gateway: Optional[str] = None
    ip_mode: str = "none"             # "auto" | "config" | "none"
    interface_ips: Dict[str, str] = {}


@router.put("/slices/{slice_name}/networks/{net_name}")
def update_network(slice_name: str, net_name: str, req: UpdateNetworkRequest) -> dict[str, Any]:
    """Update IP mode, subnet, and per-interface IPs on an existing L2 network."""
    slice_name = _resolve_slice_name(slice_name)
    try:
        slice_obj = _get_slice_obj(slice_name)
        net = slice_obj.get_network(name=net_name)
        ifaces = net.get_interfaces()

        # Update subnet/gateway
        if req.subnet:
            net.set_subnet(req.subnet)
        if req.gateway:
            net.set_gateway(req.gateway)

        # Reset all interface modes first
        for iface in ifaces:
            iface.set_mode("none")

        # Apply new mode
        if req.ip_mode == "auto" and req.subnet:
            for iface in ifaces:
                iface.set_mode("auto")
        elif req.ip_mode == "config":
            for iface in ifaces:
                iface_name = iface.get_name()
                if iface_name in req.interface_ips:
                    iface.set_mode("config")
                    iface.set_ip_addr(addr=req.interface_ips[iface_name])

        return _serialize(slice_obj, dirty=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/slices/{slice_name}/networks/{net_name}")
def remove_network(slice_name: str, net_name: str) -> dict[str, Any]:
    """Remove a network from a slice."""
    slice_name = _resolve_slice_name(slice_name)
    try:
        slice_obj = _get_slice_obj(slice_name)
        net = slice_obj.get_network(name=net_name)
        net.delete()
        return _serialize(slice_obj, dirty=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- IP Hints for L3 (FABNetv4/v6) networks ---

class IpHintsRequest(BaseModel):
    hints: Dict[str, Dict[str, Any]]  # {iface_name: {last_octet?: int, last_octet_range?: str}}


@router.get("/slices/{slice_name}/networks/{net_name}/ip-hints")
def get_ip_hints(slice_name: str, net_name: str) -> dict[str, Any]:
    """Get IP hints for a L3 network."""
    slice_name = _resolve_slice_name(slice_name)
    return {"network": net_name, "hints": _get_ip_hints(slice_name, net_name)}


@router.put("/slices/{slice_name}/networks/{net_name}/ip-hints")
def set_ip_hints(slice_name: str, net_name: str, req: IpHintsRequest) -> dict[str, Any]:
    """Save IP hints for a L3 network."""
    slice_name = _resolve_slice_name(slice_name)
    _store_ip_hints(slice_name, net_name, req.hints)
    # Re-persist draft if it's a new draft
    if _is_draft(slice_name) and _is_new_draft(slice_name):
        draft = _get_draft(slice_name)
        if draft:
            _persist_draft(slice_name, draft)
    return {"network": net_name, "hints": req.hints, "status": "ok"}


@router.post("/slices/{slice_name}/networks/{net_name}/apply-ip-hints")
async def apply_ip_hints(slice_name: str, net_name: str) -> dict[str, Any]:
    """Compute IPs from subnet + hints, write boot config entries.

    For active slices where FABNetv4 subnet is already assigned.
    """
    slice_name = _resolve_slice_name(slice_name)
    def _do():
        slice_obj = _get_slice_obj(slice_name)
        data = slice_to_dict(slice_obj)

        # Find the network
        net_data = None
        for n in data.get("networks", []):
            if n["name"] == net_name:
                net_data = n
                break
        if not net_data:
            raise HTTPException(status_code=404, detail=f"Network '{net_name}' not found")

        subnet_str = net_data.get("subnet", "")
        if not subnet_str:
            raise HTTPException(status_code=400, detail="Network has no subnet assigned yet")

        # Parse the subnet to extract prefix
        import ipaddress
        try:
            network = ipaddress.IPv4Network(subnet_str, strict=False)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid subnet '{subnet_str}': {e}")

        prefix_parts = str(network.network_address).rsplit(".", 1)
        prefix = prefix_parts[0]  # e.g. "10.128.1"

        hints = _get_ip_hints(slice_name, net_name)
        if not hints:
            return {"network": net_name, "assignments": {}, "message": "No hints configured"}

        assignments: dict[str, str] = {}
        used_octets: set[int] = set()

        # Collect gateway octet to avoid conflicts
        gw = net_data.get("gateway", "")
        if gw:
            try:
                gw_octet = int(gw.rsplit(".", 1)[1])
                used_octets.add(gw_octet)
            except (ValueError, IndexError):
                pass

        # Collect already-assigned IPs to avoid conflicts
        for iface in net_data.get("interfaces", []):
            ip = iface.get("ip_addr", "")
            if ip:
                try:
                    octet = int(ip.rsplit(".", 1)[1])
                    used_octets.add(octet)
                except (ValueError, IndexError):
                    pass

        # First pass: fixed last_octet assignments
        for iface_name, hint in hints.items():
            octet = hint.get("last_octet")
            if octet is not None:
                if not (1 <= octet <= 254):
                    continue
                assignments[iface_name] = f"{prefix}.{octet}"
                used_octets.add(octet)

        # Second pass: last_octet_range assignments
        for iface_name, hint in hints.items():
            if iface_name in assignments:
                continue
            range_str = hint.get("last_octet_range", "")
            if not range_str:
                continue
            try:
                parts = range_str.split("-")
                lo, hi = int(parts[0]), int(parts[1])
            except (ValueError, IndexError):
                continue
            lo = max(1, lo)
            hi = min(254, hi)
            for candidate in range(lo, hi + 1):
                if candidate not in used_octets:
                    assignments[iface_name] = f"{prefix}.{candidate}"
                    used_octets.add(candidate)
                    break

        # Build routes list from l3_config
        l3_cfg = _get_l3_config(slice_name, net_name)
        routes: list[str] = []
        route_mode = l3_cfg.get("route_mode", "default_fabnet")
        if l3_cfg.get("mode") == "user_octet":
            if route_mode == "default_fabnet":
                default_subnet = l3_cfg.get("default_fabnet_subnet", "10.128.0.0/10")
                if default_subnet:
                    routes.append(default_subnet)
            elif route_mode == "custom":
                routes.extend(l3_cfg.get("custom_routes", []))

        # Write boot config network entries for each assignment
        cidr_prefix = str(network.prefixlen)
        for iface_name, ip_str in assignments.items():
            # Find the node this interface belongs to
            node_name = None
            for iface in net_data.get("interfaces", []):
                if iface["name"] == iface_name:
                    node_name = iface.get("node_name")
                    break
            if not node_name:
                continue

            try:
                fab_node = slice_obj.get_node(name=node_name)
                ud = dict(fab_node.get_user_data())
                bc = ud.get("boot_config", {"uploads": [], "commands": [], "network": []})
                if not isinstance(bc, dict):
                    bc = {"uploads": [], "commands": [], "network": []}

                # Remove any existing entry for this interface
                bc["network"] = [e for e in bc.get("network", [])
                                 if e.get("iface") != iface_name]

                entry: dict[str, Any] = {
                    "id": f"ip-hint-{iface_name}",
                    "iface": iface_name,
                    "mode": "manual",
                    "ip": f"{ip_str}/{cidr_prefix}",
                    "order": 100,
                }
                if routes:
                    entry["routes"] = routes
                bc["network"].append(entry)
                ud["boot_config"] = bc
                fab_node.set_user_data(ud)
            except Exception as ex:
                logger.warning("apply_ip_hints: failed to set boot config for %s/%s: %s",
                               node_name, iface_name, ex)

        return {"network": net_name, "assignments": assignments, "status": "ok"}

    try:
        return await asyncio.to_thread(_do)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- L3 Config for FABNet networks ---

class L3ConfigRequest(BaseModel):
    mode: str = "auto"  # auto | manual | user_octet
    route_mode: str = "default_fabnet"  # default_fabnet | custom
    custom_routes: List[str] = []
    default_fabnet_subnet: str = "10.128.0.0/10"


@router.get("/slices/{slice_name}/networks/{net_name}/l3-config")
def get_l3_config_endpoint(slice_name: str, net_name: str) -> dict[str, Any]:
    """Get L3 config for a FABNet network."""
    slice_name = _resolve_slice_name(slice_name)
    return {"network": net_name, "l3_config": _get_l3_config(slice_name, net_name)}


@router.put("/slices/{slice_name}/networks/{net_name}/l3-config")
def set_l3_config_endpoint(slice_name: str, net_name: str, req: L3ConfigRequest) -> dict[str, Any]:
    """Save L3 config for a FABNet network."""
    slice_name = _resolve_slice_name(slice_name)
    config = {
        "mode": req.mode,
        "route_mode": req.route_mode,
        "custom_routes": req.custom_routes,
        "default_fabnet_subnet": req.default_fabnet_subnet,
    }
    _store_l3_config(slice_name, net_name, config)
    # Re-persist draft if it's a new draft
    if _is_draft(slice_name) and _is_new_draft(slice_name):
        draft = _get_draft(slice_name)
        if draft:
            _persist_draft(slice_name, draft)
    return {"network": net_name, "l3_config": config, "status": "ok"}


# --- Post-boot config ---

@router.put("/slices/{slice_name}/nodes/{node_name}/post-boot")
def set_post_boot_config(slice_name: str, node_name: str, req: PostBootConfigRequest) -> dict[str, Any]:
    """Set a post-boot config script on a node."""
    slice_name = _resolve_slice_name(slice_name)
    try:
        slice_obj = _get_slice_obj(slice_name)
        node = slice_obj.get_node(name=node_name)
        node.add_post_boot_upload_directory(req.script)
        return _serialize(slice_obj, dirty=True)
    except AttributeError:
        # Fallback: use execute() style or set_user_data if available
        try:
            slice_obj = _get_slice_obj(slice_name)
            node = slice_obj.get_node(name=node_name)
            node.set_user_data({"post_boot_script": req.script})
            return _serialize(slice_obj, dirty=True)
        except Exception as e2:
            raise HTTPException(status_code=500, detail=str(e2))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/slices/{slice_name}/post-boot-config")
async def run_post_boot_config(slice_name: str) -> dict[str, Any]:
    """Run FABlib's native post_boot_config() on a submitted slice.

    This configures L3 networking (hostnames, IPs, routes, VLAN interfaces)
    and any other post-boot tasks that FABlib manages internally.
    Should be called after the slice reaches StableOK/Active state.
    """
    slice_name = _resolve_slice_name(slice_name)
    def _do():
        slice_obj = _get_slice_obj(slice_name)
        state = str(slice_obj.get_state()) if slice_obj.get_state() else ""
        if state not in ("StableOK", "Active"):
            logger.warning("post_boot_config: slice '%s' in state '%s', expected StableOK/Active", slice_name, state)
        logger.info("post_boot_config: running on slice '%s' (state=%s)", slice_name, state)
        try:
            slice_obj.post_boot_config()
            logger.info("post_boot_config: completed successfully for '%s'", slice_name)
        except Exception as e:
            logger.error("post_boot_config: failed for '%s': %s", slice_name, e)
            raise
        return _serialize(slice_obj)
    try:
        return await run_in_fablib_pool(_do)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"post_boot_config failed: {e}")


# --- Clone slice ---

@router.post("/slices/{slice_name}/clone")
async def clone_slice(slice_name: str, new_name: str) -> dict[str, Any]:
    """Clone/copy a slice (or draft) as a new draft with a different name."""
    slice_name = _resolve_slice_name(slice_name)
    def _do():
        # --- Export phase: extract blueprint from source slice ---
        logger.info("Clone: exporting source slice '%s' as '%s'", slice_name, new_name)
        slice_obj = _get_slice_obj(slice_name)
        data = slice_to_dict(slice_obj)

        model_data: dict[str, Any] = {
            "format": "fabric-webgui-v1",
            "name": new_name,
            "nodes": [],
            "networks": [],
        }

        src_groups = _get_site_groups(slice_name)

        for node in data.get("nodes", []):
            # Read attributes directly from the FABlib node object for accuracy,
            # falling back to serialized data with safe int defaults.
            fab_node = slice_obj.get_node(name=node["name"])
            def _int_or(val, default):
                try:
                    v = int(val)
                    return v if v > 0 else default
                except (TypeError, ValueError):
                    return default

            cores = _int_or(node.get("cores"), 2)
            ram = _int_or(node.get("ram"), 8)
            disk = _int_or(node.get("disk"), 10)

            # Try to get more accurate values from the FABlib object
            try:
                cores = _int_or(fab_node.get_cores(), cores)
                ram = _int_or(fab_node.get_ram(), ram)
                disk = _int_or(fab_node.get_disk(), disk)
            except Exception:
                pass

            image = node.get("image", "") or "default_ubuntu_22"
            try:
                img = fab_node.get_image()
                if img:
                    image = img
            except Exception:
                pass

            # Use @group reference from source if available, else concrete site
            site = src_groups.get(node["name"], "")
            if not site:
                site = node.get("site", "")
                try:
                    s = fab_node.get_site()
                    if s:
                        site = s
                except Exception:
                    pass

            node_model: dict[str, Any] = {
                "name": node["name"],
                "site": site,
                "cores": cores,
                "ram": ram,
                "disk": disk,
                "image": image,
                "components": [],
            }
            try:
                ud = dict(fab_node.get_user_data())
                bc = ud.get("boot_config")
                if bc and isinstance(bc, dict):
                    node_model["boot_config"] = dict(bc)
                elif ud.get("post_boot_script"):
                    node_model["post_boot_script"] = ud["post_boot_script"]
            except Exception:
                pass
            node_name = node["name"]
            for comp in node.get("components", []):
                comp_name = comp["name"]
                # FABlib prefixes component names with "node_name-"; strip it
                # to avoid duplication when add_component re-adds the prefix.
                prefix = node_name + "-"
                if comp_name.startswith(prefix):
                    comp_name = comp_name[len(prefix):]
                node_model["components"].append({
                    "name": comp_name,
                    "model": comp.get("model", ""),
                })
            model_data["nodes"].append(node_model)

        # Build a map: interface name → (node_name, component_name, port_index)
        # so we can resolve interfaces in the new slice by component, not name.
        iface_key_map: dict[str, tuple[str, str, int]] = {}
        for node in data.get("nodes", []):
            for comp in node.get("components", []):
                for port_idx, iface in enumerate(comp.get("interfaces", [])):
                    iface_key_map[iface["name"]] = (node["name"], comp["name"], port_idx)

        for net in data.get("networks", []):
            # Store interface keys (node, component, port_index) instead of names
            iface_keys = []
            for i in net.get("interfaces", []):
                key = iface_key_map.get(i["name"])
                if key:
                    iface_keys.append(list(key))
                else:
                    logger.warning("Clone: interface '%s' not found in component map", i["name"])
            model_data["networks"].append({
                "name": net["name"],
                "type": net.get("type", "L2Bridge"),
                "interfaces": [],  # not used — resolved via iface_keys
                "iface_keys": iface_keys,
                "subnet": net.get("subnet", ""),
                "gateway": net.get("gateway", ""),
            })

        # --- Import phase: build the new slice directly ---
        logger.info("Clone: creating new draft '%s' with %d nodes, %d networks",
                     new_name, len(model_data["nodes"]), len(model_data["networks"]))
        fablib = get_fablib()

        # Extract @group tags without resolving — defer until user action or submit
        clone_groups: dict[str, str] = {}
        for nd in model_data["nodes"]:
            site = nd.get("site", "")
            if isinstance(site, str) and site.startswith("@"):
                clone_groups[nd["name"]] = site
                nd["site"] = ""  # Leave unset
            elif not site or site == "auto":
                nd["site"] = ""  # Leave unset
            # else: explicit site stays as-is

        new_slice = fablib.new_slice(name=new_name)

        # Add nodes and components
        for node_def in model_data["nodes"]:
            logger.info("Clone node '%s': cores=%r ram=%r disk=%r site=%r image=%r",
                        node_def["name"], node_def.get("cores"), node_def.get("ram"),
                        node_def.get("disk"), node_def.get("site"), node_def.get("image"))
            kwargs: dict[str, Any] = {
                "name": node_def["name"],
                "cores": node_def.get("cores", 2),
                "ram": node_def.get("ram", 8),
                "disk": node_def.get("disk", 10),
                "image": node_def.get("image", "default_ubuntu_22"),
            }
            site = node_def.get("site", "")
            if site and site not in ("auto", ""):
                kwargs["site"] = site
            new_node = new_slice.add_node(**kwargs)

            for comp_def in node_def.get("components", []):
                new_node.add_component(
                    model=comp_def.get("model", "NIC_Basic"),
                    name=comp_def.get("name", ""),
                )

            # Resolve boot configuration from VM template + node-level overrides
            final_bc = None
            vm_tmpl_name = node_def.get("vm_template")
            if vm_tmpl_name:
                vm_tmpl = _resolve_vm_template(vm_tmpl_name)
                if vm_tmpl:
                    vm_bc = vm_tmpl.get("boot_config", {})
                    final_bc = {
                        "uploads": list(vm_bc.get("uploads", [])),
                        "commands": list(vm_bc.get("commands", [])),
                        "network": list(vm_bc.get("network", [])),
                    }
                    if vm_tmpl.get("_tools_source"):
                        final_bc["uploads"].insert(0, {
                            "id": "vm-tools",
                            "source": vm_tmpl["_tools_source"],
                            "dest": "~/tools",
                        })
                    vm_image = vm_tmpl.get("image")
                    if vm_image:
                        new_node.set_image(vm_image)

            node_bc = node_def.get("boot_config")
            if node_bc and isinstance(node_bc, dict):
                if final_bc is None:
                    final_bc = {"uploads": [], "commands": [], "network": []}
                final_bc["uploads"].extend(node_bc.get("uploads", []))
                final_bc["commands"].extend(node_bc.get("commands", []))
                final_bc["network"].extend(node_bc.get("network", []))

            if final_bc:
                try:
                    ud = new_node.get_user_data()
                    ud["boot_config"] = final_bc
                    new_node.set_user_data(ud)
                except Exception:
                    logger.debug("Clone set_user_data failed", exc_info=True)
            else:
                post_boot = node_def.get("post_boot_script", "")
                if post_boot:
                    try:
                        new_node.set_user_data({"post_boot_script": post_boot})
                    except Exception:
                        logger.debug("Clone set_user_data failed", exc_info=True)

        # Add networks — resolve interfaces by (node_name, comp_name, port_index)
        _fabnet_to_l3 = {
            "FABNetv4": "IPv4", "FABNetv6": "IPv6",
            "FABNetv4Ext": "IPv4Ext", "FABNetv6Ext": "IPv6Ext",
        }
        l3_types = {"IPv4", "IPv6", "IPv4Ext", "IPv6Ext", "L3VPN",
                    "FABNetv4", "FABNetv6", "FABNetv4Ext", "FABNetv6Ext"}

        for net_def in model_data["networks"]:
            ifaces = []
            for key in net_def.get("iface_keys", []):
                node_name, comp_name, port_idx = key
                try:
                    n = new_slice.get_node(name=node_name)
                    c = n.get_component(name=comp_name)
                    c_ifaces = c.get_interfaces()
                    if port_idx < len(c_ifaces):
                        ifaces.append(c_ifaces[port_idx])
                    else:
                        logger.warning("Clone: port_idx %d out of range for %s/%s", port_idx, node_name, comp_name)
                except Exception as ex:
                    logger.warning("Clone: could not resolve interface %s/%s[%d]: %s", node_name, comp_name, port_idx, ex)

            net_type = net_def.get("type", "L2Bridge")
            if net_type in l3_types:
                canonical_type = _fabnet_to_l3.get(net_type, net_type)
                net = new_slice.add_l3network(
                    name=net_def["name"], interfaces=ifaces, type=canonical_type
                )
                for iface in ifaces:
                    iface.set_mode("auto")
            else:
                net = new_slice.add_l2network(
                    name=net_def["name"], interfaces=ifaces, type=net_type
                )
                subnet = net_def.get("subnet", "")
                gateway = net_def.get("gateway", "")
                if subnet:
                    net.set_subnet(subnet)
                if gateway:
                    net.set_gateway(gateway)
                ip_mode = net_def.get("ip_mode", "none")
                if ip_mode == "auto" and subnet:
                    for iface in ifaces:
                        iface.set_mode("auto")
                elif ip_mode == "config":
                    iface_ips = net_def.get("interface_ips", {})
                    for iface in ifaces:
                        iname = iface.get_name()
                        if iname in iface_ips:
                            iface.set_mode("config")
                            iface.set_ip_addr(addr=iface_ips[iname])

        _store_draft(new_name, new_slice, is_new=True)
        import uuid as _uuid_mod
        draft_id = f"draft-{_uuid_mod.uuid4()}"
        register_slice(new_name, uuid=draft_id, state="Draft")
        # Store resolved group membership for the clone
        if clone_groups:
            _store_site_groups(new_name, clone_groups)
        # Carry over IP hints from source slice
        src_all_hints = _get_all_ip_hints(slice_name)
        for net_name, net_hints in src_all_hints.items():
            _store_ip_hints(new_name, net_name, net_hints)

        # Persist boot configs to disk so they survive the submit cycle
        from app.routes.files import _save_boot_config
        for node in new_slice.get_nodes():
            try:
                ud = node.get_user_data()
                bc = ud.get("boot_config")
                if bc and isinstance(bc, dict):
                    _save_boot_config(new_name, node.get_name(), bc)
            except Exception:
                logger.debug("Clone boot config copy failed", exc_info=True)

        result = _serialize(new_slice)
        logger.info("Clone: successfully created draft '%s'", new_name)
        return result
    try:
        return await run_in_fablib_pool(_do)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Clone failed for '%s' -> '%s'", slice_name, new_name)
        raise HTTPException(status_code=500, detail=str(e))


# --- Slice export/import ---

def build_slice_model(slice_name: str) -> dict:
    """Build a portable JSON model from a slice (draft or FABRIC).

    Returns a dict with format, name, nodes, and networks suitable
    for serialisation to .fabric.json files.
    """
    slice_obj = _get_slice_obj(slice_name)
    data = slice_to_dict(slice_obj)
    site_groups = _get_site_groups(slice_name)

    model: dict[str, Any] = {
        "format": "fabric-webgui-v1",
        "name": data["name"],
        "nodes": [],
        "networks": [],
    }

    for node in data.get("nodes", []):
        # Export @group reference instead of resolved site if available
        export_site = site_groups.get(node["name"], node.get("site", ""))
        node_model: dict[str, Any] = {
            "name": node["name"],
            "site": export_site,
            "cores": node.get("cores", 2),
            "ram": node.get("ram", 8),
            "disk": node.get("disk", 10),
            "image": node.get("image", "default_ubuntu_22"),
            "components": [],
        }
        # Optional fields — only include when set
        if node.get("host"):
            node_model["host"] = node["host"]
        if node.get("image_type") and node["image_type"] != "qcow2":
            node_model["image_type"] = node["image_type"]
        if node.get("username"):
            node_model["username"] = node["username"]
        if node.get("instance_type"):
            node_model["instance_type"] = node["instance_type"]
        # Export boot config from node user_data
        try:
            fab_node = slice_obj.get_node(name=node["name"])
            ud = dict(fab_node.get_user_data())
            bc = ud.get("boot_config")
            if bc and isinstance(bc, dict):
                node_model["boot_config"] = dict(bc)
            elif ud.get("post_boot_script"):
                node_model["post_boot_script"] = ud["post_boot_script"]
        except Exception:
            pass
        node_name = node["name"]
        for comp in node.get("components", []):
            comp_name = comp["name"]
            prefix = node_name + "-"
            if comp_name.startswith(prefix):
                comp_name = comp_name[len(prefix):]
            comp_model: dict[str, Any] = {
                "name": comp_name,
                "model": comp.get("model", ""),
            }
            # Export per-interface details (vlan, bandwidth, mode)
            ifaces_out = []
            for iface in comp.get("interfaces", []):
                iface_out: dict[str, Any] = {"name": iface["name"]}
                if iface.get("vlan"):
                    iface_out["vlan"] = iface["vlan"]
                if iface.get("bandwidth"):
                    iface_out["bandwidth"] = iface["bandwidth"]
                if iface.get("mode"):
                    iface_out["mode"] = iface["mode"]
                if iface.get("ip_addr"):
                    iface_out["ip_addr"] = iface["ip_addr"]
                if len(iface_out) > 1:  # more than just name
                    ifaces_out.append(iface_out)
            if ifaces_out:
                comp_model["interfaces"] = ifaces_out
            node_model["components"].append(comp_model)
        model["nodes"].append(node_model)

    all_hints = _get_all_ip_hints(slice_name)
    all_l3_configs = _get_all_l3_configs(slice_name)
    for net in data.get("networks", []):
        net_model: dict[str, Any] = {
            "name": net["name"],
            "type": net.get("type", "L2Bridge"),
            "interfaces": [i["name"] for i in net.get("interfaces", [])],
            "subnet": net.get("subnet", ""),
            "gateway": net.get("gateway", ""),
        }
        # Derive ip_mode and interface_ips from interface modes
        ifaces = net.get("interfaces", [])
        modes = [i.get("mode", "") for i in ifaces]
        if all(m == "auto" for m in modes if m):
            net_model["ip_mode"] = "auto"
        elif any(m == "config" for m in modes):
            net_model["ip_mode"] = "config"
            net_model["interface_ips"] = {
                i["name"]: i["ip_addr"] for i in ifaces if i.get("ip_addr")
            }
        # Export IP hints if present
        net_hints = all_hints.get(net["name"])
        if net_hints:
            net_model["ip_hints"] = net_hints
        # Export L3 config if present
        net_l3 = all_l3_configs.get(net["name"])
        if net_l3:
            net_model["l3_config"] = net_l3
        model["networks"].append(net_model)

    # Export facility ports if present
    for fp in data.get("facility_ports", []):
        fp_model: dict[str, Any] = {
            "name": fp["name"],
            "site": fp.get("site", ""),
        }
        if fp.get("vlan"):
            fp_model["vlan"] = fp["vlan"]
        if fp.get("bandwidth"):
            fp_model["bandwidth"] = fp["bandwidth"]
        if fp.get("interfaces"):
            fp_model["interfaces"] = [i["name"] for i in fp["interfaces"]]
        model.setdefault("facility_ports", []).append(fp_model)

    # Export port mirrors if present
    for pm in data.get("port_mirrors", []):
        pm_model: dict[str, Any] = {
            "name": pm["name"],
            "mirror_interface_name": pm.get("mirror_interface_name", ""),
            "receive_interface_name": pm.get("receive_interface_name", ""),
            "mirror_direction": pm.get("mirror_direction", "both"),
        }
        model.setdefault("port_mirrors", []).append(pm_model)

    return model


@router.get("/slices/{slice_name}/export")
def export_slice(slice_name: str):
    """Export a slice definition as a downloadable JSON model file."""
    slice_name = _resolve_slice_name(slice_name)
    try:
        model = build_slice_model(slice_name)
        return JSONResponse(
            content=model,
            headers={
                "Content-Disposition": f'attachment; filename="{model["name"]}.fabric.json"'
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/slices/import")
def import_slice(model: SliceModelImport) -> dict[str, Any]:
    """Import a slice model and create a new draft."""
    try:
        fablib = get_fablib()
        slice_obj = fablib.new_slice(name=model.name)

        # --- Extract @group tags without resolving — defer until user action or submit ---
        node_defs = [dict(nd) for nd in model.nodes]
        node_groups: dict[str, str] = {}
        for nd in node_defs:
            site = nd.get("site", "")
            if isinstance(site, str) and site.startswith("@"):
                node_groups[nd["name"]] = site
                nd["site"] = ""  # Leave unset
            elif not site or site == "auto":
                nd["site"] = ""  # Leave unset
            # else: explicit site stays as-is

        # Add nodes and components
        for node_def in node_defs:
            kwargs: dict[str, Any] = {
                "name": node_def["name"],
                "cores": node_def.get("cores", 2),
                "ram": node_def.get("ram", 8),
                "disk": node_def.get("disk", 10),
                "image": node_def.get("image", "default_ubuntu_22"),
            }
            site = node_def.get("site", "")
            if site and site not in ("auto", ""):
                kwargs["site"] = site
            if node_def.get("host"):
                kwargs["host"] = node_def["host"]
            node = slice_obj.add_node(**kwargs)

            # Optional node-level settings
            if node_def.get("image_type") and node_def["image_type"] != "qcow2":
                node.set_image(node_def["image"], image_type=node_def["image_type"])
            if node_def.get("username"):
                node.set_username(node_def["username"])
            if node_def.get("instance_type"):
                try:
                    node.set_instance_type(node_def["instance_type"])
                except Exception:
                    pass

            for comp_def in node_def.get("components", []):
                node.add_component(
                    model=comp_def.get("model", "NIC_Basic"),
                    name=comp_def.get("name", ""),
                )

            # Resolve boot configuration from VM template + node-level overrides
            final_bc = None
            vm_tmpl_name = node_def.get("vm_template")
            if vm_tmpl_name:
                vm_tmpl = _resolve_vm_template(vm_tmpl_name)
                if vm_tmpl:
                    vm_bc = vm_tmpl.get("boot_config", {})
                    final_bc = {
                        "uploads": list(vm_bc.get("uploads", [])),
                        "commands": list(vm_bc.get("commands", [])),
                        "network": list(vm_bc.get("network", [])),
                    }
                    # Add tools upload if VM template has tools
                    if vm_tmpl.get("_tools_source"):
                        final_bc["uploads"].insert(0, {
                            "id": "vm-tools",
                            "source": vm_tmpl["_tools_source"],
                            "dest": "~/tools",
                        })
                    # Override image from VM template
                    vm_image = vm_tmpl.get("image")
                    if vm_image:
                        node.set_image(vm_image)

            # Merge node-level boot_config additions
            node_bc = node_def.get("boot_config")
            if node_bc and isinstance(node_bc, dict):
                if final_bc is None:
                    final_bc = {"uploads": [], "commands": [], "network": []}
                final_bc["uploads"].extend(node_bc.get("uploads", []))
                final_bc["commands"].extend(node_bc.get("commands", []))
                final_bc["network"].extend(node_bc.get("network", []))

            if final_bc:
                try:
                    ud = node.get_user_data()
                    ud["boot_config"] = final_bc
                    node.set_user_data(ud)
                except Exception:
                    pass
            else:
                # Legacy: apply old post_boot_script format
                post_boot = node_def.get("post_boot_script", "")
                if post_boot:
                    try:
                        node.set_user_data({"post_boot_script": post_boot})
                    except Exception:
                        pass

        # Add networks
        # FABlib serialises L3 types as FABNetv4 etc. but add_l3network
        # only accepts the canonical names (IPv4, IPv6, …).
        _fabnet_to_l3 = {
            "FABNetv4": "IPv4", "FABNetv6": "IPv6",
            "FABNetv4Ext": "IPv4Ext", "FABNetv6Ext": "IPv6Ext",
        }
        l3_types = {"IPv4", "IPv6", "IPv4Ext", "IPv6Ext", "L3VPN",
                    "FABNetv4", "FABNetv6", "FABNetv4Ext", "FABNetv6Ext"}
        for net_def in model.networks:
            # Resolve interfaces by name
            ifaces = []
            for iface_name in net_def.get("interfaces", []):
                for node in slice_obj.get_nodes():
                    for iface in node.get_interfaces():
                        if iface.get_name() == iface_name:
                            ifaces.append(iface)

            net_type = net_def.get("type", "L2Bridge")
            if net_type in l3_types:
                # Map FABNet names to canonical L3 type names
                canonical_type = _fabnet_to_l3.get(net_type, net_type)
                net = slice_obj.add_l3network(
                    name=net_def["name"], interfaces=ifaces, type=canonical_type
                )
                for iface in ifaces:
                    iface.set_mode("auto")
            else:
                net = slice_obj.add_l2network(
                    name=net_def["name"], interfaces=ifaces, type=net_type
                )
                subnet = net_def.get("subnet", "")
                gateway = net_def.get("gateway", "")
                if subnet:
                    net.set_subnet(subnet)
                if gateway:
                    net.set_gateway(gateway)

                ip_mode = net_def.get("ip_mode", "none")
                if ip_mode == "auto" and subnet:
                    for iface in ifaces:
                        iface.set_mode("auto")
                elif ip_mode == "config":
                    iface_ips = net_def.get("interface_ips", {})
                    for iface in ifaces:
                        iname = iface.get_name()
                        if iname in iface_ips:
                            iface.set_mode("config")
                            iface.set_ip_addr(addr=iface_ips[iname])

        # Add port mirrors if present
        for pm_def in (model.port_mirrors if hasattr(model, 'port_mirrors') else []):
            try:
                # Resolve receive interface
                recv_iface = None
                recv_name = pm_def.get("receive_interface_name", "")
                for node in slice_obj.get_nodes():
                    for iface in node.get_interfaces():
                        if iface.get_name() == recv_name:
                            recv_iface = iface
                            break
                    if recv_iface:
                        break
                if recv_iface:
                    slice_obj.add_port_mirror_service(
                        name=pm_def["name"],
                        mirror_interface_name=pm_def.get("mirror_interface_name", ""),
                        receive_interface=recv_iface,
                        mirror_direction=pm_def.get("mirror_direction", "both"),
                    )
            except Exception as ex:
                logger.warning("Import: could not add port mirror %s: %s", pm_def.get("name", "?"), ex)

        # Add facility ports if present
        for fp_def in model.facility_ports:
            fp_kwargs: dict[str, Any] = {
                "name": fp_def["name"],
                "site": fp_def.get("site", ""),
            }
            if fp_def.get("vlan"):
                fp_kwargs["vlan"] = fp_def["vlan"]
            if fp_def.get("bandwidth"):
                fp_kwargs["bandwidth"] = fp_def["bandwidth"]
            try:
                slice_obj.add_facility_port(**fp_kwargs)
            except Exception as ex:
                logger.warning("Import: could not add facility port %s: %s", fp_def["name"], ex)

        _store_draft(model.name, slice_obj, is_new=True)
        import uuid as _uuid_mod
        draft_id = f"draft-{_uuid_mod.uuid4()}"
        register_slice(model.name, uuid=draft_id, state="Draft")
        if node_groups:
            _store_site_groups(model.name, node_groups)
        # Restore IP hints from imported model
        for net_def in model.networks:
            net_hints = net_def.get("ip_hints")
            if net_hints and isinstance(net_hints, dict):
                _store_ip_hints(model.name, net_def["name"], net_hints)
            # Restore L3 config from imported model
            net_l3 = net_def.get("l3_config")
            if net_l3 and isinstance(net_l3, dict):
                _store_l3_config(model.name, net_def["name"], net_l3)

        # Persist boot configs to disk so they survive the submit cycle
        # (FABlib user_data may not round-trip through FABRIC control framework)
        from app.routes.files import _save_boot_config
        for node in slice_obj.get_nodes():
            try:
                ud = node.get_user_data()
                bc = ud.get("boot_config")
                if bc and isinstance(bc, dict):
                    _save_boot_config(model.name, node.get_name(), bc)
            except Exception:
                pass

        return _serialize(slice_obj)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Save/Open to container storage ---

@router.post("/slices/{slice_name}/save-to-storage")
def save_to_storage(slice_name: str):
    """Export a slice definition and save it to container storage."""
    slice_name = _resolve_slice_name(slice_name)
    import json as _json
    try:
        # Reuse export logic
        resp = export_slice(slice_name)
        model = resp.body
        if isinstance(model, bytes):
            model = _json.loads(model)

        storage_dir = get_user_storage()
        os.makedirs(storage_dir, exist_ok=True)
        filename = f"{slice_name}.fabric.json"
        path = os.path.join(storage_dir, filename)
        with open(path, "w") as f:
            _json.dump(model, f, indent=2)
        return {"status": "ok", "path": filename}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/slices/storage-files")
def list_storage_files():
    """List .fabric.json files in container storage."""
    storage_dir = get_user_storage()
    if not os.path.isdir(storage_dir):
        return []
    files = []
    for name in sorted(os.listdir(storage_dir)):
        if name.endswith(".fabric.json"):
            full = os.path.join(storage_dir, name)
            if os.path.isfile(full):
                st = os.stat(full)
                files.append({
                    "name": name,
                    "size": st.st_size,
                    "modified": st.st_mtime,
                })
    return files


@router.post("/slices/open-from-storage")
def open_from_storage(body: dict):
    """Read a .fabric.json file from storage and import it."""
    import json as _json
    filename = body.get("filename", "")
    if not filename:
        raise HTTPException(status_code=400, detail="filename required")

    storage_dir = get_user_storage()
    path = os.path.realpath(os.path.join(storage_dir, filename))
    if not path.startswith(os.path.realpath(storage_dir)):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found")

    with open(path) as f:
        model_data = _json.load(f)

    model = SliceModelImport(**model_data)
    return import_slice(model)
