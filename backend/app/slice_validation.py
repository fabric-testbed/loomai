"""Pure validation helpers for serialized FABRIC slice models."""

from __future__ import annotations

from typing import Any


FABNET_TYPE_LABELS = {
    "FABNetv4": "FABNetv4",
    "FABNetv6": "FABNetv6",
    "FABNetv4Ext": "FABNetv4Ext",
    "FABNetv6Ext": "FABNetv6Ext",
    "IPv4": "FABNetv4",
    "IPv6": "FABNetv6",
    "IPv4Ext": "FABNetv4Ext",
    "IPv6Ext": "FABNetv6Ext",
}


def network_type_label(net_type: Any) -> str:
    raw = str(net_type or "")
    return FABNET_TYPE_LABELS.get(raw, raw)


def build_node_site_indexes(nodes: list[dict[str, Any]]) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    node_sites: dict[str, str] = {}
    interface_sites: dict[str, tuple[str, str]] = {}
    for node in nodes:
        node_name = str(node.get("name") or "")
        site = str(node.get("site") or "")
        if node_name:
            node_sites[node_name] = site
        for iface in node.get("interfaces", []) or []:
            iface_name = str(iface.get("name") or "")
            if iface_name:
                interface_sites[iface_name] = (node_name, site)
        for comp in node.get("components", []) or []:
            for iface in comp.get("interfaces", []) or []:
                iface_name = str(iface.get("name") or "")
                if iface_name:
                    interface_sites[iface_name] = (node_name, site)
    return node_sites, interface_sites


def interface_node_name(iface: Any, node_names: list[str]) -> tuple[str, str]:
    if isinstance(iface, dict):
        iface_name = str(iface.get("name") or "")
        node_name = str(iface.get("node_name") or "")
    else:
        iface_name = str(iface or "")
        node_name = ""
    if not node_name and iface_name:
        for candidate in node_names:
            if iface_name == candidate or iface_name.startswith(f"{candidate}-"):
                node_name = candidate
                break
    return iface_name, node_name


def network_site_summary(
    net: dict[str, Any],
    node_sites: dict[str, str],
    interface_sites: dict[str, tuple[str, str]],
) -> tuple[list[str], int]:
    node_names = sorted(node_sites.keys(), key=len, reverse=True)
    sites: set[str] = set()
    attached_nodes: set[str] = set()
    for iface in net.get("interfaces", []) or []:
        iface_name, node_name = interface_node_name(iface, node_names)
        site = ""
        if iface_name in interface_sites:
            indexed_node, indexed_site = interface_sites[iface_name]
            node_name = node_name or indexed_node
            site = indexed_site
        if not site and node_name:
            site = node_sites.get(node_name, "")
        if node_name:
            attached_nodes.add(node_name)
        if site and site.lower() != "none":
            sites.add(site)
    return sorted(sites), len(attached_nodes)


def format_site_list(sites: list[str]) -> str:
    return ", ".join(sites) if sites else "no resolved sites"


def append_network_placement_issues(
    issues: list[dict[str, str]],
    nodes: list[dict[str, Any]],
    networks: list[dict[str, Any]],
) -> None:
    node_sites, interface_sites = build_node_site_indexes(nodes)
    for net in networks:
        net_name = str(net.get("name") or "?")
        raw_type = str(net.get("type") or "")
        net_type = network_type_label(raw_type)
        ifaces = net.get("interfaces", []) or []
        sites, attached_node_count = network_site_summary(net, node_sites, interface_sites)

        if raw_type in FABNET_TYPE_LABELS:
            if len(sites) > 1:
                issues.append({
                    "severity": "error",
                    "message": (
                        f"Network '{net_name}' ({net_type}) attaches interfaces at multiple sites "
                        f"({format_site_list(sites)}); FABNet services are one-site only."
                    ),
                    "remedy": (
                        f"Create one FABNet service per site for '{net_name}', or use add_fabnet "
                        "once per node; FABRIC routes between per-site services over "
                        "10.128.0.0/10 or 2602:fcfb::/40."
                    ),
                })
            if attached_node_count > 255:
                issues.append({
                    "severity": "error",
                    "message": (
                        f"Network '{net_name}' ({net_type}) attaches {attached_node_count} VM(s); "
                        "FABNet services support at most 255 VMs."
                    ),
                    "remedy": (
                        f"Split '{net_name}' into multiple FABNet services with at most 255 VMs "
                        "each, keeping every service within one site."
                    ),
                })
        elif raw_type == "L2Bridge" and len(sites) > 1:
            issues.append({
                "severity": "error",
                "message": (
                    f"Network '{net_name}' (L2Bridge) spans multiple sites "
                    f"({format_site_list(sites)}); L2Bridge must stay within one site."
                ),
                "remedy": (
                    f"Move all interfaces on '{net_name}' to one site, or use L2STS for "
                    "two-site L2 / per-site FABNet for routed L3."
                ),
            })
        elif raw_type == "L2STS" and ifaces and len(sites) != 2:
            issues.append({
                "severity": "error",
                "message": (
                    f"Network '{net_name}' (L2STS) spans {len(sites)} site(s) "
                    f"({format_site_list(sites)}); L2STS must span exactly 2 sites."
                ),
                "remedy": f"Connect '{net_name}' to interfaces at exactly two sites.",
            })
