"""Tests for app.graph_builder.build_graph() — pure function, no mocks needed."""

import pytest

from app.graph_builder import (
    build_graph,
    _strip_node_prefix,
    _component_summary,
    STATE_COLORS,
    STATE_COLORS_DARK,
    COMPONENT_ABBREV,
    COMPONENT_CATEGORY,
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
