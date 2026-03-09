"""Resource and site information API routes."""

from __future__ import annotations
import asyncio
import threading
import time
from typing import Any

from fastapi import APIRouter, HTTPException

from app.fablib_manager import get_fablib

router = APIRouter(tags=["resources"])

# Lock to serialize FABlib resource/topology calls (internal dicts mutate during iteration)
_fablib_lock = threading.Lock()

# Simple cache for expensive topology queries
_cache: dict[str, tuple[float, Any]] = {}
CACHE_TTL = 300  # 5 minutes

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


def _fetch_host_details_v2(resources, site_name: str) -> list[dict[str, Any]]:
    """Fetch per-host resource details for a site (FABlib v2 dict format)."""
    hosts_detail: list[dict[str, Any]] = []
    try:
        hosts_map = resources.get_hosts_by_site(site_name)
    except Exception:
        return hosts_detail
    if not hosts_map:
        return hosts_detail
    host_dicts = hosts_map.values() if isinstance(hosts_map, dict) else hosts_map
    for host in host_dicts:
        if not isinstance(host, dict):
            continue
        host_info: dict[str, Any] = {
            "name": host.get("name", ""),
            "cores_available": host.get("cores_available", 0) or 0,
            "cores_capacity": host.get("cores_capacity", 0) or 0,
            "ram_available": host.get("ram_available", 0) or 0,
            "ram_capacity": host.get("ram_capacity", 0) or 0,
            "disk_available": host.get("disk_available", 0) or 0,
            "disk_capacity": host.get("disk_capacity", 0) or 0,
        }
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
        host_info["components"] = host_components
        hosts_detail.append(host_info)
    return hosts_detail


def _fetch_sites_sync() -> list[dict[str, Any]]:
    """Fetch sites from FABlib (synchronous, must hold _fablib_lock).

    FABlib v2 returns site/host data as dicts rather than objects.
    """
    fablib = get_fablib()
    resources = fablib.get_resources()
    sites = []
    for site_name in list(resources.get_site_names()):
        site = resources.get_site(site_name)
        if site is None:
            continue
        location = SITE_LOCATIONS.get(site_name, {"lat": 0, "lon": 0})

        # In FABlib v2, site is a dict with keys like cores_available, etc.
        if isinstance(site, dict):
            # Extract components from the dict
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

            hosts_detail = _fetch_host_details_v2(resources, site_name)

            loc = site.get("location", [0, 0])
            lat = loc[0] if isinstance(loc, (list, tuple)) and len(loc) >= 2 else location["lat"]
            lon = loc[1] if isinstance(loc, (list, tuple)) and len(loc) >= 2 else location["lon"]

            sites.append({
                "name": site_name,
                "lat": lat,
                "lon": lon,
                "state": site.get("state", "Active"),
                "hosts": site.get("hosts_count", 0) or 0,
                "cores_available": site.get("cores_available", 0) or 0,
                "cores_capacity": site.get("cores_capacity", 0) or 0,
                "ram_available": site.get("ram_available", 0) or 0,
                "ram_capacity": site.get("ram_capacity", 0) or 0,
                "disk_available": site.get("disk_available", 0) or 0,
                "disk_capacity": site.get("disk_capacity", 0) or 0,
                "components": components,
                "hosts_detail": hosts_detail,
            })
        else:
            # Legacy FABlib v1 path — site is an object with methods
            components = {}
            for model_name, display_name in COMPONENT_QUERY_MODELS:
                try:
                    capacity = site.get_component_capacity(model_name)
                    if capacity and capacity > 0:
                        allocated = site.get_component_allocated(model_name) or 0
                        available = site.get_component_available(model_name) or 0
                        components[model_name] = {
                            "capacity": capacity,
                            "allocated": allocated,
                            "available": available,
                        }
                except Exception:
                    continue

            hosts_detail = _fetch_host_details_v1(site)

            sites.append({
                "name": site_name,
                "lat": location["lat"],
                "lon": location["lon"],
                "state": str(site.get_state()) if hasattr(site, "get_state") else "Active",
                "hosts": _safe_count(site, "get_hosts"),
                "cores_available": _safe_attr(site, "get_core_available", 0),
                "cores_capacity": _safe_attr(site, "get_core_capacity", 0),
                "ram_available": _safe_attr(site, "get_ram_available", 0),
                "ram_capacity": _safe_attr(site, "get_ram_capacity", 0),
                "disk_available": _safe_attr(site, "get_disk_available", 0),
                "disk_capacity": _safe_attr(site, "get_disk_capacity", 0),
                "components": components,
                "hosts_detail": hosts_detail,
            })
    _cache["sites"] = (time.time(), sites)
    return sites


