"""Deterministic FABRIC provider used by backend contract tests.

This module intentionally lives in app code, not test fixtures, because the
contract-mode backend is started as a real API server by Playwright.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return slug or "slice"


def contract_slice_id(name: str) -> str:
    """Return a deterministic fake FABRIC slice id for *name*."""
    if name.startswith("contract-"):
        return name
    return f"contract-{_slug(name)}"


class _FakeFimInterface:
    def get_property(self, pname: str = ""):
        return None


class _FakeFimNode:
    def __init__(self, cores: int, ram: int, disk: int):
        self.capacities = type(
            "Capacities",
            (),
            {"core": cores, "ram": ram, "disk": disk},
        )()


class FakeInterface:
    def __init__(
        self,
        name: str,
        *,
        node: "FakeNode | None" = None,
        network: "FakeNetworkService | None" = None,
        vlan: str = "",
        bandwidth: str | int = "",
    ):
        self._name = name
        self._node = node
        self._network = network
        self._vlan = str(vlan or "")
        self._bandwidth = str(bandwidth or "")
        self._mode = ""
        self._ip_addr = ""

    def get_name(self) -> str:
        return self._name

    def get_node(self):
        return self._node

    def get_network(self):
        return self._network

    def get_vlan(self) -> str:
        return self._vlan

    def get_bandwidth(self) -> str:
        return self._bandwidth

    def get_fablib_data(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self._mode:
            data["mode"] = self._mode
        if self._ip_addr:
            data["addr"] = self._ip_addr
        return data

    def get_fim(self):
        return _FakeFimInterface()

    def set_mode(self, mode: str) -> None:
        self._mode = mode

    def set_ip_addr(self, addr: str) -> None:
        self._ip_addr = addr
        if addr and not self._mode:
            self._mode = "config"

    def set_vlan(self, vlan: str) -> None:
        self._vlan = str(vlan or "")


class FakeComponent:
    def __init__(self, name: str, model: str, *, node: "FakeNode"):
        self._name = name
        self._model = model
        self._type = "SmartNIC" if model.startswith("NIC_") else model.split("_", 1)[0]
        self._node = node
        self._interfaces = [
            FakeInterface(name=f"{node.get_name()}-{name}-p1", node=node)
        ]

    def get_name(self) -> str:
        return self._name

    def get_model(self) -> str:
        return self._model

    def get_type(self) -> str:
        return self._type

    def get_interfaces(self) -> list[FakeInterface]:
        return self._interfaces

    def delete(self) -> None:
        self._node._components = [c for c in self._node._components if c is not self]
        remove_names = {iface.get_name() for iface in self._interfaces}
        self._node._interfaces = [
            iface for iface in self._node._interfaces
            if iface.get_name() not in remove_names
        ]
        for net in self._node._slice._networks:
            net._interfaces = [
                iface for iface in net._interfaces
                if iface.get_name() not in remove_names
            ]


class FakeNode:
    def __init__(
        self,
        name: str,
        *,
        slice_obj: "FakeSlice",
        site: str = "RENC",
        host: str = "",
        cores: int = 2,
        ram: int = 8,
        disk: int = 10,
        image: str = "default_ubuntu_22",
    ):
        self._slice = slice_obj
        self._name = name
        self._site = site
        self._host = host or ""
        self._cores = cores
        self._ram = ram
        self._disk = disk
        self._image = image
        self._image_type = "qcow2"
        self._username = "ubuntu"
        self._management_ip = ""
        self._reservation_state = "Nascent"
        self._user_data: dict[str, Any] = {}
        self._error_message = ""
        self._components: list[FakeComponent] = []
        self._interfaces: list[FakeInterface] = []

    def get_name(self) -> str:
        return self._name

    def get_site(self) -> str:
        return self._site

    def get_host(self) -> str:
        return self._host

    def get_cores(self) -> int:
        return self._cores

    def get_ram(self) -> int:
        return self._ram

    def get_disk(self) -> int:
        return self._disk

    def get_image(self) -> str:
        return self._image

    def get_image_type(self) -> str:
        return self._image_type

    def get_management_ip(self) -> str:
        return self._management_ip

    def get_reservation_state(self) -> str:
        return self._reservation_state

    def get_username(self) -> str:
        return self._username

    def get_components(self) -> list[FakeComponent]:
        return self._components

    def get_interfaces(self) -> list[FakeInterface]:
        return self._interfaces

    def get_user_data(self) -> dict[str, Any]:
        return self._user_data

    def get_error_message(self) -> str:
        return self._error_message

    def get_fim_node(self):
        return _FakeFimNode(self._cores, self._ram, self._disk)

    def add_component(self, model: str, name: str) -> FakeComponent:
        component = FakeComponent(name=name, model=model, node=self)
        self._components.append(component)
        self._interfaces.extend(component.get_interfaces())
        return component

    def get_component(self, name: str) -> FakeComponent:
        for component in self._components:
            if component.get_name() == name:
                return component
        raise RuntimeError(f"Component not found: {name}")

    def add_fabnet(self, net_type: str = "IPv4") -> None:
        component = self.add_component(model="NIC_Basic", name=f"fabnet-{net_type.lower()}")
        iface = component.get_interfaces()[0]
        iface.set_mode("auto")
        net_name = f"fabnet{net_type[-1] if net_type[-1].isdigit() else '4'}-{self._site.lower()}"
        existing = None
        for net in self._slice._networks:
            if net.get_name() == net_name:
                existing = net
                break
        if existing is None:
            existing = self._slice.add_l3network(name=net_name, interfaces=[], type=net_type)
        existing.add_interface(iface)

    def set_site(self, site: str) -> None:
        self._site = site

    def set_host(self, host: str | None) -> None:
        self._host = host or ""

    def set_capacities(
        self,
        cores: int | None = None,
        ram: int | None = None,
        disk: int | None = None,
    ) -> None:
        if cores is not None:
            self._cores = cores
        if ram is not None:
            self._ram = ram
        if disk is not None:
            self._disk = disk

    def set_image(
        self,
        image: str,
        username: str | None = None,
        image_type: str | None = None,
    ) -> None:
        self._image = image
        if username:
            self._username = username
        if image_type:
            self._image_type = image_type

    def set_username(self, username: str) -> None:
        self._username = username

    def set_instance_type(self, instance_type: str) -> None:
        self._user_data["instance_type"] = instance_type

    def set_user_data(self, data: dict[str, Any]) -> None:
        self._user_data = data

    def delete(self) -> None:
        self._slice._nodes = [node for node in self._slice._nodes if node is not self]
        iface_names = {iface.get_name() for iface in self._interfaces}
        for net in self._slice._networks:
            net._interfaces = [
                iface for iface in net._interfaces
                if iface.get_name() not in iface_names
            ]


class FakeNetworkService:
    def __init__(
        self,
        name: str,
        *,
        net_type: str = "L2Bridge",
        interfaces: list[FakeInterface] | None = None,
        slice_obj: "FakeSlice",
    ):
        self._name = name
        self._type = net_type
        self._interfaces: list[FakeInterface] = []
        self._subnet = ""
        self._gateway = ""
        self._slice = slice_obj
        for iface in interfaces or []:
            self.add_interface(iface)

    def get_name(self) -> str:
        return self._name

    def get_type(self) -> str:
        return self._type

    def get_interfaces(self) -> list[FakeInterface]:
        return self._interfaces

    def add_interface(self, interface: FakeInterface) -> None:
        if interface not in self._interfaces:
            self._interfaces.append(interface)
        interface._network = self

    def remove_interface(self, interface: FakeInterface) -> None:
        self._interfaces = [iface for iface in self._interfaces if iface is not interface]
        if interface._network is self:
            interface._network = None

    def get_subnet(self) -> str:
        return self._subnet

    def get_gateway(self) -> str:
        return self._gateway

    def set_subnet(self, subnet: str) -> None:
        self._subnet = subnet

    def set_gateway(self, gateway: str) -> None:
        self._gateway = gateway

    def delete(self) -> None:
        for iface in self._interfaces:
            if iface._network is self:
                iface._network = None
        self._slice._networks = [net for net in self._slice._networks if net is not self]


class FakeFacilityPort:
    def __init__(
        self,
        name: str,
        *,
        site: str,
        vlan: str = "",
        bandwidth: int = 10,
        slice_obj: "FakeSlice",
    ):
        self._name = name
        self._site = site
        self._vlan = str(vlan or "")
        self._bandwidth = bandwidth
        self._slice = slice_obj
        self._interfaces = [
            FakeInterface(
                name=f"{name}-p1",
                vlan=self._vlan,
                bandwidth=bandwidth,
            )
        ]

    def get_name(self) -> str:
        return self._name

    def get_site(self) -> str:
        return self._site

    def get_vlan(self) -> str:
        return self._vlan

    def get_bandwidth(self) -> str:
        return str(self._bandwidth)

    def get_interfaces(self) -> list[FakeInterface]:
        return self._interfaces

    def delete(self) -> None:
        iface_names = {iface.get_name() for iface in self._interfaces}
        for net in self._slice._networks:
            net._interfaces = [
                iface for iface in net._interfaces
                if iface.get_name() not in iface_names
            ]
        self._slice._facility_ports = [
            fp for fp in self._slice._facility_ports
            if fp is not self
        ]


class FakePortMirror:
    def __init__(
        self,
        name: str,
        *,
        mirror_interface_name: str,
        receive_interface_name: str,
        mirror_direction: str,
        slice_obj: "FakeSlice",
    ):
        self._name = name
        self._mirror_interface_name = mirror_interface_name
        self._receive_interface_name = receive_interface_name
        self._mirror_direction = mirror_direction
        self._slice = slice_obj

    def get_name(self) -> str:
        return self._name

    def get_type(self) -> str:
        return "PortMirror"

    def get_mirror_interface_name(self) -> str:
        return self._mirror_interface_name

    def get_receive_interface(self) -> FakeInterface | None:
        for node in self._slice._nodes:
            for iface in node.get_interfaces():
                if iface.get_name() == self._receive_interface_name:
                    return iface
        return None

    def get_mirror_direction(self) -> str:
        return self._mirror_direction

    def delete(self) -> None:
        self._slice._port_mirrors = [
            pm for pm in self._slice._port_mirrors
            if pm is not self
        ]


class FakeSlice:
    def __init__(
        self,
        name: str,
        *,
        manager: "FakeFablibManager",
        slice_id: str = "",
        state: str = "Draft",
    ):
        self._manager = manager
        self._name = name
        self._slice_id = slice_id
        self._state = state
        self._nodes: list[FakeNode] = []
        self._networks: list[FakeNetworkService] = []
        self._facility_ports: list[FakeFacilityPort] = []
        self._port_mirrors: list[FakePortMirror] = []
        self._error_messages: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)
        self._lease_start = now.isoformat()
        self._lease_end = (now + timedelta(hours=4)).isoformat()

    def get_name(self) -> str:
        return self._name

    def get_slice_id(self) -> str:
        return self._slice_id

    def get_state(self) -> str:
        return self._state

    def get_nodes(self) -> list[FakeNode]:
        return self._nodes

    def get_network_services(self) -> list[FakeNetworkService]:
        return self._networks

    def get_facility_ports(self) -> list[FakeFacilityPort]:
        return self._facility_ports

    def get_port_mirror_services(self) -> list[FakePortMirror]:
        return self._port_mirrors

    def get_error_messages(self) -> list[dict[str, Any]]:
        return self._error_messages

    def get_lease_start(self) -> str:
        return self._lease_start

    def get_lease_end(self) -> str:
        return self._lease_end

    def get_project_id(self) -> str:
        return self._manager.project_id

    def add_node(
        self,
        *,
        name: str,
        site: str = "RENC",
        host: str | None = None,
        cores: int = 2,
        ram: int = 8,
        disk: int = 10,
        image: str = "default_ubuntu_22",
        image_type: str | None = None,
    ) -> FakeNode:
        node = FakeNode(
            name=name,
            slice_obj=self,
            site=site or "RENC",
            host=host or "",
            cores=cores,
            ram=ram,
            disk=disk,
            image=image,
        )
        if image_type:
            node.set_image(image, image_type=image_type)
        self._nodes.append(node)
        return node

    def get_node(self, name: str) -> FakeNode:
        for node in self._nodes:
            if node.get_name() == name:
                return node
        raise RuntimeError(f"Node not found: {name}")

    def add_l2network(
        self,
        *,
        name: str,
        interfaces: list[FakeInterface] | None = None,
        type: str = "L2Bridge",
    ) -> FakeNetworkService:
        net = FakeNetworkService(
            name=name,
            net_type=type,
            interfaces=interfaces or [],
            slice_obj=self,
        )
        self._networks.append(net)
        return net

    def add_l3network(
        self,
        *,
        name: str,
        interfaces: list[FakeInterface] | None = None,
        type: str = "IPv4",
    ) -> FakeNetworkService:
        net = FakeNetworkService(
            name=name,
            net_type=type,
            interfaces=interfaces or [],
            slice_obj=self,
        )
        self._networks.append(net)
        return net

    def get_network(self, name: str) -> FakeNetworkService:
        for net in self._networks:
            if net.get_name() == name:
                return net
        raise RuntimeError(f"Network not found: {name}")

    def add_facility_port(
        self,
        *,
        name: str,
        site: str,
        vlan: str = "",
        bandwidth: int = 10,
    ) -> FakeFacilityPort:
        fp = FakeFacilityPort(
            name=name,
            site=site,
            vlan=vlan,
            bandwidth=bandwidth,
            slice_obj=self,
        )
        self._facility_ports.append(fp)
        return fp

    def add_port_mirror_service(
        self,
        *,
        name: str,
        mirror_interface_name: str,
        receive_interface,
        mirror_direction: str = "both",
    ) -> FakePortMirror:
        receive_name = receive_interface.get_name() if hasattr(receive_interface, "get_name") else str(receive_interface)
        pm = FakePortMirror(
            name=name,
            mirror_interface_name=mirror_interface_name,
            receive_interface_name=receive_name,
            mirror_direction=mirror_direction,
            slice_obj=self,
        )
        self._port_mirrors.append(pm)
        return pm

    def submit(self, wait: bool = False) -> None:
        self._slice_id = self._slice_id or contract_slice_id(self._name)
        self._state = "StableOK"
        for index, node in enumerate(self._nodes, start=10):
            node._reservation_state = "Active"
            node._management_ip = node._management_ip or f"192.0.2.{index}"
        self._manager._register(self)

    def delete(self) -> None:
        self._state = "Dead"

    def save(self, filename: str = "") -> None:
        if not filename:
            return
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        with open(filename, "w") as f:
            json.dump(self._to_json(), f)

    def load(self, filename: str = "") -> None:
        if not filename or not os.path.isfile(filename):
            return
        try:
            with open(filename) as f:
                data = json.load(f)
        except Exception:
            return
        self._from_json(data)

    def _to_json(self) -> dict[str, Any]:
        return {
            "name": self._name,
            "slice_id": self._slice_id,
            "state": self._state,
            "nodes": [
                {
                    "name": node.get_name(),
                    "site": node.get_site(),
                    "host": node.get_host(),
                    "cores": node.get_cores(),
                    "ram": node.get_ram(),
                    "disk": node.get_disk(),
                    "image": node.get_image(),
                    "image_type": node.get_image_type(),
                    "username": node.get_username(),
                    "components": [
                        {"name": comp.get_name(), "model": comp.get_model()}
                        for comp in node.get_components()
                    ],
                }
                for node in self._nodes
            ],
            "networks": [
                {
                    "name": net.get_name(),
                    "type": net.get_type(),
                    "interfaces": [iface.get_name() for iface in net.get_interfaces()],
                    "subnet": net.get_subnet(),
                    "gateway": net.get_gateway(),
                }
                for net in self._networks
            ],
        }

    def _from_json(self, data: dict[str, Any]) -> None:
        self._name = data.get("name", self._name)
        self._slice_id = data.get("slice_id", self._slice_id)
        self._state = data.get("state", self._state)
        self._nodes = []
        self._networks = []
        self._facility_ports = []
        self._port_mirrors = []
        for node_data in data.get("nodes", []):
            node = self.add_node(
                name=node_data.get("name", "node"),
                site=node_data.get("site", "RENC"),
                host=node_data.get("host", ""),
                cores=int(node_data.get("cores", 2)),
                ram=int(node_data.get("ram", 8)),
                disk=int(node_data.get("disk", 10)),
                image=node_data.get("image", "default_ubuntu_22"),
                image_type=node_data.get("image_type") or None,
            )
            if node_data.get("username"):
                node.set_username(node_data["username"])
            for comp_data in node_data.get("components", []):
                node.add_component(
                    model=comp_data.get("model", "NIC_Basic"),
                    name=comp_data.get("name", "nic1"),
                )
        for net_data in data.get("networks", []):
            interfaces = []
            wanted = set(net_data.get("interfaces", []))
            for node in self._nodes:
                interfaces.extend(
                    iface for iface in node.get_interfaces()
                    if iface.get_name() in wanted
                )
            net = self.add_l3network(
                name=net_data.get("name", "net"),
                interfaces=interfaces,
                type=net_data.get("type", "IPv4"),
            ) if net_data.get("type", "").startswith("IPv") else self.add_l2network(
                name=net_data.get("name", "net"),
                interfaces=interfaces,
                type=net_data.get("type", "L2Bridge"),
            )
            if net_data.get("subnet"):
                net.set_subnet(net_data["subnet"])
            if net_data.get("gateway"):
                net.set_gateway(net_data["gateway"])


@dataclass
class FakeSliceDto:
    name: str
    slice_id: str
    state: str
    lease_end_time: str
    project_id: str


class FakeCoreManager:
    def __init__(self, fablib: "FakeFablibManager"):
        self._fablib = fablib
        self.project_id = fablib.project_id

    def list_slices(self, *args, **kwargs) -> list[FakeSliceDto]:
        exclude_states = set(kwargs.get("exclude_states") or [])
        self.project_id = self._fablib.project_id
        result = []
        for slice_obj in self._fablib.get_slices():
            if not slice_obj.get_slice_id():
                continue
            if slice_obj.get_state() in exclude_states:
                continue
            result.append(
                FakeSliceDto(
                    name=slice_obj.get_name(),
                    slice_id=slice_obj.get_slice_id(),
                    state=slice_obj.get_state(),
                    lease_end_time=str(slice_obj.get_lease_end()),
                    project_id=self.project_id,
                )
            )
        return result

    def get_project_info(self) -> list[dict[str, str]]:
        return [{"uuid": self._fablib.project_id, "name": "Contract Project"}]

    def get_refresh_token(self) -> str:
        return ""

    def refresh_tokens(self, refresh_token: str = "") -> None:
        return None


class FakeResources:
    def __init__(self):
        self._sites_data = [
            {
                "name": "RENC",
                "state": "Active",
                "cores_available": 1000,
                "cores_capacity": 1000,
                "ram_available": 2048,
                "ram_capacity": 2048,
                "disk_available": 10000,
                "disk_capacity": 10000,
                "components": {
                    "SmartNIC-ConnectX-6": {"capacity": 8, "allocated": 0, "available": 8},
                    "SmartNIC-ConnectX-7": {"capacity": 8, "allocated": 0, "available": 8},
                },
                "hosts_count": 1,
                "location": [35.7796, -78.6382],
            }
        ]
        self._hosts_data = [
            {
                "name": "renct-contract-host-1",
                "site": "RENC",
                "cores_available": 1000,
                "cores_capacity": 1000,
                "ram_available": 2048,
                "ram_capacity": 2048,
                "disk_available": 10000,
                "disk_capacity": 10000,
                "components": {
                    "SmartNIC-ConnectX-6": {"capacity": 8, "available": 8},
                    "SmartNIC-ConnectX-7": {"capacity": 8, "available": 8},
                },
            }
        ]

    def get_site_names(self) -> list[str]:
        return [site["name"] for site in self._sites_data]

    def get_site(self, site_name: str) -> dict[str, Any] | None:
        for site in self._sites_data:
            if site["name"] == site_name:
                return site
        return None

    def get_hosts_by_site(self, site_name: str) -> list[dict[str, Any]]:
        return [host for host in self._hosts_data if host.get("site") == site_name]


class FakeFablibManager:
    FABNETV4_SUBNET = "10.128.0.0/10"
    FABNETV6_SUBNET = "2602:fcfb::/36"

    def __init__(self):
        self.project_id = os.environ.get("FABRIC_PROJECT_ID", "contract-project") or "contract-project"
        self._slices_by_name: dict[str, FakeSlice] = {}
        self._slices_by_id: dict[str, FakeSlice] = {}
        self._manager = FakeCoreManager(self)
        self._resources = FakeResources()

    def reset(self) -> None:
        self._slices_by_name.clear()
        self._slices_by_id.clear()

    def set_project_id(self, project_id: str) -> None:
        self.project_id = project_id or "contract-project"
        self._manager.project_id = self.project_id

    def get_manager(self) -> FakeCoreManager:
        return self._manager

    def new_slice(self, name: str) -> FakeSlice:
        slice_obj = FakeSlice(name=name, manager=self)
        self._register(slice_obj)
        return slice_obj

    def get_slice(
        self,
        name: str | None = None,
        slice_id: str | None = None,
    ) -> FakeSlice:
        if slice_id and slice_id in self._slices_by_id:
            return self._slices_by_id[slice_id]
        if slice_id and slice_id in self._slices_by_name:
            return self._slices_by_name[slice_id]
        if name and name in self._slices_by_name:
            return self._slices_by_name[name]
        raise RuntimeError(f"Slice not found: {name or slice_id}")

    def get_slices(self) -> list[FakeSlice]:
        return list(self._slices_by_name.values())

    def get_resources(self) -> FakeResources:
        return self._resources

    def show_config(self) -> dict[str, str]:
        return {"project_id": self.project_id}

    def seed_slice(
        self,
        *,
        name: str,
        slice_id: str | None = None,
        node_name: str = "fabric-node-1",
    ) -> FakeSlice:
        slice_obj = FakeSlice(
            name=name,
            manager=self,
            slice_id=slice_id or contract_slice_id(name),
            state="StableOK",
        )
        node = slice_obj.add_node(name=node_name, site="RENC")
        node._reservation_state = "Active"
        node._management_ip = "192.0.2.20"
        component = node.add_component(model="NIC_Basic", name="nic1")
        iface = component.get_interfaces()[0]
        iface.set_mode("auto")
        slice_obj.add_l3network(name="fabnetv4", interfaces=[iface], type="FABNetv4")
        self._register(slice_obj)
        return slice_obj

    def _register(self, slice_obj: FakeSlice) -> None:
        self._slices_by_name[slice_obj.get_name()] = slice_obj
        if slice_obj.get_slice_id():
            self._slices_by_id[slice_obj.get_slice_id()] = slice_obj
