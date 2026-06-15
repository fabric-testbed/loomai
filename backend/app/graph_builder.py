"""Convert FABlib Slice objects into Cytoscape.js graph JSON.

Replicates the logic from fabvis/graph_builder.py, producing the same
node types, labels, edge structures, and data attributes.
"""

from __future__ import annotations
from typing import Any


# State color mapping — exact match to fabvis/styles.py STATE_COLORS
STATE_COLORS = {
    "StableOK": {"bg": "#e0f2f1", "border": "#008e7a"},
    "Active": {"bg": "#e0f2f1", "border": "#008e7a"},
    "Configuring": {"bg": "#fff3e0", "border": "#ff8542"},
    "Ticketed": {"bg": "#fff3e0", "border": "#ff8542"},
    "ModifyOK": {"bg": "#fff3e0", "border": "#ff8542"},
    "Nascent": {"bg": "#f8f9fa", "border": "#838385"},
    "StableError": {"bg": "#fce4ec", "border": "#b00020"},
    "ModifyError": {"bg": "#fce4ec", "border": "#b00020"},
    "Closing": {"bg": "#eeeeee", "border": "#616161"},
    "Dead": {"bg": "#eeeeee", "border": "#616161"},
}
DEFAULT_STATE = {"bg": "#f8f9fa", "border": "#838385"}

# Dark mode state colors — brighter borders on dark tinted backgrounds
STATE_COLORS_DARK = {
    "StableOK": {"bg": "#0d2e26", "border": "#4dd0b8"},
    "Active": {"bg": "#0d2e26", "border": "#4dd0b8"},
    "Configuring": {"bg": "#3a2008", "border": "#ffb74d"},
    "Ticketed": {"bg": "#3a2008", "border": "#ffb74d"},
    "ModifyOK": {"bg": "#3a2008", "border": "#ffb74d"},
    "Nascent": {"bg": "#28283a", "border": "#a0a0b8"},
    "StableError": {"bg": "#3a1018", "border": "#ff6b6b"},
    "ModifyError": {"bg": "#3a1018", "border": "#ff6b6b"},
    "Closing": {"bg": "#222230", "border": "#8a8a9a"},
    "Dead": {"bg": "#222230", "border": "#8a8a9a"},
}
DEFAULT_STATE_DARK = {"bg": "#28283a", "border": "#a0a0b8"}

# Component model abbreviations
COMPONENT_ABBREV = {
    "NIC_Basic": "NIC",
    "NIC_ConnectX_5": "CX5",
    "NIC_ConnectX_6": "CX6",
    "NIC_ConnectX_7": "CX7",
    "GPU_TeslaT4": "T4",
    "GPU_RTX6000": "RTX",
    "GPU_A30": "A30",
    "GPU_A40": "A40",
    "FPGA_Xilinx_U280": "FPGA",
    "NVME_P4510": "NVMe",
    "NIC_ConnectX_7_100": "CX7-100",
    "NIC_ConnectX_7_400": "CX7-400",
    "NIC_BlueField_2_ConnectX_6": "BF2",
    "FPGA_Xilinx_SN1022": "SN1022",
}

# Component model to category (for CSS class)
COMPONENT_CATEGORY = {
    "NIC_Basic": "nic",
    "NIC_ConnectX_5": "nic",
    "NIC_ConnectX_6": "nic",
    "NIC_ConnectX_7": "nic",
    "GPU_TeslaT4": "gpu",
    "GPU_RTX6000": "gpu",
    "GPU_A30": "gpu",
    "GPU_A40": "gpu",
    "FPGA_Xilinx_U280": "fpga",
    "NVME_P4510": "nvme",
    "NIC_ConnectX_7_100": "nic",
    "NIC_ConnectX_7_400": "nic",
    "NIC_BlueField_2_ConnectX_6": "nic",
    "FPGA_Xilinx_SN1022": "fpga",
}


def _strip_node_prefix(name: str, node_name: str) -> str:
    """Strip the node name prefix from interface/component names.

    FABRIC names interfaces as '{node}-{component}-p{port}-{idx}'.
    Showing just '{component}-p{port}-{idx}' is cleaner since the
    VM context is already visually clear.
    """
    prefix = f"{node_name}-"
    if name.startswith(prefix):
        return name[len(prefix):]
    return name


def _component_summary(components: list) -> str:
    """Build abbreviated component summary like 'NIC x2  GPU'."""
    counts: dict[str, int] = {}
    for comp in components:
        model = comp.get("model", "")
        abbrev = COMPONENT_ABBREV.get(model, model)
        counts[abbrev] = counts.get(abbrev, 0) + 1
    parts = []
    for name, count in counts.items():
        if count > 1:
            parts.append(f"{name} x{count}")
        else:
            parts.append(name)
    return "  ".join(parts)