def _fetch_host_details_v1(site) -> list[dict[str, Any]]:
    """Fetch per-host resource details (legacy FABlib v1 object format)."""
    hosts_detail: list[dict[str, Any]] = []
    try:
        hosts = site.get_hosts()
    except Exception:
        return hosts_detail
    for host in hosts:
        host_info: dict[str, Any] = {
            "name": str(getattr(host, "name", "")),
            "cores_available": _safe_attr(host, "get_core_available", 0),
            "cores_capacity": _safe_attr(host, "get_core_capacity", 0),
            "ram_available": _safe_attr(host, "get_ram_available", 0),
            "ram_capacity": _safe_attr(host, "get_ram_capacity", 0),
            "disk_available": _safe_attr(host, "get_disk_available", 0),
            "disk_capacity": _safe_attr(host, "get_disk_capacity", 0),
        }
        host_components: dict[str, dict[str, int]] = {}
        for model_name, display_name in COMPONENT_QUERY_MODELS:
            try:
                cap = host.get_component_capacity(model_name)
                if cap and cap > 0:
                    avail = host.get_component_available(model_name) or 0
                    host_components[model_name] = {
                        "capacity": cap,
                        "available": avail,
                    }
            except Exception:
                continue
        host_info["components"] = host_components
        hosts_detail.append(host_info)
    return hosts_detail


def get_cached_sites() -> list[dict[str, Any]]:
    """Return cached sites data, fetching fresh if cache is stale or empty.

    This is used by the site resolver so it doesn't duplicate FABlib calls.
    Safe to call from a synchronous context (e.g. inside asyncio.to_thread).
    """
    cached = _cache.get("sites")
    if cached and time.time() - cached[0] < CACHE_TTL:
        return cached[1]
    with _fablib_lock:
        # Double-check after acquiring lock
        cached = _cache.get("sites")
        if cached and time.time() - cached[0] < CACHE_TTL:
            return cached[1]
        return _fetch_sites_sync()


def get_fresh_sites() -> list[dict[str, Any]]:
    """Force-refresh site data, bypassing cache.

    Used before slice submission to ensure site assignments are based on
    current resource availability including host-level data.
    Safe to call from a synchronous context (e.g. inside asyncio.to_thread).
    """
    with _fablib_lock:
        return _fetch_sites_sync()


@router.get("/sites")
async def list_sites() -> list[dict[str, Any]]:
    """List all FABRIC sites with location and availability."""
    cached = _cache.get("sites")
    if cached and time.time() - cached[0] < CACHE_TTL:
        return cached[1]

    def _do():
        with _fablib_lock:
            return _fetch_sites_sync()
    try:
        return await asyncio.to_thread(_do)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/links")
async def list_links() -> list[dict[str, Any]]:
    """List unique FABRIC backbone links between sites."""
    import re

    cached = _cache.get("links")
    if cached and time.time() - cached[0] < CACHE_TTL:
        return cached[1]

    def _do():
        with _fablib_lock:
            fablib = get_fablib()
            resources = fablib.get_resources()
            topo = resources.get_topology()
            seen: set[tuple[str, str]] = set()
            links = []
            for link in list(topo.links.values()):
                try:
                    parts = re.findall(r"port\+(\w+)-data-sw:", link.name)
                    if len(parts) < 2:
                        continue
                    site_a, site_b = parts[0].upper(), parts[1].upper()
                    if site_a == site_b:
                        continue
                    pair = tuple(sorted([site_a, site_b]))
                    if pair in seen:
                        continue
                    seen.add(pair)
                    links.append({
                        "site_a": pair[0],
                        "site_b": pair[1],
                    })
                except Exception:
                    continue
            _cache["links"] = (time.time(), links)
            return links
    try:
        return await asyncio.to_thread(_do)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


COMPONENT_QUERY_MODELS = [
    ("SharedNIC-ConnectX-6", "SharedNIC ConnectX-6"),
    ("SmartNIC-ConnectX-5", "SmartNIC ConnectX-5"),
    ("SmartNIC-ConnectX-6", "SmartNIC ConnectX-6"),
    ("SmartNIC-ConnectX-7", "SmartNIC ConnectX-7"),
    ("GPU-Tesla T4", "GPU Tesla T4"),
    ("GPU-RTX6000", "GPU RTX6000"),
    ("GPU-A30", "GPU A30"),
    ("GPU-A40", "GPU A40"),
    ("FPGA-Xilinx-U280", "FPGA Xilinx U280"),
    ("NVME-P4510", "NVMe P4510"),
]


