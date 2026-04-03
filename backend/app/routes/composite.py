"""Composite Slice API — meta-slice reference model.

A composite slice is a lightweight grouping that references existing FABRIC
and Chameleon slices. It has no resources of its own. The composite graph is
built by merging member slice graphs.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, HTTPException

from app.user_context import get_user_storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/composite", tags=["composite"])

# ---------------------------------------------------------------------------
# In-memory composite slice store (persisted to JSON)
# ---------------------------------------------------------------------------

_composite_slices: dict[str, dict] = {}  # id → composite slice dict


def _storage_path() -> str:
    storage = get_user_storage()
    return os.path.join(storage, ".loomai", "composite_slices.json")


def _persist() -> None:
    path = _storage_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(list(_composite_slices.values()), f, indent=2)


def _new_composite_slice(name: str) -> dict[str, Any]:
    """Create a new empty composite slice dict."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": f"comp-{uuid.uuid4().hex[:12]}",
        "name": name,
        "state": "Draft",
        "created": now,
        "updated": now,
        "fabric_slices": [],
        "chameleon_slices": [],
        "cross_connections": [],
    }


def _touch(s: dict) -> None:
    s["updated"] = datetime.now(timezone.utc).isoformat()


def _migrate_old_format(s: dict) -> tuple[dict, bool]:
    """Convert old independent-resource format to meta-slice reference format."""
    old_keys = {"fabric_nodes", "chameleon_nodes", "fabric_networks", "chameleon_networks"}
    if old_keys & set(s.keys()):
        for k in old_keys:
            s.pop(k, None)
        s.setdefault("fabric_slices", [])
        s.setdefault("chameleon_slices", [])
        s.setdefault("cross_connections", [])
        return s, True
    s.setdefault("fabric_slices", [])
    s.setdefault("chameleon_slices", [])
    s.setdefault("cross_connections", [])
    return s, False


def load_composite_slices() -> None:
    """Load composite slices from disk (called at startup)."""
    path = _storage_path()
    if not os.path.exists(path):
        return
    try:
        with open(path) as f:
            data = json.load(f)
        any_migrated = False
        for s in data:
            s, migrated = _migrate_old_format(s)
            any_migrated = any_migrated or migrated
            _composite_slices[s["id"]] = s
        if any_migrated:
            _persist()
            logger.info("Migrated %d composite slices to reference model", len(_composite_slices))
        else:
            logger.info("Loaded %d composite slices", len(_composite_slices))
    except Exception as e:
        logger.warning("Failed to load composite slices: %s", e)


# ---------------------------------------------------------------------------
# Helpers for member lookups
# ---------------------------------------------------------------------------


def _resolve_fabric_ref(slice_id: str) -> str:
    """Resolve a FABRIC slice reference to a name, handling stale draft IDs.

    After composite submit, the fabric_slices array may contain a FABRIC UUID
    that replaced the old draft-XXXX.  But if replacement failed, the array
    still has the old draft-XXXX which is no longer in the registry.  In that
    case, try all registered slices to find one whose name matches.
    """
    from app.routes.slices import _resolve_slice_name
    name = _resolve_slice_name(slice_id)
    # If _resolve_slice_name returned the input unchanged AND it looks like a
    # draft ID, the registry entry was replaced.  The slice likely exists under
    # its original name with a new UUID.  Search the registry for it.
    if name == slice_id and slice_id.startswith("draft-"):
        from app.slice_registry import _load as _load_registry
        try:
            reg = _load_registry()
            # Look for a slice entry whose old_draft_id matches
            for sname, entry in reg.get("slices", {}).items():
                if entry.get("old_draft_id") == slice_id:
                    logger.info("Resolved stale draft ID %s → name '%s'", slice_id, sname)
                    return sname
        except Exception:
            pass
        logger.warning("Cannot resolve stale draft ID %s — slice may have been submitted", slice_id)
    return name


