"""Resource and site information API routes."""

from __future__ import annotations
import ast
import logging
import threading
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.fablib_manager import get_fablib
from app.fablib_executor import run_in_fablib_pool
from app.fabric_call_manager import get_call_manager, CacheEntry

logger = logging.getLogger(__name__)

router = APIRouter(tags=["resources"])

# Lock to serialize FABlib resource/topology calls (internal dicts mutate during iteration)
_fablib_lock = threading.Lock()

# Default TTL for resource caches (5 minutes)
_RESOURCE_TTL = 300

# FABRIC site GPS coordinates (from FABRIC API)
SITE_LOCATIONS: dict[str, dict[str, float]] = {
    "AMST": {"lat": 52.3545, "lon": 4.9558},
    "ATLA": {"lat": 33.7586, "lon": -84.3877},
    "BRIST": {"lat": 51.4571, "lon": -2.6073},
    "CERN": {"lat": 46.2339, "lon": 6.0470},
    "CIEN": {"lat": 45.4215, "lon": -75.6972},
    "CLEM": {"lat": 34.5865, "lon": -82.8213},
    "DALL": {"lat": 32.7991, "lon": -96.8207},
    "EDC": {"lat": 40.0958, "lon": -88.2415},
    "EDUKY": {"lat": 38.0325, "lon": -84.5028},
    "FIU": {"lat": 25.7543, "lon": -80.3703},
    "GATECH": {"lat": 33.7754, "lon": -84.3875},
    "GPN": {"lat": 39.0343, "lon": -94.5826},
    "HAWI": {"lat": 21.2990, "lon": -157.8164},
    "INDI": {"lat": 39.7737, "lon": -86.1675},
    "KANS": {"lat": 39.1005, "lon": -94.5823},
    "LOSA": {"lat": 34.0491, "lon": -118.2595},
    "MASS": {"lat": 42.2025, "lon": -72.6079},
    "MAX": {"lat": 38.9886, "lon": -76.9435},
    "MICH": {"lat": 42.2931, "lon": -83.7101},
    "NCSA": {"lat": 40.0958, "lon": -88.2415},
    "NEWY": {"lat": 40.7384, "lon": -73.9992},
    "PRIN": {"lat": 40.3461, "lon": -74.6161},
    "PSC": {"lat": 40.4344, "lon": -79.7502},
    "RUTG": {"lat": 40.5225, "lon": -74.4406},
    "SALT": {"lat": 40.7571, "lon": -111.9535},
    "SEAT": {"lat": 47.6144, "lon": -122.3389},
    "SRI": {"lat": 37.4566, "lon": -122.1747},
    "STAR": {"lat": 42.2360, "lon": -88.1575},
    "TACC": {"lat": 30.3899, "lon": -97.7262},
    "TOKY": {"lat": 35.7115, "lon": 139.7641},
    "UCSD": {"lat": 32.8887, "lon": -117.2393},
    "UTAH": {"lat": 40.7504, "lon": -111.8938},
    "WASH": {"lat": 38.9209, "lon": -77.2112},
}

# Available component models
COMPONENT_MODELS = [
    {"model": "NIC_Basic", "type": "SmartNIC", "description": "Basic 100Gbps NIC"},
    {"model": "NIC_ConnectX_5", "type": "SmartNIC", "description": "Mellanox ConnectX-5 25Gbps"},
    {"model": "NIC_ConnectX_6", "type": "SmartNIC", "description": "Mellanox ConnectX-6 100Gbps"},
    {"model": "NIC_ConnectX_7", "type": "SmartNIC", "description": "Mellanox ConnectX-7 100Gbps"},
    {"model": "GPU_TeslaT4", "type": "GPU", "description": "NVIDIA Tesla T4"},
    {"model": "GPU_RTX6000", "type": "GPU", "description": "NVIDIA RTX 6000"},
    {"model": "GPU_A30", "type": "GPU", "description": "NVIDIA A30"},
    {"model": "GPU_A40", "type": "GPU", "description": "NVIDIA A40"},
    {"model": "FPGA_Xilinx_U280", "type": "FPGA", "description": "Xilinx Alveo U280"},
    {"model": "NVME_P4510", "type": "Storage", "description": "Intel P4510 NVMe"},
    {"model": "NIC_ConnectX_7_100", "type": "SmartNIC", "description": "Mellanox ConnectX-7 100Gbps (dual port)"},
    {"model": "NIC_ConnectX_7_400", "type": "SmartNIC", "description": "Mellanox ConnectX-7 400Gbps"},
    {"model": "NIC_BlueField_2_ConnectX_6", "type": "SmartNIC", "description": "NVIDIA BlueField-2 DPU with ConnectX-6"},
    {"model": "FPGA_Xilinx_SN1022", "type": "FPGA", "description": "Xilinx SN1022 FPGA"},
]

