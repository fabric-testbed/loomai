"""Serialize FABlib Slice objects into plain dicts for JSON transport.

IMPORTANT: Only uses topology/sliver data from the Orchestrator API.
Never calls methods that trigger SSH (get_ip_addr, get_mac, etc.)
to avoid hangs when bastion keys are expired or unavailable.
"""

from __future__ import annotations
from typing import Any


def _safe(fn, default=""):
    """Call fn(), return default on any exception."""
    try:
        result = fn()
        return result if result is not None else default
    except Exception:
        return default


def serialize_interface(iface) -> dict[str, Any]:
    """Serialize a FABlib Interface object (no SSH calls)."""
    # get_network() is safe — it reads from cached topology
    # get_ip_addr() is NOT safe — it falls back to SSH
    # Instead, read IP from fablib_data if available
    ip_addr = ""
    try:
        fablib_data = iface.get_fablib_data()
        if "addr" in fablib_data:
            ip_addr = str(fablib_data["addr"])
    except Exception:
        pass

    # get_mac() can also trigger SSH, read from FIM directly
    mac = ""
    try:
        fim_iface = iface.get_fim()
        if hasattr(fim_iface, 'label_allocations') and fim_iface.label_allocations:
            mac = str(fim_iface.label_allocations.mac) if hasattr(fim_iface.label_allocations, 'mac') and fim_iface.label_allocations.mac else ""
    except Exception:
        pass

    # Network name — use get_network() but with refresh=False via the safe wrapper
    network_name = ""
    try:
        net = iface.get_network()
        if net:
            network_name = net.get_name()
    except Exception:
        pass

    # Read interface mode from fablib_data (auto/config/none)
    mode = ""
    try:
        fd = iface.get_fablib_data()
        if fd:
            mode = str(fd.get("mode", ""))
    except Exception:
        pass

    return {
        "name": _safe(iface.get_name),
        "node_name": _safe(lambda: iface.get_node().get_name() if iface.get_node() else ""),
        "network_name": network_name,
        "vlan": _safe(iface.get_vlan),
        "mac": mac,
        "ip_addr": ip_addr,
        "bandwidth": _safe(iface.get_bandwidth),
        "mode": mode,
    }


def serialize_component(comp) -> dict[str, Any]:
    """Serialize a FABlib Component object."""
    return {
        "name": _safe(comp.get_name),
        "model": _safe(comp.get_model),
        "type": _safe(lambda: str(comp.get_type()) if comp.get_type() else ""),
        "interfaces": [
            serialize_interface(iface)
            for iface in (_safe(comp.get_interfaces, []) or [])
        ],
    }


def _node_capacity(node, attr: str) -> int:
    """Read a node capacity (cores/ram/disk), falling back to FIM capacities.

    FABlib's get_cores/get_ram/get_disk read from capacity_allocations which
    is None for draft slices.  Fall back to fim.capacities which holds the
    requested values."""
    val = _safe(getattr(node, f"get_{attr}"))
    try:
        v = int(val)
        if v > 0:
            return v
    except (TypeError, ValueError):
        pass
    # Fallback: read from FIM capacities object
    try:
        fim = node.get_fim_node()
        caps = fim.capacities
        if caps:
            fim_attr = attr if attr != "cores" else "core"
            v = getattr(caps, fim_attr, 0)
            if v and int(v) > 0:
                return int(v)
    except Exception:
        pass
    return 0


def serialize_node(node) -> dict[str, Any]:
    """Serialize a FABlib Node object (no SSH calls)."""
    components = [
        serialize_component(c)
        for c in (_safe(node.get_components, []) or [])
    ]
    interfaces = [
        serialize_interface(i)
        for i in (_safe(node.get_interfaces, []) or [])
    ]

    # get_management_ip reads from sliver data, should be safe
    # get_username and get_image read from topology, should be safe
    # user_data holds boot_config and other per-node metadata
    user_data = {}
    try:
        ud = node.get_user_data()
        if ud and isinstance(ud, dict):
            user_data = dict(ud)
    except Exception:
        pass

    # Error message (available on failed/closed slivers)
    error_message = ""
    try:
        em = node.get_error_message()
        if em:
            error_message = str(em)
    except Exception:
        pass

    return {
        "name": _safe(node.get_name),
        "site": _safe(node.get_site),
        "host": _safe(node.get_host),
        "cores": _node_capacity(node, "cores"),
        "ram": _node_capacity(node, "ram"),
        "disk": _node_capacity(node, "disk"),
        "image": _safe(node.get_image),
        "image_type": _safe(node.get_image_type),
        "management_ip": _safe(node.get_management_ip),
        "reservation_state": _safe(lambda: str(node.get_reservation_state())),
        "error_message": error_message,
        "username": _safe(node.get_username),
        "user_data": user_data,
        "components": components,
        "interfaces": interfaces,
    }