def _get_fabric_slice_summary(slice_id: str) -> dict | None:
    """Get a short summary of a FABRIC slice by UUID, draft-UUID, or name."""
    try:
        from app.routes.slices import _is_draft, _get_draft, _serialize
        name = _resolve_fabric_ref(slice_id)
        # Check drafts first
        if _is_draft(name):
            draft = _get_draft(name)
            if draft:
                data = _serialize(draft)
                return {
                    "id": data.get("id", slice_id),
                    "name": data.get("name", name),
                    "state": data.get("state", "Draft"),
                    "node_count": len(data.get("nodes", [])),
                }
        # Check call manager cache for submitted slices
        from app.fabric_call_manager import get_call_manager
        cm = get_call_manager()
        _cache_entry = cm._cache.get(f"slice:{name}")
        cached = _cache_entry.data if _cache_entry and _cache_entry.data else None
        if cached:
            return {
                "id": cached.get("id", slice_id),
                "name": cached.get("name", name),
                "state": cached.get("state", "Unknown"),
                "node_count": len(cached.get("nodes", [])),
            }
        # Try fetching state from the slice registry
        from app.slice_registry import get_slice_uuid as _get_uuid, _load as _load_reg
        try:
            reg = _load_reg()
            entry = reg.get("slices", {}).get(name)
            if entry:
                return {"id": entry.get("uuid", slice_id), "name": name,
                        "state": entry.get("state", "Unknown"), "node_count": 0}
        except Exception:
            pass
        return {"id": slice_id, "name": name, "state": "Unknown", "node_count": 0}
    except Exception:
        return None


def _compute_chameleon_real_state(chi: dict) -> str:
    """Compute the real state of a Chameleon slice from its resource statuses.

    The raw ``state`` field can be stale (set to "Active" when deploy starts
    but instances are still in BUILD).  This function checks actual resource
    statuses to determine the true state.
    """
    resources = chi.get("resources", [])
    if not resources:
        return chi.get("state", "Configuring") or "Configuring"

    instances = [r for r in resources if r.get("type") == "instance"]
    leases = [r for r in resources if r.get("type") == "lease"]

    # Check for errors first
    if any(r.get("status") == "ERROR" for r in resources):
        return "Error"

    # If there are instances, derive state from them
    if instances:
        statuses = [i.get("status", "") for i in instances]
        if all(s == "ACTIVE" for s in statuses):
            return "Active"
        if any(s in ("BUILD", "PENDING", "SPAWNING") for s in statuses):
            return "Deploying"
        if any(s in ("SHUTOFF", "SUSPENDED") for s in statuses):
            return "Stopped"
        if all(s in ("DELETED",) for s in statuses):
            return "Terminated"

    # If there are leases but no instances yet, derive from lease status
    if leases and not instances:
        lease_statuses = [l.get("status", "") for l in leases]
        if any(s == "PENDING" for s in lease_statuses):
            return "Deploying"
        if all(s == "ACTIVE" for s in lease_statuses):
            return "Deploying"  # Lease active but no instances yet

    return chi.get("state", "Unknown")


def _get_chameleon_slice_summary(slice_id: str) -> dict | None:
    """Get a short summary of a Chameleon slice by ID."""
    try:
        from app.routes.chameleon import _chameleon_slices
        chi = _chameleon_slices.get(slice_id)
        if not chi:
            return None
        return {
            "id": chi["id"],
            "name": chi.get("name", ""),
            "state": _compute_chameleon_real_state(chi),
            "site": chi.get("site", ""),
            "node_count": len(chi.get("nodes", [])) + len(chi.get("resources", [])),
        }
    except Exception:
        return None


def _validate_fabric_ref(slice_id: str) -> bool:
    """Check if a FABRIC slice reference is valid (including drafts)."""
    try:
        from app.routes.slices import _resolve_slice_name, _is_draft
        name = _resolve_slice_name(slice_id)
        if _is_draft(name):
            return True
        from app.slice_registry import get_slice_uuid
        return bool(get_slice_uuid(name)) or name == slice_id
    except Exception:
        return False


def _validate_chameleon_ref(slice_id: str) -> bool:
    """Check if a Chameleon slice reference is valid."""
    try:
        from app.routes.chameleon import _chameleon_slices
        return slice_id in _chameleon_slices
    except Exception:
        return False


def _compute_composite_state(s: dict) -> str:
    """Derive composite state from member states."""
    if not s.get("fabric_slices") and not s.get("chameleon_slices"):
        return "Draft"

    states = []
    for fid in s.get("fabric_slices", []):
        summary = _get_fabric_slice_summary(fid)
        if summary:
            states.append(summary.get("state", "Unknown"))
    for cid in s.get("chameleon_slices", []):
        summary = _get_chameleon_slice_summary(cid)
        if summary:
            states.append(summary.get("state", "Unknown"))

    if not states:
        return "Draft"

    error_states = {"StableError", "Error", "Terminated", "Dead", "Closing"}
    transitional = {"Configuring", "Nascent", "Modifying", "ModifyOK", "ModifyError",
                    "Deploying", "BUILD", "Submitted"}
    active_states = {"StableOK", "Active", "ACTIVE"}

    if any(st in error_states for st in states):
        return "Degraded"
    if any(st in transitional for st in states):
        return "Provisioning"
    if all(st in active_states for st in states):
        return "Active"
    return "Draft"


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------


