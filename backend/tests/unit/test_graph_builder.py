"""Tests for app.graph_builder.build_graph() — pure function, no mocks needed."""

import pytest

from app.graph_builder import (
    build_graph,
    build_chameleon_elements,
    build_chameleon_draft_graph,
    build_chameleon_slice_node_elements,
    _strip_node_prefix,
    _component_summary,
    STATE_COLORS,
    STATE_COLORS_DARK,
    COMPONENT_ABBREV,
    COMPONENT_CATEGORY,
    CHAMELEON_DRAFT_STATE,
    CHAMELEON_DRAFT_CONTAINER_COLOR,
)
from tests.fixtures.slice_data import (
    empty_slice,
    single_node_slice,
    l2_bridge_slice,
    fabnetv4_slice,
    gpu_slice,
    facility_port_slice,
    stableok_slice,
)


# ---------------------------------------------------------------------------
# Helper: _strip_node_prefix
# ---------------------------------------------------------------------------

class TestStripNodePrefix:
    def test_strips_matching_prefix(self):
        assert _strip_node_prefix("node1-nic1-p1", "node1") == "nic1-p1"

    def test_leaves_non_matching(self):
        assert _strip_node_prefix("other-nic1-p1", "node1") == "other-nic1-p1"

    def test_empty_strings(self):
        assert _strip_node_prefix("", "") == ""

    def test_name_equals_prefix(self):
        # "node1-" prefix applied to "node1-" exactly → empty string
        assert _strip_node_prefix("node1-", "node1") == ""


# ---------------------------------------------------------------------------
# Helper: _component_summary
# ---------------------------------------------------------------------------

class TestComponentSummary:
    def test_empty(self):
        assert _component_summary([]) == ""

    def test_single_known(self):
        assert _component_summary([{"model": "GPU_TeslaT4"}]) == "T4"

    def test_multiple_same(self):
        result = _component_summary([
            {"model": "NIC_Basic"},
            {"model": "NIC_Basic"},
        ])
        assert result == "NIC x2"

    def test_mixed(self):
        result = _component_summary([
            {"model": "NIC_Basic"},
            {"model": "GPU_RTX6000"},
        ])
        assert "NIC" in result
        assert "RTX" in result

    def test_unknown_model_uses_raw(self):
        result = _component_summary([{"model": "CustomDevice"}])
        assert result == "CustomDevice"


# ---------------------------------------------------------------------------
# build_graph: structure
# ---------------------------------------------------------------------------

class TestBuildGraphStructure:
    def test_returns_nodes_and_edges(self):
        result = build_graph(empty_slice())
        assert "nodes" in result
        assert "edges" in result
        assert isinstance(result["nodes"], list)
        assert isinstance(result["edges"], list)

    def test_empty_slice_has_only_container(self):
        result = build_graph(empty_slice())
        assert len(result["nodes"]) == 1
        assert len(result["edges"]) == 0
        container = result["nodes"][0]
        assert container["classes"] == "slice"
        assert container["data"]["element_type"] == "slice"

    def test_container_node_has_slice_info(self):
        result = build_graph(empty_slice(name="my-slice", slice_id="abc-123"))
        container = result["nodes"][0]
        assert container["data"]["id"] == "slice:abc-123"
        assert container["data"]["label"] == "my-slice"
        assert container["data"]["state"] == "Draft"


# ---------------------------------------------------------------------------
# build_graph: single node
# ---------------------------------------------------------------------------