# Available OS images
DEFAULT_IMAGES = [
    "default_ubuntu_22",
    "default_ubuntu_24",
    "default_ubuntu_20",
    "default_centos_8",
    "default_centos_9",
    "default_rocky_8",
    "default_rocky_9",
    "default_debian_11",
    "default_debian_12",
]


def _host_dict_to_detail(host: dict) -> dict[str, Any]:
    """Convert a ResourcesV2 host dict to our API host detail format."""
    host_components: dict[str, dict[str, int]] = {}
    comp_data = host.get("components", {})
    if isinstance(comp_data, dict):
        for model_name, comp_info in comp_data.items():
            if isinstance(comp_info, dict):
                cap = comp_info.get("capacity", 0) or 0
                if cap > 0:
                    host_components[model_name] = {
                        "capacity": cap,
                        "available": comp_info.get("available", 0) or 0,
                    }
    return {
        "name": host.get("name", ""),
        "cores_available": host.get("cores_available", 0) or 0,
        "cores_capacity": host.get("cores_capacity", 0) or 0,
        "ram_available": host.get("ram_available", 0) or 0,
        "ram_capacity": host.get("ram_capacity", 0) or 0,
        "disk_available": host.get("disk_available", 0) or 0,
        "disk_capacity": host.get("disk_capacity", 0) or 0,
        "components": host_components,
    }


def _site_dict_to_api(site: dict, hosts_data: list[dict]) -> dict[str, Any]:
    """Convert a ResourcesV2 site dict + its hosts to our API site format."""
    site_name = site.get("name", "")
    fallback = SITE_LOCATIONS.get(site_name, {"lat": 0, "lon": 0})

    # Extract components
    components: dict[str, dict[str, int]] = {}
    comp_data = site.get("components", {})
    if isinstance(comp_data, dict):
        for model_name, comp_info in comp_data.items():
            if isinstance(comp_info, dict):
                cap = comp_info.get("capacity", 0) or 0
                if cap > 0:
                    components[model_name] = {
                        "capacity": cap,
                        "allocated": comp_info.get("allocated", 0) or 0,
                        "available": comp_info.get("available", 0) or 0,
                    }

    # Host details for this site
    hosts_detail = [_host_dict_to_detail(h) for h in hosts_data if h.get("site") == site_name]

    # Recompute site-level totals from host data — the orchestrator's site-level
    # aggregates can be inaccurate (e.g., reporting 0 cores when hosts have cores).
    if hosts_detail:
        agg_cores_a = sum(h["cores_available"] for h in hosts_detail)
        agg_cores_c = sum(h["cores_capacity"] for h in hosts_detail)
        agg_ram_a = sum(h["ram_available"] for h in hosts_detail)
        agg_ram_c = sum(h["ram_capacity"] for h in hosts_detail)
        agg_disk_a = sum(h["disk_available"] for h in hosts_detail)
        agg_disk_c = sum(h["disk_capacity"] for h in hosts_detail)

        # Aggregate components from hosts
        agg_components: dict[str, dict[str, int]] = {}
        for h in hosts_detail:
            for model_name, comp_info in h.get("components", {}).items():
                if model_name not in agg_components:
                    agg_components[model_name] = {"capacity": 0, "allocated": 0, "available": 0}
                agg_components[model_name]["capacity"] += comp_info.get("capacity", 0)
                agg_components[model_name]["available"] += comp_info.get("available", 0)
            # allocated = capacity - available
        for v in agg_components.values():
            v["allocated"] = v["capacity"] - v["available"]

        # Also include components from site data that may not appear in host data
        for model_name, comp_info in components.items():
            if model_name not in agg_components:
                agg_components[model_name] = comp_info
    else:
        agg_cores_a = site.get("cores_available", 0) or 0
        agg_cores_c = site.get("cores_capacity", 0) or 0
        agg_ram_a = site.get("ram_available", 0) or 0
        agg_ram_c = site.get("ram_capacity", 0) or 0
        agg_disk_a = site.get("disk_available", 0) or 0
        agg_disk_c = site.get("disk_capacity", 0) or 0
        agg_components = components

    loc = site.get("location", [0, 0])
    lat = loc[0] if isinstance(loc, (list, tuple)) and len(loc) >= 2 else fallback["lat"]
    lon = loc[1] if isinstance(loc, (list, tuple)) and len(loc) >= 2 else fallback["lon"]

    return {
        "name": site_name,
        "lat": lat,
        "lon": lon,
        "state": site.get("state", "Active"),
        "hosts": site.get("hosts_count", site.get("hosts", 0)) or 0,
        "cores_available": agg_cores_a,
        "cores_capacity": agg_cores_c,
        "ram_available": agg_ram_a,
        "ram_capacity": agg_ram_c,
        "disk_available": agg_disk_a,
        "disk_capacity": agg_disk_c,
        "components": agg_components,
        "hosts_detail": hosts_detail,
    }


