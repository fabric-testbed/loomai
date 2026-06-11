"""Serialize FABlib Slice objects into plain dicts for JSON transport.

IMPORTANT: Only uses topology/sliver data from the Orchestrator API.
Never calls methods that trigger SSH (get_ip_addr, get_mac, etc.)
to avoid hangs when bastion keys are expired or unavailable.
"""

from __future__ import annotations
import copy
from typing import Any


def _safe(fn, default=""):
    """Call fn(), return default on any exception."""
    try:
        result = fn()
        return result if result is not None else default
    except Exception:
        return default


def _safe_method(obj, method_name: str, default=""):
    """Call a named method if present, returning default on missing/failed calls."""
    method = getattr(obj, method_name, None)
    if not callable(method):
        return default
    return _safe(method, default)


def get_slice_facility_ports(slice_obj) -> list[Any]:
    """Return facility ports across FABlib API variants.

    Older LoomAI mocks expose ``get_facility_ports()`` while current FABlib
    exposes ``get_facilities()`` for facility-port slivers.
    """
    for method_name in ("get_facility_ports", "get_facilities"):
        method = getattr(slice_obj, method_name, None)
        if not callable(method):
            continue
        try:
            if method_name == "get_facilities":
                try:
                    ports = method(refresh=True)
                except TypeError:
                    ports = method()
            else:
                ports = method()
            if ports:
                return list(ports)
        except Exception:
            continue

    facilities = getattr(slice_obj, "facilities", None)
    if isinstance(facilities, dict):
        return list(facilities.values())
    if isinstance(facilities, list):
        return list(facilities)
    return []


class _SerializationContext:
    """Request-local indexes for one slice serialization pass.

    This is intentionally not shared across requests. It keeps the response
    tied to the current FABlib slice object while avoiding repeated expensive
    relationship lookups on that same object.
    """

    def __init__(self) -> None:
        self.interface_network_names: dict[str, str] = {}
        self.network_interface_names: dict[str, list[str]] = {}
        self.network_services: list[Any] = []
        self.interface_cache: dict[str, dict[str, Any]] = {}


def _value(obj: Any, attr: str, default: Any = "") -> Any:
    try:
        val = getattr(obj, attr)
        return val if val is not None else default
    except Exception:
        return default


def _network_service_names(ns: Any) -> list[str]:
    names: list[str] = []
    raw_interfaces = _value(ns, "interfaces", {})
    if isinstance(raw_interfaces, dict):
        names.extend(str(k) for k in raw_interfaces.keys())
    raw_interface_list = _value(ns, "interface_list", ())
    for item in raw_interface_list or ():
        name = ""
        if isinstance(item, dict):
            name = str(item.get("name", ""))
        else:
            name = str(_value(item, "name", ""))
        if name and name not in names:
            names.append(name)
    return names


def _is_user_network_service(ns: Any) -> bool:
    net_type = str(_value(ns, "type", ""))
    name = str(_value(ns, "name", ""))
    if not name:
        return False
    return net_type not in {"OVS", "ServicePort"} and not name.endswith("-l2ovs")


def _normalize_service_interface_name(
    service_iface_name: str,
    *,
    actual_iface_names: set[str],
    node_names: list[str],
) -> str:
    if service_iface_name in actual_iface_names:
        return service_iface_name

    for node_name in node_names:
        prefix = f"{node_name}-"
        if service_iface_name.startswith(prefix):
            candidate = service_iface_name[len(prefix):]
            if candidate in actual_iface_names:
                return candidate

    # Last-resort compatibility for service-port names that wrap interface
    # names with provider-specific prefixes.
    for candidate in sorted(actual_iface_names, key=len, reverse=True):
        if service_iface_name.endswith(candidate):
            return candidate
    return service_iface_name


def _build_serialization_context(slice_obj) -> _SerializationContext:
    ctx = _SerializationContext()
    try:
        topo = slice_obj.get_fim_topology()
    except Exception:
        return ctx

    try:
        node_names = sorted((str(n) for n in getattr(topo, "nodes", {}).keys()), key=len, reverse=True)
    except Exception:
        node_names = []

    actual_iface_names: set[str] = set()
    try:
        for iface in getattr(topo, "interface_list", ()) or ():
            name = str(_value(iface, "name", ""))
            if name:
                actual_iface_names.add(name)
    except Exception:
        actual_iface_names = set()

    try:
        network_services = list(getattr(topo, "network_services", {}).values())
    except Exception:
        network_services = []

    for ns in network_services:
        if not _is_user_network_service(ns):
            continue
        net_name = str(_value(ns, "name", ""))
        iface_names: list[str] = []
        for service_name in _network_service_names(ns):
            iface_name = _normalize_service_interface_name(
                service_name,
                actual_iface_names=actual_iface_names,
                node_names=node_names,
            )
            if not iface_name:
                continue
            if iface_name not in iface_names:
                iface_names.append(iface_name)
            if iface_name in actual_iface_names or not actual_iface_names:
                ctx.interface_network_names[iface_name] = net_name
        ctx.network_interface_names[net_name] = iface_names
        ctx.network_services.append(ns)

    return ctx


