"""Mock FABlib objects for testing without live FABRIC infrastructure."""

from __future__ import annotations

from typing import Any, Optional
from unittest.mock import MagicMock


class MockInterface:
    """Mock FABlib Interface."""

    def __init__(self, name: str = "iface1", node: Any = None,
                 network: Any = None, vlan: str = "", bandwidth: str = ""):
        self._name = name
        self._node = node
        self._network = network
        self._vlan = vlan
        self._bandwidth = bandwidth
        self._fablib_data: dict = {}
        self._mode: str = ""
        self._ip_addr: str = ""

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

    def get_fablib_data(self) -> dict:
        return self._fablib_data

    def get_fim(self):
        mock_fim = MagicMock()
        mock_fim.label_allocations = None
        return mock_fim

    def set_mode(self, mode: str):
        self._mode = mode

    def set_ip_addr(self, addr: str):
        self._ip_addr = addr


class MockComponent:
    """Mock FABlib Component."""

    def __init__(self, name: str = "nic1", model: str = "NIC_Basic",
                 comp_type: str = "SmartNIC", interfaces: list | None = None):
        self._name = name
        self._model = model
        self._type = comp_type
        self._interfaces = interfaces or []

    def get_name(self) -> str:
        return self._name

    def get_model(self) -> str:
        return self._model

    def get_type(self) -> str:
        return self._type

    def get_interfaces(self) -> list:
        return self._interfaces

    def delete(self):
        pass


class MockNode:
    """Mock FABlib Node."""

    def __init__(self, name: str = "node1", site: str = "RENC",
                 cores: int = 2, ram: int = 8, disk: int = 10,
                 image: str = "default_ubuntu_22", host: str = "",
                 management_ip: str = "", reservation_state: str = "Active",
                 components: list | None = None, interfaces: list | None = None):
        self._name = name
        self._site = site
        self._cores = cores
        self._ram = ram
        self._disk = disk
        self._image = image
        self._host = host
        self._management_ip = management_ip
        self._reservation_state = reservation_state
        self._components = components or []
        self._interfaces = interfaces or []
        self._user_data: dict = {}
        self._error_message: str = ""

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
        return "qcow2"

    def get_management_ip(self) -> str:
        return self._management_ip

    def get_reservation_state(self) -> str:
        return self._reservation_state

    def get_username(self) -> str:
        return "ubuntu"

    def get_components(self) -> list:
        return self._components

    def get_interfaces(self) -> list:
        return self._interfaces

    def get_user_data(self) -> dict:
        return self._user_data

    def get_error_message(self) -> str:
        return self._error_message

    def get_fim_node(self):
        mock_fim = MagicMock()
        mock_caps = MagicMock()
        mock_caps.core = self._cores
        mock_caps.ram = self._ram
        mock_caps.disk = self._disk
        mock_fim.capacities = mock_caps
        return mock_fim

    def add_component(self, model: str, name: str):
        comp = MockComponent(name=name, model=model)
        self._components.append(comp)
        # Create an interface on the component
        iface = MockInterface(
            name=f"{self._name}-{name}-p1",
            node=self,
        )
        comp._interfaces.append(iface)
        self._interfaces.append(iface)
        return comp

    def get_component(self, name: str):
        for c in self._components:
            if c.get_name() == name:
                return c
        raise Exception(f"Component not found: {name}")

    def set_site(self, site: str):
        self._site = site

    def set_host(self, host: str):
        self._host = host or ""

    def set_capacities(self, cores: int = None, ram: int = None, disk: int = None):
        if cores is not None:
            self._cores = cores
        if ram is not None:
            self._ram = ram
        if disk is not None:
            self._disk = disk

    def set_image(self, image: str, image_type: str = None):
        self._image = image

    def set_username(self, username: str):
        pass

    def set_instance_type(self, instance_type: str):
        pass

    def set_user_data(self, data: dict):
        self._user_data = data

    def delete(self):
        pass


