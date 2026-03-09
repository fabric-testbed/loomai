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
        layer = net.get("layer", "L2")
        net_id = f"net:{slice_id}:{net_name}"

        # Label FABNetv4 networks as gateways
        is_fabnetv4 = net_type in ("FABNetv4", "FABNetv6")
        if is_fabnetv4:
            label = f"{net_name}\nFABNet Gateway"
            fabnet_net_ids.append(net_id)
        else:
            label = f"{net_name}\n({net_type})"

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
            "classes": f"network-{layer.lower()}",
        })

        # Edges from nodes/components to networks via interfaces
        for iface in net.get("interfaces", []):
            iface_node = iface.get("node_name", "")
            iface_name = iface.get("name", "")
            if iface_node:
                vm_id = f"node:{slice_id}:{iface_node}"
                # Route from component if available, else from VM
                comp_id = iface_to_comp.get(iface_name, "")
                source_id = comp_id if comp_id else vm_id
                comp_name = iface_to_comp_name.get(iface_name, "")

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
                    "classes": f"edge-{layer.lower()}",
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
                "parent": f"slice:{slice_id}",
                "label": "\n".join(label_lines),
                "element_type": "facility-port",
                "name": fp_name,
                "site": fp_site,
                "vlan": str(fp_vlan),
                "bandwidth": str(fp_bw),
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
                    "classes": "edge-l2",
                })

    return {"nodes": nodes, "edges": edges}