def _copy_interface_data(data: dict[str, Any], network_name: str | None = None) -> dict[str, Any]:
    copied = copy.deepcopy(data)
    if network_name is not None:
        copied["network_name"] = network_name
    return copied


def serialize_interface(
    iface,
    *,
    network_name: str | None = None,
    context: _SerializationContext | None = None,
) -> dict[str, Any]:
    """Serialize a FABlib Interface object (no SSH calls)."""
    iface_name = _safe(iface.get_name)
    if context is not None and iface_name:
        cached = context.interface_cache.get(iface_name)
        if cached is not None:
            if network_name is None:
                network_name = context.interface_network_names.get(iface_name)
            return _copy_interface_data(cached, network_name)

    # get_network() is intentionally avoided when the request-local topology
    # index can answer the relationship. On large drafts it is far slower than
    # reading the already-loaded FIM topology.
    # get_ip_addr() is NOT safe — it falls back to SSH
    # Instead, read IP from fablib_data if available
    ip_addr = ""
    try:
        fablib_data = iface.get_fablib_data()
        if "addr" in fablib_data:
            ip_addr = str(fablib_data["addr"])
    except Exception:
        pass

    # get_mac() can also trigger SSH, read from FIM label_allocations directly
    mac = ""
    try:
        fim_iface = iface.get_fim()
        if fim_iface:
            label_alloc = fim_iface.get_property(pname="label_allocations") if hasattr(fim_iface, 'get_property') else None
            if label_alloc and hasattr(label_alloc, 'mac') and label_alloc.mac:
                mac = str(label_alloc.mac)
    except Exception:
        pass

    # Prefer the request-local topology index. Falling back to get_network()
    # preserves behavior for direct serialize_interface() callers and unusual
    # FABlib objects that do not expose topology metadata.
    if network_name is None and context is not None and iface_name:
        network_name = context.interface_network_names.get(iface_name)
    if network_name is None:
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

    result = {
        "name": iface_name,
        "node_name": _safe(lambda: iface.get_node().get_name() if iface.get_node() else ""),
        "network_name": network_name,
        "vlan": _safe(iface.get_vlan),
        "mac": mac,
        "ip_addr": ip_addr,
        "bandwidth": _safe(iface.get_bandwidth),
        "mode": mode,
    }
    if context is not None and iface_name:
        context.interface_cache[iface_name] = dict(result)
    return result


