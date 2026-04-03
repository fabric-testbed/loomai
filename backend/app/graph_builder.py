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
            f"[FAB] {node_name}",
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
        label = f"[CHI] {name}\n{site}\n{node_type}"

        nodes.append({
            "data": {
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
            },
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

    # Map planned node names to deployed instance resources
    resource_map: dict[tuple[str, str], dict] = {}
    for res in draft.get("resources", []):
        if res.get("type") == "instance":
            key = (res.get("name", ""), res.get("site", ""))
            resource_map[key] = res

    # Map instance IDs to live data
    instance_map: dict[str, dict] = {}
    if live_instances:
        for inst in live_instances:
            instance_map[inst.get("id", "")] = inst

    # Collect unique sites from nodes (fall back to legacy draft.site)
    unique_sites = sorted(set(
        n.get("site") or draft.get("site", "?")
        for n in draft.get("nodes", [])
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
    floating_ips_set = set(draft.get("floating_ips", []))

    for node in draft.get("nodes", []):
        node_id = node.get("id", "")
        node_name = node.get("name", "node")
        node_type = node.get("node_type", "?")
        image = node.get("image", "?")
        count = node.get("count", 1)
        node_site = node.get("site") or draft.get("site", "?")

        label_parts = [f"[CHI] {node_name}"]
        if count > 1:
            label_parts.append(f"x{count}")

        # Check for deployed instance matching this planned node
        matched_resource = resource_map.get((node_name, node_site))
        live_inst = None
        if matched_resource:
            live_inst = instance_map.get(matched_resource.get("id", ""))

        ssh_ready = False
        if live_inst:
            status = live_inst.get("status", "UNKNOWN")
            state_colors = CHAMELEON_STATE_COLORS.get(status, {"bg": "#fff3e0", "border": "#ff8542"})
            state_colors_dark = CHAMELEON_STATE_COLORS_DARK.get(status, {"bg": "#3a2a1a", "border": "#ff8542"})
            instance_id = live_inst.get("id", "")
            floating_ip = live_inst.get("floating_ip", "")
            ip = floating_ip or (live_inst.get("ip_addresses", [""])[0] if live_inst.get("ip_addresses") else "")
            label_parts.append(f"[{status}]")
            if floating_ip:
                label_parts.append(f"Floating IP: {floating_ip}")
            elif ip:
                label_parts.append(ip)
            node_classes = f"chameleon-instance chameleon-{status.lower()}"
            ssh_ready = bool(matched_resource and matched_resource.get("ssh_ready"))
        elif matched_resource and matched_resource.get("id"):
            status = matched_resource.get("status", "DEPLOYED")
            state_colors = CHAMELEON_STATE_COLORS.get(status, {"bg": "#fff3e0", "border": "#ff8542"})
            state_colors_dark = CHAMELEON_STATE_COLORS_DARK.get(status, {"bg": "#3a2a1a", "border": "#ff8542"})
            instance_id = matched_resource.get("id", "")
            floating_ip = matched_resource.get("floating_ip", "")
            ip = floating_ip
            label_parts.append(f"[{status}]")
            if ip:
                label_parts.append(ip)
            node_classes = f"chameleon-instance chameleon-{status.lower()}"
            ssh_ready = bool(matched_resource.get("ssh_ready"))
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
                "name": node_name,
                "site": node_site,
                "status": status,
                "instance_id": instance_id,
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
        if net and net.get("id") and net["id"] not in seen_net_ids:
            seen_net_ids.add(net["id"])

    # Legacy networks array (backward compat)
    for net in draft.get("networks", []):
        net_id = net.get("id", "")
        if net_id not in seen_net_ids:
            seen_net_ids.add(net_id)

    # --- Helper: extract all network assignments from a node ---
    def _get_node_networks(node: dict) -> list[tuple[int, dict | None]]:
        """Return list of (nic_index, network_dict_or_None) for a node.
        Handles interfaces array, legacy network field, and legacy connection_type.
        """
        ifaces = node.get("interfaces")
        if ifaces:
            return [(ifc.get("nic", i), ifc.get("network")) for i, ifc in enumerate(ifaces)]
        # Legacy: single network field
        net = node.get("network")
        if net and net.get("id"):
            return [(0, net)]
        # Legacy: connection_type
        conn_type = node.get("connection_type", "")
        if conn_type == "fabnet_v4":
            return [(0, {"id": "_fabnetv4", "name": "fabnetv4"})]
        return []

    # --- Network elements ---
    # Emit from per-node assignments (interfaces array or legacy network field)
    emitted_nets: dict[str, str] = {}  # net_id → cy_net_id
    for node in draft.get("nodes", []):
        node_site = node.get("site") or draft.get("site", "?")
        for _nic, net_assign in _get_node_networks(node):
            if not net_assign or not net_assign.get("id"):
                continue
            net_id = net_assign["id"]
            if net_id in emitted_nets:
                continue
            net_name = net_assign.get("name", "net")
            # Skip fabnetv4 networks — handled separately below
            if "fabnet" in net_name.lower():
                continue
            cy_net_id = f"chi-draft-net:{draft_id}:{net_id}"
            emitted_nets[net_id] = cy_net_id
            net_parent = site_container_ids.get(node_site, next(iter(site_container_ids.values()), ""))
            nodes.append({
                "data": {
                    "id": cy_net_id,
                    "label": f"{net_name}\n(network)",
                    "element_type": "network",
                    "name": net_name,
                    "parent": net_parent,
                },
                "classes": "network-l2 chameleon-draft-net",
            })

    # Also emit legacy networks (from networks array, backward compat)
    for net in draft.get("networks", []):
        net_id = net.get("id", "")
        if net_id in emitted_nets:
            continue
        net_name = net.get("name", "net")
        cy_net_id = f"chi-draft-net:{draft_id}:{net_id}"
        emitted_nets[net_id] = cy_net_id
        connected_nodes = net.get("connected_nodes", [])
        net_site = net.get("site", "")
        if not net_site and connected_nodes:
            for cn in connected_nodes:
                cn_node = next((n for n in draft.get("nodes", []) if n.get("id") == cn), None)
                if cn_node:
                    net_site = cn_node.get("site", "")
                    break
        net_parent = site_container_ids.get(net_site, next(iter(site_container_ids.values()), ""))
        nodes.append({
            "data": {
                "id": cy_net_id,
                "label": f"{net_name}\n(network)",
                "element_type": "network",
                "name": net_name,
                "parent": net_parent,
            },
            "classes": "network-l2 chameleon-draft-net",
        })

    # --- FABNetv4 site-scoped network nodes + global internet ---
    fabnetv4_sites: set[str] = set()
    has_fabnetv4 = False
    for node in draft.get("nodes", []):
        for _nic, net_assign in _get_node_networks(node):
            if net_assign and net_assign.get("name") and "fabnet" in net_assign["name"].lower():
                has_fabnetv4 = True
                node_site = node.get("site") or draft.get("site", "?")
                fabnetv4_sites.add(node_site)

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
                "name": "fabnetv4",
                "net_type": "FABNetv4",
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

            if "fabnet" in net_name.lower() and node_site in fabnetv4_net_ids:
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
                cy_net_id = emitted_nets.get(net_id, f"chi-draft-net:{draft_id}:{net_id}")
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

# Chameleon state colors (orange theme)
CHAMELEON_STATE_COLORS = {
    "ACTIVE": {"bg": "#fff3e0", "border": "#ff8542"},
    "BUILD": {"bg": "#fff3e0", "border": "#ffb74d"},
    "SHUTOFF": {"bg": "#eeeeee", "border": "#616161"},
    "ERROR": {"bg": "#fce4ec", "border": "#b00020"},
    "DELETED": {"bg": "#eeeeee", "border": "#616161"},
}
CHAMELEON_DEFAULT_STATE = {"bg": "#fff3e0", "border": "#ff8542"}

CHAMELEON_STATE_COLORS_DARK = {
    "ACTIVE": {"bg": "#3a2008", "border": "#ffb74d"},
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

        label = f"[CHI] {name}\n@ {site}\n{ip}" if ip else f"[CHI] {name}\n@ {site}"

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

    # --- FABRIC members ---
    for slice_data, member_id in fabric_members:
        member_graph = build_graph(slice_data)
        prefix = f"fab:{member_id}"
        member_parent_id = f"member:fab:{member_id}"

        # Add member bounding box
        all_nodes.append({
            "data": {
                "id": member_parent_id,
                "label": f"[FABRIC] {slice_data.get('name', member_id)}",
                "element_type": "composite_member",
                "testbed": "FABRIC",
                "member_id": member_id,
                "member_state": slice_data.get("state", ""),
            },
            "classes": "composite-member composite-member-fabric",
        })

        prefixed = _prefix_graph_ids(member_graph, prefix, member_parent_id)
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
        member_parent_id = f"member:chi:{member_id}"

        all_nodes.append({
            "data": {
                "id": member_parent_id,
                "label": f"[CHI] {chi_slice.get('name', member_id)}",
                "element_type": "composite_member",
                "testbed": "Chameleon",
                "member_id": member_id,
                "member_state": chi_slice.get("state", ""),
            },
            "classes": "composite-member composite-member-chameleon",
        })

        prefixed = _prefix_graph_ids(member_graph, prefix, member_parent_id)
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

    # --- Cross-connections ---
    if cross_connections:
        for conn in cross_connections:
            conn_type = conn.get("type", "fabnetv4")
            fab_slice = conn.get("fabric_slice", "")
            fab_node = conn.get("fabric_node", "")
            chi_slice_id = conn.get("chameleon_slice", "")
            chi_node = conn.get("chameleon_node", "")

            if fab_slice and fab_node and chi_slice_id and chi_node:
                source_id = f"fab:{fab_slice}:node:{fab_slice}:{fab_node}"
                target_id = f"chi:{chi_slice_id}:chi-draft-node:{chi_slice_id}:{chi_node}"
                edge_label = "L2 Stitch" if conn_type == "l2_stitch" else "FABnet v4"
                all_edges.append({
                    "data": {
                        "id": f"xconn:{fab_node}-{chi_node}",
                        "source": source_id,
                        "target": target_id,
                        "label": edge_label,
                        "element_type": "cross_testbed",
                        "connection_type": conn_type,
                    },
                    "classes": f"edge-cross-testbed edge-{conn_type.replace('_', '-')}",
                })

    return {"nodes": all_nodes, "edges": all_edges}
