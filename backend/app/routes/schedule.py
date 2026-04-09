"""Resource scheduling API routes.

Provides calendar views, next-available lookups, and alternative
resource suggestions by combining slice lease data with site availability.
Uses FABlib's ``find_resource_slot()`` for future availability projections.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from app.fablib_manager import get_fablib, is_configured
from app.fablib_executor import run_in_fablib_pool
from app.routes.resources import get_cached_sites
from app.site_resolver import COMPONENT_RESOURCE_MAP

logger = logging.getLogger(__name__)

router = APIRouter(tags=["schedule"])


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


def _build_resource_list(cores: int, ram: int, disk: int,
                         gpu: str = "", site: str = "") -> list[dict[str, Any]]:
    """Build a resource requirements list for ``find_resource_slot``."""
    resource: dict[str, Any] = {"type": "compute"}
    if site:
        resource["site"] = site
    if cores > 0:
        resource["cores"] = cores
    if ram > 0:
        resource["ram"] = ram
    if disk > 0:
        resource["disk"] = disk
    if gpu:
        resource["components"] = {gpu: 1}
    return [resource]


async def _find_slot_for_site(site_name: str, cores: int, ram: int,
                              disk: int, gpu: str) -> Optional[dict[str, Any]]:
    """Call ``find_resource_slot`` for a single site.

    Returns a dict with ``site`` and ``earliest_time`` if a slot is found,
    or ``None`` if no slot exists in the next 7 days.
    """
    now = datetime.now(timezone.utc)
    search_end = now + timedelta(days=7)
    resources = _build_resource_list(cores, ram, disk, gpu, site_name)

    req_desc = f"cores={cores} ram={ram} disk={disk}"
    if gpu:
        req_desc += f" gpu={gpu}"
    logger.info("find_resource_slot: searching %s (%s) over next 7 days",
                site_name, req_desc)

    def _call():
        return get_fablib().find_resource_slot(
            start=now, end=search_end, duration=24,
            resources=resources, max_results=1,
        )

    try:
        result = await run_in_fablib_pool(_call)
        slots = result.get("slots", [])
        if slots:
            slot = slots[0]
            earliest = slot.get("start", "")
            logger.info("find_resource_slot: %s — slot available at %s",
                        site_name, earliest)
            return {
                "site": site_name,
                "earliest_time": earliest,
            }
        else:
            logger.info("find_resource_slot: %s — no slots in next 7 days",
                        site_name)
    except Exception as exc:
        logger.warning("find_resource_slot: %s — failed: %s",
                       site_name, exc, exc_info=True)
    return None


# ---------------------------------------------------------------------------
# GET /api/schedule/calendar
# ---------------------------------------------------------------------------

@router.get("/schedule/calendar")
async def get_calendar(
    days: int = Query(14, ge=1, le=30),
    interval: str = Query("day", description="Granularity: hour, day, or week"),
    site: Optional[str] = Query(None, description="Comma-separated site names to include"),
    exclude_site: Optional[str] = Query(None, description="Comma-separated site names to exclude"),
    show: str = Query("sites", description="Resource level: sites, hosts, or all"),
):
    """Produce a resource availability calendar using FABlib's
    ``resources_calendar()`` API.

    Returns per-time-slot resource availability for sites (and optionally
    hosts), with configurable interval granularity (hour/day/week).
    """
    if interval not in ("hour", "day", "week"):
        raise HTTPException(status_code=400, detail="interval must be hour, day, or week")
    if show not in ("sites", "hosts", "all"):
        raise HTTPException(status_code=400, detail="show must be sites, hosts, or all")

    now = datetime.now(timezone.utc)
    end_time = now + timedelta(days=days)

    site_list = [s.strip() for s in site.split(",") if s.strip()] if site else None
    exclude_list = [s.strip() for s in exclude_site.split(",") if s.strip()] if exclude_site else None

    def _fetch():
        fablib = get_fablib()
        # Use the raw manager API to get structured calendar data
        # (fablib.resources_calendar() flattens into display rows)
        return fablib.get_manager().resources_calendar(
            start=now,
            end=end_time,
            interval=interval,
            site=site_list,
            exclude_site=exclude_list,
        )

    try:
        calendar_data = await run_in_fablib_pool(_fetch)
    except Exception:
        logger.warning("resources_calendar failed", exc_info=True)
        calendar_data = {"data": [], "interval": interval,
                         "query_start": now.isoformat(),
                         "query_end": end_time.isoformat(), "total": 0}

    # Filter to requested show level (sites/hosts/all)
    include_sites = show in ("all", "sites")
    include_hosts = show in ("all", "hosts")
    for slot in calendar_data.get("data", []):
        if not include_sites:
            slot.pop("sites", None)
        if not include_hosts:
            slot.pop("hosts", None)

    return calendar_data


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

    Uses cached site data for an instant "available now" check, then
    delegates to FABlib's ``find_resource_slot()`` (via the Reports API)
    for future availability projections.

    At least one resource constraint must be provided.
    """
    if cores == 0 and ram == 0 and disk == 0 and not gpu:
        raise HTTPException(
            status_code=400,
            detail="At least one resource constraint (cores, ram, disk, gpu) is required",
        )

    sites_data = get_cached_sites()

    # Filter to requested site if specified
    target_sites = sites_data
    if site:
        target_sites = [s for s in sites_data if s.get("name") == site]
        if not target_sites:
            raise HTTPException(status_code=404, detail=f"Site not found: {site}")

    available_now: list[dict[str, Any]] = []
    needs_slot_check: list[dict[str, Any]] = []
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

        needs_slot_check.append(s)

    # Use find_resource_slot for sites that have capacity but not enough now
    available_soon: list[dict[str, Any]] = []
    if needs_slot_check and is_configured():
        results = await asyncio.gather(
            *(_find_slot_for_site(s.get("name", ""), cores, ram, disk, gpu)
              for s in needs_slot_check),
            return_exceptions=True,
        )
        found_sites: set[str] = set()
        for r in results:
            if isinstance(r, dict) and r is not None:
                available_soon.append(r)
                found_sites.add(r["site"])
        for s in needs_slot_check:
            sn = s.get("name", "")
            if sn not in found_sites:
                not_available.append({
                    "site": sn,
                    "reason": "No available slot found in the next 7 days",
                })
    elif needs_slot_check:
        for s in needs_slot_check:
            not_available.append({
                "site": s.get("name", ""),
                "reason": "Cannot check future availability",
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

    # 3. Compute wait time at preferred site using find_resource_slot
    if preferred_site_data and not preferred_available and is_configured():
        slot_result = await _find_slot_for_site(
            preferred_site, cores, ram, disk, gpu,
        )
        if slot_result:
            alternatives.append({
                "type": "wait",
                "site": preferred_site,
                "earliest_time": slot_result["earliest_time"],
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