def serialize_component(comp, *, context: _SerializationContext | None = None) -> dict[str, Any]:
    """Serialize a FABlib Component object."""
    return {
        "name": _safe(comp.get_name),
        "model": _safe(comp.get_model),
        "type": _safe(lambda: str(comp.get_type()) if comp.get_type() else ""),
        "interfaces": [
            serialize_interface(iface, context=context)
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


def serialize_node(node, *, context: _SerializationContext | None = None) -> dict[str, Any]:
    """Serialize a FABlib Node object (no SSH calls)."""
    components = [
        serialize_component(c, context=context)
        for c in (_safe(node.get_components, []) or [])
    ]
    interfaces = [
        serialize_interface(i, context=context)
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


def _serialize_network_from_topology(
    net,
    context: _SerializationContext,
    fallback_net: Any | None = None,
) -> dict[str, Any]:
    """Serialize a FIM NetworkService from topology metadata."""
    net_name = str(_value(net, "name", ""))
    iface_names = context.network_interface_names.get(net_name, [])
    if fallback_net is not None and any(iface_name not in context.interface_cache for iface_name in iface_names):
        return serialize_network(fallback_net, context=context)

    net_type = str(_value(net, "type", ""))
    layer = str(_value(net, "layer", "")) or (
        "L3" if any(ind in net_type for ind in ("IPv", "FABNetv", "L3VPN")) else "L2"
    )
    user_data = _value(net, "user_data", {}) or {}
    fablib_data = user_data.get("fablib_data", {}) if isinstance(user_data, dict) else {}
    subnet_data = fablib_data.get("subnet", {}) if isinstance(fablib_data, dict) else {}
    subnet = _value(net, "subnet", "")
    if not subnet and isinstance(subnet_data, dict):
        subnet = subnet_data.get("subnet", "")
    gateway = _value(net, "gateway", "")

    interfaces = [
        _copy_interface_data(context.interface_cache[iface_name], net_name)
        for iface_name in iface_names
        if iface_name in context.interface_cache
    ]

    return {
        "name": net_name,
        "type": net_type,
        "layer": layer,
        "subnet": str(subnet) if subnet else "",
        "gateway": str(gateway) if gateway else "",
        "interfaces": interfaces,
    }


def serialize_network(net, *, context: _SerializationContext | None = None) -> dict[str, Any]:
    """Serialize a FABlib NetworkService object."""
    net_type = _safe(lambda: str(net.get_type()))
    l3_indicators = ("IPv", "FABNetv", "L3VPN")
    layer = "L3" if any(ind in net_type for ind in l3_indicators) else "L2"
    net_name = _safe(net.get_name)
    interfaces = [
        serialize_interface(i, network_name=net_name, context=context)
        for i in (_safe(net.get_interfaces, []) or [])
    ]
    return {
        "name": net_name,
        "type": net_type,
        "layer": layer,
        "subnet": _safe(lambda: str(net.get_subnet()) if net.get_subnet() else ""),
        "gateway": _safe(lambda: str(net.get_gateway()) if net.get_gateway() else ""),
        "interfaces": interfaces,
    }


def serialize_facility_port(fp, *, context: _SerializationContext | None = None) -> dict[str, Any]:
    """Serialize a FABlib FacilityPort object."""
    interfaces = [
        serialize_interface(i, context=context)
        for i in (_safe_method(fp, "get_interfaces", []) or [])
    ]
    vlan = _safe_method(fp, "get_vlan")
    if not vlan:
        vlan = next((str(i.get("vlan", "")) for i in interfaces if i.get("vlan")), "")
    bandwidth = _safe_method(fp, "get_bandwidth")
    if not bandwidth:
        bandwidth = next((str(i.get("bandwidth", "")) for i in interfaces if i.get("bandwidth")), "")
    fim = _safe_method(fp, "get_fim", None)
    if not bandwidth and fim is not None:
        try:
            capacities = getattr(fim, "capacities", None)
            if capacities and getattr(capacities, "bw", None):
                bandwidth = str(capacities.bw)
        except Exception:
            pass
    return {
        "name": _safe_method(fp, "get_name") or str(getattr(fim, "name", "") if fim is not None else ""),
        "site": _safe_method(fp, "get_site") or str(getattr(fim, "site", "") if fim is not None else ""),
        "vlan": str(vlan),
        "bandwidth": str(bandwidth),
        "interfaces": interfaces,
    }


def serialize_port_mirror(pm) -> dict[str, Any]:
    """Serialize a FABlib PortMirror service object."""
    mirror_iface_name = ""
    receive_iface_name = ""
    direction = "both"
    try:
        mirror_iface_name = str(pm.get_mirror_interface_name()) if hasattr(pm, 'get_mirror_interface_name') else ""
    except Exception:
        pass
    try:
        recv_iface = pm.get_receive_interface() if hasattr(pm, 'get_receive_interface') else None
        if recv_iface:
            receive_iface_name = recv_iface.get_name()
    except Exception:
        pass
    try:
        direction = str(pm.get_mirror_direction()) if hasattr(pm, 'get_mirror_direction') else "both"
    except Exception:
        pass
    return {
        "name": _safe(pm.get_name),
        "mirror_interface_name": mirror_iface_name,
        "receive_interface_name": receive_iface_name,
        "mirror_direction": direction,
    }


def slice_to_dict(slice_obj) -> dict[str, Any]:
    """Convert a full FABlib Slice into a plain dict."""
    context = _build_serialization_context(slice_obj)
    nodes = [serialize_node(n, context=context) for n in (_safe(slice_obj.get_nodes, []) or [])]
    if context.network_services:
        fallback_networks: dict[str, Any] = {}
        needs_fallback = any(
            iface_name not in context.interface_cache
            for net in context.network_services
            for iface_name in context.network_interface_names.get(str(_value(net, "name", "")), [])
        )
        if needs_fallback:
            fallback_networks = {
                _safe(net.get_name): net
                for net in (_safe(slice_obj.get_network_services, []) or [])
                if _safe(net.get_name)
            }
        networks = [
            _serialize_network_from_topology(
                n,
                context,
                fallback_net=fallback_networks.get(str(_value(n, "name", ""))),
            )
            for n in context.network_services
        ]
    else:
        networks = [
            serialize_network(n, context=context)
            for n in (_safe(slice_obj.get_network_services, []) or [])
        ]
    facility_ports = []
    for fp in get_slice_facility_ports(slice_obj):
        try:
            facility_ports.append(serialize_facility_port(fp, context=context))
        except Exception:
            pass

    port_mirrors = []
    try:
        # FABlib may expose port mirrors via get_network_services() with type PortMirror,
        # or via a dedicated method. Try dedicated method first.
        pms = None
        if hasattr(slice_obj, 'get_port_mirror_services'):
            pms = slice_obj.get_port_mirror_services()
        if pms:
            for pm in pms:
                port_mirrors.append(serialize_port_mirror(pm))
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
        "port_mirrors": port_mirrors,
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
        "lease_end": _safe(lambda: str(slice_obj.get_lease_end()) if slice_obj.get_lease_end() else ""),
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
