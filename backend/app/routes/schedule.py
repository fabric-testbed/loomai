"""Resource scheduling API routes.

Provides calendar views, next-available lookups, and alternative
resource suggestions by combining slice lease data with site availability.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from app.fablib_manager import get_fablib, is_configured
from app.fablib_executor import run_in_fablib_pool
from app.fabric_call_manager import get_call_manager
from app.routes.resources import get_cached_sites
from app.site_resolver import (
    _build_availability,
    _site_can_host,
    COMPONENT_RESOURCE_MAP,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["schedule"])

# States that indicate an active (resource-consuming) slice
_ACTIVE_STATES = {"StableOK", "StableError", "ModifyOK", "ModifyError",
                  "Configuring", "Nascent", "AllocatedOK"}
_TERMINAL_STATES = {"Dead", "Closing"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_iso(val: str) -> Optional[datetime]:
    """Parse an ISO-format timestamp string, returning None on failure."""
    if not val:
        return None
    try:
        dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _get_slice_nodes(slice_obj) -> list[dict[str, Any]]:
    """Extract node resource info from a FABlib slice object."""
    nodes = []
    try:
        for node in slice_obj.get_nodes():
            nodes.append({
                "name": node.get_name(),
                "site": node.get_site(),
                "cores": node.get_cores(),
                "ram": node.get_ram(),
                "disk": node.get_disk(),
            })
    except Exception:
        logger.debug("Failed to extract nodes from slice", exc_info=True)
    return nodes


def _list_active_slices_sync() -> list[dict[str, Any]]:
    """Fetch all active slices with per-node resource details.

    Returns list of dicts with keys: name, id, state, lease_end, nodes.
    Each node has: name, site, cores, ram, disk.
    """
    if not is_configured():
        return []

    fablib = get_fablib()
    slices = fablib.get_slices()
    result = []
    for s in slices:
        try:
            state = str(s.get_state())
        except Exception:
            continue

        if state in _TERMINAL_STATES:
            continue

        # Only include active slices (consuming resources)
        if state not in _ACTIVE_STATES:
            continue

        try:
            lease_end_raw = s.get_lease_end()
            lease_end = str(lease_end_raw) if lease_end_raw else ""
        except Exception:
            lease_end = ""

        nodes = _get_slice_nodes(s)

        result.append({
            "name": s.get_name(),
            "id": s.get_slice_id(),
            "state": state,
            "lease_end": lease_end,
            "nodes": nodes,
        })
    return result


async def _get_active_slices(max_age: float = 60) -> list[dict[str, Any]]:
    """Get active slices with caching via the call manager."""
    mgr = get_call_manager()
    return await mgr.get(
        "schedule:active_slices",
        fetcher=_list_active_slices_sync,
        max_age=max_age,
        stale_while_revalidate=True,
    )


def _site_capacity(site: dict[str, Any]) -> dict[str, int]:
    """Extract total capacity for a site, with fallbacks."""
    return {
        "cores": site.get("cores_capacity", 0) or 0,
        "ram": site.get("ram_capacity", 0) or 0,
        "disk": site.get("disk_capacity", 0) or 0,
    }


def _site_available(site: dict[str, Any]) -> dict[str, int]:
    """Extract current availability for a site."""
    return {
        "cores": site.get("cores_available", 0) or 0,
        "ram": site.get("ram_available", 0) or 0,
        "disk": site.get("disk_available", 0) or 0,
    }


def _site_has_component(site: dict[str, Any], gpu_model: str) -> bool:
    """Check if site has the requested component type available."""
    if not gpu_model:
        return True
    # Map from template model name to resource query name
    resource_name = COMPONENT_RESOURCE_MAP.get(gpu_model, gpu_model)
    components = site.get("components", {})
    # Check both the mapped name and direct name
    for name in (resource_name, gpu_model):
        comp = components.get(name, {})
        if isinstance(comp, dict) and (comp.get("available", 0) or 0) > 0:
            return True
        elif isinstance(comp, int) and comp > 0:
            return True
    return False


def _component_available_count(site: dict[str, Any], gpu_model: str) -> int:
    """Return available count of a component at a site."""
    if not gpu_model:
        return 0
    resource_name = COMPONENT_RESOURCE_MAP.get(gpu_model, gpu_model)
    components = site.get("components", {})
    for name in (resource_name, gpu_model):
        comp = components.get(name, {})
        if isinstance(comp, dict):
            val = comp.get("available", 0) or 0
            if val > 0:
                return val
        elif isinstance(comp, int) and comp > 0:
            return comp
    return 0


def _meets_requirements(avail: dict[str, int], cores: int, ram: int,
                        disk: int, site: dict[str, Any],
                        gpu: str = "") -> bool:
    """Check if available resources meet the requested requirements."""
    if cores > 0 and avail.get("cores", 0) < cores:
        return False
    if ram > 0 and avail.get("ram", 0) < ram:
        return False
    if disk > 0 and avail.get("disk", 0) < disk:
        return False
    if gpu and not _site_has_component(site, gpu):
        return False
    return True


# ---------------------------------------------------------------------------
# GET /api/schedule/calendar
# ---------------------------------------------------------------------------

@router.get("/schedule/calendar")
async def get_calendar(days: int = Query(14, ge=1, le=90)):
    """Combine slice lease data with site availability to produce a calendar.

    Returns per-site resource usage including which slices are running and
    when their leases expire.
    """
    now = datetime.now(timezone.utc)
    end_time = now + timedelta(days=days)

    # Fetch site data and active slices in parallel
    sites = get_cached_sites()
    try:
        active_slices = await _get_active_slices()
    except Exception:
        logger.warning("Failed to fetch active slices for calendar", exc_info=True)
        active_slices = []

    # Index slices by site via their nodes
    site_slices: dict[str, list[dict[str, Any]]] = {}
    for sl in active_slices:
        # Group this slice's nodes by site
        nodes_by_site: dict[str, list[dict]] = {}
        for node in sl.get("nodes", []):
            site_name = node.get("site", "")
            if site_name:
                nodes_by_site.setdefault(site_name, []).append({
                    "name": node.get("name", ""),
                    "cores": node.get("cores", 0),
                    "ram": node.get("ram", 0),
                    "disk": node.get("disk", 0),
                })
        for site_name, site_nodes in nodes_by_site.items():
            site_slices.setdefault(site_name, []).append({
                "name": sl.get("name", ""),
                "id": sl.get("id", ""),
                "state": sl.get("state", ""),
                "lease_end": sl.get("lease_end", ""),
                "nodes": site_nodes,
            })

    # Build the response
    result_sites = []
    for site in sites:
        name = site.get("name", "")
        state = site.get("state", "")
        if state != "Active":
            continue

        cap = _site_capacity(site)
        avail = _site_available(site)

        result_sites.append({
            "name": name,
            "cores_capacity": cap["cores"],
            "cores_available": avail["cores"],
            "ram_capacity": cap["ram"],
            "ram_available": avail["ram"],
            "slices": site_slices.get(name, []),
        })

    return {
        "time_range": {
            "start": now.isoformat(),
            "end": end_time.isoformat(),
        },
        "sites": result_sites,
    }


# ---------------------------------------------------------------------------
# GET /api/schedule/next-available
# ---------------------------------------------------------------------------

@router.get("/schedule/next-available")
async def get_next_available(
    cores: int = Query(0, ge=0),
    ram: int = Query(0, ge=0),
    disk: int = Query(0, ge=0),
    gpu: str = Query(""),
    site: str = Query(""),
):
    """Find when and where the requested resources will be available.

    At least one resource constraint must be provided.
    """
    if cores == 0 and ram == 0 and disk == 0 and not gpu:
        raise HTTPException(
            status_code=400,
            detail="At least one resource constraint (cores, ram, disk, gpu) is required",
        )

    sites_data = get_cached_sites()
    try:
        active_slices = await _get_active_slices()
    except Exception:
        logger.warning("Failed to fetch active slices", exc_info=True)
        active_slices = []

    # Filter to requested site if specified
    target_sites = sites_data
    if site:
        target_sites = [s for s in sites_data if s.get("name") == site]
        if not target_sites:
            raise HTTPException(status_code=404, detail=f"Site not found: {site}")

    available_now: list[dict[str, Any]] = []
    available_soon: list[dict[str, Any]] = []
    not_available: list[dict[str, Any]] = []

    for s in target_sites:
        site_name = s.get("name", "")
        state = s.get("state", "")
        if state != "Active":
            continue

        avail = _site_available(s)
        cap = _site_capacity(s)

        # Check if requirement is met now
        if _meets_requirements(avail, cores, ram, disk, s, gpu):
            available_now.append({
                "site": site_name,
                "cores_available": avail["cores"],
                "ram_available": avail["ram"],
            })
            continue

        # Check if site can ever meet the requirement (capacity check)
        can_ever_meet = True
        if cores > 0 and cap.get("cores", 0) < cores:
            can_ever_meet = False
        if ram > 0 and cap.get("ram", 0) < ram:
            can_ever_meet = False
        if disk > 0 and cap.get("disk", 0) < disk:
            can_ever_meet = False
        # For GPUs, check if site has any capacity (not just available)
        if gpu:
            resource_name = COMPONENT_RESOURCE_MAP.get(gpu, gpu)
            components = s.get("components", {})
            has_any = False
            for name in (resource_name, gpu):
                comp = components.get(name, {})
                if isinstance(comp, dict) and (comp.get("capacity", 0) or 0) > 0:
                    has_any = True
                    break
            if not has_any:
                can_ever_meet = False

        if not can_ever_meet:
            not_available.append({
                "site": site_name,
                "reason": "Insufficient capacity",
            })
            continue

        # Simulate freeing resources by processing lease expirations
        # Collect slices at this site
        site_slice_nodes: list[dict[str, Any]] = []
        for sl in active_slices:
            lease_end_str = sl.get("lease_end", "")
            lease_end_dt = _parse_iso(lease_end_str)
            if not lease_end_dt:
                continue
            for node in sl.get("nodes", []):
                if node.get("site") == site_name:
                    site_slice_nodes.append({
                        "slice_name": sl.get("name", ""),
                        "lease_end": lease_end_str,
                        "lease_end_dt": lease_end_dt,
                        "cores": node.get("cores", 0),
                        "ram": node.get("ram", 0),
                        "disk": node.get("disk", 0),
                    })

        # Sort by lease_end ascending
        site_slice_nodes.sort(key=lambda x: x["lease_end_dt"])

        # Simulate freeing resources
        projected = dict(avail)
        found_time = None
        freeing_slices = []

        # Group by unique lease_end to process all nodes expiring at the same time
        seen_times: dict[str, list[dict]] = {}
        for sn in site_slice_nodes:
            seen_times.setdefault(sn["lease_end"], []).append(sn)

        for le_str in sorted(seen_times.keys()):
            group = seen_times[le_str]
            batch_slices = set()
            for sn in group:
                projected["cores"] = projected.get("cores", 0) + sn["cores"]
                projected["ram"] = projected.get("ram", 0) + sn["ram"]
                projected["disk"] = projected.get("disk", 0) + sn["disk"]
                batch_slices.add(sn["slice_name"])

            freeing_slices.extend([
                {"name": sn, "lease_end": le_str} for sn in batch_slices
            ])

            # Check if we now meet the requirement (ignoring GPU for projection)
            gpu_ok = gpu == "" or _site_has_component(s, gpu)
            if (projected.get("cores", 0) >= cores and
                    projected.get("ram", 0) >= ram and
                    projected.get("disk", 0) >= disk and
                    gpu_ok):
                found_time = le_str
                break

        if found_time:
            available_soon.append({
                "site": site_name,
                "earliest_time": found_time,
                "freeing_slices": freeing_slices,
                "projected_cores": projected.get("cores", 0),
                "projected_ram": projected.get("ram", 0),
            })
        else:
            not_available.append({
                "site": site_name,
                "reason": "Cannot project sufficient resources from known lease expirations",
            })

    return {
        "available_now": available_now,
        "available_soon": available_soon,
        "not_available": not_available,
    }


# ---------------------------------------------------------------------------
# GET /api/schedule/alternatives
# ---------------------------------------------------------------------------

@router.get("/schedule/alternatives")
async def get_alternatives(
    cores: int = Query(0, ge=0),
    ram: int = Query(0, ge=0),
    disk: int = Query(0, ge=0),
    gpu: str = Query(""),
    preferred_site: str = Query(""),
):
    """Find alternative ways to meet resource requirements.

    Suggests different sites, reduced configurations, or wait times.
    """
    if cores == 0 and ram == 0 and disk == 0 and not gpu:
        raise HTTPException(
            status_code=400,
            detail="At least one resource constraint (cores, ram, disk, gpu) is required",
        )

    sites_data = get_cached_sites()
    try:
        active_slices = await _get_active_slices()
    except Exception:
        logger.warning("Failed to fetch active slices", exc_info=True)
        active_slices = []

    requested = {"cores": cores, "ram": ram, "disk": disk}
    if gpu:
        requested["gpu"] = gpu

    # Check preferred site
    preferred_available = False
    preferred_site_data = None
    if preferred_site:
        for s in sites_data:
            if s.get("name") == preferred_site and s.get("state") == "Active":
                preferred_site_data = s
                avail = _site_available(s)
                if _meets_requirements(avail, cores, ram, disk, s, gpu):
                    preferred_available = True
                break

    # If preferred site is available, return early
    if preferred_available:
        return {
            "requested": requested,
            "preferred_site": preferred_site,
            "preferred_available": True,
            "alternatives": [],
        }

    alternatives: list[dict[str, Any]] = []

    # 1. Search all other sites for exact match
    for s in sites_data:
        site_name = s.get("name", "")
        state = s.get("state", "")
        if state != "Active":
            continue
        if site_name == preferred_site:
            continue

        avail = _site_available(s)
        if _meets_requirements(avail, cores, ram, disk, s, gpu):
            alternatives.append({
                "type": "different_site",
                "site": site_name,
                "available_now": True,
                "cores_available": avail["cores"],
                "ram_available": avail["ram"],
                "has_requested_gpu": _site_has_component(s, gpu) if gpu else True,
            })

    # 2. For preferred site, compute reduced configs that fit
    if preferred_site_data and not preferred_available:
        avail = _site_available(preferred_site_data)
        # Try halving cores
        if cores > 0:
            reduced_cores = cores // 2
            if reduced_cores > 0 and _meets_requirements(
                avail, reduced_cores, ram, disk, preferred_site_data, gpu
            ):
                alternatives.append({
                    "type": "reduced_config",
                    "site": preferred_site,
                    "suggestion": f"Reduce to {reduced_cores} cores, {ram} GB RAM",
                    "available_now": True,
                    "cores_available": avail["cores"],
                    "ram_available": avail["ram"],
                })
        # Try halving RAM
        if ram > 0:
            reduced_ram = ram // 2
            if reduced_ram > 0 and _meets_requirements(
                avail, cores, reduced_ram, disk, preferred_site_data, gpu
            ):
                alternatives.append({
                    "type": "reduced_config",
                    "site": preferred_site,
                    "suggestion": f"Reduce to {cores} cores, {reduced_ram} GB RAM",
                    "available_now": True,
                    "cores_available": avail["cores"],
                    "ram_available": avail["ram"],
                })
        # Try halving both
        if cores > 0 and ram > 0:
            reduced_cores = cores // 2
            reduced_ram = ram // 2
            if reduced_cores > 0 and reduced_ram > 0 and _meets_requirements(
                avail, reduced_cores, reduced_ram, disk, preferred_site_data, gpu
            ):
                # Only add if we haven't already found single reductions
                already_found = any(
                    a["type"] == "reduced_config" and a["site"] == preferred_site
                    for a in alternatives
                )
                if not already_found:
                    alternatives.append({
                        "type": "reduced_config",
                        "site": preferred_site,
                        "suggestion": f"Reduce to {reduced_cores} cores, {reduced_ram} GB RAM",
                        "available_now": True,
                        "cores_available": avail["cores"],
                        "ram_available": avail["ram"],
                    })

    # 3. Compute wait time at preferred site (reuse next-available logic)
    if preferred_site_data and not preferred_available:
        site_name = preferred_site
        avail = _site_available(preferred_site_data)

        # Collect slices at this site with lease_end
        site_slice_nodes: list[dict[str, Any]] = []
        for sl in active_slices:
            lease_end_str = sl.get("lease_end", "")
            lease_end_dt = _parse_iso(lease_end_str)
            if not lease_end_dt:
                continue
            for node in sl.get("nodes", []):
                if node.get("site") == site_name:
                    site_slice_nodes.append({
                        "slice_name": sl.get("name", ""),
                        "lease_end": lease_end_str,
                        "lease_end_dt": lease_end_dt,
                        "cores": node.get("cores", 0),
                        "ram": node.get("ram", 0),
                        "disk": node.get("disk", 0),
                    })

        site_slice_nodes.sort(key=lambda x: x["lease_end_dt"])

        projected = dict(avail)
        found_time = None
        freeing_names: list[str] = []

        seen_times: dict[str, list[dict]] = {}
        for sn in site_slice_nodes:
            seen_times.setdefault(sn["lease_end"], []).append(sn)

        for le_str in sorted(seen_times.keys()):
            group = seen_times[le_str]
            batch_slices = set()
            for sn in group:
                projected["cores"] = projected.get("cores", 0) + sn["cores"]
                projected["ram"] = projected.get("ram", 0) + sn["ram"]
                projected["disk"] = projected.get("disk", 0) + sn["disk"]
                batch_slices.add(sn["slice_name"])

            freeing_names.extend(batch_slices)

            gpu_ok = gpu == "" or _site_has_component(preferred_site_data, gpu)
            if (projected.get("cores", 0) >= cores and
                    projected.get("ram", 0) >= ram and
                    projected.get("disk", 0) >= disk and
                    gpu_ok):
                found_time = le_str
                break

        if found_time:
            alternatives.append({
                "type": "wait",
                "site": preferred_site,
                "earliest_time": found_time,
                "freeing_slices": freeing_names,
            })

    # Sort: available_now first (different_site, reduced_config), then wait
    type_order = {"different_site": 0, "reduced_config": 1, "wait": 2}
    alternatives.sort(key=lambda a: type_order.get(a.get("type", ""), 99))

    return {
        "requested": requested,
        "preferred_site": preferred_site,
        "preferred_available": False,
        "alternatives": alternatives,
    }


# ---------------------------------------------------------------------------
# POST /api/schedule/reservations — create a future reservation
# ---------------------------------------------------------------------------

@router.post("/schedule/reservations")
async def create_reservation(body: dict):
    """Create a future reservation for a scheduled slice submission."""
    slice_name = body.get("slice_name")
    scheduled_time = body.get("scheduled_time")
    if not slice_name or not scheduled_time:
        raise HTTPException(
            status_code=400,
            detail="slice_name and scheduled_time are required",
        )

    from app.reservation_manager import add_reservation

    reservation = add_reservation({
        "slice_name": slice_name,
        "scheduled_time": scheduled_time,
        "duration_hours": body.get("duration_hours", 24),
        "auto_submit": body.get("auto_submit", True),
    })
    return reservation


# ---------------------------------------------------------------------------
# GET /api/schedule/reservations — list all reservations
# ---------------------------------------------------------------------------

@router.get("/schedule/reservations")
async def list_reservations():
    """List all reservations."""
    from app.reservation_manager import load_reservations

    return load_reservations()


# ---------------------------------------------------------------------------
# DELETE /api/schedule/reservations/{id} — cancel a reservation
# ---------------------------------------------------------------------------

@router.delete("/schedule/reservations/{reservation_id}")
async def delete_reservation(reservation_id: str):
    """Cancel a pending reservation."""
    from app.reservation_manager import cancel_reservation

    if not cancel_reservation(reservation_id):
        raise HTTPException(status_code=404, detail="Reservation not found")
    return {"status": "cancelled", "id": reservation_id}
