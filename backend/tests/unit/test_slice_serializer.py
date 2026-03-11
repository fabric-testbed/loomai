"""Tests for app.slice_serializer — uses mock FABlib objects."""

import pytest

from app.slice_serializer import (
    _safe,
    serialize_interface,
    serialize_component,
    serialize_node,
    serialize_network,
    serialize_facility_port,
    slice_to_dict,
    slice_summary,
    check_has_errors,
    _node_capacity,
)
from tests.fixtures.fablib_mocks import (
    MockInterface,
    MockComponent,
    MockNode,
    MockNetworkService,
    MockSlice,
)


# ---------------------------------------------------------------------------
# _safe
# ---------------------------------------------------------------------------

class TestSafe:
    def test_successful_call(self):
        assert _safe(lambda: "hello") == "hello"

    def test_exception_returns_default(self):
        assert _safe(lambda: 1/0, "fallback") == "fallback"

    def test_none_returns_default(self):
        assert _safe(lambda: None) == ""

    def test_custom_default(self):
        assert _safe(lambda: None, []) == []


# ---------------------------------------------------------------------------
# serialize_interface
# ---------------------------------------------------------------------------

class TestSerializeInterface:
    def test_basic_interface(self):
        node = MockNode(name="n1")
        iface = MockInterface(name="n1-nic1-p1", node=node, vlan="100")
        result = serialize_interface(iface)
        assert result["name"] == "n1-nic1-p1"
        assert result["node_name"] == "n1"
        assert result["vlan"] == "100"

    def test_interface_with_network(self):
        net = MockNetworkService(name="lan")
        iface = MockInterface(name="iface1", network=net)
        result = serialize_interface(iface)
        assert result["network_name"] == "lan"

    def test_interface_without_network(self):
        iface = MockInterface(name="iface1")
        result = serialize_interface(iface)
        assert result["network_name"] == ""


# ---------------------------------------------------------------------------
# serialize_component
# ---------------------------------------------------------------------------

class TestSerializeComponent:
    def test_basic_component(self):
        comp = MockComponent(name="nic1", model="NIC_Basic", comp_type="SmartNIC")
        result = serialize_component(comp)
        assert result["name"] == "nic1"
        assert result["model"] == "NIC_Basic"
        assert result["type"] == "SmartNIC"
        assert result["interfaces"] == []

    def test_component_with_interfaces(self):
        iface = MockInterface(name="nic1-p1")
        comp = MockComponent(name="nic1", model="NIC_Basic", interfaces=[iface])
        result = serialize_component(comp)
        assert len(result["interfaces"]) == 1
        assert result["interfaces"][0]["name"] == "nic1-p1"


# ---------------------------------------------------------------------------
# serialize_node
# ---------------------------------------------------------------------------

class TestSerializeNode:
    def test_basic_node(self):
        node = MockNode(name="node1", site="RENC", cores=4, ram=16, disk=50)
        result = serialize_node(node)
        assert result["name"] == "node1"
        assert result["site"] == "RENC"
        assert result["cores"] == 4
        assert result["ram"] == 16
        assert result["disk"] == 50

    def test_node_with_components(self):
        comp = MockComponent(name="nic1", model="NIC_Basic")
        node = MockNode(name="node1", components=[comp])
        result = serialize_node(node)
        assert len(result["components"]) == 1
        assert result["components"][0]["model"] == "NIC_Basic"

    def test_node_management_ip(self):
        node = MockNode(name="node1", management_ip="10.0.0.1")
        result = serialize_node(node)
        assert result["management_ip"] == "10.0.0.1"

    def test_node_reservation_state(self):
        node = MockNode(name="node1", reservation_state="Active")
        result = serialize_node(node)
        assert result["reservation_state"] == "Active"

    def test_node_with_user_data(self):
        node = MockNode(name="node1")
        node._user_data = {"boot_config": {"commands": ["apt update"]}}
        result = serialize_node(node)
        assert result["user_data"]["boot_config"]["commands"] == ["apt update"]

    def test_node_with_error_message(self):
        node = MockNode(name="node1")
        node._error_message = "Resource unavailable"
        result = serialize_node(node)
        assert result["error_message"] == "Resource unavailable"


