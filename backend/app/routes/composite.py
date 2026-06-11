"""Composite/Federated Slice API — cross-testbed reference model.

Federated slice is the forward product name.  The existing composite API,
storage file, and code symbols remain as compatibility aliases while callers
migrate to /api/federated.
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
federated_router = APIRouter(prefix="/api/federated", tags=["federated"])

# ---------------------------------------------------------------------------
# In-memory composite slice store (persisted to JSON)
# ---------------------------------------------------------------------------

_composite_slices: dict[str, dict] = {}  # id → composite slice dict


def _storage_path() -> str:
    storage = get_user_storage()
    return os.path.join(storage, ".loomai", "composite_slices.json")


def _federated_storage_path() -> str:
    storage = get_user_storage()
    return os.path.join(storage, ".loomai", "federated_slices.json")


def _persist() -> None:
    data = list(_composite_slices.values())
    for path in (_storage_path(), _federated_storage_path()):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)


def _new_composite_slice(name: str, *, id_prefix: str = "comp", kind: str = "composite") -> dict[str, Any]:
    """Create a new empty composite/federated slice dict."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": f"{id_prefix}-{uuid.uuid4().hex[:12]}",
        "name": name,
        "kind": kind,
        "state": "Draft",
        "created": now,
        "updated": now,
        "fabric_slices": [],
        "chameleon_slices": [],
        "members": [],
        "cross_connections": [],
    }


def _touch(s: dict) -> None:
    s["updated"] = datetime.now(timezone.utc).isoformat()


def _migrate_old_format(s: dict) -> tuple[dict, bool]:
    """Convert old independent-resource format to meta-slice reference format."""
    changed = False
    old_keys = {"fabric_nodes", "chameleon_nodes", "fabric_networks", "chameleon_networks"}
    if old_keys & set(s.keys()):
        for k in old_keys:
            s.pop(k, None)
        s.setdefault("fabric_slices", [])
        s.setdefault("chameleon_slices", [])
        s.setdefault("cross_connections", [])
        changed = True
    s.setdefault("fabric_slices", [])
    s.setdefault("chameleon_slices", [])
    s.setdefault("cross_connections", [])
    if "kind" not in s:
        s["kind"] = "federated" if str(s.get("id", "")).startswith("fed-") else "composite"
        changed = True
    members = _normalize_members(s)
    if s.get("members") != members:
        s["members"] = members
        changed = True
    _sync_legacy_member_fields(s)
    return s, changed


def _normalize_member(member: dict) -> dict[str, Any]:
    provider = str(member.get("provider", "")).lower()
    slice_id = member.get("slice_id") or member.get("id") or member.get("resource_id") or ""
    if not provider or not slice_id:
        raise HTTPException(400, "Federated members require provider and slice_id")
    normalized = {
        "provider": provider,
        "slice_id": slice_id,
    }
    for key in (
        "name", "role", "state", "testbed", "resource_ids", "site",
        "endpoint_type", "interface", "interface_id", "network",
        "network_id", "network_name", "metadata",
    ):
        if key in member and member.get(key) is not None:
            normalized[key] = member[key]
    return normalized


def _normalize_members(s: dict) -> list[dict[str, Any]]:
    """Return canonical provider-member records from generic + legacy fields."""
    members: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def _add(member: dict) -> None:
        normalized = _normalize_member(member)
        key = (normalized["provider"], normalized["slice_id"])
        if key not in seen:
            seen.add(key)
            members.append(normalized)

    for member in s.get("members", []) or []:
        _add(member)
    for fid in s.get("fabric_slices", []) or []:
        _add({"provider": "fabric", "slice_id": fid})
    for cid in s.get("chameleon_slices", []) or []:
        _add({"provider": "chameleon", "slice_id": cid})
    return members


def _sync_legacy_member_fields(s: dict) -> None:
    """Keep legacy arrays in sync with generic members for old clients."""
    members = _normalize_members(s)
    s["members"] = members
    s["fabric_slices"] = [m["slice_id"] for m in members if m["provider"] == "fabric"]
    s["chameleon_slices"] = [m["slice_id"] for m in members if m["provider"] == "chameleon"]


def load_composite_slices() -> None:
    """Load composite slices from disk (called at startup)."""
    paths = [_federated_storage_path(), _storage_path()]
    existing_paths = [p for p in paths if os.path.exists(p)]
    if not existing_paths:
        return
    try:
        data: list[dict] = []
        seen_ids: set[str] = set()
        for path in existing_paths:
            with open(path) as f:
                loaded = json.load(f)
            for s in loaded if isinstance(loaded, list) else []:
                sid = s.get("id")
                if sid and sid not in seen_ids:
                    seen_ids.add(sid)
                    data.append(s)
        any_migrated = False
        for s in data:
            s, migrated = _migrate_old_format(s)
            any_migrated = any_migrated or migrated
            _composite_slices[s["id"]] = s
        if any_migrated:
            _persist()
            logger.info("Migrated %d federated/composite slices to reference model", len(_composite_slices))
        else:
            logger.info("Loaded %d federated/composite slices", len(_composite_slices))
    except Exception as e:
        logger.warning("Failed to load federated/composite slices: %s", e)


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
        # Prefer lightweight sliver polling cache when present. It is fresher
        # than the full slice cache during provisioning and carries the state
        # transitions that federated polling needs.
        from app.fabric_call_manager import get_call_manager
        cm = get_call_manager()
        _sliver_entry = cm._cache.get(f"slice:{name}:slivers")
        sliver_cached = _sliver_entry.data if _sliver_entry and _sliver_entry.data else None
        if sliver_cached:
            return {
                "id": slice_id,
                "name": sliver_cached.get("slice_name", name),
                "state": sliver_cached.get("slice_state", "Unknown"),
                "node_count": len(sliver_cached.get("nodes", [])),
            }
        # Check call manager cache for submitted slices
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


