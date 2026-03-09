"""Smart site resolution engine for FABRIC slices.

Resolves site specifications in node definitions:
- "@group"  — co-location group: all nodes in same group get same site
- "auto"    — any available site (no co-location constraint)
- "RENC"    — explicit site (honored as-is)

Uses the cached site availability data from resources.py rather than
making its own FABlib calls.
"""

from __future__ import annotations

import logging
import random
from typing import Any

logger = logging.getLogger(__name__)

# Map template component model names to the resource query names
# used by FABlib's site.get_component_available().
COMPONENT_RESOURCE_MAP = {
    "GPU_RTX6000": "GPU-RTX6000",
    "GPU_TeslaT4": "GPU-Tesla T4",
    "GPU_A30": "GPU-A30",
    "GPU_A40": "GPU-A40",
    "NIC_ConnectX_5": "SmartNIC-ConnectX-5",
    "NIC_ConnectX_6": "SmartNIC-ConnectX-6",
    "NIC_ConnectX_7": "SmartNIC-ConnectX-7",
    "FPGA_Xilinx_U280": "FPGA-Xilinx-U280",
    "NVME_P4510": "NVME-P4510",
}
# NIC_Basic uses SharedNIC — always available, skip checking


def _build_availability(sites: list[dict]) -> dict[str, dict[str, Any]]:
    """Convert the cached sites list (from resources.py) into a resolver
    availability map.

    Args:
        sites: List of site dicts as returned by get_cached_sites(), each
               having keys: name, state, cores_available, ram_available,
               disk_available, and optionally components and hosts_detail.

    Returns:
        {site_name: {cores, ram, disk, components: {model: available}, hosts: [...]}}
        Only includes Active sites.
    """
    availability: dict[str, dict[str, Any]] = {}
    for site in sites:
        state = site.get("state", "")
        if state != "Active":
            continue
        name = site.get("name", "")
        if not name:
            continue

        cores = _int_or(site.get("cores_available"), 0)
        ram = _int_or(site.get("ram_available"), 0)
        disk = _int_or(site.get("disk_available"), 0)

        # Component availability — populated if site detail was fetched
        components: dict[str, int] = {}
        site_components = site.get("components", {})
        for model, resource_name in COMPONENT_RESOURCE_MAP.items():
            comp_info = site_components.get(resource_name, {})
            components[model] = _int_or(comp_info.get("available"), 0)

        # Per-host detail for host-level feasibility checks
        hosts = []
        for h in site.get("hosts_detail", []):
            host_comps: dict[str, int] = {}
            for model, resource_name in COMPONENT_RESOURCE_MAP.items():
                comp_info = h.get("components", {}).get(resource_name, {})
                host_comps[model] = _int_or(comp_info.get("available"), 0)
            hosts.append({
                "name": h.get("name", ""),
                "cores": _int_or(h.get("cores_available"), 0),
                "ram": _int_or(h.get("ram_available"), 0),
                "disk": _int_or(h.get("disk_available"), 0),
                "components": host_comps,
            })

        availability[name] = {
            "cores": cores,
            "ram": ram,
            "disk": disk,
            "components": components,
            "hosts": hosts,
        }

    return availability


def _int_or(val, default: int) -> int:
    try:
        v = int(val)
        return v if v >= 0 else default
    except (TypeError, ValueError):
        return default


def _node_component_requirements(node_def: dict) -> dict[str, int]:
    """Extract component requirements from a node definition.

    Returns {model: count} for components that need availability checking.
    """
    reqs: dict[str, int] = {}
    for comp in node_def.get("components", []):
        model = comp.get("model", "")
        if model in COMPONENT_RESOURCE_MAP:
            reqs[model] = reqs.get(model, 0) + 1
    return reqs


def _host_can_fit(host: dict, cores: int, ram: int, disk: int,
                  comp_reqs: dict[str, int]) -> bool:
    """Check if a single host has enough resources for a node."""
    if host["cores"] < cores:
        return False
    if host["ram"] < ram:
        return False
    if host["disk"] < disk:
        return False
    for model, count in comp_reqs.items():
        if host["components"].get(model, 0) < count:
            return False
    return True