# ---------------------------------------------------------------------------
# _node_capacity
# ---------------------------------------------------------------------------

class TestNodeCapacity:
    def test_reads_from_getter(self):
        node = MockNode(cores=8)
        assert _node_capacity(node, "cores") == 8

    def test_fallback_to_fim(self):
        node = MockNode(cores=0, ram=0, disk=0)  # 0 triggers FIM fallback
        # Override get_fim_node to return an object with numeric capacities
        from unittest.mock import MagicMock
        mock_fim = MagicMock()
        mock_caps = MagicMock()
        mock_caps.core = 4
        mock_caps.ram = 16
        mock_caps.disk = 50
        mock_fim.capacities = mock_caps
        node.get_fim_node = lambda: mock_fim
        assert _node_capacity(node, "cores") == 4
        assert _node_capacity(node, "ram") == 16
        assert _node_capacity(node, "disk") == 50


# ---------------------------------------------------------------------------
# serialize_network
# ---------------------------------------------------------------------------

class TestSerializeNetwork:
    def test_l2_network(self):
        net = MockNetworkService(name="lan", net_type="L2Bridge")
        result = serialize_network(net)
        assert result["name"] == "lan"
        assert result["type"] == "L2Bridge"
        assert result["layer"] == "L2"

    def test_l3_fabnet_network(self):
        net = MockNetworkService(name="fabnet", net_type="FABNetv4")
        result = serialize_network(net)
        assert result["layer"] == "L3"

    def test_network_with_subnet(self):
        net = MockNetworkService(name="lan", subnet="192.168.1.0/24",
                                  gateway="192.168.1.1")
        result = serialize_network(net)
        assert result["subnet"] == "192.168.1.0/24"
        assert result["gateway"] == "192.168.1.1"


# ---------------------------------------------------------------------------
# slice_to_dict
# ---------------------------------------------------------------------------

class TestSliceToDict:
    def test_empty_slice(self):
        s = MockSlice(name="test", slice_id="uuid-1")
        result = slice_to_dict(s)
        assert result["name"] == "test"
        assert result["id"] == "uuid-1"
        assert result["state"] == "Draft"
        assert result["nodes"] == []
        assert result["networks"] == []
        assert result["facility_ports"] == []

    def test_slice_with_nodes(self):
        node = MockNode(name="node1", site="RENC")
        s = MockSlice(name="test", nodes=[node])
        result = slice_to_dict(s)
        assert len(result["nodes"]) == 1
        assert result["nodes"][0]["name"] == "node1"

    def test_slice_with_networks(self):
        net = MockNetworkService(name="lan", net_type="L2Bridge")
        s = MockSlice(name="test", networks=[net])
        result = slice_to_dict(s)
        assert len(result["networks"]) == 1
        assert result["networks"][0]["name"] == "lan"

    def test_slice_error_messages(self):
        s = MockSlice(name="test")
        s._error_messages = [{"notice": "Something failed", "sliver": None}]
        result = slice_to_dict(s)
        assert len(result["error_messages"]) == 1
        assert result["error_messages"][0]["message"] == "Something failed"


# ---------------------------------------------------------------------------
# slice_summary
# ---------------------------------------------------------------------------

class TestSliceSummary:
    def test_summary(self):
        s = MockSlice(name="test", slice_id="uuid-1", state="StableOK")
        result = slice_summary(s)
        assert result["name"] == "test"
        assert result["id"] == "uuid-1"
        assert result["state"] == "StableOK"


# ---------------------------------------------------------------------------
# check_has_errors
# ---------------------------------------------------------------------------

class TestCheckHasErrors:
    def test_no_errors(self):
        s = MockSlice(name="test")
        assert check_has_errors(s) is False

    def test_with_errors(self):
        s = MockSlice(name="test")
        s._error_messages = [{"notice": "Error occurred"}]
        assert check_has_errors(s) is True

    def test_empty_notice_ignored(self):
        s = MockSlice(name="test")
        s._error_messages = [{"notice": ""}]
        assert check_has_errors(s) is False