class MockNetworkService:
    """Mock FABlib NetworkService."""

    def __init__(self, name: str = "net1", net_type: str = "L2Bridge",
                 interfaces: list | None = None, subnet: str = "",
                 gateway: str = ""):
        self._name = name
        self._type = net_type
        self._interfaces = interfaces or []
        self._subnet = subnet
        self._gateway = gateway

    def get_name(self) -> str:
        return self._name

    def get_type(self) -> str:
        return self._type

    def get_interfaces(self) -> list:
        return self._interfaces

    def get_subnet(self) -> str:
        return self._subnet

    def get_gateway(self) -> str:
        return self._gateway

    def set_subnet(self, subnet: str):
        self._subnet = subnet

    def set_gateway(self, gateway: str):
        self._gateway = gateway

    def delete(self):
        pass


class MockSlice:
    """Mock FABlib Slice."""

    def __init__(self, name: str = "test-slice", slice_id: str = "test-uuid-1234",
                 state: str = "Draft", nodes: list | None = None,
                 networks: list | None = None):
        self._name = name
        self._slice_id = slice_id
        self._state = state
        self._nodes = nodes or []
        self._networks = networks or []
        self._facility_ports: list = []
        self._error_messages: list = []

    def get_name(self) -> str:
        return self._name

    def get_slice_id(self) -> str:
        return self._slice_id

    def get_state(self) -> str:
        return self._state

    def get_nodes(self) -> list:
        return self._nodes

    def get_network_services(self) -> list:
        return self._networks

    def get_facility_ports(self) -> list:
        return self._facility_ports

    def get_error_messages(self) -> list:
        return self._error_messages

    def get_lease_start(self):
        return None

    def get_lease_end(self):
        return None

    def add_node(self, name: str, site: str = "RENC", cores: int = 2,
                 ram: int = 8, disk: int = 10, image: str = "default_ubuntu_22",
                 host: str = None, image_type: str = None) -> MockNode:
        node = MockNode(name=name, site=site, cores=cores, ram=ram,
                        disk=disk, image=image)
        self._nodes.append(node)
        return node

    def add_l2network(self, name: str, interfaces: list | None = None,
                      type: str = "L2Bridge") -> MockNetworkService:
        net = MockNetworkService(name=name, net_type=type, interfaces=interfaces or [])
        self._networks.append(net)
        return net

    def add_l3network(self, name: str, interfaces: list | None = None,
                      type: str = "IPv4") -> MockNetworkService:
        net = MockNetworkService(name=name, net_type=type, interfaces=interfaces or [])
        self._networks.append(net)
        return net

    def add_facility_port(self, name: str, site: str, vlan: str = "",
                          bandwidth: int = 10):
        pass

    def get_node(self, name: str) -> MockNode:
        for n in self._nodes:
            if n.get_name() == name:
                return n
        raise Exception(f"Node not found: {name}")

    def get_network(self, name: str) -> MockNetworkService:
        for n in self._networks:
            if n.get_name() == name:
                return n
        raise Exception(f"Network not found: {name}")

    def get_project_id(self) -> str:
        return ""

    def submit(self):
        self._state = "Configuring"

    def save(self, filename: str = ""):
        if filename:
            with open(filename, "w") as f:
                f.write("<graphml></graphml>")

    def load(self, filename: str = ""):
        pass

    def delete(self):
        self._state = "Dead"


class MockResources:
    """Mock FABlib Resources/Topology."""

    def __init__(self, sites: list[dict] | None = None):
        self._sites = sites or []

    def get_sites(self) -> list:
        return [s["name"] for s in self._sites]

    def get_hosts_by_site(self, site_name: str) -> dict:
        return {}


class MockFablibManager:
    """Mock FablibManager — replaces get_fablib() return value."""

    def __init__(self, slices: list[MockSlice] | None = None,
                 sites: list[dict] | None = None):
        self._slices = {s.get_name(): s for s in (slices or [])}
        self._sites = sites or []
        self._resources = MockResources(self._sites)

    def new_slice(self, name: str) -> MockSlice:
        # Return empty slice_id — the route will assign a draft UUID via the registry
        s = MockSlice(name=name, slice_id="")
        self._slices[name] = s
        return s

    def get_slice(self, name: str = None, slice_id: str = None) -> MockSlice:
        if slice_id:
            for s in self._slices.values():
                if s.get_slice_id() == slice_id:
                    return s
        if name and name in self._slices:
            return self._slices[name]
        raise Exception(f"Slice not found: {name or slice_id}")

    def get_slices(self) -> list[MockSlice]:
        return list(self._slices.values())

    def get_resources(self):
        return self._resources

    def show_config(self) -> dict:
        return {"project_id": "test-project-id"}
