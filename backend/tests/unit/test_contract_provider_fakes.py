"""Unit coverage for deterministic provider fakes used by contract tests."""

from __future__ import annotations

from app.contract_fabric import FakeFablibManager, contract_slice_id
from app.slice_serializer import slice_to_dict
import app.chameleon_manager as chameleon_manager


def test_contract_fabric_submit_assigns_id_and_registers_slice():
    manager = FakeFablibManager()
    slice_obj = manager.new_slice("My Contract Slice")
    node = slice_obj.add_node(name="fabric-node-1", site="RENC")
    component = node.add_component(model="NIC_Basic", name="nic1")
    iface = component.get_interfaces()[0]
    slice_obj.add_l2network(name="fabric-net-1", interfaces=[iface], type="L2Bridge")

    slice_obj.submit(wait=False)

    assert slice_obj.get_slice_id() == "contract-my-contract-slice"
    assert contract_slice_id("already-contract") == "contract-already-contract"
    assert manager.get_slice(slice_id="contract-my-contract-slice") is slice_obj
    assert manager.get_slice(name="My Contract Slice") is slice_obj
    assert manager.get_slices() == [slice_obj]

    serialized = slice_to_dict(slice_obj)
    assert serialized["state"] == "StableOK"
    assert serialized["nodes"][0]["management_ip"] == "192.0.2.10"
    assert serialized["nodes"][0]["components"][0]["interfaces"][0]["name"] == "fabric-node-1-nic1-p1"
    assert serialized["networks"][0]["interfaces"][0]["name"] == "fabric-node-1-nic1-p1"


def test_contract_fabric_component_delete_detaches_network_interface():
    manager = FakeFablibManager()
    slice_obj = manager.new_slice("contract-delete-component")
    node = slice_obj.add_node(name="fabric-node-1", site="RENC")
    component = node.add_component(model="NIC_Basic", name="delete-me")
    iface = component.get_interfaces()[0]
    network = slice_obj.add_l2network(name="fabric-net-1", interfaces=[iface], type="L2Bridge")

    component.delete()

    assert component not in node.get_components()
    assert iface not in node.get_interfaces()
    assert network.get_interfaces() == []


def test_contract_chameleon_session_tracks_mutating_fake_resources(monkeypatch):
    monkeypatch.setenv("LOOMAI_CONTRACT_MODE", "1")
    chameleon_manager.reset_sessions()
    session = chameleon_manager.get_session("CHI@TACC")

    network = session.api_post("network", "/v2.0/networks", {
        "network": {"name": "tenant-net"},
    })["network"]
    subnet = session.api_post("network", "/v2.0/subnets", {
        "subnet": {
            "network_id": network["id"],
            "name": "tenant-subnet",
            "cidr": "192.168.50.0/24",
        },
    })["subnet"]
    assert subnet["id"] in next(
        net for net in session.api_get("network", "/v2.0/networks?name=tenant-net")["networks"]
        if net["id"] == network["id"]
    )["subnets"]

    security_group = session.api_post("network", "/v2.0/security-groups", {
        "security_group": {"name": "loomai-ssh"},
    })["security_group"]
    rule = session.api_post("network", "/v2.0/security-group-rules", {
        "security_group_rule": {
            "security_group_id": security_group["id"],
            "direction": "ingress",
            "protocol": "tcp",
            "port_range_min": 22,
            "port_range_max": 22,
        },
    })["security_group_rule"]
    stored_sg = next(
        sg for sg in session.api_get("network", "/v2.0/security-groups")["security_groups"]
        if sg["id"] == security_group["id"]
    )
    assert stored_sg["security_group_rules"] == [rule]

    floating_ip = session.api_post("network", "/v2.0/floatingips", {
        "floatingip": {"floating_network_id": "public-id"},
    })["floatingip"]
    updated_ip = session.api_put("network", f"/v2.0/floatingips/{floating_ip['id']}", {
        "floatingip": {"port_id": "port-1"},
    })["floatingip"]
    assert updated_ip["status"] == "ACTIVE"
    assert updated_ip["port_id"] == "port-1"

    session.api_delete("network", f"/v2.0/floatingips/{floating_ip['id']}")
    assert session.api_get("network", "/v2.0/floatingips")["floatingips"] == []
    chameleon_manager.reset_sessions()