class TestBuildGraphSingleNode:
    def test_produces_vm_node(self):
        result = build_graph(single_node_slice())
        vm_nodes = [n for n in result["nodes"] if n["classes"] == "vm"]
        assert len(vm_nodes) == 1

    def test_vm_node_has_correct_data(self):
        result = build_graph(single_node_slice())
        vm = [n for n in result["nodes"] if n["classes"] == "vm"][0]
        assert vm["data"]["name"] == "node1"
        assert vm["data"]["site"] == "RENC"
        assert vm["data"]["cores"] == 2
        assert vm["data"]["ram"] == 8
        assert vm["data"]["disk"] == 10

    def test_vm_label_includes_name_and_resources(self):
        result = build_graph(single_node_slice())
        vm = [n for n in result["nodes"] if n["classes"] == "vm"][0]
        label = vm["data"]["label"]
        assert "node1" in label
        assert "RENC" in label
        assert "2c / 8G / 10G" in label

    def test_vm_parent_is_slice_container(self):
        result = build_graph(single_node_slice(slice_id="hello-uuid"))
        vm = [n for n in result["nodes"] if n["classes"] == "vm"][0]
        assert vm["data"]["parent"] == "slice:hello-uuid"


# ---------------------------------------------------------------------------
# build_graph: state colors
# ---------------------------------------------------------------------------

class TestBuildGraphStateColors:
    @pytest.mark.parametrize("state", ["StableOK", "Active", "Configuring",
                                        "StableError", "Dead", "Nascent"])
    def test_state_colors_applied(self, state):
        data = single_node_slice(state=state)
        data["nodes"][0]["reservation_state"] = state
        result = build_graph(data)
        vm = [n for n in result["nodes"] if n["classes"] == "vm"][0]
        expected = STATE_COLORS[state]
        assert vm["data"]["state_bg"] == expected["bg"]
        assert vm["data"]["state_color"] == expected["border"]

    def test_unknown_state_uses_default(self):
        data = single_node_slice()
        data["nodes"][0]["reservation_state"] = "WeirdState"
        result = build_graph(data)
        vm = [n for n in result["nodes"] if n["classes"] == "vm"][0]
        assert vm["data"]["state_bg"] == "#f8f9fa"

    @pytest.mark.parametrize("state", ["StableOK", "StableError"])
    def test_dark_mode_colors_present(self, state):
        data = single_node_slice(state=state)
        data["nodes"][0]["reservation_state"] = state
        result = build_graph(data)
        vm = [n for n in result["nodes"] if n["classes"] == "vm"][0]
        expected_dark = STATE_COLORS_DARK[state]
        assert vm["data"]["state_bg_dark"] == expected_dark["bg"]
        assert vm["data"]["state_color_dark"] == expected_dark["border"]


# ---------------------------------------------------------------------------
# build_graph: L2 bridge
# ---------------------------------------------------------------------------

class TestBuildGraphL2Bridge:
    def test_two_vms_and_network(self):
        result = build_graph(l2_bridge_slice())
        vm_nodes = [n for n in result["nodes"] if n["classes"] == "vm"]
        net_nodes = [n for n in result["nodes"] if "network" in n["classes"]]
        assert len(vm_nodes) == 2
        assert len(net_nodes) == 1

    def test_network_node_type(self):
        result = build_graph(l2_bridge_slice())
        net = [n for n in result["nodes"] if "network" in n["classes"]][0]
        assert net["classes"] == "network-l2"
        assert net["data"]["type"] == "L2Bridge"
        assert net["data"]["name"] == "lan"

    def test_edges_connect_components_to_network(self):
        result = build_graph(l2_bridge_slice())
        # Should have 2 edges: one from each node's component to the network
        edges = result["edges"]
        assert len(edges) == 2
        for edge in edges:
            assert edge["data"]["target"].startswith("net:")

    def test_component_badge_nodes_created(self):
        result = build_graph(l2_bridge_slice())
        comp_nodes = [n for n in result["nodes"]
                      if n["data"].get("element_type") == "component"]
        assert len(comp_nodes) == 2
        for comp in comp_nodes:
            assert "component" in comp["classes"]
            assert "component-nic" in comp["classes"]

    def test_edge_routes_from_component(self):
        result = build_graph(l2_bridge_slice())
        for edge in result["edges"]:
            # source should be a component ID, not a VM ID
            assert edge["data"]["source"].startswith("comp:")


# ---------------------------------------------------------------------------
# build_graph: FABNetv4 / internet node
# ---------------------------------------------------------------------------