async def _get_live_fabric_slice_summary(slice_id: str) -> dict | None:
    """Get a FABRIC member summary using live sliver state when available."""
    summary = _get_fabric_slice_summary(slice_id)
    if summary and summary.get("state") == "Draft":
        return summary
    try:
        from app.fablib_executor import run_in_fablib_pool
        from app.routes.slices import _fetch_sliver_states
        name = _resolve_fabric_ref(slice_id)
        sliver_data = await run_in_fablib_pool(lambda: _fetch_sliver_states(name))
        return {
            "id": (summary or {}).get("id", slice_id),
            "name": sliver_data.get("slice_name") or (summary or {}).get("name", name),
            "state": sliver_data.get("slice_state") or (summary or {}).get("state", "Unknown"),
            "node_count": len(sliver_data.get("nodes", [])) or (summary or {}).get("node_count", 0),
        }
    except Exception as exc:
        logger.debug("Could not refresh live FABRIC member %s: %s", slice_id, exc)
        return summary


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


def _validate_member_ref(member: dict) -> bool:
    provider = member.get("provider")
    slice_id = member.get("slice_id")
    if provider == "fabric":
        return _validate_fabric_ref(slice_id)
    if provider == "chameleon":
        return _validate_chameleon_ref(slice_id)
    # Future testbeds can be attached as opaque provider members until a
    # provider-specific validator/graph renderer exists.
    return bool(provider and slice_id)


def _compute_composite_state_from_states(states: list[str]) -> str:
    """Derive composite state from provider member states."""
    if not states:
        return "Draft"

    error_states = {"StableError", "Error", "Terminated", "Dead", "Closing"}
    transitional = {"Configuring", "Nascent", "Modifying", "ModifyOK", "ModifyError",
                    "Deploying", "BUILD", "PENDING", "SPAWNING", "Submitted"}
    active_states = {"StableOK", "Active", "ACTIVE"}

    if any(st in error_states for st in states):
        return "Degraded"
    if any(st in transitional for st in states):
        return "Provisioning"
    if all(st in active_states for st in states):
        return "Active"
    return "Draft"


def _compute_composite_state_from_summaries(
    fabric_member_summaries: list[dict[str, Any]],
    chameleon_member_summaries: list[dict[str, Any]],
) -> str:
    states = [
        str(summary.get("state", "Unknown"))
        for summary in [*fabric_member_summaries, *chameleon_member_summaries]
        if summary
    ]
    return _compute_composite_state_from_states(states)


def _compute_composite_state(s: dict) -> str:
    """Derive composite state from member states."""
    if not s.get("fabric_slices") and not s.get("chameleon_slices"):
        return "Draft"

    fabric_member_summaries = [
        summary for fid in s.get("fabric_slices", [])
        if (summary := _get_fabric_slice_summary(fid))
    ]
    chameleon_member_summaries = [
        summary for cid in s.get("chameleon_slices", [])
        if (summary := _get_chameleon_slice_summary(cid))
    ]
    return _compute_composite_state_from_summaries(
        fabric_member_summaries,
        chameleon_member_summaries,
    )


def _summary_matches_member(summary: dict[str, Any], member: dict[str, Any]) -> bool:
    member_values = {
        str(member.get("slice_id", "")),
        str(member.get("id", "")),
        str(member.get("name", "")),
    } - {""}
    summary_values = {
        str(summary.get("id", "")),
        str(summary.get("slice_id", "")),
        str(summary.get("name", "")),
    } - {""}
    return bool(member_values & summary_values)


def _find_member_summary(
    summaries: list[dict[str, Any]],
    member: dict[str, Any],
) -> dict[str, Any] | None:
    for summary in summaries:
        if _summary_matches_member(summary, member):
            return summary
    return None