def _fetch_sites_sync() -> list[dict[str, Any]]:
    """Fetch sites from FABlib using ResourcesV2 data APIs (plain dicts).

    Uses list_sites() and _hosts_data instead of iterating FIM topology
    objects, avoiding thread-safety issues with the NetworkX graph.
    """
    fablib = get_fablib()
    resources = fablib.get_resources()

    # ResourcesV2: _sites_data is a list of dicts, _hosts_data likewise
    hosts_data = getattr(resources, '_hosts_data', []) or []

    sites = []
    for site_name in list(resources.get_site_names()):
        site = resources.get_site(site_name)
        if site is None:
            continue
        if isinstance(site, dict):
            sites.append(_site_dict_to_api(site, hosts_data))
        else:
            # Fallback for non-dict (shouldn't happen with ResourcesV2)
            sites.append({"name": site_name, "state": "Unknown"})
    return sites


def _fetch_sites_locked() -> list[dict[str, Any]]:
    """Fetch sites with lock held (used as call manager fetcher)."""
    with _fablib_lock:
        return _fetch_sites_sync()


def get_cached_sites() -> list[dict[str, Any]]:
    """Return cached sites data, fetching fresh if cache is empty.

    This is used by the site resolver so it doesn't duplicate FABlib calls.
    Safe to call from a synchronous context (e.g. inside asyncio.to_thread).

    Reads directly from the call manager cache (safe under GIL).
    Falls back to a locked fetch if no cached data exists.
    """
    mgr = get_call_manager()
    entry = mgr._cache.get("sites")
    if entry is not None and entry.data is not None:
        return entry.data
    # No cache — must block and fetch
    result = _fetch_sites_locked()
    # Store in call manager cache for future use
    if "sites" not in mgr._cache:
        mgr._cache["sites"] = CacheEntry()
    mgr._cache["sites"].data = result
    mgr._cache["sites"].timestamp = time.time()
    return result


def get_fresh_sites() -> list[dict[str, Any]]:
    """Force-refresh site data, bypassing cache.

    Used before slice submission to ensure site assignments are based on
    current resource availability including host-level data.
    Safe to call from a synchronous context (e.g. inside asyncio.to_thread).
    """
    mgr = get_call_manager()
    mgr.invalidate("sites")
    result = _fetch_sites_locked()
    # Update call manager cache
    if "sites" not in mgr._cache:
        mgr._cache["sites"] = CacheEntry()
    mgr._cache["sites"].data = result
    mgr._cache["sites"].timestamp = time.time()
    return result


@router.get("/sites")
async def list_sites(max_age: float = Query(_RESOURCE_TTL, ge=0)) -> list[dict[str, Any]]:
    """List all FABRIC sites with location and availability.

    Uses stale-while-revalidate via the unified call manager.
    """
    mgr = get_call_manager()
    return await mgr.get(
        "sites",
        fetcher=_fetch_sites_locked,
        max_age=max_age,
        stale_while_revalidate=(max_age > 0),
    )


def _fetch_links_locked() -> list[dict[str, Any]]:
    """Fetch backbone links using ResourcesV2 _links_data (plain dicts).

    Each link dict has a ``sites`` list (e.g. ['CERN', 'AMST']) plus
    bandwidth info.  No FIM topology iteration needed.
    """
    with _fablib_lock:
        fablib = get_fablib()
        resources = fablib.get_resources()
        raw = getattr(resources, '_links_data', None)
        if raw is None:
            raw = resources.list_links(output='list') or []
        seen: set[tuple[str, str]] = set()
        links = []
        for link in raw:
            sites = link.get("sites", [])
            if len(sites) < 2:
                continue
            site_a, site_b = sites[0].upper(), sites[1].upper()
            if site_a == site_b:
                continue
            pair = tuple(sorted([site_a, site_b]))
            if pair in seen:
                continue
            seen.add(pair)
            links.append({
                "site_a": pair[0],
                "site_b": pair[1],
                "bandwidth": link.get("bandwidth", 0),
                "available_bandwidth": link.get("available_bandwidth", 0),
                "layer": link.get("layer", ""),
            })
        return links


