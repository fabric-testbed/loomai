"""Tests for post-StableOK runtime network configuration helpers."""

from __future__ import annotations

import pytest

from tests.fixtures.fablib_mocks import MockInterface, MockNetworkService, MockNode, MockSlice


class ExecNode(MockNode):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.commands: list[str] = []

    def execute(self, command: str, timeout: int | None = None, quiet: bool = True):
        self.commands.append(command)
        if "ping" in command:
            return (
                "PING target (192.168.100.2) 56(84) bytes of data.\n"
                "3 packets transmitted, 3 received, 0% packet loss\n"
                "__loomai_ping_rc=0\n",
                "",
            )
        return "", ""


def _iface(name: str, dev: str, ip: str = "") -> MockInterface:
    iface = MockInterface(name=name)
    iface.get_os_interface = lambda: dev
    if ip:
        iface._fablib_data["addr"] = ip
    return iface


def test_configure_runtime_networking_assigns_l2_ips_and_pings(monkeypatch):
    from app.routes import slices

    iface1 = _iface("vm1-nic1-p1", "ens7")
    iface2 = _iface("vm2-nic1-p1", "ens7")
    node1 = ExecNode(name="vm1", interfaces=[iface1])
    node2 = ExecNode(name="vm2", interfaces=[iface2])
    net = MockNetworkService(name="lan", net_type="L2Bridge", interfaces=[iface1, iface2])
    slice_obj = MockSlice(name="bench-l2", state="StableOK", nodes=[node1, node2], networks=[net])

    monkeypatch.setattr(slices, "_get_slice_obj", lambda _name: slice_obj)

    result = slices._configure_runtime_networking(
        "bench-l2",
        run_post_boot=False,
        configure_fabnet=False,
        verify=True,
    )

    assert result["status"] == "ok"
    assert [row["ip"] for row in result["l2_assignments"]] == ["192.168.100.1", "192.168.100.2"]
    assert "sudo ip addr replace 192.168.100.1/24 dev ens7" in node1.commands[0]
    assert result["pings"][0]["target_ip"] == "192.168.100.2"
    assert result["pings"][0]["ok"] is True
    assert "ping -c 3 -W 2 192.168.100.2" in result["pings"][0]["command"]


def test_configure_runtime_networking_adds_fabnet_route_and_pings(monkeypatch):
    from app.routes import slices

    iface1 = _iface("vm1-fabnet-p1", "ens8", "10.129.1.2")
    iface2 = _iface("vm2-fabnet-p1", "ens8", "10.130.1.2")
    node1 = ExecNode(name="vm1", interfaces=[iface1])
    node2 = ExecNode(name="vm2", interfaces=[iface2])
    net1 = MockNetworkService(
        name="fabnetv4-vm1",
        net_type="IPv4",
        interfaces=[iface1],
        subnet="10.129.1.0/24",
        gateway="10.129.1.1",
    )
    net2 = MockNetworkService(
        name="fabnetv4-vm2",
        net_type="IPv4",
        interfaces=[iface2],
        subnet="10.130.1.0/24",
        gateway="10.130.1.1",
    )
    slice_obj = MockSlice(name="bench-fabnet", state="StableOK", nodes=[node1, node2], networks=[net1, net2])

    class Fablib:
        FABNETV4_SUBNET = "10.128.0.0/10"

    monkeypatch.setattr(slices, "_get_slice_obj", lambda _name: slice_obj)
    monkeypatch.setattr(slices, "get_fablib", lambda: Fablib())

    result = slices._configure_runtime_networking(
        "bench-fabnet",
        run_post_boot=False,
        configure_l2=False,
        verify=True,
    )

    assert result["status"] == "ok"
    assert len(result["fabnet_assignments"]) == 2
    assert any("sudo ip route replace 10.128.0.0/10 via 10.129.1.1 dev ens8" in cmd for cmd in node1.commands)
    assert result["pings"][0]["network"] == "FABNetv4"
    assert result["pings"][0]["target_ip"] == "10.130.1.2"
    assert result["pings"][0]["ok"] is True


def test_configure_runtime_networking_refuses_non_stable_slice(monkeypatch):
    from app.routes import slices

    node = ExecNode(name="vm1")
    slice_obj = MockSlice(name="draft", state="Configuring", nodes=[node])
    monkeypatch.setattr(slices, "_get_slice_obj", lambda _name: slice_obj)

    result = slices._configure_runtime_networking("draft", run_post_boot=False)

    assert result["status"] == "not_ready"
    assert node.commands == []


def test_ai_chat_exposes_configure_networking_tool():
    from app.routes.ai_chat import TOOL_SCHEMAS

    names = {schema["function"]["name"] for schema in TOOL_SCHEMAS}
    assert "configure_networking" in names


@pytest.mark.asyncio
async def test_ai_chat_execute_tool_calls_configure_networking(monkeypatch):
    from app.routes import ai_chat, slices

    captured = {}

    async def fake_configure(slice_name, req):
        captured["slice_name"] = slice_name
        captured["request"] = req
        return {"status": "ok", "pings": [{"ok": True}]}

    monkeypatch.setattr(slices, "configure_networking", fake_configure)

    raw = await ai_chat.execute_tool(
        "configure_networking",
        {"slice_name": "bench", "verify": True, "l2_subnet_base": "192.168.200.0/24"},
    )

    assert captured["slice_name"] == "bench"
    assert captured["request"].verify is True
    assert captured["request"].l2_subnet_base == "192.168.200.0/24"
    assert '"status": "ok"' in raw