def _enrich_composite_slice(
    s: dict,
    *,
    fabric_summary_overrides: list[dict[str, Any]] | None = None,
    chameleon_summary_overrides: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return a federated/composite slice with live member summaries."""
    _sync_legacy_member_fields(s)
    result = {**s}
    _sync_legacy_member_fields(result)
    fabric_member_summaries: list[dict[str, Any]] = []
    chameleon_member_summaries: list[dict[str, Any]] = []
    fabric_overrides = fabric_summary_overrides or []
    chameleon_overrides = chameleon_summary_overrides or []
    for member in result.get("members", []) or []:
        provider = member.get("provider")
        slice_id = member.get("slice_id", "")
        if provider == "fabric":
            summary = _find_member_summary(fabric_overrides, member) or _get_fabric_slice_summary(slice_id)
            if summary and member.get("name") and summary.get("name") == slice_id:
                summary = {**summary, "name": member["name"]}
            fabric_member_summaries.append(summary or {
                "id": slice_id,
                "name": member.get("name", slice_id),
                "state": member.get("state", "Unknown"),
                "node_count": 0,
            })
        elif provider == "chameleon":
            summary = _find_member_summary(chameleon_overrides, member) or _get_chameleon_slice_summary(slice_id)
            chameleon_member_summaries.append(summary or {
                "id": slice_id,
                "name": member.get("name", slice_id),
                "state": member.get("state", "Unknown"),
                "node_count": 0,
            })
    result["fabric_member_summaries"] = fabric_member_summaries
    result["chameleon_member_summaries"] = chameleon_member_summaries
    result["other_member_summaries"] = [
        {
            "provider": m["provider"],
            "id": m["slice_id"],
            "name": m.get("name", m["slice_id"]),
            "state": m.get("state", "Referenced"),
        }
        for m in result.get("members", [])
        if m["provider"] not in {"fabric", "chameleon"}
    ]
    result["state"] = _compute_composite_state_from_summaries(
        fabric_member_summaries,
        chameleon_member_summaries,
    )
    return result


async def _enrich_composite_slice_live(s: dict) -> dict[str, Any]:
    """Return an enriched slice and update stored state from live members."""
    _sync_legacy_member_fields(s)
    fabric_summaries = await asyncio.gather(*[
        _get_live_fabric_slice_summary(member.get("slice_id", ""))
        for member in s.get("members", [])
        if member.get("provider") == "fabric"
    ])
    chameleon_summaries = [
        _get_chameleon_slice_summary(member.get("slice_id", ""))
        for member in s.get("members", [])
        if member.get("provider") == "chameleon"
    ]
    result = _enrich_composite_slice(
        s,
        fabric_summary_overrides=[summary for summary in fabric_summaries if summary],
        chameleon_summary_overrides=[summary for summary in chameleon_summaries if summary],
    )
    if s.get("state") != result.get("state"):
        s["state"] = result["state"]
        _touch(s)
        _persist()
    return result


def _legacy_chameleon_state(status: str | None) -> str:
    status_key = str(status or "").upper()
    if status_key in {"ERROR", "FAILED", "FAILURE"}:
        return "Error"
    if status_key in {"ACTIVE", "RUNNING", "STARTED"}:
        return "Deploying"
    return "Deploying"


def _ensure_legacy_chameleon_slice(
    slice_name: str,
    chameleon_nodes: list[dict],
    *,
    state: str = "Deploying",
    lease: dict | None = None,
) -> dict[str, Any] | None:
    """Create/update a Chameleon member record for the legacy run workflow."""
    if not chameleon_nodes:
        return None

    from app.routes.chameleon import (
        _chameleon_slices,
        _chameleon_slices_lock,
        _now_iso,
        _persist_slices,
        _slice_sites,
    )

    metadata = {
        "source": "legacy_submit_composite",
        "fabric_slice_name": slice_name,
    }
    with _chameleon_slices_lock:
        chi = next(
            (
                s for s in _chameleon_slices.values()
                if s.get("metadata", {}).get("source") == metadata["source"]
                and s.get("metadata", {}).get("fabric_slice_name") == slice_name
            ),
            None,
        )
        if not chi:
            chi = {
                "id": f"chi-slice-{uuid.uuid4()}",
                "name": f"{slice_name}-chameleon",
                "provider": "chameleon",
                "state": state,
                "created": datetime.now(timezone.utc).isoformat(),
                "nodes": [],
                "networks": [],
                "floating_ips": [],
                "resources": [],
                "metadata": metadata,
            }
            _chameleon_slices[chi["id"]] = chi

        existing_nodes = {node.get("name"): node for node in chi.get("nodes", [])}
        converted_nodes: list[dict[str, Any]] = []
        for idx, source in enumerate(chameleon_nodes, start=1):
            name = source.get("name") or f"chi-node-{idx}"
            existing = existing_nodes.get(name, {})
            node = {
                **existing,
                "id": existing.get("id") or source.get("id") or f"node-{uuid.uuid4()}",
                "name": name,
                "node_type": source.get("node_type", existing.get("node_type", "compute_haswell")),
                "image": source.get("image") or source.get("image_id") or existing.get("image", "CC-Ubuntu22.04"),
                "count": source.get("count", existing.get("count", 1)),
                "site": source.get("site", existing.get("site", "CHI@TACC")),
                "connection_type": source.get("connection_type", existing.get("connection_type", "fabnet_v4")),
                "status": state,
            }
            if source.get("interfaces"):
                node["interfaces"] = source["interfaces"]
            elif not node.get("interfaces") and node.get("connection_type") == "fabnet_v4":
                node["interfaces"] = [{"nic": 0, "network": {"name": "fabnetv4"}}]
            converted_nodes.append(node)

        chi["nodes"] = converted_nodes
        chi["state"] = state
        chi["updated"] = _now_iso()
        chi["sites"] = _slice_sites(chi)
        if chi["sites"]:
            chi["site"] = chi["sites"][0]

        if lease:
            lease_id = lease.get("id") or lease.get("lease_id")
            if lease_id:
                resources = [
                    r for r in chi.get("resources", [])
                    if not (r.get("type") == "lease" and r.get("id") == lease_id)
                ]
                resources.append({
                    "type": "lease",
                    "id": lease_id,
                    "name": lease.get("name", f"{slice_name}-chi-lease"),
                    "status": lease.get("status", "PENDING"),
                    "site": lease.get("_site") or chi.get("site", ""),
                    "ownership": "managed",
                })
                chi["resources"] = resources

        _persist_slices()
        return {**chi}


def create_or_update_legacy_federated_slice(
    slice_name: str,
    *,
    fabric_ref: str | None = None,
    chameleon_nodes: list[dict] | None = None,
    chameleon_status: str | None = None,
    chameleon_lease: dict | None = None,
) -> dict[str, Any]:
    """Materialize a Federated Slice for legacy FABRIC+Chameleon submits.

    Older workflows attach Chameleon nodes directly to a FABRIC draft and run
    ``/api/slices/{name}/submit-composite``.  This helper gives those runs the
    same first-class Federated Slice entry as the newer editor flow.
    """
    fabric_ref = fabric_ref or slice_name
    chameleon_nodes = chameleon_nodes or []
    chi = _ensure_legacy_chameleon_slice(
        slice_name,
        chameleon_nodes,
        state=_legacy_chameleon_state(chameleon_status),
        lease=chameleon_lease,
    )

    metadata = {
        "source": "legacy_submit_composite",
        "fabric_slice_name": slice_name,
    }
    s = next(
        (
            existing for existing in _composite_slices.values()
            if existing.get("metadata", {}).get("source") == metadata["source"]
            and existing.get("metadata", {}).get("fabric_slice_name") == slice_name
        ),
        None,
    )
    if not s:
        s = _new_composite_slice(slice_name, id_prefix="fed", kind="federated")
        s["metadata"] = metadata
        _composite_slices[s["id"]] = s

    members = [
        {
            "provider": "fabric",
            "slice_id": fabric_ref,
            "name": slice_name,
            "role": "fabric-sub-slice",
            "state": "Provisioning",
        },
    ]
    if chi:
        members.append({
            "provider": "chameleon",
            "slice_id": chi["id"],
            "name": chi.get("name", f"{slice_name}-chameleon"),
            "role": "chameleon-sub-slice",
        })
    s["members"] = members
    s["state"] = "Provisioning"
    s["metadata"] = {**s.get("metadata", {}), **metadata}
    _sync_legacy_member_fields(s)
    _touch(s)
    _persist()
    return _enrich_composite_slice(s)


def _connection_type_key(conn_type: str) -> str:
    conn_type = str(conn_type).lower()
    if conn_type == "fabnetv4":
        return "fabnetv4_l3"
    if conn_type == "l2_stitch":
        return "facility_port_l2"
    return conn_type


def _endpoint_for_provider(conn: dict[str, Any], provider: str) -> dict[str, Any] | None:
    provider = provider.lower()
    for key in ("endpoint_a", "endpoint_b", "source", "target"):
        endpoint = conn.get(key)
        if isinstance(endpoint, dict) and str(endpoint.get("provider", "")).lower() == provider:
            normalized = {**endpoint, "provider": provider}
            if normalized.get("slice_id") or normalized.get("resource_id"):
                return normalized

    legacy_slice_key = f"{provider}_slice"
    legacy_node_key = f"{provider}_node"
    if conn.get(legacy_slice_key):
        endpoint = {"provider": provider, "slice_id": conn[legacy_slice_key]}
        if conn.get(legacy_node_key):
            endpoint["node"] = conn[legacy_node_key]
        return endpoint
    return None


def _connection_l2_metadata(conn: dict[str, Any]) -> bool:
    if conn.get("vlan") not in (None, "") or conn.get("facility_port"):
        return True
    for key in ("endpoint_a", "endpoint_b", "source", "target"):
        endpoint = conn.get(key)
        if isinstance(endpoint, dict) and (
            endpoint.get("vlan") not in (None, "") or endpoint.get("facility_port")
        ):
            return True
    return False


def _connection_dedupe_key(conn: dict[str, Any]) -> tuple[Any, ...]:
    fabric = _endpoint_for_provider(conn, "fabric") or {}
    chameleon = _endpoint_for_provider(conn, "chameleon") or {}
    return (
        _connection_type_key(conn.get("type", "")),
        fabric.get("slice_id") or fabric.get("resource_id"),
        fabric.get("node") or fabric.get("interface") or fabric.get("network"),
        chameleon.get("slice_id") or chameleon.get("resource_id"),
        chameleon.get("node") or chameleon.get("interface") or chameleon.get("network"),
        str(conn.get("vlan", "")),
        conn.get("facility_port", ""),
    )


def _normalize_connection(conn: dict) -> dict[str, Any]:
    """Normalize and validate a cross-testbed connection intent."""
    if not isinstance(conn, dict):
        raise HTTPException(400, "Connection records must be objects")
    conn_type = conn.get("type") or conn.get("connection_type") or conn.get("kind")
    if not conn_type:
        raise HTTPException(400, "Connection records require type")
    normalized = {**conn}
    normalized["type"] = str(conn_type).lower()
    type_key = _connection_type_key(normalized["type"])
    if type_key not in {"fabnetv4_l3", "facility_port_l2"}:
        raise HTTPException(400, f"Unsupported connection type: {normalized['type']}")

    fabric = _endpoint_for_provider(normalized, "fabric")
    chameleon = _endpoint_for_provider(normalized, "chameleon")
    if not fabric or not chameleon:
        raise HTTPException(400, "Connections require FABRIC and Chameleon endpoints")

    if type_key == "fabnetv4_l3":
        fabric.setdefault("network", "FABNetv4")
        chameleon.setdefault("network", "fabnetv4")
    if type_key == "facility_port_l2" and not _connection_l2_metadata(normalized):
        raise HTTPException(400, "Facility Port L2 connections require VLAN or facility_port metadata")

    normalized["endpoint_a"] = fabric
    normalized["endpoint_b"] = chameleon
    normalized.setdefault("fabric_slice", fabric.get("slice_id") or fabric.get("resource_id"))
    normalized.setdefault("chameleon_slice", chameleon.get("slice_id") or chameleon.get("resource_id"))
    normalized.setdefault("id", f"conn-{uuid.uuid4().hex[:12]}")
    return normalized


def _get_slice_or_404(slice_id: str) -> dict:
    s = _composite_slices.get(slice_id)
    if not s:
        raise HTTPException(404, "Federated slice not found")
    return s


def _fabnetv4_chameleon_member_ids(s: dict) -> set[str]:
    """Return Chameleon member slice IDs participating in FABNetv4 L3 intent."""
    member_ids: set[str] = set()
    for conn in s.get("cross_connections", []) or []:
        if _connection_type_key(conn.get("type", "")) != "fabnetv4_l3":
            continue
        endpoint = _endpoint_for_provider(conn, "chameleon")
        slice_id = endpoint.get("slice_id") if endpoint else conn.get("chameleon_slice")
        if slice_id:
            member_ids.add(slice_id)
    return member_ids


def _fabnetv4_fabric_member_nodes(s: dict) -> dict[str, set[str]]:
    """Return FABRIC member slice IDs and optional node names for FABNetv4 L3 intent."""
    members: dict[str, set[str]] = {}
    for conn in s.get("cross_connections", []) or []:
        if _connection_type_key(conn.get("type", "")) != "fabnetv4_l3":
            continue
        endpoint = _endpoint_for_provider(conn, "fabric")
        slice_id = endpoint.get("slice_id") if endpoint else conn.get("fabric_slice")
        if not slice_id:
            continue
        members.setdefault(slice_id, set())
        node_name = endpoint.get("node") if endpoint else conn.get("fabric_node")
        if node_name:
            members[slice_id].add(node_name)
    return members


def _facility_port_l2_connection_plan(s: dict) -> list[dict[str, Any]]:
    """Summarize Facility Port L2 intents for submit responses and UI status."""
    plan: list[dict[str, Any]] = []
    for conn in s.get("cross_connections", []) or []:
        if _connection_type_key(conn.get("type", "")) != "facility_port_l2":
            continue
        fabric = _endpoint_for_provider(conn, "fabric") or {}
        chameleon = _endpoint_for_provider(conn, "chameleon") or {}
        plan.append({
            "id": conn.get("id", ""),
            "type": "facility_port_l2",
            "status": "ready-for-submit",
            "vlan": conn.get("vlan") or fabric.get("vlan") or chameleon.get("vlan"),
            "facility_port": conn.get("facility_port") or fabric.get("facility_port"),
            "fabric_slice": fabric.get("slice_id") or conn.get("fabric_slice", ""),
            "chameleon_slice": chameleon.get("slice_id") or conn.get("chameleon_slice", ""),
            "fabric_site": conn.get("fabric_site") or fabric.get("site", ""),
            "chameleon_site": conn.get("chameleon_site") or chameleon.get("site", ""),
            "actions": [
                "Create or reuse the Chameleon VLAN network for the negotiated VLAN",
                "Attach the Chameleon endpoint server to that VLAN network",
                "Add the matching FABRIC facility port to the FABRIC member slice",
            ],
        })
    return plan


def _facility_port_l2_chameleon_intents(s: dict) -> dict[str, list[dict[str, Any]]]:
    """Return per-Chameleon-member Facility Port L2 preparation intents."""
    intents: dict[str, list[dict[str, Any]]] = {}
    for conn in s.get("cross_connections", []) or []:
        if _connection_type_key(conn.get("type", "")) != "facility_port_l2":
            continue
        fabric = _endpoint_for_provider(conn, "fabric") or {}
        chameleon = _endpoint_for_provider(conn, "chameleon") or {}
        slice_id = chameleon.get("slice_id") or chameleon.get("resource_id") or conn.get("chameleon_slice")
        if not slice_id:
            continue
        intents.setdefault(slice_id, []).append({
            "connection_id": conn.get("id", ""),
            "vlan": conn.get("vlan") or chameleon.get("vlan") or fabric.get("vlan"),
            "facility_port": conn.get("facility_port") or fabric.get("facility_port") or chameleon.get("facility_port"),
            "fabric_site": conn.get("fabric_site") or fabric.get("site", ""),
            "chameleon_site": conn.get("chameleon_site") or chameleon.get("site", ""),
            "physical_network": conn.get("physical_network") or chameleon.get("physical_network", ""),
            "cidr": conn.get("cidr") or chameleon.get("cidr", ""),
            "node_name": chameleon.get("node") or conn.get("chameleon_node", ""),
        })
    return intents


def _facility_port_l2_fabric_intents(s: dict) -> dict[str, list[dict[str, Any]]]:
    """Return per-FABRIC-member Facility Port L2 preparation intents."""
    intents: dict[str, list[dict[str, Any]]] = {}
    for conn in s.get("cross_connections", []) or []:
        if _connection_type_key(conn.get("type", "")) != "facility_port_l2":
            continue
        fabric = _endpoint_for_provider(conn, "fabric") or {}
        chameleon = _endpoint_for_provider(conn, "chameleon") or {}
        slice_id = fabric.get("slice_id") or fabric.get("resource_id") or conn.get("fabric_slice")
        if not slice_id:
            continue
        intents.setdefault(slice_id, []).append({
            "connection_id": conn.get("id", ""),
            "vlan": conn.get("vlan") or fabric.get("vlan") or chameleon.get("vlan"),
            "facility_port": conn.get("facility_port") or fabric.get("facility_port") or chameleon.get("facility_port"),
            "fabric_site": conn.get("fabric_site") or fabric.get("site", ""),
            "node_name": fabric.get("node") or conn.get("fabric_node", ""),
            "network_name": conn.get("network") or fabric.get("network", ""),
            "bandwidth": conn.get("bandwidth") or fabric.get("bandwidth"),
        })
    return intents


def _federated_connection_plan(s: dict) -> list[dict[str, Any]]:
    """Return provider action plan for all federated cross-testbed connections."""
    plan: list[dict[str, Any]] = []
    for conn in s.get("cross_connections", []) or []:
        conn_type = _connection_type_key(conn.get("type", ""))
        fabric = _endpoint_for_provider(conn, "fabric") or {}
        chameleon = _endpoint_for_provider(conn, "chameleon") or {}
        if conn_type == "fabnetv4_l3":
            plan.append({
                "id": conn.get("id", ""),
                "type": "fabnetv4_l3",
                "status": "ready-for-submit",
                "fabric_slice": fabric.get("slice_id") or conn.get("fabric_slice", ""),
                "fabric_node": fabric.get("node") or conn.get("fabric_node", ""),
                "chameleon_slice": chameleon.get("slice_id") or conn.get("chameleon_slice", ""),
                "chameleon_node": chameleon.get("node") or conn.get("chameleon_node", ""),
                "actions": [
                    "Attach FABRIC endpoint nodes to FABNetv4",
                    "Attach Chameleon endpoint servers to fabnetv4",
                    "Apply Chameleon route-metric userdata to FABNet servers",
                ],
            })
        elif conn_type == "facility_port_l2":
            plan.extend(_facility_port_l2_connection_plan({"cross_connections": [conn]}))
    return plan


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------


@router.get("/slices")
async def list_composite_slices() -> list[dict]:
    """List all composite slices."""
    return await asyncio.gather(*[
        _enrich_composite_slice_live(s)
        for s in _composite_slices.values()
    ])


@router.get("/slices/{slice_id}")
async def get_composite_slice(slice_id: str) -> dict:
    """Get a composite slice with member summaries."""
    s = _composite_slices.get(slice_id)
    if not s:
        raise HTTPException(404, "Composite slice not found")
    return await _enrich_composite_slice_live(s)


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


async def _delete_provider_member_slice(
    member: dict[str, Any],
    *,
    delete_imported_resources: bool = False,
) -> dict[str, Any]:
    """Delete one provider slice referenced by a federated parent."""
    provider = str(member.get("provider", "")).lower()
    slice_id = str(member.get("slice_id") or member.get("id") or "")
    result: dict[str, Any] = {
        "provider": provider,
        "slice_id": slice_id,
    }
    if not provider or not slice_id:
        result.update({"status": "skipped", "error": "member missing provider or slice_id"})
        return result

    try:
        if provider == "fabric":
            from app.routes.slices import delete_slice

            result["result"] = await delete_slice(slice_id)
            result["status"] = "deleted"
        elif provider == "chameleon":
            from app.routes.chameleon import delete_chameleon_slice

            result["result"] = await delete_chameleon_slice(
                slice_id,
                delete_resources=True,
                delete_imported_resources=delete_imported_resources,
            )
            result["status"] = "deleted"
        else:
            result.update({
                "status": "skipped",
                "error": f"Provider '{provider}' does not have a registered delete handler",
            })
    except HTTPException as exc:
        result.update({
            "status": "error",
            "error": str(exc.detail),
            "status_code": exc.status_code,
        })
    except Exception as exc:  # pragma: no cover - defensive wrapper for provider SDK failures
        logger.exception("Failed to delete %s member slice %s", provider, slice_id)
        result.update({"status": "error", "error": str(exc)})
    return result


@router.delete("/slices/{slice_id}")
async def delete_composite_slice(
    slice_id: str,
    delete_members: bool = False,
    delete_imported_resources: bool = False,
) -> dict:
    """Delete a composite slice, optionally deleting provider member slices."""
    s = _composite_slices.get(slice_id)
    if not s:
        raise HTTPException(404, "Composite slice not found")

    member_deletions: list[dict[str, Any]] = []
    if delete_members:
        for member in _normalize_members(s):
            member_deletions.append(await _delete_provider_member_slice(
                member,
                delete_imported_resources=delete_imported_resources,
            ))

    del _composite_slices[slice_id]
    _persist()
    result: dict[str, Any] = {"status": "deleted", "id": slice_id}
    if delete_members:
        result["member_deletions"] = member_deletions
        errors = [item for item in member_deletions if item.get("status") == "error"]
        skipped = [item for item in member_deletions if item.get("status") == "skipped"]
        if errors:
            result["member_delete_errors"] = errors
        if skipped:
            result["member_delete_skipped"] = skipped
    return result


@federated_router.get("/slices")
async def list_federated_slices() -> list[dict]:
    """List all federated slices.

    This is the forward API surface backed by the same store as the legacy
    composite endpoints.
    """
    return await list_composite_slices()


@federated_router.get("/slices/{slice_id}")
async def get_federated_slice(slice_id: str) -> dict:
    """Get a federated slice with member summaries."""
    return await get_composite_slice(slice_id)


@federated_router.post("/slices")
async def create_federated_slice(body: dict = Body(...)) -> dict:
    """Create a new federated slice.

    Body: {"name": "my-experiment"}
    """
    name = body.get("name", "federated-slice")
    s = _new_composite_slice(name, id_prefix="fed", kind="federated")
    _composite_slices[s["id"]] = s
    _persist()
    return s


@federated_router.delete("/slices/{slice_id}")
async def delete_federated_slice(
    slice_id: str,
    delete_members: bool = False,
    delete_imported_resources: bool = False,
) -> dict:
    """Delete a federated slice, optionally deleting provider member slices."""
    return await delete_composite_slice(
        slice_id,
        delete_members=delete_members,
        delete_imported_resources=delete_imported_resources,
    )


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

    member_input = body.get("members")
    if member_input is None:
        member_input = [
            *({"provider": "fabric", "slice_id": fid} for fid in body.get("fabric_slices", [])),
            *({"provider": "chameleon", "slice_id": cid} for cid in body.get("chameleon_slices", [])),
        ]
    members = [_normalize_member(m) for m in member_input]

    invalid = []
    for member in members:
        if not _validate_member_ref(member):
            invalid.append(f"{member.get('provider', 'unknown')}: {member.get('slice_id', '')}")

    if invalid:
        raise HTTPException(400, f"Invalid member references: {', '.join(invalid)}")

    s["members"] = members
    # This endpoint replaces the full membership set. Clear legacy arrays before
    # syncing so stale fabric_slices/chameleon_slices are not merged back in.
    s["fabric_slices"] = []
    s["chameleon_slices"] = []
    _sync_legacy_member_fields(s)
    _touch(s)
    _persist()
    return s


@router.post("/slices/{slice_id}/members/add")
async def add_composite_member(slice_id: str, body: dict = Body(...)) -> dict:
    """Attach one provider slice/member to an existing composite slice."""
    s = _composite_slices.get(slice_id)
    if not s:
        raise HTTPException(404, "Composite slice not found")
    member = _normalize_member(body)
    if not _validate_member_ref(member):
        raise HTTPException(400, f"Invalid member reference: {member['provider']}: {member['slice_id']}")
    _sync_legacy_member_fields(s)
    key = (member["provider"], member["slice_id"])
    if key not in {(m["provider"], m["slice_id"]) for m in s.get("members", [])}:
        s["members"].append(member)
    _sync_legacy_member_fields(s)
    _touch(s)
    _persist()
    return s


@router.post("/slices/{slice_id}/members/remove")
async def remove_composite_member(slice_id: str, body: dict = Body(...)) -> dict:
    """Detach one provider slice/member from a composite slice."""
    s = _composite_slices.get(slice_id)
    if not s:
        raise HTTPException(404, "Composite slice not found")
    provider = str(body.get("provider", "")).lower()
    member_slice_id = body.get("slice_id") or body.get("id") or ""
    if not provider or not member_slice_id:
        raise HTTPException(400, "provider and slice_id required")
    _sync_legacy_member_fields(s)
    s["members"] = [
        m for m in s.get("members", [])
        if not (m.get("provider") == provider and m.get("slice_id") == member_slice_id)
    ]
    if provider == "fabric":
        s["fabric_slices"] = [fid for fid in s.get("fabric_slices", []) if fid != member_slice_id]
    elif provider == "chameleon":
        s["chameleon_slices"] = [cid for cid in s.get("chameleon_slices", []) if cid != member_slice_id]
    _sync_legacy_member_fields(s)
    _touch(s)
    _persist()
    return s


@federated_router.put("/slices/{slice_id}/members")
async def update_federated_members(slice_id: str, body: dict = Body(...)) -> dict:
    """Replace the member slices/resources of a federated slice."""
    return await update_composite_members(slice_id, body)


@federated_router.post("/slices/{slice_id}/members/add")
async def add_federated_member(slice_id: str, body: dict = Body(...)) -> dict:
    """Attach one provider member to an existing federated slice."""
    return await add_composite_member(slice_id, body)


@federated_router.post("/slices/{slice_id}/members/remove")
async def remove_federated_member(slice_id: str, body: dict = Body(...)) -> dict:
    """Detach one provider member from a federated slice."""
    return await remove_composite_member(slice_id, body)


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
        _sync_legacy_member_fields(s)
        fab = s.get("fabric_slices", [])
        if old_id in fab:
            s["fabric_slices"] = [new_id if fid == old_id else fid for fid in fab]
            for member in s.get("members", []):
                if member.get("provider") == "fabric" and member.get("slice_id") == old_id:
                    member["slice_id"] = new_id
            # Also update cross_connections
            for conn in s.get("cross_connections", []):
                if conn.get("fabric_slice") == old_id:
                    conn["fabric_slice"] = new_id
                for endpoint_key in ("endpoint_a", "endpoint_b", "source", "target"):
                    endpoint = conn.get(endpoint_key)
                    if isinstance(endpoint, dict) and endpoint.get("provider") == "fabric" and endpoint.get("slice_id") == old_id:
                        endpoint["slice_id"] = new_id
            _sync_legacy_member_fields(s)
            _touch(s)
            updated_count += 1
    if updated_count > 0:
        _persist()
    return {"updated": updated_count, "old_id": old_id, "new_id": new_id}


@federated_router.post("/replace-fabric-member")
async def replace_federated_fabric_member(body: dict = Body(...)) -> dict:
    """Replace a FABRIC member ID across all federated/composite slices."""
    return await replace_fabric_member(body)


@router.put("/slices/{slice_id}/cross-connections")
async def update_cross_connections(slice_id: str, body: list = Body(...)) -> dict:
    """Update cross-testbed connections for a composite slice.

    Body: [{"type": "fabnetv4", "fabric_slice": "id", "fabric_node": "name",
            "chameleon_slice": "id", "chameleon_node": "name"}, ...]
    """
    s = _composite_slices.get(slice_id)
    if not s:
        raise HTTPException(404, "Composite slice not found")
    normalized_connections = [_normalize_connection(conn) for conn in body]
    connection_keys = [_connection_dedupe_key(conn) for conn in normalized_connections]
    if len(set(connection_keys)) != len(connection_keys):
        raise HTTPException(400, "Duplicate federated connections are not allowed")
    s["cross_connections"] = normalized_connections
    _touch(s)
    _persist()
    return s


@federated_router.get("/slices/{slice_id}/connections")
async def list_federated_connections(slice_id: str) -> list[dict]:
    """List cross-testbed connections for a federated slice."""
    s = _get_slice_or_404(slice_id)
    return s.get("cross_connections", [])


@federated_router.put("/slices/{slice_id}/connections")
async def update_federated_connections(slice_id: str, body: list = Body(...)) -> dict:
    """Replace all cross-testbed connections for a federated slice."""
    return await update_cross_connections(slice_id, body)


@federated_router.put("/slices/{slice_id}/cross-connections")
async def update_federated_cross_connections(slice_id: str, body: list = Body(...)) -> dict:
    """Compatibility spelling for replacing federated cross-testbed connections."""
    return await update_cross_connections(slice_id, body)


@federated_router.post("/slices/{slice_id}/connections/add")
async def add_federated_connection(slice_id: str, body: dict = Body(...)) -> dict:
    """Attach one cross-testbed connection intent to a federated slice."""
    s = _get_slice_or_404(slice_id)
    conn = _normalize_connection(body)
    existing_ids = {c.get("id") for c in s.get("cross_connections", [])}
    conn_key = _connection_dedupe_key(conn)
    if any(_connection_dedupe_key(existing) == conn_key for existing in s.get("cross_connections", [])):
        raise HTTPException(409, "Federated connection already exists")
    if conn["id"] not in existing_ids:
        s.setdefault("cross_connections", []).append(conn)
    _touch(s)
    _persist()
    return s


@federated_router.post("/slices/{slice_id}/connections/remove")
async def remove_federated_connection(slice_id: str, body: dict = Body(...)) -> dict:
    """Detach one cross-testbed connection intent from a federated slice."""
    s = _get_slice_or_404(slice_id)
    conn_id = body.get("id")
    if not conn_id:
        raise HTTPException(400, "connection id required")
    before = len(s.get("cross_connections", []))
    s["cross_connections"] = [c for c in s.get("cross_connections", []) if c.get("id") != conn_id]
    if len(s["cross_connections"]) == before:
        raise HTTPException(404, "Connection not found")
    _touch(s)
    _persist()
    return s


@federated_router.get("/slices/{slice_id}/connection-plan")
async def get_federated_connection_plan(slice_id: str) -> list[dict]:
    """Return the provider-side action plan for federated connection intents."""
    s = _get_slice_or_404(slice_id)
    return _federated_connection_plan(s)


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
    _sync_legacy_member_fields(s)

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
            # Fetch submitted slices live before consulting the call manager
            # cache. Embedded member editors mutate local draft objects; a
            # stale cache here hides just-added topology such as facility ports
            # from the federated graph.
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
            # Fall back to call manager cache for submitted slices if the live
            # fetch failed, so the graph can still render last-known topology.
            if not slice_data:
                from app.fabric_call_manager import get_call_manager
                cm = get_call_manager()
                _entry = cm._cache.get(f"slice:{name}")
                slice_data = _entry.data if _entry and _entry.data else None
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


@federated_router.get("/slices/{slice_id}/graph")
async def get_federated_graph(slice_id: str) -> dict:
    """Build a merged topology graph from all federated member slices."""
    return await get_composite_graph(slice_id)


# ---------------------------------------------------------------------------
# Submit — deploy un-deployed member slices in parallel
# ---------------------------------------------------------------------------


@router.post("/slices/{slice_id}/submit")
async def submit_composite_slice(slice_id: str, body: dict = Body(default={})) -> dict:
    """Submit a composite slice — deploys all un-deployed member slices in parallel."""
    s = _composite_slices.get(slice_id)
    if not s:
        raise HTTPException(404, "Composite slice not found")
    _sync_legacy_member_fields(s)

    fabric_refs = s.get("fabric_slices", [])
    chameleon_refs = s.get("chameleon_slices", [])
    fabnetv4_chameleon_refs = _fabnetv4_chameleon_member_ids(s)
    fabnetv4_fabric_refs = _fabnetv4_fabric_member_nodes(s)
    facility_port_l2_chameleon_refs = _facility_port_l2_chameleon_intents(s)
    facility_port_l2_fabric_refs = _facility_port_l2_fabric_intents(s)

    if not fabric_refs and not chameleon_refs:
        raise HTTPException(400, "Composite slice has no members to submit")

    results: dict[str, Any] = {
        "composite_id": slice_id,
        "connection_results": _federated_connection_plan(s),
    }

    async def _submit_fabric_member(fid: str) -> dict:
        try:
            from app.slice_registry import resolve_slice_name, get_slice_uuid
            name = resolve_slice_name(fid)
            logger.info("Composite submit: FABRIC member fid=%s resolved to name=%s", fid, name)
            connection_preparation = None
            if fid in fabnetv4_fabric_refs:
                from app.routes.slices import prepare_slice_for_fabnetv4
                connection_preparation = prepare_slice_for_fabnetv4(
                    fid,
                    sorted(fabnetv4_fabric_refs[fid]) or None,
                )
            facility_port_preparation = None
            if fid in facility_port_l2_fabric_refs:
                from app.routes.slices import prepare_slice_for_facility_port_l2
                facility_port_preparation = [
                    {
                        "connection_id": intent.get("connection_id", ""),
                        **prepare_slice_for_facility_port_l2(
                            fid,
                            facility_port=intent.get("facility_port", ""),
                            fabric_site=intent.get("fabric_site", ""),
                            vlan=intent.get("vlan"),
                            node_name=intent.get("node_name", ""),
                            network_name=intent.get("network_name", ""),
                            bandwidth=intent.get("bandwidth"),
                        ),
                    }
                    for intent in facility_port_l2_fabric_refs[fid]
                ]
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

            response = {"id": fid, "new_id": new_id, "name": name, "status": "submitted", "state": result.get("state", "")}
            if connection_preparation:
                response["connection_preparation"] = connection_preparation
            if facility_port_preparation:
                response["facility_port_l2_preparation"] = facility_port_preparation
            return response
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
            connection_preparation: dict[str, Any] = {}
            if cid in fabnetv4_chameleon_refs:
                from app.routes.chameleon import prepare_draft_for_fabnetv4
                connection_preparation["fabnetv4_l3"] = prepare_draft_for_fabnetv4(cid)
            if cid in facility_port_l2_chameleon_refs:
                from app.routes.chameleon import prepare_draft_for_facility_port_l2
                connection_preparation["facility_port_l2"] = [
                    {
                        "connection_id": intent.get("connection_id", ""),
                        **prepare_draft_for_facility_port_l2(
                            cid,
                            vlan=intent.get("vlan"),
                            chameleon_site=intent.get("chameleon_site", ""),
                            fabric_site=intent.get("fabric_site", ""),
                            facility_port=intent.get("facility_port", ""),
                            physical_network=intent.get("physical_network", ""),
                            cidr=intent.get("cidr", ""),
                            node_name=intent.get("node_name", ""),
                        ),
                    }
                    for intent in facility_port_l2_chameleon_refs[cid]
                ]
            # Trigger full deploy via the Chameleon deploy endpoint
            # (lease creation + wait ACTIVE + launch instances)
            from app.routes.chameleon import deploy_draft
            deploy_body = {**body, "full_deploy": True}
            result = await deploy_draft(cid, deploy_body)
            response = {"id": cid, "status": "submitted", "result": result}
            if connection_preparation:
                response["connection_preparation"] = connection_preparation
            return response
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
                for member in s.get("members", []):
                    if member.get("provider") == "fabric" and member.get("slice_id") == old_id:
                        member["slice_id"] = new_id
                # Also update cross_connections
                for conn in s.get("cross_connections", []):
                    if conn.get("fabric_slice") == old_id:
                        conn["fabric_slice"] = new_id
                    for endpoint_key in ("endpoint_a", "endpoint_b", "source", "target"):
                        endpoint = conn.get(endpoint_key)
                        if isinstance(endpoint, dict) and endpoint.get("provider") == "fabric" and endpoint.get("slice_id") == old_id:
                            endpoint["slice_id"] = new_id
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
    _sync_legacy_member_fields(s)
    _touch(s)
    _persist()

    results["federated_slice"] = _enrich_composite_slice(s)
    return results


@federated_router.post("/slices/{slice_id}/submit")
async def submit_federated_slice(slice_id: str, body: dict = Body(default={})) -> dict:
    """Submit a federated slice — deploys all un-deployed member slices in parallel."""
    result = await submit_composite_slice(slice_id, body)
    result["federated_id"] = result.get("composite_id", slice_id)
    if isinstance(result.get("federated_slice"), dict):
        result["federated_slice"]["kind"] = "federated"
    return result