def _site_can_host(site_avail: dict, cores: int, ram: int, disk: int,
                   comp_reqs: dict[str, int]) -> bool:
    """Check if a site has enough resources for the given requirements.

    First does a quick site-level check, then validates that at least one
    host can actually fit the request (if host data is available).
    """
    if site_avail["cores"] < cores:
        return False
    if site_avail["ram"] < ram:
        return False
    if site_avail["disk"] < disk:
        return False
    for model, count in comp_reqs.items():
        if site_avail["components"].get(model, 0) < count:
            return False

    # Host-level validation: ensure at least one host can fit
    hosts = site_avail.get("hosts", [])
    if hosts:
        if not any(_host_can_fit(h, cores, ram, disk, comp_reqs) for h in hosts):
            return False

    return True


def _site_can_host_group(site_avail: dict, node_reqs: list[dict]) -> bool:
    """Check if a site can host a group of nodes.

    Site-level totals must fit, and each individual node must fit on at
    least one host at the site.
    """
    total_cores = sum(n["cores"] for n in node_reqs)
    total_ram = sum(n["ram"] for n in node_reqs)
    total_disk = sum(n["disk"] for n in node_reqs)
    total_comp: dict[str, int] = {}
    for n in node_reqs:
        for m, c in n.get("comp_reqs", {}).items():
            total_comp[m] = total_comp.get(m, 0) + c

    # Site-level check
    if not _site_can_host(site_avail, total_cores, total_ram, total_disk, total_comp):
        return False

    # Host-level per-node check: each node must fit on at least one host
    hosts = site_avail.get("hosts", [])
    if hosts:
        for n in node_reqs:
            if not any(_host_can_fit(h, n["cores"], n["ram"], n["disk"],
                                     n.get("comp_reqs", {})) for h in hosts):
                return False

    return True


def _subtract_resources(site_avail: dict, cores: int, ram: int, disk: int,
                        comp_reqs: dict[str, int]) -> None:
    """Subtract allocated resources from site availability (in-place)."""
    site_avail["cores"] -= cores
    site_avail["ram"] -= ram
    site_avail["disk"] -= disk
    for model, count in comp_reqs.items():
        site_avail["components"][model] = site_avail["components"].get(model, 0) - count


