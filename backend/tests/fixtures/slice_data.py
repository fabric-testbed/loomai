"""Factory functions producing slice data dicts for testing."""

from __future__ import annotations

from typing import Any


def empty_slice(name: str = "empty", slice_id: str = "empty-uuid") -> dict[str, Any]:
    """Minimal empty slice — no nodes, no networks."""
    return {
        "name": name,
        "id": slice_id,
        "state": "Draft",
        "nodes": [],
        "networks": [],
        "facility_ports": [],
    }


def single_node_slice(name: str = "hello", slice_id: str = "hello-uuid",
                       state: str = "Draft") -> dict[str, Any]:
    """Single-node slice (like Hello_FABRIC)."""
    return {
        "name": name,
        "id": slice_id,
        "state": state,
        "nodes": [
            {
                "name": "node1",
                "site": "RENC",
                "cores": 2,
                "ram": 8,
                "disk": 10,
                "image": "default_ubuntu_22",
                "reservation_state": state if state != "Draft" else "Unknown",
                "management_ip": "",
                "components": [],
                "interfaces": [],
            }
        ],
        "networks": [],
        "facility_ports": [],
    }


def l2_bridge_slice(name: str = "l2-bridge", slice_id: str = "l2-uuid") -> dict[str, Any]:
    """Two nodes connected by an L2Bridge (like L2_Bridge template)."""
    return {
        "name": name,
        "id": slice_id,
        "state": "Draft",
        "nodes": [
            {
                "name": "node1",
                "site": "RENC",
                "cores": 2,
                "ram": 8,
                "disk": 10,
                "image": "default_ubuntu_22",
                "reservation_state": "Unknown",
                "management_ip": "",
                "components": [
                    {
                        "name": "nic1",
                        "model": "NIC_Basic",
                        "type": "SmartNIC",
                        "interfaces": [
                            {"name": "node1-nic1-p1", "node_name": "node1",
                             "network_name": "lan", "vlan": "", "mac": "",
                             "ip_addr": "", "bandwidth": "", "mode": ""}
                        ],
                    }
                ],
                "interfaces": [
                    {"name": "node1-nic1-p1", "node_name": "node1",
                     "network_name": "lan", "vlan": "", "mac": "",
                     "ip_addr": "", "bandwidth": "", "mode": ""}
                ],
            },
            {
                "name": "node2",
                "site": "RENC",
                "cores": 2,
                "ram": 8,
                "disk": 10,
                "image": "default_ubuntu_22",
                "reservation_state": "Unknown",
                "management_ip": "",
                "components": [
                    {
                        "name": "nic1",
                        "model": "NIC_Basic",
                        "type": "SmartNIC",
                        "interfaces": [
                            {"name": "node2-nic1-p1", "node_name": "node2",
                             "network_name": "lan", "vlan": "", "mac": "",
                             "ip_addr": "", "bandwidth": "", "mode": ""}
                        ],
                    }
                ],
                "interfaces": [
                    {"name": "node2-nic1-p1", "node_name": "node2",
                     "network_name": "lan", "vlan": "", "mac": "",
                     "ip_addr": "", "bandwidth": "", "mode": ""}
                ],
            },
        ],
        "networks": [
            {
                "name": "lan",
                "type": "L2Bridge",
                "layer": "L2",
                "subnet": "192.168.1.0/24",
                "gateway": "",
                "interfaces": [
                    {"name": "node1-nic1-p1", "node_name": "node1",
                     "network_name": "lan", "vlan": "", "mac": "",
                     "ip_addr": "", "bandwidth": "", "mode": ""},
                    {"name": "node2-nic1-p1", "node_name": "node2",
                     "network_name": "lan", "vlan": "", "mac": "",
                     "ip_addr": "", "bandwidth": "", "mode": ""},
                ],
            }
        ],
        "facility_ports": [],
    }