def serialize_network(net) -> dict[str, Any]:
    """Serialize a FABlib NetworkService object."""
    net_type = _safe(lambda: str(net.get_type()))
    l3_indicators = ("IPv", "FABNetv", "L3VPN")
    layer = "L3" if any(ind in net_type for ind in l3_indicators) else "L2"
    interfaces = [
        serialize_interface(i)
        for i in (_safe(net.get_interfaces, []) or [])
    ]
    return {
        "name": _safe(net.get_name),
        "type": net_type,
        "layer": layer,
        "subnet": _safe(lambda: str(net.get_subnet()) if net.get_subnet() else ""),
        "gateway": _safe(lambda: str(net.get_gateway()) if net.get_gateway() else ""),
        "interfaces": interfaces,
    }


def serialize_facility_port(fp) -> dict[str, Any]:
    """Serialize a FABlib FacilityPort object."""
    interfaces = [
        serialize_interface(i)
        for i in (_safe(fp.get_interfaces, []) or [])
    ]
    return {
        "name": _safe(fp.get_name),
        "site": _safe(fp.get_site),
        "vlan": _safe(fp.get_vlan),
        "bandwidth": _safe(fp.get_bandwidth),
        "interfaces": interfaces,
    }


def slice_to_dict(slice_obj) -> dict[str, Any]:
    """Convert a full FABlib Slice into a plain dict."""
    nodes = [serialize_node(n) for n in (_safe(slice_obj.get_nodes, []) or [])]
    networks = [serialize_network(n) for n in (_safe(slice_obj.get_network_services, []) or [])]
    facility_ports = []
    try:
        for fp in (slice_obj.get_facility_ports() or []):
            facility_ports.append(serialize_facility_port(fp))
    except Exception:
        pass

    # Collect slice-level error messages and notices
    error_messages: list[dict[str, str]] = []
    try:
        for err in (slice_obj.get_error_messages() or []):
            notice = err.get("notice", "")
            if notice:
                sliver = err.get("sliver")
                sliver_name = ""
                try:
                    sliver_name = sliver.get_name() if sliver else ""
                except Exception:
                    pass
                error_messages.append({
                    "sliver": sliver_name,
                    "message": str(notice),
                })
    except Exception:
        pass

    return {
        "name": _safe(slice_obj.get_name),
        "id": _safe(slice_obj.get_slice_id),
        "state": _safe(lambda: str(slice_obj.get_state())),
        "lease_start": _safe(lambda: str(slice_obj.get_lease_start()) if slice_obj.get_lease_start() else ""),
        "lease_end": _safe(lambda: str(slice_obj.get_lease_end()) if slice_obj.get_lease_end() else ""),
        "error_messages": error_messages,
        "nodes": nodes,
        "networks": networks,
        "facility_ports": facility_ports,
    }


def slice_summary(slice_obj) -> dict[str, Any]:
    """Convert a FABlib Slice into a summary dict (for list view).

    Note: has_errors is NOT included here (too expensive for large lists).
    The caller should populate it from the slice registry instead.
    """
    return {
        "name": _safe(slice_obj.get_name),
        "id": _safe(slice_obj.get_slice_id),
        "state": _safe(lambda: str(slice_obj.get_state())),
    }


def check_has_errors(slice_obj) -> bool:
    """Check whether a FABlib Slice has error messages."""
    try:
        errors = slice_obj.get_error_messages()
        if errors:
            return any(e.get("notice", "") for e in errors)
    except Exception:
        pass
    return False