class TestBuildGraphFABNet:
    def test_internet_node_created(self):
        result = build_graph(fabnetv4_slice())
        internet = [n for n in result["nodes"]
                    if n["data"].get("element_type") == "fabnet-internet"]
        assert len(internet) == 1
        assert internet[0]["data"]["id"] == "fabnet-internet-v4"

    def test_internet_node_label(self):
        result = build_graph(fabnetv4_slice())
        internet = [n for n in result["nodes"]
                    if n["data"].get("element_type") == "fabnet-internet"][0]
        assert "FABRIC Internet" in internet["data"]["label"]

    def test_internet_edges_from_gateways(self):
        result = build_graph(fabnetv4_slice())
        internet_edges = [e for e in result["edges"]
                          if e["data"].get("element_type") == "fabnet-internet-edge"]
        assert len(internet_edges) == 2
        for edge in internet_edges:
            assert edge["data"]["target"] == "fabnet-internet-v4"
            assert edge["data"]["source"].startswith("net:")

    def test_fabnet_networks_are_l3(self):
        result = build_graph(fabnetv4_slice())
        nets = [n for n in result["nodes"] if "network" in n["classes"]]
        for net in nets:
            assert net["classes"] == "network-l3"

    def test_no_internet_without_fabnet(self):
        result = build_graph(l2_bridge_slice())
        internet = [n for n in result["nodes"]
                    if n["data"].get("element_type") == "fabnet-internet"]
        assert len(internet) == 0


# ---------------------------------------------------------------------------
# build_graph: GPU components
# ---------------------------------------------------------------------------

class TestBuildGraphGPU:
    def test_gpu_component_without_interfaces_in_label(self):
        result = build_graph(gpu_slice())
        vm = [n for n in result["nodes"] if n["classes"] == "vm"][0]
        # GPU has no interfaces → should appear in VM label
        assert "RTX" in vm["data"]["label"]

    def test_nic_component_with_interfaces_as_badge(self):
        result = build_graph(gpu_slice())
        comp_nodes = [n for n in result["nodes"]
                      if n["data"].get("element_type") == "component"]
        # Only NIC_Basic components have interfaces → become badge nodes
        assert len(comp_nodes) == 2
        for comp in comp_nodes:
            assert comp["data"]["model"] == "NIC_Basic"

    def test_component_categories(self):
        # Verify category mapping
        assert COMPONENT_CATEGORY["GPU_RTX6000"] == "gpu"
        assert COMPONENT_CATEGORY["NIC_Basic"] == "nic"
        assert COMPONENT_CATEGORY["FPGA_Xilinx_U280"] == "fpga"
        assert COMPONENT_CATEGORY["NVME_P4510"] == "nvme"

    def test_component_abbreviations(self):
        assert COMPONENT_ABBREV["GPU_TeslaT4"] == "T4"
        assert COMPONENT_ABBREV["GPU_RTX6000"] == "RTX"
        assert COMPONENT_ABBREV["NIC_ConnectX_6"] == "CX6"
        assert COMPONENT_ABBREV["FPGA_Xilinx_U280"] == "FPGA"


# ---------------------------------------------------------------------------
# build_graph: facility ports
# ---------------------------------------------------------------------------

class TestBuildGraphFacilityPort:
    def test_facility_port_node_created(self):
        result = build_graph(facility_port_slice())
        fp_nodes = [n for n in result["nodes"]
                    if n["data"].get("element_type") == "facility-port"]
        assert len(fp_nodes) == 1

    def test_facility_port_data(self):
        result = build_graph(facility_port_slice())
        fp = [n for n in result["nodes"]
              if n["data"].get("element_type") == "facility-port"][0]
        assert fp["data"]["name"] == "fp1"
        assert fp["data"]["site"] == "RENC"
        assert fp["data"]["vlan"] == "100"

    def test_facility_port_edge_to_network(self):
        result = build_graph(facility_port_slice())
        edges = result["edges"]
        assert len(edges) == 1
        edge = edges[0]
        assert edge["data"]["source"].startswith("fp:")
        assert edge["data"]["target"].startswith("net:")