@router.get("/links")
async def list_links(max_age: float = Query(_RESOURCE_TTL, ge=0)) -> list[dict[str, Any]]:
    """List unique FABRIC backbone links between sites."""
    mgr = get_call_manager()
    return await mgr.get(
        "links",
        fetcher=_fetch_links_locked,
        max_age=max_age,
        stale_while_revalidate=(max_age > 0),
    )




@router.get("/sites/{site_name}/hosts")
async def list_site_hosts(site_name: str) -> list[dict[str, Any]]:
    """Get per-host resource availability for a site."""
    # Try cached data first (from call manager)
    mgr = get_call_manager()
    entry = mgr._cache.get("sites")
    if entry is not None and entry.data is not None:
        for site in entry.data:
            if site.get("name") == site_name:
                return site.get("hosts_detail", [])

    def _do():
        with _fablib_lock:
            fablib = get_fablib()
            resources = fablib.get_resources()
            hosts_map = resources.get_hosts_by_site(site_name)
            if not hosts_map:
                return []
            host_dicts = hosts_map.values() if isinstance(hosts_map, dict) else hosts_map
            return [_host_dict_to_detail(h) for h in host_dicts if isinstance(h, dict)]
    try:
        return await run_in_fablib_pool(_do)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sites/{site_name}")
async def get_site_detail(site_name: str) -> dict[str, Any]:
    """Get detailed site info including per-component resource allocation."""
    def _do():
        with _fablib_lock:
            fablib = get_fablib()
            resources = fablib.get_resources()
            site = resources.get_site(site_name)
            if site is None:
                raise HTTPException(status_code=404, detail=f"Site '{site_name}' not found")
            location = SITE_LOCATIONS.get(site_name, {"lat": 0, "lon": 0})

            components: dict[str, dict[str, int]] = {}
            comp_data = site.get("components", {})
            if isinstance(comp_data, dict):
                for model_name, comp_info in comp_data.items():
                    if isinstance(comp_info, dict):
                        cap = comp_info.get("capacity", 0) or 0
                        if cap > 0:
                            components[model_name] = {
                                "capacity": cap,
                                "allocated": comp_info.get("allocated", 0) or 0,
                                "available": comp_info.get("available", 0) or 0,
                            }

            # Fetch host data and recompute site totals from hosts
            # (orchestrator site-level aggregates can be inaccurate)
            hosts_data = getattr(resources, '_hosts_data', []) or []
            hosts_detail = [_host_dict_to_detail(h) for h in hosts_data if h.get("site") == site_name]

            if hosts_detail:
                agg_cores_a = sum(h["cores_available"] for h in hosts_detail)
                agg_cores_c = sum(h["cores_capacity"] for h in hosts_detail)
                agg_ram_a = sum(h["ram_available"] for h in hosts_detail)
                agg_ram_c = sum(h["ram_capacity"] for h in hosts_detail)
                agg_disk_a = sum(h["disk_available"] for h in hosts_detail)
                agg_disk_c = sum(h["disk_capacity"] for h in hosts_detail)

                agg_components: dict[str, dict[str, int]] = {}
                for h in hosts_detail:
                    for mn, ci in h.get("components", {}).items():
                        if mn not in agg_components:
                            agg_components[mn] = {"capacity": 0, "allocated": 0, "available": 0}
                        agg_components[mn]["capacity"] += ci.get("capacity", 0)
                        agg_components[mn]["available"] += ci.get("available", 0)
                for v in agg_components.values():
                    v["allocated"] = v["capacity"] - v["available"]
                for mn, ci in components.items():
                    if mn not in agg_components:
                        agg_components[mn] = ci
            else:
                agg_cores_a = site.get("cores_available", 0) or 0
                agg_cores_c = site.get("cores_capacity", 0) or 0
                agg_ram_a = site.get("ram_available", 0) or 0
                agg_ram_c = site.get("ram_capacity", 0) or 0
                agg_disk_a = site.get("disk_available", 0) or 0
                agg_disk_c = site.get("disk_capacity", 0) or 0
                agg_components = components

            loc = site.get("location", [0, 0])
            lat = loc[0] if isinstance(loc, (list, tuple)) and len(loc) >= 2 else location["lat"]
            lon = loc[1] if isinstance(loc, (list, tuple)) and len(loc) >= 2 else location["lon"]

            return {
                "name": site_name,
                "lat": lat,
                "lon": lon,
                "state": site.get("state", "Active"),
                "hosts": site.get("hosts_count", site.get("hosts", 0)) or 0,
                "cores_available": agg_cores_a,
                "cores_capacity": agg_cores_c,
                "cores_allocated": agg_cores_c - agg_cores_a,
                "ram_available": agg_ram_a,
                "ram_capacity": agg_ram_c,
                "ram_allocated": agg_ram_c - agg_ram_a,
                "disk_available": agg_disk_a,
                "disk_capacity": agg_disk_c,
                "disk_allocated": agg_disk_c - agg_disk_a,
                "components": agg_components,
            }
    try:
        return await run_in_fablib_pool(_do)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/resources")