def _normalized_graph_token(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _is_facility_vlan_helper_network(
    net: dict,
    *,
    facility_endpoint_names: set[str],
    referenced_facility_networks: set[str],
) -> bool:
    """Return true for disconnected FABRIC facility-port VLAN helper services."""
    net_name = str(net.get("name", ""))
    if str(net.get("type", "")) != "VLAN":
        return False
    if net.get("interfaces"):
        return False
    if not facility_endpoint_names:
        return False
    if net_name in referenced_facility_networks:
        return False

    normalized_name = _normalized_graph_token(net_name)
    if normalized_name in {"", "vlan"}:
        return True
    if net_name.endswith("-ns"):
        return True
    return any(
        token and token in normalized_name
        for token in (_normalized_graph_token(name) for name in facility_endpoint_names)
    )


def build_graph(slice_data: dict) -> dict[str, Any]:
    """Build a Cytoscape.js-compatible graph JSON from slice data.

    Args:
        slice_data: Dict with keys: name, id, state, nodes, networks,
                    interfaces, components (as returned by slice_to_dict).

    Returns:
        {"nodes": [...], "edges": [...]} in Cytoscape.js JSON format.
    """
    nodes = []
    edges = []
    slice_name = slice_data.get("name", "slice")
    slice_id = slice_data.get("id", "unknown")
    node_names = {node.get("name") for node in slice_data.get("nodes", []) if node.get("name")}
    facility_ports_by_name = {
        fp.get("name"): fp
        for fp in slice_data.get("facility_ports", [])
        if fp.get("name")
    }
    facility_endpoint_names = set(facility_ports_by_name)
    referenced_facility_networks: set[str] = set()
    for fp in slice_data.get("facility_ports", []):
        for iface in fp.get("interfaces", []):
            network_name = iface.get("network_name")
            if network_name:
                referenced_facility_networks.add(str(network_name))
    for net in slice_data.get("networks", []):
        for iface in net.get("interfaces", []):
            iface_node = iface.get("node_name", "")
            if iface_node and iface_node not in node_names:
                facility_endpoint_names.add(str(iface_node))
    external_iface_node_ids: set[str] = set()

    # Slice container node
    nodes.append({
        "data": {
            "id": f"slice:{slice_id}",
            "label": slice_name,
            "element_type": "slice",
            "state": slice_data.get("state", "Unknown"),
        },
        "classes": "slice",
    })

    # VM nodes
    for node in slice_data.get("nodes", []):
        node_name = node["name"]
        site = node.get("site", "?")
        cores = node.get("cores", "?")
        ram = node.get("ram", "?")
        disk = node.get("disk", "?")
        state = node.get("reservation_state", "Unknown")
        state_colors = STATE_COLORS.get(state, DEFAULT_STATE)
        state_colors_dark = STATE_COLORS_DARK.get(state, DEFAULT_STATE_DARK)
        components = node.get("components", [])

        # Separate components: those with interfaces get graph nodes,
        # those without get summarized in the VM label
        comps_with_ifaces = [c for c in components if c.get("interfaces")]
        comps_without_ifaces = [c for c in components if not c.get("interfaces")]

        site_group = node.get("site_group", "")
        site_line = f"@ {site}"
        if site_group:
            site_line += f"  ({site_group})"
        label_lines = [
            node_name,
            site_line,
            f"{cores}c / {ram}G / {disk}G",
        ]
        if comps_without_ifaces:
            label_lines.append(_component_summary(comps_without_ifaces))

        node_id = f"node:{slice_id}:{node_name}"
        nodes.append({
            "data": {
                "id": node_id,
                "parent": f"slice:{slice_id}",
                "label": "\n".join(label_lines),
                "element_type": "node",
                "name": node_name,
                "site": site,
                "cores": cores,
                "ram": ram,
                "disk": disk,
                "state": state,
                "state_bg": state_colors["bg"],
                "state_color": state_colors["border"],
                "state_bg_dark": state_colors_dark["bg"],
                "state_color_dark": state_colors_dark["border"],
                "testbed": "FABRIC",
                "site_group": site_group,
                "image": node.get("image", ""),
                "management_ip": node.get("management_ip", ""),
                "username": node.get("username", ""),
                "host": node.get("host", ""),
            },
            "classes": "vm",
        })

        # Component badge nodes for interface-bearing components.
        # These are independent nodes (NOT children of the VM) so the VM
        # keeps its fixed size and centered label.  The frontend positions
        # them at the bottom edge of the VM after layout.
        for comp in comps_with_ifaces:
            comp_name = comp.get("name", "")
            comp_model = comp.get("model", "")
            short_comp = _strip_node_prefix(comp_name, node_name)
            abbrev = COMPONENT_ABBREV.get(comp_model, comp_model[:6])
            category = COMPONENT_CATEGORY.get(comp_model, "nic")
            comp_id = f"comp:{slice_id}:{node_name}:{comp_name}"

            nodes.append({
                "data": {
                    "id": comp_id,
                    "parent_vm": node_id,
                    "label": short_comp,
                    "element_type": "component",
                    "name": comp_name,
                    "model": comp_model,
                    "node_name": node_name,
                },
                "classes": f"component component-{category}",
            })

    # Build lookup: interface name → component node ID
    # so edges can route from the specific component rather than the VM
    iface_to_comp: dict[str, str] = {}
    iface_to_comp_name: dict[str, str] = {}
    for node in slice_data.get("nodes", []):
        node_name = node["name"]
        for comp in node.get("components", []):
            comp_name = comp.get("name", "")
            comp_id = f"comp:{slice_id}:{node_name}:{comp_name}"
            for ci in comp.get("interfaces", []):
                ci_name = ci.get("name", "")
                if ci_name:
                    iface_to_comp[ci_name] = comp_id
                    iface_to_comp_name[ci_name] = comp_name

    # Network nodes
    fabnet_net_ids: list[str] = []  # track FABNetv4 networks for internet node

    for net in slice_data.get("networks", []):
        net_name = net["name"]
        net_type = net.get("type", "L2Bridge")
        if _is_facility_vlan_helper_network(
            net,
            facility_endpoint_names=facility_endpoint_names,
            referenced_facility_networks=referenced_facility_networks,
        ):
            continue
        layer = net.get("layer", "L2")
        net_id = f"net:{slice_id}:{net_name}"

        # Label FABNet/Ext networks as gateways
        is_fabnet_private = net_type in ("FABNetv4", "FABNetv6")
        is_fabnet_public = net_type in ("FABNetv4Ext", "FABNetv6Ext", "IPv4Ext", "IPv6Ext")
        if is_fabnet_private:
            label = f"{net_name}\nFABNet Gateway"
            fabnet_net_ids.append(net_id)
        elif is_fabnet_public:
            label = f"{net_name}\nPublic Internet"
            fabnet_net_ids.append(net_id)
        else:
            label = f"{net_name}\n({net_type})"

        net_classes = f"network-{layer.lower()}"
        if is_fabnet_public:
            net_classes += " network-l3-ext"

        nodes.append({
            "data": {
                "id": net_id,
                "parent": f"slice:{slice_id}",
                "label": label,
                "element_type": "network",
                "name": net_name,
                "type": net_type,
                "layer": layer,
                "subnet": net.get("subnet", ""),
                "gateway": net.get("gateway", ""),
            },
            "classes": net_classes,
        })

        # Edges from nodes/components to networks via interfaces. Some FABRIC
        # facility-port stitches are returned as network interfaces with a
        # non-VM node_name (for example "Chameleon-TACC") rather than in the
        # facility_ports collection; render those endpoints explicitly so graph
        # edges never point at a missing VM node.
        for iface in net.get("interfaces", []):
            iface_node = iface.get("node_name", "")
            iface_name = iface.get("name", "")
            if iface_node:
                if iface_node in node_names:
                    vm_id = f"node:{slice_id}:{iface_node}"
                    # Route from component if available, else from VM
                    comp_id = iface_to_comp.get(iface_name, "")
                    source_id = comp_id if comp_id else vm_id
                    comp_name = iface_to_comp_name.get(iface_name, "")
                else:
                    vm_id = ""
                    comp_id = ""
                    comp_name = ""
                    source_id = f"fp:{slice_id}:{iface_node}"
                    matching_fp = facility_ports_by_name.get(iface_node)
                    if source_id not in external_iface_node_ids:
                        label_lines = [iface_node, "(facility port)"]
                        fp_site = matching_fp.get("site", iface_node) if matching_fp else iface_node
                        fp_vlan = matching_fp.get("vlan", iface.get("vlan", "")) if matching_fp else iface.get("vlan", "")
                        fp_bw = matching_fp.get("bandwidth", iface.get("bandwidth", "")) if matching_fp else iface.get("bandwidth", "")
                        if fp_vlan:
                            label_lines.append(f"VLAN {fp_vlan}")
                        nodes.append({
                            "data": {
                                "id": source_id,
                                "label": "\n".join(label_lines),
                                "element_type": "facility-port",
                                "name": iface_node,
                                "site": fp_site,
                                "vlan": str(fp_vlan),
                                "bandwidth": str(fp_bw),
                                "deletable": "true" if matching_fp else "false",
                            },
                            "classes": "facility-port",
                        })
                        external_iface_node_ids.add(source_id)

                edge_id = f"edge:{slice_id}:{iface_name}"
                short_iface = _strip_node_prefix(iface_name, iface_node)
                edge_label_parts = [short_iface]
                if iface.get("vlan"):
                    edge_label_parts.append(f"VLAN {iface['vlan']}")
                if iface.get("ip_addr"):
                    edge_label_parts.append(iface["ip_addr"])

                edges.append({
                    "data": {
                        "id": edge_id,
                        "source": source_id,
                        "target": net_id,
                        "source_vm": vm_id,
                        "source_comp": comp_id,
                        "component_name": comp_name,
                        "label": "\n".join(edge_label_parts),
                        "element_type": "interface",
                        "interface_name": iface_name,
                        "node_name": iface_node,
                        "network_name": net_name,
                        "vlan": iface.get("vlan", ""),
                        "mac": iface.get("mac", ""),
                        "ip_addr": iface.get("ip_addr", ""),
                        "bandwidth": iface.get("bandwidth", ""),
                    },
                    "classes": f"edge-{layer.lower()} edge-facility-port-l2" if not vm_id else f"edge-{layer.lower()}",
                })

    # Synthetic FABRIC Internet node — shown when any FABNetv4/v6 gateways exist
    if fabnet_net_ids:
        internet_id = "fabnet-internet-v4"
        nodes.append({
            "data": {
                "id": internet_id,
                "label": "☁\nFABRIC Internet\n(FABNetv4)",
                "element_type": "fabnet-internet",
            },
            "classes": "fabnet-internet",
        })
        for gw_id in fabnet_net_ids:
            edges.append({
                "data": {
                    "id": f"edge-fabnet-internet:{gw_id}",
                    "source": gw_id,
                    "target": internet_id,
                    "label": "",
                    "element_type": "fabnet-internet-edge",
                },
                "classes": "edge-fabnet-internet",
            })

    # Facility port nodes
    for fp in slice_data.get("facility_ports", []):
        fp_name = fp["name"]
        fp_site = fp.get("site", "?")
        fp_vlan = fp.get("vlan", "")
        fp_bw = fp.get("bandwidth", "")
        fp_id = f"fp:{slice_id}:{fp_name}"

        label_lines = [fp_name, f"@ {fp_site}"]
        if fp_vlan:
            label_lines.append(f"VLAN {fp_vlan}")

        nodes.append({
            "data": {
                "id": fp_id,
                "label": "\n".join(label_lines),
                "element_type": "facility-port",
                "name": fp_name,
                "site": fp_site,
                "vlan": str(fp_vlan),
                "bandwidth": str(fp_bw),
                "deletable": "true",
            },
            "classes": "facility-port",
        })

        # Edges from facility port interfaces to networks
        for iface in fp.get("interfaces", []):
            iface_name = iface.get("name", "")
            net_name = iface.get("network_name", "")
            if net_name:
                target_id = f"net:{slice_id}:{net_name}"
                edge_id = f"edge:{slice_id}:{iface_name}"
                edges.append({
                    "data": {
                        "id": edge_id,
                        "source": fp_id,
                        "target": target_id,
                        "label": "",
                        "element_type": "interface",
                        "interface_name": iface_name,
                        "node_name": "",
                        "network_name": net_name,
                        "vlan": iface.get("vlan", ""),
                        "mac": iface.get("mac", ""),
                        "ip_addr": iface.get("ip_addr", ""),
                        "bandwidth": iface.get("bandwidth", ""),
                    },
                    "classes": "edge-l2 edge-facility-port-l2",
                })

    # Port mirror service nodes
    for pm in slice_data.get("port_mirrors", []):
        pm_name = pm["name"]
        pm_id = f"pm:{slice_id}:{pm_name}"
        mirror_iface = pm.get("mirror_interface_name", "")
        receive_iface = pm.get("receive_interface_name", "")
        direction = pm.get("mirror_direction", "both")

        nodes.append({
            "data": {
                "id": pm_id,
                "parent": f"slice:{slice_id}",
                "label": f"{pm_name}\n(PortMirror)\n{direction}",
                "element_type": "port-mirror",
                "name": pm_name,
                "mirror_interface_name": mirror_iface,
                "receive_interface_name": receive_iface,
                "mirror_direction": direction,
            },
            "classes": "port-mirror",
        })

        # Edge from source interface component to mirror node
        source_comp_id = iface_to_comp.get(mirror_iface, "")
        if source_comp_id:
            edges.append({
                "data": {
                    "id": f"edge-pm-src:{slice_id}:{pm_name}",
                    "source": source_comp_id,
                    "target": pm_id,
                    "label": "mirror src",
                    "element_type": "port-mirror-edge",
                },
                "classes": "edge-port-mirror",
            })

        # Edge from mirror node to receive interface component
        receive_comp_id = iface_to_comp.get(receive_iface, "")
        if receive_comp_id:
            edges.append({
                "data": {
                    "id": f"edge-pm-recv:{slice_id}:{pm_name}",
                    "source": pm_id,
                    "target": receive_comp_id,
                    "label": "capture",
                    "element_type": "port-mirror-edge",
                },
                "classes": "edge-port-mirror",
            })

    # Merge Chameleon slice nodes if present
    chi_nodes = slice_data.get("chameleon_nodes")
    if chi_nodes:
        chi_elements = build_chameleon_slice_node_elements(chi_nodes, slice_id)
        nodes.extend(chi_elements["nodes"])
        edges.extend(chi_elements["edges"])

    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# Chameleon slice-node graph elements (merged into FABRIC slice graph)
# ---------------------------------------------------------------------------


def _find_chi_instance_for_composite_node(name: str, site: str) -> dict:
    """Search all Chameleon slices for an instance matching (name, site).

    Returns a dict with instance_id, floating_ip, status, ssh_ready if found,
    else an empty dict. Used to enrich composite-view Chameleon nodes so the
    right-click "Open Terminal" menu item can fire.
    """
    try:
        from app.routes.chameleon import _chameleon_slices
    except ImportError:
        return {}
    for slice_obj in _chameleon_slices.values():
        for res in slice_obj.get("resources", []):
            if (
                res.get("type") == "instance"
                and res.get("name") == name
                and res.get("site") == site
                and res.get("id")
            ):
                return {
                    "instance_id": res.get("id", ""),
                    "floating_ip": res.get("floating_ip", ""),
                    "status": res.get("status", ""),
                    "ssh_ready": res.get("ssh_ready", False),
                }
    return {}


def build_chameleon_slice_node_elements(chameleon_nodes: list[dict], slice_id: str = "") -> dict[str, Any]:
    """Build Cytoscape.js elements for Chameleon nodes attached to a FABRIC slice.

    These elements are merged into the FABRIC slice graph to show cross-testbed topology.
    """
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    if not chameleon_nodes:
        return {"nodes": [], "edges": []}

    # Container node
    nodes.append({
        "data": {
            "id": "chameleon:slice-cluster",
            "label": "Chameleon Cloud",
            "element_type": "chameleon_cluster",
        },
        "classes": "chameleon-cluster",
    })

    for chi in chameleon_nodes:
        name = chi.get("name", "")
        site = chi.get("site", "?")
        node_type = chi.get("node_type", "?")
        status = chi.get("status", "draft")
        connection_type = chi.get("connection_type", "fabnet_v4")

        # Enrich with live instance data if a matching Chameleon slice instance exists
        live = _find_chi_instance_for_composite_node(name, site)
        if live.get("status"):
            status = live["status"]

        # Use draft colors (gray) for draft nodes, existing state colors for deployed
        if status == "draft":
            bg = "#f5f5f5"
            border = "#999"
            bg_dark = "#2a2a2a"
            border_dark = "#666"
        else:
            bg = "#e8f5e9"
            border = "#39B54A"
            bg_dark = "#1b3a1b"
            border_dark = "#4caf50"

        node_id = f"chi-slice:{name}"
        label = f"{name}\n{site}\n{node_type}"

        node_data = {
            "id": node_id,
            "label": label,
            "element_type": "chameleon_instance",
            "name": name,
            "site": site,
            "status": status,
            "node_type": node_type,
            "connection_type": connection_type,
            "testbed": "Chameleon",
            "parent": "chameleon:slice-cluster",
            "bg_color": bg,
            "border_color": border,
            "bg_color_dark": bg_dark,
            "border_color_dark": border_dark,
        }
        # Attach instance metadata so right-click "Open Terminal" works
        if live.get("instance_id"):
            node_data["instance_id"] = live["instance_id"]
            node_data["floating_ip"] = live.get("floating_ip", "")
            node_data["ssh_ready"] = live.get("ssh_ready", False)

        nodes.append({
            "data": node_data,
            "classes": "chameleon-instance" + (" chameleon-draft-node" if status == "draft" else ""),
        })

    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# Chameleon draft graph elements
# ---------------------------------------------------------------------------

# Draft state colors — gray for "not yet deployed"
CHAMELEON_DRAFT_STATE = {"bg": "#f5f5f5", "border": "#999999"}
CHAMELEON_DRAFT_STATE_DARK = {"bg": "#2a2a3a", "border": "#888888"}
# Draft container color — green
CHAMELEON_DRAFT_CONTAINER_COLOR = "#39B54A"


def build_chameleon_slice_graph(
    draft: dict,
    live_instances: list[dict] | None = None,
) -> dict[str, Any]:
    """Build Cytoscape.js graph elements from a Chameleon slice/draft topology.

    Args:
        draft: Slice dict with keys: id, name, nodes, networks, floating_ips.
               Nodes have per-node ``site`` fields; slices may span multiple sites.
        live_instances: Optional list of live Nova instance dicts (id, name, site,
               status, ip_addresses, floating_ip) used to overlay real state onto
               planned nodes.

    Returns:
        {"nodes": [...], "edges": [...]} in Cytoscape.js JSON format.
    """
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    draft_id = draft.get("id", "unknown")
    draft_name = draft.get("name", "draft")

    # Map deployed instance resources back to planned nodes. New deploys track
    # planned_node_id; legacy resources only have instance/planned names.
    resource_map: dict[tuple[str, str], dict] = {}
    resource_map_by_planned_name: dict[tuple[str, str], list[dict]] = {}
    resource_map_by_node_id: dict[str, list[dict]] = {}
    instance_resources: list[dict] = []
    network_resources: list[dict] = []
    for res in draft.get("resources", []):
        if res.get("type") == "instance":
            instance_resources.append(res)
            key = (res.get("name", ""), res.get("site", ""))
            resource_map[key] = res
            relationship = res.get("relationship") if isinstance(res.get("relationship"), dict) else {}
            planned_node_id = res.get("planned_node_id", "") or relationship.get("planned_node_id", "")
            if planned_node_id:
                resource_map_by_node_id.setdefault(planned_node_id, []).append(res)
            planned_node_name = res.get("planned_node_name", "") or relationship.get("planned_node_name", "")
            if planned_node_name:
                resource_map_by_planned_name.setdefault((planned_node_name, res.get("site", "")), []).append(res)
        elif res.get("type") == "network":
            network_resources.append(res)

    # Map instance IDs to live data
    instance_map: dict[str, dict] = {}
    if live_instances:
        for inst in live_instances:
            instance_map[inst.get("id", "")] = inst

    # Collect unique sites from planned nodes and deployed resources. Some
    # federated workflows attach an already deployed Chameleon slice whose
    # resources are known but whose original planned ``nodes`` array is empty.
    unique_sites = sorted(set(
        site
        for site in [
            *(n.get("site") or draft.get("site", "?") for n in draft.get("nodes", [])),
            *(r.get("site") or draft.get("site", "?") for r in draft.get("resources", [])),
        ]
        if site
    )) or [draft.get("site", "?")]

    # One container per site
    site_container_ids: dict[str, str] = {}
    for site in unique_sites:
        container_id = f"chi-draft:{draft_id}:{site}"
        site_container_ids[site] = container_id
        nodes.append({
            "data": {
                "id": container_id,
                "label": f"{draft_name}\n@ {site}",
                "element_type": "chameleon_draft",
                "draft_id": draft_id,
                "site": site,
                "bg_color": CHAMELEON_DRAFT_CONTAINER_COLOR,
                "border_color": CHAMELEON_DRAFT_CONTAINER_COLOR,
            },
            "classes": "chameleon-cluster chameleon-draft",
        })

    # Node elements
    # floating_ips can be a list of strings (legacy) or list of dicts
    # ({"node_id": ..., "nic": ...}) — normalize to a set of node_ids.
    _raw_fips = draft.get("floating_ips", []) or []
    floating_ips_set = set()
    for entry in _raw_fips:
        if isinstance(entry, str):
            floating_ips_set.add(entry)
        elif isinstance(entry, dict) and entry.get("node_id"):
            floating_ips_set.add(entry["node_id"])

    rendered_instance_resource_ids: set[str] = set()
    for node in draft.get("nodes", []):
        node_id = node.get("id", "")
        node_name = node.get("name", "node")
        node_type = node.get("node_type", "?")
        image = node.get("image", "?")
        count = node.get("count", 1)
        node_site = node.get("site") or draft.get("site", "?")

        label_parts = [node_name]
        if count > 1:
            label_parts.append(f"x{count}")

        # Check for deployed instances matching this planned node. Counted nodes
        # may have multiple resources named <node>-1, <node>-2, ...
        matched_resources = resource_map_by_node_id.get(node_id, [])
        if not matched_resources:
            matched_resources = resource_map_by_planned_name.get((node_name, node_site), [])
        if not matched_resources:
            legacy_match = resource_map.get((node_name, node_site))
            matched_resources = [legacy_match] if legacy_match else []
        matched_resource = matched_resources[0] if matched_resources else None

        ssh_ready = False
        if matched_resources:
            rendered_instance_resource_ids.update(r.get("id", "") for r in matched_resources if r.get("id"))
            live_by_resource = [
                instance_map.get(r.get("id", "")) for r in matched_resources
            ]
            statuses = [
                str((live or r).get("status", "UNKNOWN")).upper()
                for r, live in zip(matched_resources, live_by_resource)
            ]
            if any(s == "ERROR" for s in statuses):
                status = "ERROR"
            elif statuses and all(s == "ACTIVE" for s in statuses):
                status = "ACTIVE"
            elif any(s in ("BUILD", "PENDING", "SPAWNING") for s in statuses):
                status = "BUILD"
            else:
                status = statuses[0] if statuses else "DEPLOYED"
            state_colors = CHAMELEON_STATE_COLORS.get(status, {"bg": "#fff3e0", "border": "#ff8542"})
            state_colors_dark = CHAMELEON_STATE_COLORS_DARK.get(status, {"bg": "#3a2a1a", "border": "#ff8542"})
            instance_id = matched_resource.get("id", "")
            floating_ips = [
                (live or r).get("floating_ip", "")
                for r, live in zip(matched_resources, live_by_resource)
                if (live or r).get("floating_ip", "")
            ]
            ips = []
            for r, live in zip(matched_resources, live_by_resource):
                source = live or r
                if source.get("ip_addresses"):
                    ips.append(source["ip_addresses"][0])
                elif source.get("floating_ip"):
                    ips.append(source["floating_ip"])
            floating_ip = floating_ips[0] if floating_ips else ""
            ip = floating_ip or (ips[0] if ips else "")
            if len(matched_resources) > 1:
                active_count = sum(1 for s in statuses if s == "ACTIVE")
                label_parts.append(f"[{status}: {active_count}/{len(matched_resources)} ACTIVE]")
                if floating_ips:
                    label_parts.append(f"Floating IPs: {len(floating_ips)}")
            else:
                label_parts.append(f"[{status}]")
                if floating_ip:
                    label_parts.append(f"Floating IP: {floating_ip}")
                elif ip:
                    label_parts.append(ip)
            node_classes = f"chameleon-instance chameleon-{status.lower()}"
            ssh_ready = all(bool(r.get("ssh_ready")) for r in matched_resources)
        else:
            status = "DRAFT"
            state_colors = CHAMELEON_DRAFT_STATE
            state_colors_dark = CHAMELEON_DRAFT_STATE_DARK
            instance_id = ""
            floating_ip = ""
            ip = ""
            label_parts.extend([node_type, image])
            node_classes = "chameleon-instance chameleon-draft-node"

        parent_id = site_container_ids.get(node_site, next(iter(site_container_ids.values()), ""))
        cy_node_id = f"chi-draft-node:{draft_id}:{node_id}"
        nodes.append({
            "data": {
                "id": cy_node_id,
                "label": "\n".join(label_parts),
                "element_type": "chameleon_instance",
                "testbed": "Chameleon",
                "draft_id": draft_id,
                "node_id": node_id,
                "planned_node_id": node_id,
                "name": node_name,
                "site": node_site,
                "status": status,
                "instance_id": instance_id,
                "resource_id": matched_resource.get("resource_id", "") if matched_resource else "",
                "provider_id": matched_resource.get("provider_id", "") if matched_resource else "",
                "floating_ip": floating_ip,
                "ip": ip,
                "ssh_ready": ssh_ready,
                "node_type": node_type,
                "image": image,
                "count": count,
                "parent": parent_id,
                "bg_color": state_colors["bg"],
                "border_color": state_colors["border"],
                "bg_color_dark": state_colors_dark["bg"],
                "border_color_dark": state_colors_dark["border"],
            },
            "classes": node_classes,
        })

    # --- Collect unique networks from per-node assignments + legacy networks array ---
    seen_net_ids: set[str] = set()

    # Per-node network assignments (new model)
    for node in draft.get("nodes", []):
        net = node.get("network")
        if isinstance(net, dict):
            net_id = net.get("id") or net.get("network_id") or net.get("name", "")
        elif isinstance(net, str):
            net_id = net
        else:
            net_id = ""
        if net_id and net_id not in seen_net_ids:
            seen_net_ids.add(net_id)

    # Legacy networks array (backward compat)
    for net in draft.get("networks", []):
        if isinstance(net, dict):
            net_id = net.get("id") or net.get("name", "")
        elif isinstance(net, str):
            net_id = net
        else:
            net_id = ""
        if net_id not in seen_net_ids:
            seen_net_ids.add(net_id)

    def _normalize_chameleon_network_ref(value: Any) -> dict | None:
        if isinstance(value, dict):
            net = dict(value)
        elif isinstance(value, str) and value:
            net = {"id": value, "name": value}
        else:
            return None

        name = net.get("name") or net.get("network_name") or net.get("id")
        net_id = net.get("id") or net.get("network_id") or name
        if not net_id and not name:
            return None
        net["id"] = net_id or name
        net["name"] = name or net_id
        return net

    def _is_site_scoped_chameleon_network(net_id: str, net_name: str) -> bool:
        text = f"{net_id} {net_name}".lower()
        return "sharednet" in text

    def _network_scope_key(site: str, net_id: str, net_name: str) -> str:
        if _is_site_scoped_chameleon_network(net_id, net_name):
            return f"{site}:{net_id}"
        return net_id

    def _network_cy_id(site: str, net_id: str, net_name: str) -> str:
        if _is_site_scoped_chameleon_network(net_id, net_name):
            return f"chi-draft-net:{draft_id}:{site}:{net_id}"
        return f"chi-draft-net:{draft_id}:{net_id}"

    def _network_label(site: str, net_id: str, net_name: str) -> str:
        if _is_site_scoped_chameleon_network(net_id, net_name) and site:
            return f"{net_name}\n@ {site}\n(network)"
        return f"{net_name}\n(network)"

    def _is_fabnet_network_name(net_name: str) -> bool:
        normalized = "".join(ch for ch in str(net_name).lower() if ch.isalnum())
        return normalized.startswith("fabnetv4") or normalized.startswith("fabnetv6")

    def _get_node_networks(node: dict) -> list[tuple[int, dict | None]]:
        """Return list of (nic_index, network_dict_or_None) for a node.
        Handles interfaces array, legacy network field, and legacy connection_type.
        """
        ifaces = node.get("interfaces")
        if ifaces:
            assignments = []
            for i, ifc in enumerate(ifaces):
                if not isinstance(ifc, dict):
                    continue
                net = _normalize_chameleon_network_ref(ifc.get("network"))
                if not net:
                    net = _normalize_chameleon_network_ref({
                        "id": ifc.get("network_id") or ifc.get("network_name") or ifc.get("name"),
                        "name": ifc.get("network_name") or ifc.get("name") or ifc.get("network_id"),
                    })
                assignments.append((ifc.get("nic", i), net))
            return assignments
        # Legacy: single network field
        net = _normalize_chameleon_network_ref(node.get("network"))
        if net:
            return [(0, net)]
        # Legacy: connection_type
        conn_type = node.get("connection_type", "")
        if conn_type == "fabnet_v4":
            return [(0, {"id": "_fabnetv4", "name": "fabnetv4"})]
        return []

    def _looks_like_fabnetv4_ip(ip: str) -> bool:
        """Chameleon FABNetv4 addresses are allocated from 10.128.0.0/10."""
        parts = str(ip or "").split(".")
        if len(parts) != 4:
            return False
        try:
            first = int(parts[0])
            second = int(parts[1])
        except ValueError:
            return False
        return first == 10 and 128 <= second <= 191

    def _instance_ip_addresses(res: dict) -> list[str]:
        ips = res.get("ip_addresses") or []
        if isinstance(ips, str):
            ips = [ips]
        elif not isinstance(ips, list):
            ips = []
        return [str(ip) for ip in ips if ip]

    def _runtime_resource_display_name(res: dict) -> str:
        relationship = res.get("relationship") if isinstance(res.get("relationship"), dict) else {}
        return (
            res.get("planned_node_name")
            or relationship.get("planned_node_name")
            or res.get("name")
            or res.get("id")
            or "server"
        )

    # --- Network elements ---
    # Emit from per-node assignments (interfaces array or legacy network field)
    emitted_nets: dict[str, str] = {}  # network scope key → cy_net_id
    for node in draft.get("nodes", []):
        node_site = node.get("site") or draft.get("site", "?")
        for _nic, net_assign in _get_node_networks(node):
            if not net_assign or not net_assign.get("id"):
                continue
            net_id = net_assign["id"]
            net_name = net_assign.get("name", "net")
            # Skip fabnetv4 networks — handled separately below
            if _is_fabnet_network_name(net_name):
                continue
            net_key = _network_scope_key(node_site, net_id, net_name)
            if net_key in emitted_nets:
                continue
            cy_net_id = _network_cy_id(node_site, net_id, net_name)
            emitted_nets[net_key] = cy_net_id
            net_parent = site_container_ids.get(node_site, next(iter(site_container_ids.values()), ""))
            nodes.append({
                "data": {
                    "id": cy_net_id,
                    "label": _network_label(node_site, net_id, net_name),
                    "element_type": "network",
                    "testbed": "Chameleon",
                    "draft_id": draft_id,
                    "network_id": net_id,
                    "deletable": "false",
                    "name": net_name,
                    "site": node_site,
                    "parent": net_parent,
                },
                "classes": "network-l2 chameleon-draft-net",
            })

    # Also emit legacy networks (from networks array, backward compat)
    for net in draft.get("networks", []):
        net_id = net.get("id") or net.get("name", "")
        if not net_id:
            continue
        net_name = net.get("name", "net")
        connected_nodes = net.get("connected_nodes", [])
        net_site = net.get("site", "")
        if not net_site and connected_nodes:
            for cn in connected_nodes:
                cn_node = next((n for n in draft.get("nodes", []) if n.get("id") == cn), None)
                if cn_node:
                    net_site = cn_node.get("site", "")
                    break
        net_key = _network_scope_key(net_site, net_id, net_name)
        if net_key in emitted_nets:
            existing_net_id = emitted_nets[net_key]
            for existing_node in nodes:
                data = existing_node.get("data", {})
                if data.get("id") == existing_net_id:
                    data.setdefault("type", net.get("type", ""))
                    data.setdefault("vlan", str(net.get("vlan", "")))
                    data.setdefault("facility_port", net.get("facility_port", ""))
                    data.setdefault("fabric_site", net.get("fabric_site", ""))
                    break
            continue
        cy_net_id = _network_cy_id(net_site, net_id, net_name)
        emitted_nets[net_key] = cy_net_id
        net_parent = site_container_ids.get(net_site, next(iter(site_container_ids.values()), ""))
        nodes.append({
            "data": {
                "id": cy_net_id,
                "label": _network_label(net_site, net_id, net_name),
                "element_type": "network",
                "testbed": "Chameleon",
                "draft_id": draft_id,
                "network_id": net_id,
                "type": net.get("type", ""),
                "vlan": str(net.get("vlan", "")),
                "facility_port": net.get("facility_port", ""),
                "fabric_site": net.get("fabric_site", ""),
                "deletable": "true",
                "name": net_name,
                "site": net_site,
                "parent": net_parent,
            },
            "classes": "network-l2 chameleon-draft-net",
        })

    # Runtime-only Chameleon networks. These appear when a deployed Chameleon
    # slice is attached to a federated slice after launch, or when the original
    # planned topology is not present in the registry.
    for res in network_resources:
        net_id = res.get("id") or res.get("provider_id") or res.get("name", "")
        if not net_id:
            continue
        net_name = res.get("name") or net_id
        if _is_fabnet_network_name(net_name):
            continue
        net_site = res.get("site") or draft.get("site", "")
        net_key = _network_scope_key(net_site, net_id, net_name)
        if net_key in emitted_nets:
            continue
        cy_net_id = _network_cy_id(net_site, net_id, net_name)
        emitted_nets[net_key] = cy_net_id
        net_parent = site_container_ids.get(net_site, next(iter(site_container_ids.values()), ""))
        nodes.append({
            "data": {
                "id": cy_net_id,
                "label": _network_label(net_site, net_id, net_name),
                "element_type": "network",
                "testbed": "Chameleon",
                "draft_id": draft_id,
                "name": net_name,
                "site": net_site,
                "network_id": net_id,
                "resource_id": res.get("resource_id", ""),
                "provider_id": res.get("provider_id", ""),
                "status": res.get("status", ""),
                "parent": net_parent,
            },
            "classes": "network-l2 chameleon-draft-net",
        })

    # --- FABNetv4 site-scoped network nodes + global internet ---
    fabnetv4_sites: set[str] = set()
    has_fabnetv4 = False
    for node in draft.get("nodes", []):
        for _nic, net_assign in _get_node_networks(node):
            if net_assign and net_assign.get("name") and _is_fabnet_network_name(net_assign["name"]):
                has_fabnetv4 = True
                node_site = node.get("site") or draft.get("site", "?")
                fabnetv4_sites.add(node_site)
    for res in instance_resources:
        if any(_looks_like_fabnetv4_ip(ip) for ip in _instance_ip_addresses(res)):
            has_fabnetv4 = True
            fabnetv4_sites.add(res.get("site") or draft.get("site", "?"))

    fabnetv4_net_ids: dict[str, str] = {}  # site → cy network ID
    for site in fabnetv4_sites:
        cy_fabnet_id = f"chi-fabnetv4:{draft_id}:{site}"
        fabnetv4_net_ids[site] = cy_fabnet_id
        net_parent = site_container_ids.get(site, next(iter(site_container_ids.values()), ""))
        nodes.append({
            "data": {
                "id": cy_fabnet_id,
                "label": f"FABNetv4 Gateway\n@ {site}",
                "element_type": "network",
                "testbed": "Chameleon",
                "draft_id": draft_id,
                "name": "fabnetv4",
                "net_type": "FABNetv4",
                "deletable": "false",
                "parent": net_parent,
            },
            "classes": "network-l3 chameleon-draft-net",
        })

    if has_fabnetv4:
        # Global FABRIC Internet node (same ID as FABRIC uses for dedup in composite)
        nodes.append({
            "data": {
                "id": "fabnet-internet-v4",
                "label": "☁\nFABRIC Internet\n(FABNetv4)",
                "element_type": "fabnet-internet",
            },
            "classes": "fabnet-internet",
        })
        # Edges from site-scoped fabnetv4 to global internet
        for site, cy_fabnet_id in fabnetv4_net_ids.items():
            edges.append({
                "data": {
                    "id": f"edge-fabnet-internet:{draft_id}:{site}",
                    "source": cy_fabnet_id,
                    "target": "fabnet-internet-v4",
                    "label": "",
                    "element_type": "fabnet-internet-edge",
                },
                "classes": "edge-fabnet-internet",
            })

    def _ensure_runtime_l2_network(site: str, net_id: str, net_name: str) -> str:
        net_key = _network_scope_key(site, net_id, net_name)
        existing = emitted_nets.get(net_key)
        if existing:
            return existing
        cy_net_id = _network_cy_id(site, net_id, net_name)
        emitted_nets[net_key] = cy_net_id
        net_parent = site_container_ids.get(site, next(iter(site_container_ids.values()), ""))
        nodes.append({
            "data": {
                "id": cy_net_id,
                "label": _network_label(site, net_id, net_name),
                "element_type": "network",
                "testbed": "Chameleon",
                "draft_id": draft_id,
                "name": net_name,
                "site": site,
                "network_id": net_id,
                "deletable": "false",
                "parent": net_parent,
            },
            "classes": "network-l2 chameleon-draft-net",
        })
        return cy_net_id

    def _append_runtime_interface(
        *,
        instance_node_id: str,
        instance_name: str,
        resource_id: str,
        nic_index: int,
        network_id: str,
        network_name: str,
        target_id: str,
        layer: str = "l2",
    ) -> None:
        comp_id = f"chi-resource-comp:{draft_id}:{resource_id}:nic-{nic_index}"
        nodes.append({
            "data": {
                "id": comp_id,
                "parent_vm": instance_node_id,
                "label": network_name[:12],
                "element_type": "component",
                "name": f"nic-{nic_index}",
                "model": "NIC_Basic",
                "node_name": instance_name,
            },
            "classes": "component component-nic",
        })
        edges.append({
            "data": {
                "id": f"edge-chi-runtime:{draft_id}:{resource_id}:nic{nic_index}-{network_id}",
                "source": comp_id,
                "target": target_id,
                "source_vm": instance_node_id,
                "source_comp": comp_id,
                "component_name": f"nic-{nic_index}",
                "label": network_name[:12],
                "element_type": "interface",
                "interface_name": f"nic-{nic_index}",
                "node_name": instance_name,
                "network_name": network_name,
            },
            "classes": f"edge-{layer} edge-draft",
        })

    # Deployed instances that do not correspond to planned nodes still need to
    # render in topology. This is common for federated slices created from
    # provider resources after deployment.
    for res in instance_resources:
        instance_id = res.get("id", "")
        if instance_id and instance_id in rendered_instance_resource_ids:
            continue
        resource_id = instance_id or res.get("resource_id") or res.get("provider_id") or res.get("name", "instance")
        site = res.get("site") or draft.get("site", "?")
        display_name = _runtime_resource_display_name(res)
        instance_name = res.get("name") or display_name
        status = str(res.get("status") or "UNKNOWN").upper()
        state_colors = CHAMELEON_STATE_COLORS.get(status, CHAMELEON_DEFAULT_STATE)
        state_colors_dark = CHAMELEON_STATE_COLORS_DARK.get(status, CHAMELEON_DEFAULT_STATE_DARK)
        floating_ip = res.get("floating_ip") or res.get("management_ip") or ""
        ip_addresses = _instance_ip_addresses(res)
        ip = floating_ip or (ip_addresses[0] if ip_addresses else "")

        label_parts = [display_name, f"[{status}]"]
        if floating_ip:
            label_parts.append(f"Floating IP: {floating_ip}")
        elif ip:
            label_parts.append(ip)

        parent_id = site_container_ids.get(site, next(iter(site_container_ids.values()), ""))
        cy_node_id = f"chi-resource-node:{draft_id}:{resource_id}"
        nodes.append({
            "data": {
                "id": cy_node_id,
                "label": "\n".join(label_parts),
                "element_type": "chameleon_instance",
                "testbed": "Chameleon",
                "name": display_name,
                "instance_name": instance_name,
                "site": site,
                "status": status,
                "instance_id": instance_id,
                "resource_id": res.get("resource_id", ""),
                "provider_id": res.get("provider_id", ""),
                "floating_ip": floating_ip,
                "management_ip": res.get("management_ip", ""),
                "ip": ip,
                "ip_addresses": ip_addresses,
                "ssh_ready": bool(res.get("ssh_ready")),
                "ssh_command": res.get("ssh_command", ""),
                "ssh_user": res.get("ssh_user", ""),
                "node_type": res.get("node_type", "?"),
                "image": res.get("image", "?"),
                "count": 1,
                "parent": parent_id,
                "bg_color": state_colors["bg"],
                "border_color": state_colors["border"],
                "bg_color_dark": state_colors_dark["bg"],
                "border_color_dark": state_colors_dark["border"],
            },
            "classes": f"chameleon-instance chameleon-{status.lower()}",
        })

        runtime_network_targets: list[tuple[str, str, str, str]] = []
        if floating_ip or res.get("management_ip"):
            sharednet_id = _ensure_runtime_l2_network(site, "sharednet1", "sharednet1")
            runtime_network_targets.append(("sharednet1", "sharednet1", sharednet_id, "l2"))
        for net_res in network_resources:
            net_site = net_res.get("site") or draft.get("site", "")
            if net_site and site and net_site != site:
                continue
            net_id = net_res.get("id") or net_res.get("provider_id") or net_res.get("name", "")
            net_name = net_res.get("name") or net_id
            if not net_id or _is_fabnet_network_name(net_name):
                continue
            target_id = _ensure_runtime_l2_network(site, net_id, net_name)
            runtime_network_targets.append((net_id, net_name, target_id, "l2"))
        if any(_looks_like_fabnetv4_ip(ip_addr) for ip_addr in ip_addresses):
            fabnet_target = fabnetv4_net_ids.get(site)
            if fabnet_target:
                runtime_network_targets.append(("_fabnetv4", "fabnetv4", fabnet_target, "l3"))

        seen_runtime_targets: set[str] = set()
        for nic_index, (net_id, net_name, target_id, layer) in enumerate(runtime_network_targets):
            if target_id in seen_runtime_targets:
                continue
            seen_runtime_targets.add(target_id)
            _append_runtime_interface(
                instance_node_id=cy_node_id,
                instance_name=display_name,
                resource_id=resource_id,
                nic_index=nic_index,
                network_id=net_id,
                network_name=net_name,
                target_id=target_id,
                layer=layer,
            )

    # --- NIC component badges + interface edges per node ---
    for node in draft.get("nodes", []):
        node_id = node.get("id", "")
        node_name = node.get("name", "node")
        node_site = node.get("site") or draft.get("site", "?")
        cy_node_id = f"chi-draft-node:{draft_id}:{node_id}"

        for nic_index, net_assign in _get_node_networks(node):
            if not net_assign or not net_assign.get("id"):
                continue
            net_id = net_assign["id"]
            net_name = net_assign.get("name", "net")

            if _is_fabnet_network_name(net_name) and node_site in fabnetv4_net_ids:
                # FABNetv4 — NIC connects to site-scoped gateway
                comp_id = f"chi-comp:{draft_id}:{node_id}:nic-{nic_index}"
                cy_fabnet_id = fabnetv4_net_ids[node_site]
                nodes.append({
                    "data": {
                        "id": comp_id,
                        "parent_vm": cy_node_id,
                        "label": "fabnetv4",
                        "element_type": "component",
                        "name": f"nic-{nic_index}",
                        "model": "NIC_Basic",
                        "node_name": node_name,
                    },
                    "classes": "component component-nic",
                })
                edges.append({
                    "data": {
                        "id": f"edge-chi-fabnet:{draft_id}:{node_id}:nic{nic_index}",
                        "source": comp_id,
                        "target": cy_fabnet_id,
                        "source_vm": cy_node_id,
                        "source_comp": comp_id,
                        "component_name": f"nic-{nic_index}",
                        "label": "fabnetv4",
                        "element_type": "interface",
                        "interface_name": f"nic-{nic_index}",
                        "node_name": node_name,
                        "network_name": "fabnetv4",
                    },
                    "classes": "edge-l3 edge-draft",
                })
            else:
                # Regular network — NIC → network node
                net_key = _network_scope_key(node_site, net_id, net_name)
                cy_net_id = emitted_nets.get(net_key, _network_cy_id(node_site, net_id, net_name))
                comp_id = f"chi-comp:{draft_id}:{node_id}:nic-{nic_index}"
                nodes.append({
                    "data": {
                        "id": comp_id,
                        "parent_vm": cy_node_id,
                        "label": net_name[:12],
                        "element_type": "component",
                        "name": f"nic-{nic_index}",
                        "model": "NIC_Basic",
                        "node_name": node_name,
                    },
                    "classes": "component component-nic",
                })
                edges.append({
                    "data": {
                        "id": f"edge-chi:{draft_id}:{node_id}:nic{nic_index}-{net_id}",
                        "source": comp_id,
                        "target": cy_net_id,
                        "source_vm": cy_node_id,
                        "source_comp": comp_id,
                        "component_name": f"nic-{nic_index}",
                        "label": net_name[:12],
                        "element_type": "interface",
                        "interface_name": f"nic-{nic_index}",
                        "node_name": node_name,
                        "network_name": net_name,
                    },
                    "classes": "edge-l2 edge-draft",
                })

    return {"nodes": nodes, "edges": edges}


# Backward-compatible alias
build_chameleon_draft_graph = build_chameleon_slice_graph


# ---------------------------------------------------------------------------
# Chameleon graph elements — merge into existing FABRIC graph
# ---------------------------------------------------------------------------

# Chameleon state colors — ACTIVE = Chameleon green (#39B54A), others orange
CHAMELEON_STATE_COLORS = {
    "ACTIVE": {"bg": "#e8f5e9", "border": "#39B54A"},
    "BUILD": {"bg": "#fff3e0", "border": "#ffb74d"},
    "SHUTOFF": {"bg": "#eeeeee", "border": "#616161"},
    "ERROR": {"bg": "#fce4ec", "border": "#b00020"},
    "DELETED": {"bg": "#eeeeee", "border": "#616161"},
}
CHAMELEON_DEFAULT_STATE = {"bg": "#fff3e0", "border": "#ff8542"}

CHAMELEON_STATE_COLORS_DARK = {
    "ACTIVE": {"bg": "#0f2818", "border": "#39B54A"},
    "BUILD": {"bg": "#3a2008", "border": "#ff8542"},
    "SHUTOFF": {"bg": "#222230", "border": "#8a8a9a"},
    "ERROR": {"bg": "#3a1018", "border": "#ff6b6b"},
    "DELETED": {"bg": "#222230", "border": "#8a8a9a"},
}
CHAMELEON_DEFAULT_STATE_DARK = {"bg": "#3a2008", "border": "#ffb74d"}


def build_chameleon_elements(instances: list[dict], connections: list[dict] | None = None) -> dict[str, Any]:
    """Build Cytoscape.js graph elements for Chameleon instances.

    Args:
        instances: List of Chameleon instance dicts (from /api/chameleon/instances).
        connections: Optional list of cross-testbed connections:
            [{"chameleon_instance_id": str, "fabric_node": str, "type": "l2_stitch" | "fabnet_v4"}]

    Returns:
        {"nodes": [...], "edges": [...]} that can be merged into an existing FABRIC graph.
    """
    nodes = []
    edges = []

    if not instances:
        return {"nodes": [], "edges": []}

    # Chameleon cluster container node
    nodes.append({
        "data": {
            "id": "chameleon:cluster",
            "label": "Chameleon Cloud",
            "element_type": "chameleon_cluster",
        },
        "classes": "chameleon-cluster",
    })

    for inst in instances:
        inst_id = inst.get("id", "")
        name = inst.get("name", "instance")
        site = inst.get("site", "?")
        status = inst.get("status", "UNKNOWN")
        ip = inst.get("floating_ip") or (inst.get("ip_addresses", [""])[0] if inst.get("ip_addresses") else "")
        state_colors = CHAMELEON_STATE_COLORS.get(status, CHAMELEON_DEFAULT_STATE)
        state_colors_dark = CHAMELEON_STATE_COLORS_DARK.get(status, CHAMELEON_DEFAULT_STATE_DARK)

        label = f"{name}\n@ {site}\n{ip}" if ip else f"{name}\n@ {site}"

        nodes.append({
            "data": {
                "id": f"chi:{inst_id}",
                "label": label,
                "element_type": "chameleon_instance",
                "testbed": "Chameleon",
                "name": name,
                "site": site,
                "status": status,
                "ip": ip,
                "instance_id": inst_id,
                "parent": "chameleon:cluster",
                "bg_color": state_colors["bg"],
                "border_color": state_colors["border"],
                "bg_color_dark": state_colors_dark["bg"],
                "border_color_dark": state_colors_dark["border"],
            },
            "classes": f"chameleon-instance chameleon-{status.lower()}",
        })

    # Cross-testbed connections
    if connections:
        for conn in connections:
            chi_id = conn.get("chameleon_instance_id", "")
            fabric_node = conn.get("fabric_node", "")
            conn_type = conn.get("type", "fabnet_v4")

            if chi_id and fabric_node:
                edge_label = "L2 Stitch" if conn_type == "l2_stitch" else "FABnet v4"
                edges.append({
                    "data": {
                        "id": f"xtb:{chi_id}-{fabric_node}",
                        "source": f"chi:{chi_id}",
                        "target": fabric_node,  # FABRIC node ID
                        "label": edge_label,
                        "element_type": "cross_testbed",
                        "connection_type": conn_type,
                    },
                    "classes": f"edge-cross-testbed edge-{conn_type.replace('_', '-')}",
                })

    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# Composite graph — merge member slice graphs
# ---------------------------------------------------------------------------

_ID_FIELDS = ("id", "parent", "source", "target", "source_vm", "source_comp", "parent_vm", "parent_node")


def _prefix_graph_ids(graph: dict[str, Any], prefix: str, member_parent: str | None = None) -> dict[str, Any]:
    """Prefix all element IDs in a graph to avoid collisions between members.

    Args:
        graph: ``{"nodes": [...], "edges": [...]}``
        prefix: e.g. ``"fab:slice-uuid-1"``
        member_parent: if set, top-level nodes (those without a parent, or whose
            parent is a slice container) get this as their parent.
    """
    id_map: dict[str, str] = {}  # original_id → prefixed_id
    out_nodes: list[dict] = []
    out_edges: list[dict] = []

    # First pass: build ID map from nodes
    for node in graph.get("nodes", []):
        old_id = node["data"]["id"]
        new_id = f"{prefix}:{old_id}"
        id_map[old_id] = new_id

    # Second pass: rewrite nodes
    for node in graph.get("nodes", []):
        data = {**node["data"]}
        data["id"] = id_map[data["id"]]

        # Rewrite parent references
        for field in ("parent", "parent_vm", "parent_node"):
            if field in data and data[field]:
                data[field] = id_map.get(data[field], f"{prefix}:{data[field]}")

        # Top-level slice/cluster container nodes become children of the member bounding box.
        # fabnet-internet nodes stay independent (shared across all members in composite).
        etype = data.get("element_type", "")
        if etype == "fabnet-internet":
            pass  # Never parent under a member — stays top-level
        elif member_parent and etype in ("slice", "chameleon_draft", "chameleon_cluster"):
            data["parent"] = member_parent
        elif member_parent and "parent" not in data:
            data["parent"] = member_parent

        out_nodes.append({"data": data, "classes": node.get("classes", "")})

    # Third pass: rewrite edges
    for edge in graph.get("edges", []):
        data = {**edge["data"]}
        data["id"] = f"{prefix}:{data['id']}"
        for field in ("source", "target", "source_vm", "source_comp"):
            if field in data and data[field]:
                data[field] = id_map.get(data[field], f"{prefix}:{data[field]}")
        out_edges.append({"data": data, "classes": edge.get("classes", "")})

    return {"nodes": out_nodes, "edges": out_edges}


_COMPOSITE_MEMBER_CONTAINER_TYPES = {"slice", "chameleon_draft", "chameleon_cluster"}


def _flatten_composite_member_graph(graph: dict[str, Any]) -> dict[str, Any]:
    """Remove standalone member grouping containers from a composite graph.

    Standalone FABRIC and Chameleon topology views use compound slice/site
    containers as visual folders. Federated/composite topology views already
    have testbed and connection context, so those folders add visual clutter.
    """
    container_ids = {
        node.get("data", {}).get("id")
        for node in graph.get("nodes", [])
        if node.get("data", {}).get("element_type") in _COMPOSITE_MEMBER_CONTAINER_TYPES
    }
    container_ids.discard(None)
    if not container_ids:
        return graph

    flattened_nodes: list[dict] = []
    for node in graph.get("nodes", []):
        data = dict(node.get("data", {}))
        if data.get("id") in container_ids:
            continue
        if data.get("parent") in container_ids:
            data.pop("parent", None)
        flattened_nodes.append({"data": data, "classes": node.get("classes", "")})

    flattened_edges = [
        edge
        for edge in graph.get("edges", [])
        if edge.get("data", {}).get("source") not in container_ids
        and edge.get("data", {}).get("target") not in container_ids
    ]
    return {"nodes": flattened_nodes, "edges": flattened_edges}


def _composite_member_endpoint_fallback_id(graph: dict[str, Any]) -> str:
    """Return a real member resource to anchor slice-level fallback edges."""
    priority = {
        "node": 0,
        "chameleon_instance": 0,
        "network": 1,
        "facility-port": 2,
        "component": 3,
        "port-mirror": 4,
    }
    best: tuple[int, str] | None = None
    for node in graph.get("nodes", []):
        data = node.get("data", {})
        node_id = str(data.get("id", ""))
        element_type = data.get("element_type", "")
        if not node_id or element_type in _COMPOSITE_MEMBER_CONTAINER_TYPES:
            continue
        if element_type == "fabnet-internet":
            continue
        score = priority.get(element_type, 100)
        if best is None or score < best[0]:
            best = (score, node_id)
    return best[1] if best else ""


def build_composite_graph(
    fabric_members: list[tuple[dict, str]],
    chameleon_members: list[tuple[dict, str]],
    cross_connections: list[dict] | None = None,
) -> dict[str, Any]:
    """Build a merged Cytoscape.js graph from composite slice members.

    Args:
        fabric_members: list of ``(slice_data, member_id)`` for FABRIC slices
        chameleon_members: list of ``(chameleon_slice, member_id)`` for Chameleon slices
        cross_connections: optional overlay connections between members

    Returns:
        ``{"nodes": [...], "edges": [...]}`` — merged Cytoscape.js elements
    """
    all_nodes: list[dict] = []
    all_edges: list[dict] = []
    fabnet_internet_ids: list[str] = []  # prefixed IDs of fabnet-internet nodes to deduplicate
    member_endpoint_fallbacks: dict[tuple[str, str], str] = {}
    member_slice_names: dict[tuple[str, str], str] = {}

    # --- FABRIC members ---
    for slice_data, member_id in fabric_members:
        member_graph = build_graph(slice_data)
        prefix = f"fab:{member_id}"
        member_slice_name = slice_data.get("name", member_id)
        member_slice_names[("fab", member_id)] = member_slice_name

        # FABRIC member graphs already include the same slice container used by
        # the standalone FABRIC topology view. Do not wrap them in an extra
        # composite-member box; otherwise federated FABRIC sub-slices show two
        # nested boxes for the same slice.
        prefixed = _prefix_graph_ids(member_graph, prefix, None)
        # Tag every prefixed FABRIC node with its parent slice context so the
        # frontend can dispatch terminal/SSH actions against the right slice
        # (the composite view's selectedSliceName is the *composite* slice,
        # not the member, so we can't fall back to it).
        for n in prefixed["nodes"]:
            n["data"]["slice_name"] = member_slice_name
            n["data"]["slice_id"] = member_id
            n["data"]["testbed"] = "FABRIC"
        prefixed = _flatten_composite_member_graph(prefixed)
        member_endpoint_fallbacks[("fab", member_id)] = _composite_member_endpoint_fallback_id(prefixed)
        all_nodes.extend(prefixed["nodes"])
        all_edges.extend(prefixed["edges"])

        # Track fabnet-internet nodes for dedup
        for node in prefixed["nodes"]:
            if node["data"].get("element_type") == "fabnet-internet":
                fabnet_internet_ids.append(node["data"]["id"])

    # --- Chameleon members ---
    for chi_slice, member_id in chameleon_members:
        member_graph = build_chameleon_slice_graph(chi_slice)
        prefix = f"chi:{member_id}"
        member_slice_names[("chi", member_id)] = chi_slice.get("name", member_id)

        # Chameleon member graphs already have the same site-cluster containers
        # used by the standalone Chameleon topology view. Do not wrap them in an
        # extra composite-member box; otherwise federated Chameleon sub-slices
        # look different from normal Chameleon slices.
        prefixed = _prefix_graph_ids(member_graph, prefix, None)
        for n in prefixed["nodes"]:
            n["data"]["slice_name"] = member_slice_names[("chi", member_id)]
            n["data"]["slice_id"] = member_id
            if n["data"].get("element_type") != "fabnet-internet":
                n["data"]["testbed"] = "Chameleon"
        prefixed = _flatten_composite_member_graph(prefixed)
        member_endpoint_fallbacks[("chi", member_id)] = _composite_member_endpoint_fallback_id(prefixed)
        all_nodes.extend(prefixed["nodes"])
        all_edges.extend(prefixed["edges"])

        # Track fabnet-internet nodes from Chameleon members for dedup
        for node in prefixed["nodes"]:
            if node["data"].get("element_type") == "fabnet-internet":
                fabnet_internet_ids.append(node["data"]["id"])

    # --- Deduplicate FABNet Internet nodes ---
    if len(fabnet_internet_ids) > 1:
        shared_id = "shared:fabnet-internet-v4"
        # Remove all individual fabnet-internet nodes, add one shared node
        all_nodes = [n for n in all_nodes if n["data"]["id"] not in fabnet_internet_ids]
        all_nodes.append({
            "data": {
                "id": shared_id,
                "label": "☁\nFABRIC Internet\n(FABNetv4)",
                "element_type": "fabnet-internet",
                "testbed": "SHARED",
            },
            "classes": "fabnet-internet composite-shared-network",
        })
        # Re-point edges that targeted any of the individual nodes
        for edge in all_edges:
            if edge["data"].get("target") in fabnet_internet_ids:
                edge["data"]["target"] = shared_id
            if edge["data"].get("source") in fabnet_internet_ids:
                edge["data"]["source"] = shared_id
    elif len(fabnet_internet_ids) == 1:
        # Single FABNet internet node — mark it as shared for potential future connections
        for node in all_nodes:
            if node["data"]["id"] == fabnet_internet_ids[0]:
                node["data"]["testbed"] = "SHARED"
                node["classes"] = node.get("classes", "") + " composite-shared-network"
                break

    def _find_member_node_id(provider_prefix: str, member_id: str, node_name: str) -> str:
        if not node_name:
            return ""
        prefix = f"{provider_prefix}:{member_id}:"
        for node in all_nodes:
            data = node.get("data", {})
            if not str(data.get("id", "")).startswith(prefix):
                continue
            if data.get("name") == node_name and data.get("element_type") in {"node", "chameleon_instance"}:
                return data.get("id", "")
        return ""

    def _find_member_network_id(provider_prefix: str, member_id: str, network_name: str) -> str:
        if not network_name:
            return ""
        prefix = f"{provider_prefix}:{member_id}:"
        for node in all_nodes:
            data = node.get("data", {})
            if not str(data.get("id", "")).startswith(prefix):
                continue
            if data.get("element_type") != "network":
                continue
            if data.get("name") == network_name or data.get("network_name") == network_name:
                return data.get("id", "")
        return ""

    hidden_transport_node_ids: set[str] = set()

    def _node_by_id(node_id: str) -> dict | None:
        for node in all_nodes:
            if node.get("data", {}).get("id") == node_id:
                return node
        return None

    def _member_testbed(provider_prefix: str) -> str:
        return "FABRIC" if provider_prefix == "fab" else "Chameleon"

    def _find_facility_port_name_for_network(network_id: str) -> str:
        if not network_id:
            return ""
        for edge in all_edges:
            data = edge.get("data", {})
            if data.get("source") == network_id:
                other_id = data.get("target", "")
            elif data.get("target") == network_id:
                other_id = data.get("source", "")
            else:
                continue
            other = _node_by_id(other_id)
            other_data = other.get("data", {}) if other else {}
            if other_data.get("element_type") == "facility-port":
                return other_data.get("name", "")
        return ""

    def _network_has_vlan(network_id: str, vlan: str) -> bool:
        if not network_id or not vlan:
            return False
        for edge in all_edges:
            data = edge.get("data", {})
            if network_id not in {data.get("source"), data.get("target")}:
                continue
            if str(data.get("vlan", "")) == str(vlan):
                return True
        return False

    def _network_has_endpoint(network_id: str, endpoint_id: str) -> bool:
        if not network_id or not endpoint_id:
            return False
        for edge in all_edges:
            data = edge.get("data", {})
            source = data.get("source", "")
            target = data.get("target", "")
            if network_id not in {source, target}:
                continue
            other_id = target if source == network_id else source
            if other_id == endpoint_id:
                return True
            if data.get("source_vm") == endpoint_id or data.get("target_vm") == endpoint_id:
                return True
            other = _node_by_id(other_id)
            if other and other.get("data", {}).get("parent_vm") == endpoint_id:
                return True
        return False

    def _network_endpoint_attachment_id(provider_prefix: str, member_id: str, node_name: str, network_id: str) -> str:
        endpoint_id = _find_member_node_id(provider_prefix, member_id, node_name) if node_name else ""
        if not network_id:
            return endpoint_id
        for edge in all_edges:
            data = edge.get("data", {})
            source = data.get("source", "")
            target = data.get("target", "")
            if network_id not in {source, target}:
                continue
            other_id = target if source == network_id else source
            if not endpoint_id:
                other = _node_by_id(other_id)
                other_data = other.get("data", {}) if other else {}
                if other_data.get("element_type") in {"node", "chameleon_instance", "component"}:
                    return other_id
                continue
            if other_id == endpoint_id or data.get("source_vm") == endpoint_id or data.get("target_vm") == endpoint_id:
                return other_id
            other = _node_by_id(other_id)
            if other and other.get("data", {}).get("parent_vm") == endpoint_id:
                return other_id
        return endpoint_id

    def _find_facility_l2_network_id(
        provider_prefix: str,
        member_id: str,
        endpoint: dict,
        conn: dict,
        fp_name: str,
        vlan: str,
    ) -> str:
        explicit_network = (
            conn.get(f"{'fabric' if provider_prefix == 'fab' else 'chameleon'}_network")
            or endpoint.get("network", "")
            or (conn.get("network", "") if provider_prefix == "fab" else "")
        )
        explicit_id = _find_member_network_id(provider_prefix, member_id, explicit_network)
        if explicit_id:
            return explicit_id

        endpoint_node = endpoint.get("node") or (
            conn.get("fabric_node") if provider_prefix == "fab" else conn.get("chameleon_node")
        )
        endpoint_id = _find_member_node_id(provider_prefix, member_id, endpoint_node) if endpoint_node else ""
        prefix = f"{provider_prefix}:{member_id}:"
        candidates: list[tuple[int, str]] = []
        for node in all_nodes:
            data = node.get("data", {})
            node_id = str(data.get("id", ""))
            if not node_id.startswith(prefix) or data.get("element_type") != "network":
                continue
            name = str(data.get("name") or data.get("network_name") or "")
            score = 0
            facility_signal = False
            if provider_prefix == "fab" and fp_name and _find_facility_port_name_for_network(node_id) == fp_name:
                score += 5
                facility_signal = True
            if provider_prefix == "chi" and (
                data.get("type") == "facility_port_l2"
                or data.get("connection_type") == "facility_port_l2"
                or (fp_name and data.get("facility_port") == fp_name)
            ):
                score += 5
                facility_signal = True
            if vlan and (str(data.get("vlan", "")) == str(vlan) or _network_has_vlan(node_id, vlan)):
                score += 2
                facility_signal = True
            if endpoint_id and _network_has_endpoint(node_id, endpoint_id):
                score += 2
            if name.startswith("fp-l2-") or "stitch" in name.lower():
                score += 1
                facility_signal = True
            if facility_signal and score:
                candidates.append((score, node_id))
        if not candidates:
            return ""
        candidates.sort(reverse=True)
        return candidates[0][1]

    def _hide_local_facility_port_nodes(provider_prefix: str, member_id: str, fp_name: str) -> None:
        if not fp_name:
            return
        prefix = f"{provider_prefix}:{member_id}:"
        for node in all_nodes:
            data = node.get("data", {})
            if not str(data.get("id", "")).startswith(prefix):
                continue
            if data.get("element_type") == "facility-port" and data.get("name") == fp_name:
                hidden_transport_node_ids.add(data.get("id", ""))

    def _normalized_token(value: str) -> str:
        return "".join(ch for ch in str(value or "").lower() if ch.isalnum())

    def _hide_related_facility_l2_networks(
        provider_prefix: str,
        member_id: str,
        primary_network_id: str,
        explicit_network: str,
        fp_name: str,
        vlan: str,
    ) -> None:
        prefix = f"{provider_prefix}:{member_id}:"
        primary = _node_by_id(primary_network_id)
        primary_name = (primary.get("data", {}) if primary else {}).get("name", "")
        fp_token = _normalized_token(fp_name)
        for node in all_nodes:
            data = node.get("data", {})
            node_id = str(data.get("id", ""))
            if not node_id.startswith(prefix) or data.get("element_type") != "network":
                continue
            if primary_network_id and node_id == primary_network_id:
                continue

            name = str(data.get("name") or data.get("network_name") or "")
            hide = bool(primary_name and name == primary_name)
            hide = hide or bool(explicit_network and name == explicit_network)

            if provider_prefix == "fab":
                hide = hide or bool(fp_name and _find_facility_port_name_for_network(node_id) == fp_name)
                hide = hide or bool(fp_token and fp_token in _normalized_token(name) and data.get("type") == "VLAN")
            else:
                hide = hide or data.get("type") == "facility_port_l2"
                hide = hide or data.get("connection_type") == "facility_port_l2"
                hide = hide or bool(fp_name and data.get("facility_port") == fp_name)
                hide = hide or (name.startswith("fp-l2-") and (not vlan or str(data.get("vlan", "")) in {"", str(vlan)}))
                hide = hide or ("stitch" in name.lower() and bool(primary_network_id or explicit_network or vlan))

            if vlan:
                hide = hide or str(data.get("vlan", "")) == str(vlan)
                hide = hide or _network_has_vlan(node_id, vlan)

            if hide:
                hidden_transport_node_ids.add(node_id)

    def _slug(value: str) -> str:
        chars = [
            ch.lower() if ch.isalnum() else "-"
            for ch in str(value or "")
        ]
        return "-".join(part for part in "".join(chars).split("-") if part) or "unknown"

    def _shared_facility_port_id(conn: dict, fab_endpoint: dict, chi_endpoint: dict) -> str:
        fp_name = (
            conn.get("facility_port")
            or fab_endpoint.get("facility_port")
            or chi_endpoint.get("facility_port")
            or fab_endpoint.get("site")
            or chi_endpoint.get("site")
            or "facility-port"
        )
        vlan = conn.get("vlan") or fab_endpoint.get("vlan") or chi_endpoint.get("vlan") or ""
        if vlan:
            return f"shared:facility-port-l2:{_slug(fp_name)}:vlan-{_slug(vlan)}"
        conn_id = conn.get("id") or f"{fp_name}-{fab_endpoint.get('slice_id', '')}-{chi_endpoint.get('slice_id', '')}"
        return f"shared:facility-port-l2:{_slug(fp_name)}:{_slug(conn_id)}"

    def _upsert_shared_facility_port(conn: dict, fab_endpoint: dict, chi_endpoint: dict) -> str:
        shared_id = _shared_facility_port_id(conn, fab_endpoint, chi_endpoint)
        for node in all_nodes:
            if node.get("data", {}).get("id") == shared_id:
                return shared_id

        fp_name = (
            conn.get("facility_port")
            or fab_endpoint.get("facility_port")
            or chi_endpoint.get("facility_port")
            or fab_endpoint.get("site")
            or chi_endpoint.get("site")
            or "Facility Port"
        )
        vlan = conn.get("vlan") or fab_endpoint.get("vlan") or chi_endpoint.get("vlan") or ""
        label_lines = [str(fp_name)]
        if vlan:
            label_lines.append(f"VLAN {vlan}")
        all_nodes.append({
            "data": {
                "id": shared_id,
                "label": "\n".join(label_lines),
                "element_type": "facility-port",
                "name": fp_name,
                "site": fab_endpoint.get("site") or chi_endpoint.get("site") or "",
                "vlan": str(vlan),
                "connection_type": "facility_port_l2",
                "testbed": "SHARED",
            },
            "classes": "facility-port composite-shared-network",
        })
        return shared_id

    def _facility_l2_network_name(provider_prefix: str, endpoint: dict, conn: dict, fp_name: str) -> str:
        explicit_name = (
            conn.get(f"{'fabric' if provider_prefix == 'fab' else 'chameleon'}_network")
            or endpoint.get("network")
            or (conn.get("network") if provider_prefix == "fab" else "")
        )
        return str(explicit_name or fp_name or "Facility L2")

    def _local_facility_l2_network_id(
        provider_prefix: str,
        member_id: str,
        endpoint: dict,
        conn: dict,
        fp_name: str,
        vlan: str,
    ) -> str:
        name = _facility_l2_network_name(provider_prefix, endpoint, conn, fp_name)
        parts = ["facility-l2-net", _slug(name)]
        if vlan:
            parts.append(f"vlan-{_slug(vlan)}")
        else:
            parts.append(_slug(conn.get("id") or member_id))
        return f"{provider_prefix}:{member_id}:{':'.join(parts)}"

    def _upsert_local_facility_l2_network(
        provider_prefix: str,
        member_id: str,
        endpoint: dict,
        conn: dict,
        fp_name: str,
        vlan: str,
    ) -> str:
        local_id = _local_facility_l2_network_id(provider_prefix, member_id, endpoint, conn, fp_name, vlan)
        for node in all_nodes:
            if node.get("data", {}).get("id") == local_id:
                return local_id

        name = _facility_l2_network_name(provider_prefix, endpoint, conn, fp_name)
        label_lines = [str(name)]
        if vlan:
            label_lines.append(f"VLAN {vlan}")
        all_nodes.append({
            "data": {
                "id": local_id,
                "label": "\n".join(label_lines),
                "element_type": "network",
                "name": name,
                "type": "facility_port_l2",
                "layer": "L2",
                "vlan": str(vlan),
                "connection_type": "facility_port_l2",
                "facility_port": fp_name,
                "testbed": _member_testbed(provider_prefix),
                "slice_id": member_id,
                "slice_name": member_slice_names.get((provider_prefix, member_id), member_id),
            },
            "classes": "network-l2 composite-facility-l2-network",
        })
        return local_id

    def _mark_facility_l2_network(network_id: str, vlan: str, fp_name: str) -> None:
        node = _node_by_id(network_id)
        if not node:
            return
        data = node.get("data", {})
        data["connection_type"] = "facility_port_l2"
        data.setdefault("layer", "L2")
        if vlan:
            data["vlan"] = str(vlan)
        if fp_name:
            data["facility_port"] = fp_name
        classes = node.get("classes", "")
        if "composite-facility-l2-network" not in classes:
            node["classes"] = f"{classes} composite-facility-l2-network".strip()

    def _promote_matching_facility_port_node(shared_id: str, provider_prefix: str, member_id: str, fp_name: str) -> None:
        if not fp_name:
            return
        prefix = f"{provider_prefix}:{member_id}:"
        for node in list(all_nodes):
            data = node.get("data", {})
            if data.get("element_type") != "facility-port":
                continue
            if not str(data.get("id", "")).startswith(prefix):
                continue
            if data.get("name") != fp_name:
                continue

            old_id = data.get("id", "")
            if not old_id:
                continue
            for edge in all_edges:
                if edge.get("data", {}).get("source") == old_id:
                    edge["data"]["source"] = shared_id
                if edge.get("data", {}).get("target") == old_id:
                    edge["data"]["target"] = shared_id
                if edge.get("data", {}).get("source") == shared_id or edge.get("data", {}).get("target") == shared_id:
                    edge["data"]["element_type"] = "cross_testbed"
                    edge["data"]["connection_type"] = "facility_port_l2"
                    edge["classes"] = "edge-cross-testbed edge-facility-port-l2"
            all_nodes.remove(node)

    def _add_stitch_edge(conn_id: str, source_id: str, target_id: str, label: str, suffix: str) -> None:
        if not source_id or not target_id:
            return
        for edge in all_edges:
            data = edge.get("data", {})
            existing_pair = {data.get("source"), data.get("target")}
            if existing_pair == {source_id, target_id}:
                if label and not data.get("label"):
                    data["label"] = label
                edge["classes"] = "edge-cross-testbed edge-facility-port-l2"
                data["element_type"] = "cross_testbed"
                data["connection_type"] = "facility_port_l2"
                return
        edge_id = f"xconn:{conn_id}:{suffix}"
        if any(edge.get("data", {}).get("id") == edge_id for edge in all_edges):
            return
        all_edges.append({
            "data": {
                "id": edge_id,
                "source": source_id,
                "target": target_id,
                "label": label,
                "element_type": "cross_testbed",
                "connection_type": "facility_port_l2",
            },
            "classes": "edge-cross-testbed edge-facility-port-l2",
        })

    def _add_local_facility_l2_edge(conn_id: str, source_id: str, target_id: str, label: str, suffix: str) -> None:
        if not source_id or not target_id:
            return
        for edge in all_edges:
            data = edge.get("data", {})
            existing_pair = {data.get("source"), data.get("target")}
            if existing_pair == {source_id, target_id}:
                if label and not data.get("label"):
                    data["label"] = label
                data["connection_type"] = "facility_port_l2"
                classes = edge.get("classes", "")
                if "edge-facility-port-l2" not in classes:
                    edge["classes"] = f"{classes} edge-facility-port-l2".strip()
                return
        edge_id = f"xconn:{conn_id}:{suffix}"
        if any(edge.get("data", {}).get("id") == edge_id for edge in all_edges):
            return
        all_edges.append({
            "data": {
                "id": edge_id,
                "source": source_id,
                "target": target_id,
                "label": label,
                "element_type": "interface",
                "connection_type": "facility_port_l2",
            },
            "classes": "edge-l2 edge-facility-port-l2",
        })

    def _connection_type_key(conn_type: Any) -> str:
        normalized = str(conn_type or "").lower()
        if normalized in {"fabnetv4", "fabnet_v4"}:
            return "fabnetv4_l3"
        if normalized == "l2_stitch":
            return "facility_port_l2"
        return normalized

    def _is_fabnetv4_network_node(data: dict[str, Any]) -> bool:
        if data.get("element_type") != "network":
            return False
        for value in (data.get("name"), data.get("network_name"), data.get("type"), data.get("net_type")):
            normalized = "".join(ch for ch in str(value or "").lower() if ch.isalnum())
            if normalized.startswith("fabnetv4"):
                return True
        return False

    def _has_fabnet_internet_uplink(network_id: str) -> bool:
        for edge in all_edges:
            data = edge.get("data", {})
            if data.get("element_type") != "fabnet-internet-edge":
                continue
            source = data.get("source", "")
            target = data.get("target", "")
            if network_id == source:
                other_id = target
            elif network_id == target:
                other_id = source
            else:
                continue
            other = _node_by_id(other_id)
            if other and other.get("data", {}).get("element_type") == "fabnet-internet":
                return True
        return False

    def _member_has_fabnetv4_path(provider_prefix: str, member_id: str) -> bool:
        prefix = f"{provider_prefix}:{member_id}:"
        for node in all_nodes:
            data = node.get("data", {})
            node_id = str(data.get("id", ""))
            if not node_id.startswith(prefix):
                continue
            if _is_fabnetv4_network_node(data) and _has_fabnet_internet_uplink(node_id):
                return True
        return False

    # --- Cross-connections ---
    if cross_connections:
        for conn in cross_connections:
            conn_type = conn.get("type", "fabnetv4")
            conn_type_key = _connection_type_key(conn_type)
            endpoints = [conn.get("endpoint_a"), conn.get("endpoint_b"), conn.get("source"), conn.get("target")]
            fab_endpoint = next((e for e in endpoints if isinstance(e, dict) and e.get("provider") == "fabric"), {})
            chi_endpoint = next((e for e in endpoints if isinstance(e, dict) and e.get("provider") == "chameleon"), {})
            fab_slice = conn.get("fabric_slice") or fab_endpoint.get("slice_id", "")
            fab_node = conn.get("fabric_node") or fab_endpoint.get("node", "")
            chi_slice_id = conn.get("chameleon_slice") or chi_endpoint.get("slice_id", "")
            chi_node = conn.get("chameleon_node") or chi_endpoint.get("node", "")

            if fab_slice and chi_slice_id:
                if conn_type_key == "facility_port_l2":
                    conn_id = conn.get("id") or f"{fab_slice}-{chi_slice_id}-{fab_node}-{chi_node}"
                    fp_name = (
                        conn.get("facility_port")
                        or fab_endpoint.get("facility_port")
                        or chi_endpoint.get("facility_port")
                        or ""
                    )
                    vlan = conn.get("vlan") or fab_endpoint.get("vlan") or chi_endpoint.get("vlan") or ""
                    fab_explicit_network = (
                        conn.get("fabric_network")
                        or fab_endpoint.get("network", "")
                        or conn.get("network", "")
                    )
                    chi_explicit_network = conn.get("chameleon_network") or chi_endpoint.get("network", "")
                    fab_net_id = _find_facility_l2_network_id("fab", fab_slice, fab_endpoint, conn, fp_name, str(vlan))
                    chi_net_id = _find_facility_l2_network_id("chi", chi_slice_id, chi_endpoint, conn, fp_name, str(vlan))

                    if not fp_name:
                        fp_name = _find_facility_port_name_for_network(fab_net_id)
                    conn_for_fp = {**conn}
                    if fp_name:
                        conn_for_fp["facility_port"] = fp_name
                    if not fab_net_id:
                        fab_net_id = _upsert_local_facility_l2_network("fab", fab_slice, fab_endpoint, conn_for_fp, fp_name, str(vlan))
                    if not chi_net_id:
                        chi_net_id = _upsert_local_facility_l2_network("chi", chi_slice_id, chi_endpoint, conn_for_fp, fp_name, str(vlan))
                    shared_fp_id = _upsert_shared_facility_port(conn_for_fp, fab_endpoint, chi_endpoint)
                    _promote_matching_facility_port_node(shared_fp_id, "fab", fab_slice, fp_name)
                    edge_label = f"VLAN {vlan}" if vlan else ""
                    _mark_facility_l2_network(fab_net_id, str(vlan), fp_name)
                    _mark_facility_l2_network(chi_net_id, str(vlan), fp_name)
                    fab_source_id = _network_endpoint_attachment_id("fab", fab_slice, fab_node, fab_net_id)
                    chi_source_id = _network_endpoint_attachment_id("chi", chi_slice_id, chi_node, chi_net_id)
                    _hide_related_facility_l2_networks("fab", fab_slice, fab_net_id, fab_explicit_network, fp_name, str(vlan))
                    _hide_related_facility_l2_networks("chi", chi_slice_id, chi_net_id, chi_explicit_network, fp_name, str(vlan))
                    _hide_local_facility_port_nodes("fab", fab_slice, fp_name)
                    _hide_local_facility_port_nodes("chi", chi_slice_id, fp_name)
                    _add_local_facility_l2_edge(conn_id, fab_source_id, fab_net_id, edge_label, "fabric-endpoint")
                    _add_local_facility_l2_edge(conn_id, chi_source_id, chi_net_id, edge_label, "chameleon-endpoint")
                    _add_stitch_edge(conn_id, fab_net_id, shared_fp_id, edge_label, "fabric-facility-port")
                    _add_stitch_edge(conn_id, chi_net_id, shared_fp_id, edge_label, "chameleon-facility-port")
                    continue

                if (
                    conn_type_key == "fabnetv4_l3"
                    and _member_has_fabnetv4_path("fab", fab_slice)
                    and _member_has_fabnetv4_path("chi", chi_slice_id)
                ):
                    continue

                source_id = _find_member_node_id("fab", fab_slice, fab_node) if fab_node else ""
                target_id = _find_member_node_id("chi", chi_slice_id, chi_node) if chi_node else ""
                source_id = source_id or member_endpoint_fallbacks.get(("fab", fab_slice), "")
                target_id = target_id or member_endpoint_fallbacks.get(("chi", chi_slice_id), "")
                if not source_id or not target_id:
                    continue
                if conn_type_key == "facility_port_l2":
                    label_parts = ["Facility Port L2"]
                    if conn.get("facility_port") or fab_endpoint.get("facility_port"):
                        label_parts.append(str(conn.get("facility_port") or fab_endpoint.get("facility_port")))
                    if conn.get("vlan") or fab_endpoint.get("vlan") or chi_endpoint.get("vlan"):
                        label_parts.append(f"VLAN {conn.get('vlan') or fab_endpoint.get('vlan') or chi_endpoint.get('vlan')}")
                    edge_label = "\n".join(label_parts)
                else:
                    edge_label = "FABNetv4 L3"
                conn_id = conn.get("id") or f"{fab_slice}-{chi_slice_id}-{fab_node}-{chi_node}"
                all_edges.append({
                    "data": {
                        "id": f"xconn:{conn_id}",
                        "source": source_id,
                        "target": target_id,
                        "label": edge_label,
                        "element_type": "cross_testbed",
                        "connection_type": conn_type,
                    },
                    "classes": f"edge-cross-testbed edge-{conn_type.replace('_', '-')}",
                })

    if hidden_transport_node_ids:
        all_nodes = [
            node for node in all_nodes
            if node.get("data", {}).get("id") not in hidden_transport_node_ids
        ]
        all_edges = [
            edge for edge in all_edges
            if edge.get("data", {}).get("source") not in hidden_transport_node_ids
            and edge.get("data", {}).get("target") not in hidden_transport_node_ids
        ]

    deduped_edges: list[dict] = []
    seen_edge_ids: dict[str, dict] = {}
    seen_facility_pairs: dict[frozenset[str], dict] = {}
    for edge in all_edges:
        data = edge.get("data", {})
        edge_id = str(data.get("id", ""))
        source = str(data.get("source", ""))
        target = str(data.get("target", ""))
        classes = edge.get("classes", "")
        existing = seen_edge_ids.get(edge_id) if edge_id else None
        if not existing and "edge-facility-port-l2" in classes:
            existing = seen_facility_pairs.get(frozenset({source, target}))
        if existing:
            existing_data = existing.get("data", {})
            if data.get("label") and not existing_data.get("label"):
                existing_data["label"] = data.get("label")
            existing_classes = existing.get("classes", "")
            for cls in classes.split():
                if cls not in existing_classes.split():
                    existing_classes = f"{existing_classes} {cls}".strip()
            existing["classes"] = existing_classes
            continue
        deduped_edges.append(edge)
        if edge_id:
            seen_edge_ids[edge_id] = edge
        if "edge-facility-port-l2" in classes:
            seen_facility_pairs[frozenset({source, target})] = edge
    all_edges = deduped_edges

    return {"nodes": all_nodes, "edges": all_edges}