# ---------------------------------------------------------------------------
# build_graph: site groups
# ---------------------------------------------------------------------------

class TestBuildGraphSiteGroups:
    def test_site_group_in_label(self):
        data = single_node_slice()
        data["nodes"][0]["site_group"] = "@compute"
        result = build_graph(data)
        vm = [n for n in result["nodes"] if n["classes"] == "vm"][0]
        assert "@compute" in vm["data"]["label"]
        assert vm["data"]["site_group"] == "@compute"


# ---------------------------------------------------------------------------
# build_graph: edge details
# ---------------------------------------------------------------------------

class TestBuildGraphEdges:
    def test_edge_with_vlan(self):
        data = l2_bridge_slice()
        data["networks"][0]["interfaces"][0]["vlan"] = "100"
        result = build_graph(data)
        edge = result["edges"][0]
        assert "VLAN 100" in edge["data"]["label"]

    def test_edge_with_ip(self):
        data = l2_bridge_slice()
        data["networks"][0]["interfaces"][0]["ip_addr"] = "192.168.1.10"
        result = build_graph(data)
        edge = result["edges"][0]
        assert "192.168.1.10" in edge["data"]["label"]

    def test_edge_classes_match_layer(self):
        result = build_graph(l2_bridge_slice())
        for edge in result["edges"]:
            assert edge["classes"] == "edge-l2"

    def test_l3_edge_classes(self):
        result = build_graph(fabnetv4_slice())
        l3_edges = [e for e in result["edges"]
                    if e["data"].get("element_type") == "interface"]
        for edge in l3_edges:
            assert edge["classes"] == "edge-l3"


# ---------------------------------------------------------------------------
# build_graph: edge cases
# ---------------------------------------------------------------------------

class TestBuildGraphEdgeCases:
    def test_empty_slice_no_nodes_no_networks(self):
        """Empty slice should have only the container node and no edges."""
        data = {"name": "empty", "id": "e-uuid", "state": "Draft",
                "nodes": [], "networks": [], "facility_ports": []}
        result = build_graph(data)
        assert len(result["nodes"]) == 1
        assert result["nodes"][0]["classes"] == "slice"
        assert len(result["edges"]) == 0

    def test_slice_with_port_mirrors(self):
        """Port mirror nodes should be created with correct data."""
        data = l2_bridge_slice()
        data["port_mirrors"] = [{
            "name": "pm1",
            "mirror_interface_name": "node1-nic1-p1",
            "receive_interface_name": "node2-nic1-p1",
            "mirror_direction": "both",
        }]
        result = build_graph(data)
        pm_nodes = [n for n in result["nodes"]
                    if n["data"].get("element_type") == "port-mirror"]
        assert len(pm_nodes) == 1
        assert pm_nodes[0]["data"]["name"] == "pm1"
        assert pm_nodes[0]["data"]["mirror_direction"] == "both"
        # Should have mirror edges
        pm_edges = [e for e in result["edges"]
                    if e["data"].get("element_type") == "port-mirror-edge"]
        assert len(pm_edges) == 2  # one source, one receive

    def test_chameleon_nodes_merged(self):
        """When chameleon_nodes key is present, Chameleon elements are merged."""
        data = single_node_slice()
        data["chameleon_nodes"] = [
            {"name": "chi-node1", "site": "CHI@TACC",
             "node_type": "compute_haswell", "status": "draft",
             "connection_type": "fabnet_v4"}
        ]
        result = build_graph(data)
        chi_nodes = [n for n in result["nodes"]
                     if n["data"].get("element_type") == "chameleon_instance"]
        assert len(chi_nodes) >= 1
        # Should also have a cluster container
        clusters = [n for n in result["nodes"]
                    if n["data"].get("element_type") == "chameleon_cluster"]
        assert len(clusters) == 1

    def test_chameleon_nodes_empty_list(self):
        """Empty chameleon_nodes list should not add any elements."""
        data = single_node_slice()
        data["chameleon_nodes"] = []
        result = build_graph(data)
        chi_nodes = [n for n in result["nodes"]
                     if n["data"].get("element_type") in ("chameleon_instance", "chameleon_cluster")]
        assert len(chi_nodes) == 0

    def test_missing_optional_keys(self):
        """Slice data with minimal keys should not crash."""
        data = {"name": "minimal", "id": "min-uuid", "state": "Draft"}
        result = build_graph(data)
        assert len(result["nodes"]) == 1  # just slice container
        assert len(result["edges"]) == 0

    def test_public_internet_ext_networks(self):
        """IPv4Ext networks should get the l3-ext class and internet node."""
        data = single_node_slice()
        data["nodes"][0]["components"] = [
            {"name": "nic1", "model": "NIC_Basic", "interfaces": [
                {"name": "node1-nic1-p1", "node_name": "node1"}
            ]}
        ]
        data["networks"] = [{
            "name": "public-net",
            "type": "IPv4Ext",
            "layer": "L3",
            "interfaces": [
                {"name": "node1-nic1-p1", "node_name": "node1"}
            ],
        }]
        result = build_graph(data)
        net_nodes = [n for n in result["nodes"] if "network" in n.get("classes", "")]
        assert len(net_nodes) == 1
        assert "network-l3-ext" in net_nodes[0]["classes"]
        # Should also create the internet node
        internet = [n for n in result["nodes"]
                    if n["data"].get("element_type") == "fabnet-internet"]
        assert len(internet) == 1