async def get_resources() -> dict[str, Any]:
    """Get resource availability across all sites."""
    def _do():
        with _fablib_lock:
            fablib = get_fablib()
            resources = fablib.get_resources()
            hosts_data = getattr(resources, '_hosts_data', []) or []
            result = {}
            for site_name in list(resources.get_site_names()):
                try:
                    site = resources.get_site(site_name)
                    if site is None:
                        continue
                    # Recompute from hosts for accuracy
                    site_hosts = [_host_dict_to_detail(h) for h in hosts_data if h.get("site") == site_name]
                    if site_hosts:
                        result[site_name] = {
                            "cores_available": sum(h["cores_available"] for h in site_hosts),
                            "cores_capacity": sum(h["cores_capacity"] for h in site_hosts),
                            "ram_available": sum(h["ram_available"] for h in site_hosts),
                            "ram_capacity": sum(h["ram_capacity"] for h in site_hosts),
                            "disk_available": sum(h["disk_available"] for h in site_hosts),
                            "disk_capacity": sum(h["disk_capacity"] for h in site_hosts),
                        }
                    else:
                        result[site_name] = {
                            "cores_available": site.get("cores_available", 0) or 0,
                            "cores_capacity": site.get("cores_capacity", 0) or 0,
                            "ram_available": site.get("ram_available", 0) or 0,
                            "ram_capacity": site.get("ram_capacity", 0) or 0,
                            "disk_available": site.get("disk_available", 0) or 0,
                            "disk_capacity": site.get("disk_capacity", 0) or 0,
                        }
                except Exception:
                    result[site_name] = {"error": "unavailable"}
            return result
    try:
        return await run_in_fablib_pool(_do)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _fetch_facility_ports_locked() -> list[dict[str, Any]]:
    """Fetch facility ports using ResourcesV2 _facility_ports_data (plain dicts).

    No FIM topology iteration needed — all data comes from the REST API
    response cached in ResourcesV2.
    """
    with _fablib_lock:
        fablib = get_fablib()
        resources = fablib.get_resources()
        raw = getattr(resources, '_facility_ports_data', None)
        if raw is None:
            # Fallback: use the old FacilityPorts object
            fp_obj = fablib.get_facility_ports()
            raw = getattr(fp_obj, '_facility_ports_data', None)
            if raw is None:
                raw = fp_obj.list_facility_ports(output='list') or []

        result = []
        for fp in raw:
            fp_name = fp.get("name", "")
            switch = fp.get("switch", "")
            local_name = switch.split(":")[-1] if ":" in switch else switch
            vlans_raw = fp.get("vlans", "")
            if isinstance(vlans_raw, list):
                vlan_range = vlans_raw
            elif isinstance(vlans_raw, str) and vlans_raw.startswith("["):
                try:
                    vlan_range = ast.literal_eval(vlans_raw)
                except Exception:
                    vlan_range = [vlans_raw]
            else:
                vlan_range = [vlans_raw] if vlans_raw else []

            result.append({
                "name": fp_name,
                "site": fp.get("site", ""),
                "interfaces": [{
                    "name": fp.get("port", ""),
                    "vlan_range": vlan_range,
                    "local_name": local_name,
                    "device_name": "",
                    "allocated_vlans": [],
                    "region": "",
                }],
            })
        return result


@router.get("/facility-ports")
async def list_facility_ports(max_age: float = Query(_RESOURCE_TTL, ge=0)) -> list[dict[str, Any]]:
    """List available FABRIC facility ports with VLAN availability."""
    mgr = get_call_manager()
    return await mgr.get(
        "facility_ports",
        fetcher=_fetch_facility_ports_locked,
        max_age=max_age,
        stale_while_revalidate=(max_age > 0),
    )


@router.get("/images")
async def list_images() -> list[str]:
    """List available VM images."""
    return DEFAULT_IMAGES


@router.get("/component-models")
async def list_component_models() -> list[dict[str, str]]:
    """List available component models."""
    return COMPONENT_MODELS