def resolve_sites(node_defs: list[dict], sites: list[dict]) -> tuple[list[dict], dict[str, str]]:
    """Resolve site specifications in node definitions using cached site data.

    Args:
        node_defs: List of node dicts with site, cores, ram, disk, components fields.
        sites: List of site dicts from get_cached_sites() — the already-loaded
               resource data with name, state, cores_available, etc.

    Returns:
        (resolved_node_defs, node_groups) where:
        - resolved_node_defs: node defs with concrete site names
        - node_groups: {node_name: "@group"} mapping for group members
    """
    node_defs = [dict(nd) for nd in node_defs]  # shallow copy
    node_groups: dict[str, str] = {}

    # Build availability map from cached site data
    availability = _build_availability(sites)
    if not availability:
        # Fallback: use site names from the list even if no Active sites
        fallback_sites = [s["name"] for s in sites if s.get("name")]
        if not fallback_sites:
            logger.error("Cannot resolve sites: no sites available")
            return node_defs, node_groups
        logger.warning("No active sites with availability; falling back to site name list (%d sites)", len(fallback_sites))
        return _fallback_resolve(node_defs, fallback_sites)

    active_sites = list(availability.keys())
    logger.info("Site resolver: %d active sites with availability data", len(active_sites))

    # Categorize nodes
    grouped: dict[str, list[int]] = {}   # "@group" -> [indices]
    auto_indices: list[int] = []
    for i, nd in enumerate(node_defs):
        site = nd.get("site", "")
        if isinstance(site, str) and site.startswith("@"):
            group = site
            node_groups[nd["name"]] = group
            grouped.setdefault(group, []).append(i)
        elif not site or site == "auto":
            auto_indices.append(i)
        # else: explicit site, keep as-is

    # Resolve groups — sorted by total resource demand (heaviest first)
    used_sites: set[str] = set()
    group_order = sorted(grouped.keys(), key=lambda g: _group_demand(node_defs, grouped[g]), reverse=True)

    for group in group_order:
        indices = grouped[group]
        total_cores = sum(node_defs[i].get("cores", 2) for i in indices)
        total_ram = sum(node_defs[i].get("ram", 8) for i in indices)
        total_disk = sum(node_defs[i].get("disk", 10) for i in indices)

        # Aggregate component requirements
        total_comp_reqs: dict[str, int] = {}
        for i in indices:
            for model, count in _node_component_requirements(node_defs[i]).items():
                total_comp_reqs[model] = total_comp_reqs.get(model, 0) + count

        # Build per-node requirement list for host-level group validation
        group_node_reqs = []
        for i in indices:
            group_node_reqs.append({
                "cores": node_defs[i].get("cores", 2),
                "ram": node_defs[i].get("ram", 8),
                "disk": node_defs[i].get("disk", 10),
                "comp_reqs": _node_component_requirements(node_defs[i]),
            })

        # Find candidate sites using host-level group validation
        candidates = []
        for site, avail in availability.items():
            if _site_can_host_group(avail, group_node_reqs):
                candidates.append(site)

        # Prefer sites not used by other groups (for multi-site templates)
        preferred = [s for s in candidates if s not in used_sites]
        pick_from = preferred if preferred else candidates

        if pick_from:
            chosen = random.choice(pick_from)
        elif candidates:
            chosen = random.choice(candidates)
        else:
            # Best-effort fallback: pick site with most cores
            chosen = max(availability, key=lambda s: availability[s]["cores"])
            logger.warning("Group %s: no site meets all requirements, falling back to %s", group, chosen)

        used_sites.add(chosen)
        for i in indices:
            node_defs[i]["site"] = chosen

        # Subtract allocated resources so subsequent groups see reduced availability
        if chosen in availability:
            _subtract_resources(availability[chosen], total_cores, total_ram, total_disk, total_comp_reqs)

        logger.info("Group %s: resolved to site %s (%d nodes, %d cores, %d GB RAM)",
                     group, chosen, len(indices), total_cores, total_ram)

    # Resolve auto nodes — heaviest first
    auto_order = sorted(auto_indices, key=lambda i: _node_demand(node_defs[i]), reverse=True)
    for i in auto_order:
        nd = node_defs[i]
        cores = nd.get("cores", 2)
        ram = nd.get("ram", 8)
        disk = nd.get("disk", 10)
        comp_reqs = _node_component_requirements(nd)

        candidates = [
            site for site, avail in availability.items()
            if _site_can_host(avail, cores, ram, disk, comp_reqs)
        ]

        if candidates:
            # Random choice among validated candidates to spread VMs across sites
            chosen = random.choice(candidates)
        else:
            # Best-effort fallback
            chosen = max(availability, key=lambda s: availability[s]["cores"])
            logger.warning("Auto node %s: no site meets requirements, falling back to %s", nd.get("name"), chosen)

        nd["site"] = chosen
        if chosen in availability:
            _subtract_resources(availability[chosen], cores, ram, disk, comp_reqs)

        logger.info("Auto node %s: resolved to site %s", nd.get("name"), chosen)

    return node_defs, node_groups


def _group_demand(node_defs: list[dict], indices: list[int]) -> int:
    """Total resource demand score for a group (for sorting)."""
    return sum(_node_demand(node_defs[i]) for i in indices)


def _node_demand(nd: dict) -> int:
    """Simple demand score for a node (cores + ram + disk)."""
    return nd.get("cores", 2) + nd.get("ram", 8) + nd.get("disk", 10)


def _fallback_resolve(node_defs: list[dict], sites: list[str]) -> tuple[list[dict], dict[str, str]]:
    """Fallback resolution without resource checking (random assignment)."""
    node_groups: dict[str, str] = {}
    group_map: dict[str, str] = {}
    used: set[str] = set()

    for nd in node_defs:
        site = nd.get("site", "")
        if isinstance(site, str) and site.startswith("@"):
            node_groups[nd["name"]] = site
            if site not in group_map:
                # Prefer unused site for different groups
                unused = [s for s in sites if s not in used]
                pick_from = unused if unused else sites
                group_map[site] = random.choice(pick_from)
                used.add(group_map[site])
            nd["site"] = group_map[site]
        elif not site or site == "auto":
            nd["site"] = random.choice(sites)

    return node_defs, node_groups