# ---------------------------------------------------------------------------
# build_chameleon_elements
# ---------------------------------------------------------------------------

class TestBuildChameleonElements:
    def test_empty_instances(self):
        """Empty instances list returns empty nodes and edges."""
        result = build_chameleon_elements([])
        assert result["nodes"] == []
        assert result["edges"] == []

    def test_single_instance(self):
        """Single instance should create cluster + instance nodes."""
        instances = [
            {"id": "inst-1", "name": "my-server", "site": "CHI@TACC",
             "status": "ACTIVE", "floating_ip": "129.114.1.1"}
        ]
        result = build_chameleon_elements(instances)
        assert len(result["nodes"]) == 2  # cluster + instance
        cluster = [n for n in result["nodes"]
                   if n["data"]["element_type"] == "chameleon_cluster"]
        assert len(cluster) == 1
        inst = [n for n in result["nodes"]
                if n["data"]["element_type"] == "chameleon_instance"]
        assert len(inst) == 1
        assert inst[0]["data"]["name"] == "my-server"
        assert inst[0]["data"]["ip"] == "129.114.1.1"

    def test_instance_state_colors(self):
        """Instance status should map to correct state colors."""
        for status in ["ACTIVE", "BUILD", "SHUTOFF", "ERROR"]:
            instances = [{"id": f"i-{status}", "name": "n", "site": "CHI@TACC", "status": status}]
            result = build_chameleon_elements(instances)
            inst = [n for n in result["nodes"]
                    if n["data"]["element_type"] == "chameleon_instance"][0]
            assert "bg_color" in inst["data"]
            assert "border_color" in inst["data"]

    def test_cross_testbed_connections(self):
        """Connections between Chameleon and FABRIC nodes create edges."""
        instances = [
            {"id": "inst-1", "name": "chi-node", "site": "CHI@TACC", "status": "ACTIVE"}
        ]
        connections = [
            {"chameleon_instance_id": "inst-1", "fabric_node": "node:uuid:fab-node", "type": "l2_stitch"}
        ]
        result = build_chameleon_elements(instances, connections)
        assert len(result["edges"]) == 1
        edge = result["edges"][0]
        assert edge["data"]["element_type"] == "cross_testbed"
        assert edge["data"]["connection_type"] == "l2_stitch"
        assert "L2 Stitch" in edge["data"]["label"]

    def test_fabnet_v4_connection_label(self):
        instances = [{"id": "i1", "name": "n", "site": "s", "status": "ACTIVE"}]
        connections = [{"chameleon_instance_id": "i1", "fabric_node": "fn", "type": "fabnet_v4"}]
        result = build_chameleon_elements(instances, connections)
        assert "FABnet v4" in result["edges"][0]["data"]["label"]

    def test_empty_connections(self):
        """No connections should produce no edges."""
        instances = [{"id": "i1", "name": "n", "site": "s", "status": "ACTIVE"}]
        result = build_chameleon_elements(instances, connections=None)
        assert result["edges"] == []

    def test_multiple_instances(self):
        """Multiple instances should all be children of the cluster node."""
        instances = [
            {"id": f"i{i}", "name": f"n{i}", "site": "CHI@TACC", "status": "ACTIVE"}
            for i in range(3)
        ]
        result = build_chameleon_elements(instances)
        inst_nodes = [n for n in result["nodes"]
                      if n["data"]["element_type"] == "chameleon_instance"]
        assert len(inst_nodes) == 3
        for inst in inst_nodes:
            assert inst["data"]["parent"] == "chameleon:cluster"