@router.get("/slices")
async def list_composite_slices() -> list[dict]:
    """List all composite slices."""
    return list(_composite_slices.values())


@router.get("/slices/{slice_id}")
async def get_composite_slice(slice_id: str) -> dict:
    """Get a composite slice with member summaries."""
    s = _composite_slices.get(slice_id)
    if not s:
        raise HTTPException(404, "Composite slice not found")

    result = {**s}
    result["fabric_member_summaries"] = [
        summary for fid in s.get("fabric_slices", [])
        if (summary := _get_fabric_slice_summary(fid)) is not None
    ]
    result["chameleon_member_summaries"] = [
        summary for cid in s.get("chameleon_slices", [])
        if (summary := _get_chameleon_slice_summary(cid)) is not None
    ]
    result["state"] = _compute_composite_state(s)
    return result


@router.post("/slices")
async def create_composite_slice(body: dict = Body(...)) -> dict:
    """Create a new composite slice.

    Body: {"name": "my-experiment"}
    """
    name = body.get("name", "composite-slice")
    s = _new_composite_slice(name)
    _composite_slices[s["id"]] = s
    _persist()
    return s


@router.delete("/slices/{slice_id}")
async def delete_composite_slice(slice_id: str) -> dict:
    """Delete a composite slice (grouping only — member slices are not affected)."""
    if slice_id not in _composite_slices:
        raise HTTPException(404, "Composite slice not found")
    del _composite_slices[slice_id]
    _persist()
    return {"status": "deleted", "id": slice_id}


# ---------------------------------------------------------------------------
# Member management
# ---------------------------------------------------------------------------


@router.put("/slices/{slice_id}/members")
async def update_composite_members(slice_id: str, body: dict = Body(...)) -> dict:
    """Update the member slices of a composite.

    Body: {"fabric_slices": ["uuid1", ...], "chameleon_slices": ["chi-slice-xxx", ...]}
    Replaces the current member lists entirely.
    """
    s = _composite_slices.get(slice_id)
    if not s:
        raise HTTPException(404, "Composite slice not found")

    fabric_refs = body.get("fabric_slices", [])
    chameleon_refs = body.get("chameleon_slices", [])

    invalid = []
    for fid in fabric_refs:
        if not _validate_fabric_ref(fid):
            invalid.append(f"FABRIC: {fid}")
    for cid in chameleon_refs:
        if not _validate_chameleon_ref(cid):
            invalid.append(f"Chameleon: {cid}")

    if invalid:
        raise HTTPException(400, f"Invalid member references: {', '.join(invalid)}")

    s["fabric_slices"] = fabric_refs
    s["chameleon_slices"] = chameleon_refs
    _touch(s)
    _persist()
    return s


@router.post("/replace-fabric-member")
async def replace_fabric_member(body: dict = Body(...)) -> dict:
    """Replace a FABRIC member ID across all composite slices.

    Called when a FABRIC draft is submitted and gets a new UUID.
    Body: {"old_id": "draft-xxx", "new_id": "fabric-uuid"}
    """
    old_id = body.get("old_id", "")
    new_id = body.get("new_id", "")
    if not old_id or not new_id:
        raise HTTPException(400, "old_id and new_id required")

    updated_count = 0
    for s in _composite_slices.values():
        fab = s.get("fabric_slices", [])
        if old_id in fab:
            s["fabric_slices"] = [new_id if fid == old_id else fid for fid in fab]
            # Also update cross_connections
            for conn in s.get("cross_connections", []):
                if conn.get("fabric_slice") == old_id:
                    conn["fabric_slice"] = new_id
            _touch(s)
            updated_count += 1
    if updated_count > 0:
        _persist()
    return {"updated": updated_count, "old_id": old_id, "new_id": new_id}