def fabnetv4_slice(name: str = "fabnet", slice_id: str = "fabnet-uuid") -> dict[str, Any]:
    """Two nodes with FABNetv4 gateways (triggers internet node)."""
    return {
        "name": name,
        "id": slice_id,
        "state": "Draft",
        "nodes": [
            {
                "name": "node-a",
                "site": "RENC",
                "cores": 2,
                "ram": 8,
                "disk": 10,
                "image": "default_ubuntu_22",
                "reservation_state": "Unknown",
                "management_ip": "",
                "components": [
                    {
                        "name": "nic1",
                        "model": "NIC_Basic",
                        "type": "SmartNIC",
                        "interfaces": [
                            {"name": "node-a-nic1-p1", "node_name": "node-a",
                             "network_name": "fabnet-a", "vlan": "", "mac": "",
                             "ip_addr": "", "bandwidth": "", "mode": ""}
                        ],
                    }
                ],
                "interfaces": [
                    {"name": "node-a-nic1-p1", "node_name": "node-a",
                     "network_name": "fabnet-a", "vlan": "", "mac": "",
                     "ip_addr": "", "bandwidth": "", "mode": ""}
                ],
            },
            {
                "name": "node-b",
                "site": "UCSD",
                "cores": 2,
                "ram": 8,
                "disk": 10,
                "image": "default_ubuntu_22",
                "reservation_state": "Unknown",
                "management_ip": "",
                "components": [
                    {
                        "name": "nic1",
                        "model": "NIC_Basic",
                        "type": "SmartNIC",
                        "interfaces": [
                            {"name": "node-b-nic1-p1", "node_name": "node-b",
                             "network_name": "fabnet-b", "vlan": "", "mac": "",
                             "ip_addr": "", "bandwidth": "", "mode": ""}
                        ],
                    }
                ],
                "interfaces": [
                    {"name": "node-b-nic1-p1", "node_name": "node-b",
                     "network_name": "fabnet-b", "vlan": "", "mac": "",
                     "ip_addr": "", "bandwidth": "", "mode": ""}
                ],
            },
        ],
        "networks": [
            {
                "name": "fabnet-a",
                "type": "FABNetv4",
                "layer": "L3",
                "subnet": "",
                "gateway": "",
                "interfaces": [
                    {"name": "node-a-nic1-p1", "node_name": "node-a",
                     "network_name": "fabnet-a", "vlan": "", "mac": "",
                     "ip_addr": "", "bandwidth": "", "mode": ""}
                ],
            },
            {
                "name": "fabnet-b",
                "type": "FABNetv4",
                "layer": "L3",
                "subnet": "",
                "gateway": "",
                "interfaces": [
                    {"name": "node-b-nic1-p1", "node_name": "node-b",
                     "network_name": "fabnet-b", "vlan": "", "mac": "",
                     "ip_addr": "", "bandwidth": "", "mode": ""}
                ],
            },
        ],
        "facility_ports": [],
    }