# ---------------------------------------------------------------------------
# build_chameleon_draft_graph
# ---------------------------------------------------------------------------

class TestBuildChameleonDraftGraph:
    def test_empty_draft(self):
        """Draft with no nodes or networks."""
        draft = {"id": "d1", "name": "empty-draft", "site": "CHI@TACC",
                 "nodes": [], "networks": [], "floating_ips": []}
        result = build_chameleon_draft_graph(draft)
        assert len(result["nodes"]) == 1  # just the container
        assert result["nodes"][0]["data"]["element_type"] == "chameleon_draft"
        assert len(result["edges"]) == 0

    def test_draft_with_nodes(self):
        """Draft with nodes creates instance elements."""
        draft = {
            "id": "d2", "name": "my-draft", "site": "CHI@TACC",
            "nodes": [
                {"id": "n1", "name": "server-1", "node_type": "compute_haswell",
                 "image": "CC-Ubuntu22.04", "count": 1},
            ],
            "networks": [],
            "floating_ips": [],
        }
        result = build_chameleon_draft_graph(draft)
        inst_nodes = [n for n in result["nodes"]
                      if n["data"]["element_type"] == "chameleon_instance"]
        assert len(inst_nodes) == 1
        assert inst_nodes[0]["data"]["status"] == "DRAFT"
        assert inst_nodes[0]["data"]["bg_color"] == CHAMELEON_DRAFT_STATE["bg"]

    def test_draft_with_networks(self):
        """Draft with per-node interface network assignments produces NIC + edges."""
        draft = {
            "id": "d3", "name": "net-draft", "site": "CHI@TACC",
            "nodes": [
                {"id": "n1", "name": "s1", "node_type": "compute_haswell",
                 "image": "CC-Ubuntu22.04", "count": 1,
                 "interfaces": [{"nic": 0, "network": {"id": "net1", "name": "my-net"}}]},
                {"id": "n2", "name": "s2", "node_type": "compute_haswell",
                 "image": "CC-Ubuntu22.04", "count": 1,
                 "interfaces": [{"nic": 0, "network": {"id": "net1", "name": "my-net"}}]},
            ],
            "networks": [],
            "floating_ips": [],
        }
        result = build_chameleon_draft_graph(draft)
        net_nodes = [n for n in result["nodes"]
                     if n["data"]["element_type"] == "network"]
        assert len(net_nodes) == 1
        assert "network" in net_nodes[0]["data"]["label"].lower()
        # Should have 2 NIC→network edges (one per node interface)
        nic_edges = [e for e in result["edges"]
                     if e["data"]["element_type"] == "interface"]
        assert len(nic_edges) == 2

    def test_draft_with_floating_ips(self):
        """Floating IPs are tracked in node data for post-deploy assignment."""
        draft = {
            "id": "d4", "name": "fip-draft", "site": "CHI@TACC",
            "nodes": [
                {"id": "n1", "name": "fip-server", "node_type": "compute_haswell",
                 "image": "CC-Ubuntu22.04", "count": 1},
            ],
            "networks": [],
            "floating_ips": ["n1"],
        }
        result = build_chameleon_draft_graph(draft)
        # Floating IPs are now shown in node label/data rather than as separate badges
        inst_nodes = [n for n in result["nodes"]
                      if n["data"]["element_type"] == "chameleon_instance"]
        assert len(inst_nodes) == 1
        assert inst_nodes[0]["data"]["name"] == "fip-server"

    def test_draft_container_has_green_color(self):
        """Draft container should use the green Chameleon brand color."""
        draft = {"id": "d5", "name": "green", "site": "CHI@TACC",
                 "nodes": [], "networks": [], "floating_ips": []}
        result = build_chameleon_draft_graph(draft)
        container = result["nodes"][0]
        assert container["data"]["bg_color"] == CHAMELEON_DRAFT_CONTAINER_COLOR

    def test_draft_node_count_in_label(self):
        """When node count > 1, it should appear in the label."""
        draft = {
            "id": "d6", "name": "multi", "site": "CHI@TACC",
            "nodes": [
                {"id": "n1", "name": "worker", "node_type": "compute_haswell",
                 "image": "CC-Ubuntu22.04", "count": 5},
            ],
            "networks": [],
            "floating_ips": [],
        }
        result = build_chameleon_draft_graph(draft)
        inst = [n for n in result["nodes"]
                if n["data"]["element_type"] == "chameleon_instance"][0]
        assert "x5" in inst["data"]["label"]