@router.put("/slices/{slice_id}/cross-connections")
async def update_cross_connections(slice_id: str, body: list = Body(...)) -> dict:
    """Update cross-testbed connections for a composite slice.

    Body: [{"type": "fabnetv4", "fabric_slice": "id", "fabric_node": "name",
            "chameleon_slice": "id", "chameleon_node": "name"}, ...]
    """
    s = _composite_slices.get(slice_id)
    if not s:
        raise HTTPException(404, "Composite slice not found")
    s["cross_connections"] = body
    _touch(s)
    _persist()
    return s


# ---------------------------------------------------------------------------
# Topology graph — merged from member slices
# ---------------------------------------------------------------------------


@router.get("/slices/{slice_id}/graph")
async def get_composite_graph(slice_id: str) -> dict:
    """Build a merged topology graph from all member slices.

    Fetches each member's graph and merges them with ID prefixing,
    compound parent nodes (bounding boxes), and FABNetv4 deduplication.
    """
    s = _composite_slices.get(slice_id)
    if not s:
        raise HTTPException(404, "Composite slice not found")

    from app.graph_builder import build_composite_graph

    # Gather FABRIC member data
    fabric_members: list[tuple[dict, str]] = []
    for fid in s.get("fabric_slices", []):
        try:
            from app.routes.slices import _is_draft, _get_draft, _serialize
            name = _resolve_fabric_ref(fid)
            slice_data = None
            # Check drafts first
            if _is_draft(name):
                draft = _get_draft(name)
                if draft:
                    slice_data = _serialize(draft)
            # Fall back to call manager cache for submitted slices
            if not slice_data:
                from app.fabric_call_manager import get_call_manager
                cm = get_call_manager()
                _entry = cm._cache.get(f"slice:{name}")
                slice_data = _entry.data if _entry and _entry.data else None
            # If still no data (e.g. slice is Configuring and not yet cached),
            # fetch live from FABlib — use max_age=0 so we get fresh state
            if not slice_data:
                try:
                    from app.routes.slices import get_slice
                    slice_data = await get_slice(fid, max_age=0)
                except Exception:
                    # Also try by name if ID lookup failed
                    try:
                        slice_data = await get_slice(name, max_age=0)
                    except Exception:
                        pass
            if slice_data:
                fabric_members.append((slice_data, fid))
            else:
                logger.warning("FABRIC slice %s (name=%s) not available for composite graph", fid, name)
        except Exception:
            logger.warning("Could not fetch FABRIC slice %s for composite graph", fid)

    # Gather Chameleon member data
    chameleon_members: list[tuple[dict, str]] = []
    for cid in s.get("chameleon_slices", []):
        try:
            from app.routes.chameleon import _chameleon_slices
            chi = _chameleon_slices.get(cid)
            if chi:
                chameleon_members.append((chi, cid))
        except Exception:
            logger.warning("Could not fetch Chameleon slice %s for composite graph", cid)

    return build_composite_graph(
        fabric_members=fabric_members,
        chameleon_members=chameleon_members,
        cross_connections=s.get("cross_connections"),
    )


# ---------------------------------------------------------------------------
# Submit — deploy un-deployed member slices in parallel
# ---------------------------------------------------------------------------