def gpu_slice(name: str = "gpu-pair", slice_id: str = "gpu-uuid") -> dict[str, Any]:
    """Two GPU nodes with RTX6000 + NIC components."""
    return {
        "name": name,
        "id": slice_id,
        "state": "Draft",
        "nodes": [
            {
                "name": "gpu-node1",
                "site": "UCSD",
                "cores": 8,
                "ram": 32,
                "disk": 100,
                "image": "default_ubuntu_22",
                "reservation_state": "Unknown",
                "management_ip": "",
                "components": [
                    {
                        "name": "gpu1",
                        "model": "GPU_RTX6000",
                        "type": "GPU",
                        "interfaces": [],
                    },
                    {
                        "name": "nic1",
                        "model": "NIC_Basic",
                        "type": "SmartNIC",
                        "interfaces": [
                            {"name": "gpu-node1-nic1-p1", "node_name": "gpu-node1",
                             "network_name": "gpu-link", "vlan": "", "mac": "",
                             "ip_addr": "", "bandwidth": "", "mode": ""}
                        ],
                    },
                ],
                "interfaces": [
                    {"name": "gpu-node1-nic1-p1", "node_name": "gpu-node1",
                     "network_name": "gpu-link", "vlan": "", "mac": "",
                     "ip_addr": "", "bandwidth": "", "mode": ""}
                ],
            },
            {
                "name": "gpu-node2",
                "site": "TACC",
                "cores": 8,
                "ram": 32,
                "disk": 100,
                "image": "default_ubuntu_22",
                "reservation_state": "Unknown",
                "management_ip": "",
                "components": [
                    {
                        "name": "gpu1",
                        "model": "GPU_RTX6000",
                        "type": "GPU",
                        "interfaces": [],
                    },
                    {
                        "name": "nic1",
                        "model": "NIC_Basic",
                        "type": "SmartNIC",
                        "interfaces": [
                            {"name": "gpu-node2-nic1-p1", "node_name": "gpu-node2",
                             "network_name": "gpu-link", "vlan": "", "mac": "",
                             "ip_addr": "", "bandwidth": "", "mode": ""}
                        ],
                    },
                ],
                "interfaces": [
                    {"name": "gpu-node2-nic1-p1", "node_name": "gpu-node2",
                     "network_name": "gpu-link", "vlan": "", "mac": "",
                     "ip_addr": "", "bandwidth": "", "mode": ""}
                ],
            },
        ],
        "networks": [
            {
                "name": "gpu-link",
                "type": "L2STS",
                "layer": "L2",
                "subnet": "",
                "gateway": "",
                "interfaces": [
                    {"name": "gpu-node1-nic1-p1", "node_name": "gpu-node1",
                     "network_name": "gpu-link", "vlan": "", "mac": "",
                     "ip_addr": "", "bandwidth": "", "mode": ""},
                    {"name": "gpu-node2-nic1-p1", "node_name": "gpu-node2",
                     "network_name": "gpu-link", "vlan": "", "mac": "",
                     "ip_addr": "", "bandwidth": "", "mode": ""},
                ],
            }
        ],
        "facility_ports": [],
    }


def facility_port_slice(name: str = "fp-test", slice_id: str = "fp-uuid") -> dict[str, Any]:
    """Slice with a facility port."""
    return {
        "name": name,
        "id": slice_id,
        "state": "Draft",
        "nodes": [],
        "networks": [
            {
                "name": "fp-net",
                "type": "L2Bridge",
                "layer": "L2",
                "subnet": "",
                "gateway": "",
                "interfaces": [
                    {"name": "fp1-p1", "node_name": "",
                     "network_name": "fp-net", "vlan": "100", "mac": "",
                     "ip_addr": "", "bandwidth": "", "mode": ""},
                ],
            }
        ],
        "facility_ports": [
            {
                "name": "fp1",
                "site": "RENC",
                "vlan": "100",
                "bandwidth": "10",
                "interfaces": [
                    {"name": "fp1-p1", "node_name": "",
                     "network_name": "fp-net", "vlan": "100", "mac": "",
                     "ip_addr": "", "bandwidth": "", "mode": ""},
                ],
            }
        ],
    }


def stableok_slice(name: str = "running", slice_id: str = "running-uuid") -> dict[str, Any]:
    """A slice in StableOK state with a provisioned node."""
    return {
        "name": name,
        "id": slice_id,
        "state": "StableOK",
        "nodes": [
            {
                "name": "node1",
                "site": "RENC",
                "cores": 4,
                "ram": 16,
                "disk": 50,
                "image": "default_ubuntu_22",
                "reservation_state": "Active",
                "management_ip": "10.0.0.1",
                "host": "renc-w1.fabric-testbed.net",
                "username": "ubuntu",
                "components": [],
                "interfaces": [],
            }
        ],
        "networks": [],
        "facility_ports": [],
    }