# ---------------------------------------------------------------------------
# build_chameleon_slice_node_elements
# ---------------------------------------------------------------------------

class TestBuildChameleonSliceNodeElements:
    def test_empty_nodes(self):
        result = build_chameleon_slice_node_elements([])
        assert result["nodes"] == []
        assert result["edges"] == []

    def test_draft_status_uses_gray_colors(self):
        chi_nodes = [
            {"name": "chi-1", "site": "CHI@TACC", "node_type": "compute_haswell",
             "status": "draft", "connection_type": "fabnet_v4"}
        ]
        result = build_chameleon_slice_node_elements(chi_nodes, "slice-123")
        inst = [n for n in result["nodes"]
                if n["data"]["element_type"] == "chameleon_instance"][0]
        assert inst["data"]["bg_color"] == "#f5f5f5"
        assert inst["data"]["border_color"] == "#999"
        assert "chameleon-draft-node" in inst["classes"]

    def test_deployed_status_uses_green_colors(self):
        chi_nodes = [
            {"name": "chi-2", "site": "CHI@UC", "node_type": "compute_skylake",
             "status": "ACTIVE", "connection_type": "l2_stitch"}
        ]
        result = build_chameleon_slice_node_elements(chi_nodes, "slice-456")
        inst = [n for n in result["nodes"]
                if n["data"]["element_type"] == "chameleon_instance"][0]
        assert inst["data"]["bg_color"] == "#e8f5e9"
        assert inst["data"]["border_color"] == "#39B54A"
        assert "chameleon-draft-node" not in inst["classes"]

    def test_cluster_container_always_created(self):
        chi_nodes = [
            {"name": "c1", "site": "CHI@TACC", "node_type": "t",
             "status": "draft", "connection_type": "fabnet_v4"}
        ]
        result = build_chameleon_slice_node_elements(chi_nodes)
        clusters = [n for n in result["nodes"]
                    if n["data"]["element_type"] == "chameleon_cluster"]
        assert len(clusters) == 1
        assert clusters[0]["data"]["label"] == "Chameleon Cloud"

    def test_multiple_nodes_all_parented(self):
        chi_nodes = [
            {"name": f"n{i}", "site": "CHI@TACC", "node_type": "compute",
             "status": "draft", "connection_type": "fabnet_v4"}
            for i in range(3)
        ]
        result = build_chameleon_slice_node_elements(chi_nodes, "s-id")
        instances = [n for n in result["nodes"]
                     if n["data"]["element_type"] == "chameleon_instance"]
        assert len(instances) == 3
        for inst in instances:
            assert inst["data"]["parent"] == "chameleon:slice-cluster"