@router.get("/sites/{site_name}/hosts")
async def list_site_hosts(site_name: str) -> list[dict[str, Any]]:
    """Get per-host resource availability for a site."""
    # Try cached data first
    cached = _cache.get("sites")
    if cached and time.time() - cached[0] < CACHE_TTL:
        for site in cached[1]:
            if site.get("name") == site_name:
                return site.get("hosts_detail", [])

    def _do():
        with _fablib_lock:
            fablib = get_fablib()
            resources = fablib.get_resources()
            try:
                site = resources.get_site(site_name)
            except Exception:
                return []
            if isinstance(site, dict):
                return _fetch_host_details_v2(resources, site_name)
            return _fetch_host_details_v1(site)
    try:
        return await asyncio.to_thread(_do)
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

            if isinstance(site, dict):
                components: dict[str, dict[str, int]] = {}
                comp_data = site.get("components", {})
                if isinstance(comp_data, dict):
                    for model_name, comp_info in comp_data.items():
                        if isinstance(comp_info, dict):
                            cap = comp_info.get("capacity", 0) or 0
                            if cap > 0:
                                display = model_name
                                for mn, dn in COMPONENT_QUERY_MODELS:
                                    if mn == model_name:
                                        display = dn
                                        break
                                components[display] = {
                                    "capacity": cap,
                                    "allocated": comp_info.get("allocated", 0) or 0,
                                    "available": comp_info.get("available", 0) or 0,
                                }
                return {
                    "name": site_name,
                    "lat": location["lat"],
                    "lon": location["lon"],
                    "state": site.get("state", "Active"),
                    "hosts": site.get("hosts_count", 0) or 0,
                    "cores_available": site.get("cores_available", 0) or 0,
                    "cores_capacity": site.get("cores_capacity", 0) or 0,
                    "cores_allocated": site.get("cores_allocated", 0) or 0,
                    "ram_available": site.get("ram_available", 0) or 0,
                    "ram_capacity": site.get("ram_capacity", 0) or 0,
                    "ram_allocated": site.get("ram_allocated", 0) or 0,
                    "disk_available": site.get("disk_available", 0) or 0,
                    "disk_capacity": site.get("disk_capacity", 0) or 0,
                    "disk_allocated": site.get("disk_allocated", 0) or 0,
                    "components": components,
                }
            else:
                # Legacy FABlib v1
                components = {}
                for model_name, display_name in COMPONENT_QUERY_MODELS:
                    try:
                        capacity = site.get_component_capacity(model_name)
                        if capacity and capacity > 0:
                            allocated = site.get_component_allocated(model_name) or 0
                            available = site.get_component_available(model_name) or 0
                            components[display_name] = {
                                "capacity": capacity,
                                "allocated": allocated,
                                "available": available,
                            }
                    except Exception:
                        continue
                return {
                    "name": site_name,
                    "lat": location["lat"],
                    "lon": location["lon"],
                    "state": str(site.get_state()) if hasattr(site, "get_state") else "Active",
                    "hosts": _safe_count(site, "get_hosts"),
                    "cores_available": _safe_attr(site, "get_core_available", 0),
                    "cores_capacity": _safe_attr(site, "get_core_capacity", 0),
                    "cores_allocated": _safe_attr(site, "get_core_allocated", 0),
                    "ram_available": _safe_attr(site, "get_ram_available", 0),
                    "ram_capacity": _safe_attr(site, "get_ram_capacity", 0),
                    "ram_allocated": _safe_attr(site, "get_ram_allocated", 0),
                    "disk_available": _safe_attr(site, "get_disk_available", 0),
                    "disk_capacity": _safe_attr(site, "get_disk_capacity", 0),
                    "disk_allocated": _safe_attr(site, "get_disk_allocated", 0),
                    "components": components,
                }
    try:
        return await asyncio.to_thread(_do)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/resources")
async def get_resources() -> dict[str, Any]:
    """Get resource availability across all sites."""
    def _do():
        with _fablib_lock:
            fablib = get_fablib()
            resources = fablib.get_resources()
            result = {}
            for site_name in list(resources.get_site_names()):
                try:
                    site = resources.get_site(site_name)
                    if isinstance(site, dict):
                        result[site_name] = {
                            "cores_available": site.get("cores_available", 0) or 0,
                            "cores_capacity": site.get("cores_capacity", 0) or 0,
                            "ram_available": site.get("ram_available", 0) or 0,
                            "ram_capacity": site.get("ram_capacity", 0) or 0,
                            "disk_available": site.get("disk_available", 0) or 0,
                            "disk_capacity": site.get("disk_capacity", 0) or 0,
                        }
                    else:
                        result[site_name] = {
                            "cores_available": _safe_attr(site, "get_core_available"),
                            "cores_capacity": _safe_attr(site, "get_core_capacity"),
                            "ram_available": _safe_attr(site, "get_ram_available"),
                            "ram_capacity": _safe_attr(site, "get_ram_capacity"),
                            "disk_available": _safe_attr(site, "get_disk_available"),
                            "disk_capacity": _safe_attr(site, "get_disk_capacity"),
                        }
                except Exception:
                    result[site_name] = {"error": "unavailable"}
            return result
    try:
        return await asyncio.to_thread(_do)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/images")
async def list_images() -> list[str]:
    """List available VM images."""
    return DEFAULT_IMAGES


@router.get("/component-models")
async def list_component_models() -> list[dict[str, str]]:
    """List available component models."""
    return COMPONENT_MODELS


def _safe_attr(obj, method_name, default=None):
    try:
        return getattr(obj, method_name)()
    except Exception:
        return default


def _safe_count(obj, method_name):
    try:
        return len(getattr(obj, method_name)())
    except Exception:
        return 0