@router.post("/slices/{slice_id}/submit")
async def submit_composite_slice(slice_id: str, body: dict = Body(default={})) -> dict:
    """Submit a composite slice — deploys all un-deployed member slices in parallel."""
    s = _composite_slices.get(slice_id)
    if not s:
        raise HTTPException(404, "Composite slice not found")

    fabric_refs = s.get("fabric_slices", [])
    chameleon_refs = s.get("chameleon_slices", [])

    if not fabric_refs and not chameleon_refs:
        raise HTTPException(400, "Composite slice has no members to submit")

    results: dict[str, Any] = {"composite_id": slice_id}

    async def _submit_fabric_member(fid: str) -> dict:
        try:
            from app.slice_registry import resolve_slice_name, get_slice_uuid
            name = resolve_slice_name(fid)
            logger.info("Composite submit: FABRIC member fid=%s resolved to name=%s", fid, name)
            from app.routes.slices import submit_slice
            result = await submit_slice(name)
            new_id = result.get("id", "")
            # If the result ID is missing or is a name (not UUID), try the registry
            if not new_id or new_id == name:
                reg_uuid = get_slice_uuid(name)
                if reg_uuid:
                    new_id = reg_uuid
                    logger.info("Composite submit: used registry UUID for %s: %s", name, new_id)
            if not new_id:
                new_id = fid  # fallback to old ID
            logger.info("Composite submit: FABRIC %s (fid=%s) → new_id=%s, state=%s",
                        name, fid, new_id, result.get("state", ""))

            # Cache the submit result so the composite graph can find this slice
            # immediately (before FABlib's next poll makes it available via get_slice).
            try:
                import time as _time
                from app.fabric_call_manager import get_call_manager, CacheEntry
                cm = get_call_manager()
                entry = CacheEntry()
                entry.data = result
                entry.timestamp = _time.time()
                cm._cache[f"slice:{name}"] = entry
                logger.info("Composite submit: cached slice data for '%s'", name)
            except Exception:
                pass

            return {"id": fid, "new_id": new_id, "name": name, "status": "submitted", "state": result.get("state", "")}
        except HTTPException as e:
            logger.warning("Composite submit: FABRIC %s failed: %s", fid, e.detail)
            return {"id": fid, "status": "error", "error": e.detail}
        except Exception as e:
            logger.warning("Composite submit: FABRIC %s exception: %s", fid, e)
            return {"id": fid, "status": "error", "error": str(e)}

    async def _submit_chameleon_member(cid: str) -> dict:
        try:
            from app.routes.chameleon import _chameleon_slices
            chi = _chameleon_slices.get(cid)
            if not chi:
                return {"id": cid, "status": "error", "error": "Slice not found"}
            if chi.get("state") in ("Active", "Deploying"):
                return {"id": cid, "status": "skipped", "reason": f"Already {chi['state']}"}
            # Trigger full deploy via the Chameleon deploy endpoint
            # (lease creation + wait ACTIVE + launch instances)
            from app.routes.chameleon import deploy_draft
            deploy_body = {**body, "full_deploy": True}
            result = await deploy_draft(cid, deploy_body)
            return {"id": cid, "status": "submitted", "result": result}
        except HTTPException as e:
            return {"id": cid, "status": "error", "error": e.detail}
        except Exception as e:
            return {"id": cid, "status": "error", "error": str(e)}

    # Run all submissions in parallel
    tasks = []
    for fid in fabric_refs:
        tasks.append(_submit_fabric_member(fid))
    for cid in chameleon_refs:
        tasks.append(_submit_chameleon_member(cid))

    all_results = await asyncio.gather(*tasks, return_exceptions=True)

    fabric_results = []
    chameleon_results = []
    idx = 0
    for fid in fabric_refs:
        r = all_results[idx]
        fabric_results.append(r if not isinstance(r, Exception) else {"id": fid, "status": "error", "error": str(r)})
        idx += 1
    for cid in chameleon_refs:
        r = all_results[idx]
        chameleon_results.append(r if not isinstance(r, Exception) else {"id": cid, "status": "error", "error": str(r)})
        idx += 1

    results["fabric_results"] = fabric_results
    results["chameleon_results"] = chameleon_results

    # Auto-replace draft IDs with real FABRIC UUIDs in the composite member list
    # so subsequent graph fetches can find the submitted slices.
    for fr in fabric_results:
        new_id = fr.get("new_id")
        old_id = fr.get("id")
        fab_name = fr.get("name", "")

        if fr.get("status") == "submitted":
            if new_id and old_id and new_id != old_id:
                s["fabric_slices"] = [new_id if fid == old_id else fid for fid in s["fabric_slices"]]
                # Also update cross_connections
                for conn in s.get("cross_connections", []):
                    if conn.get("fabric_slice") == old_id:
                        conn["fabric_slice"] = new_id
                logger.info("Composite %s: replaced FABRIC member %s → %s", slice_id, old_id, new_id)

                # Record the old draft ID in the registry so the composite graph
                # can still resolve it if subsequent code references the old ID.
                if old_id.startswith("draft-") and fab_name:
                    try:
                        from app.slice_registry import _load as _load_reg, _save as _save_reg
                        reg = _load_reg()
                        entry = reg.get("slices", {}).get(fab_name)
                        if entry:
                            entry["old_draft_id"] = old_id
                            _save_reg(reg)
                    except Exception:
                        pass
            elif new_id == old_id:
                logger.warning("Composite %s: FABRIC member %s submitted but ID unchanged (name=%s)", slice_id, old_id, fab_name)
            else:
                logger.warning("Composite %s: FABRIC member %s submitted but no new ID (name=%s)", slice_id, old_id, fab_name)

    s["state"] = "Provisioning"
    _touch(s)
    _persist()

    return results
