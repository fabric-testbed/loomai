#!/usr/bin/env python3
"""
Chameleon OpenStack API patterns for LoomAI agents and weaves.

Use this when an agent needs the exact API payloads behind Chameleon lease,
server, network, floating-IP, security-group, and FABNetv4 workflows.

Preferred order:
1. Use LoomAI's `/api/chameleon/...` REST endpoints from weaves and agents.
2. From backend-owned code, use `app.chameleon_manager.get_session(site)`.
3. Use python-chi/OpenStack SDK only when the user's environment is already
   configured for Chameleon auth outside LoomAI.

Chameleon is OpenStack-based:
- Blazar Reservation API owns leases.
- Nova Compute API owns servers, keypairs, and server scheduling hints.
- Neutron Network API owns networks, ports, floating IPs, and security groups.

This file is intentionally safe to import: functions build payloads and examples,
but `main()` only prints them unless you explicitly wire in real IDs.
"""

from __future__ import annotations

import base64
import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    import requests
except Exception:  # pragma: no cover - examples may be syntax-checked only
    requests = None


DEFAULT_SITE = "CHI@TACC"
DEFAULT_IMAGE = "CC-Ubuntu24.04"
DEFAULT_NODE_TYPE = "compute_haswell"
DEFAULT_EXTERNAL_NETWORK = "public"
DEFAULT_SHARED_NETWORK = "sharednet1"
DEFAULT_FABNET_NETWORK = "fabnetv4"


def _with_api_suffix(url: str) -> str:
    url = url.rstrip("/")
    return url if url.endswith("/api") else f"{url}/api"


def loomai_api_url() -> str:
    """Return the LoomAI backend URL agents should use for REST calls."""
    configured = os.environ.get("LOOMAI_API_URL") or os.environ.get("LOOMAI_URL") or "http://127.0.0.1:8000/api"
    return _with_api_suffix(configured)


def loomai_auth_cookies() -> dict[str, str] | None:
    """Return LoomAI session cookies for authenticated in-container helpers."""
    session_cookie = os.environ.get("LOOMAI_SESSION_COOKIE", "")
    if not session_cookie or "\n" in session_cookie or "\r" in session_cookie:
        return None
    return {"loomai_session": session_cookie}


def utc_end_time(hours: int) -> str:
    """Blazar lease end_date format used by Chameleon examples."""
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M")


def nova_user_data_base64(user_data: str) -> str:
    """Nova expects user_data to be base64-encoded."""
    return base64.b64encode(user_data.encode("utf-8")).decode("ascii")


def route_metric_cloud_init(
    shared_iface: str = "eno1np0",
    fabnet_iface: str = "eno2np1",
    *,
    shared_metric: int = 50,
    fabnet_metric: int = 500,
) -> str:
    """Cloud-init/netplan pattern for Chameleon nodes using fabnetv4.

    Apply this to every Chameleon server attached to fabnetv4. For the common
    dual-NIC layout, NIC 0/sharednet1 carries floating-IP SSH and NIC 1/fabnetv4
    carries FABRIC-Chameleon dataplane traffic. For a FABNet-only single-NIC
    server, call `fabnet_only_route_metric_cloud_init()` instead.
    """
    return f"""#cloud-config
write_files:
  - path: /etc/netplan/99-chameleon-route-metrics.yaml
    owner: root:root
    permissions: '0600'
    content: |
      network:
        version: 2
        ethernets:
          {shared_iface}:
            dhcp4-overrides:
              route-metric: {shared_metric}
          {fabnet_iface}:
            dhcp4-overrides:
              route-metric: {fabnet_metric}
runcmd:
  - [ netplan, apply ]
"""


def fabnet_only_route_metric_cloud_init(fabnet_iface: str = "eno1np0", *, fabnet_metric: int = 500) -> str:
    """Cloud-init for a single-NIC/FABNet-only Chameleon server."""
    return f"""#cloud-config
write_files:
  - path: /etc/netplan/99-chameleon-fabnet-metric.yaml
    owner: root:root
    permissions: '0600'
    content: |
      network:
        version: 2
        ethernets:
          {fabnet_iface}:
            dhcp4-overrides:
              route-metric: {fabnet_metric}
runcmd:
  - [ netplan, apply ]
"""


# ---------------------------------------------------------------------------
# LoomAI REST API examples
# ---------------------------------------------------------------------------


def loomai_create_lease(
    site: str,
    name: str,
    node_type: str = DEFAULT_NODE_TYPE,
    count: int = 1,
    hours: int = 4,
) -> dict[str, Any]:
    """Create a Chameleon Blazar lease through LoomAI."""
    if requests is None:
        raise RuntimeError("requests is required to call LoomAI REST examples")
    response = requests.post(
        f"{loomai_api_url()}/chameleon/leases",
        json={
            "site": site,
            "name": name,
            "node_type": node_type,
            "node_count": count,
            "duration_hours": hours,
        },
        cookies=loomai_auth_cookies(),
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def loomai_wait_for_lease_active(site: str, lease_id: str, timeout_seconds: int = 900) -> dict[str, Any]:
    """Poll LoomAI until a Chameleon lease reaches ACTIVE."""
    if requests is None:
        raise RuntimeError("requests is required to call LoomAI REST examples")
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        response = requests.get(
            f"{loomai_api_url()}/chameleon/leases",
            params={"site": site},
            cookies=loomai_auth_cookies(),
            timeout=30,
        )
        response.raise_for_status()
        for lease in response.json():
            if lease.get("id") == lease_id:
                status = str(lease.get("status", "")).upper()
                if status == "ACTIVE":
                    return lease
                if status in {"ERROR", "FAILED"}:
                    raise RuntimeError(f"Lease {lease_id} failed: {lease}")
        time.sleep(30)
    raise TimeoutError(f"Lease {lease_id} did not become ACTIVE within {timeout_seconds}s")


def loomai_create_instance(
    site: str,
    name: str,
    reservation_id: str,
    image_id: str = DEFAULT_IMAGE,
    network_ids: list[str] | None = None,
    key_name: str | None = None,
    security_groups: list[str] | None = None,
    user_data: str | None = None,
) -> dict[str, Any]:
    """Launch a Chameleon server through LoomAI's Nova wrapper."""
    if requests is None:
        raise RuntimeError("requests is required to call LoomAI REST examples")
    body: dict[str, Any] = {
        "site": site,
        "name": name,
        "reservation_id": reservation_id,
        "image_id": image_id,
    }
    if network_ids:
        body["network_ids"] = network_ids
    if key_name:
        body["key_name"] = key_name
    if security_groups:
        body["security_groups"] = security_groups
    if user_data:
        body["user_data"] = user_data

    response = requests.post(
        f"{loomai_api_url()}/chameleon/instances",
        json=body,
        cookies=loomai_auth_cookies(),
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def loomai_allocate_and_associate_floating_ip(site: str, instance_id: str) -> dict[str, Any]:
    """Allocate a floating IP and associate it with a server.

    LoomAI's helper discovers the external network and the Neutron port for the
    instance, then creates the floating IP with `port_id` in one backend call.
    """
    if requests is None:
        raise RuntimeError("requests is required to call LoomAI REST examples")
    response = requests.post(
        f"{loomai_api_url()}/chameleon/instances/{instance_id}/associate-ip",
        json={"site": site},
        cookies=loomai_auth_cookies(),
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# Direct OpenStack payload builders
# ---------------------------------------------------------------------------


def blazar_physical_host_lease_payload(
    name: str,
    node_type: str = DEFAULT_NODE_TYPE,
    count: int = 1,
    hours: int = 4,
) -> dict[str, Any]:
    """Payload for Blazar `POST /leases` physical-host reservations."""
    return {
        "name": name,
        "start_date": "now",
        "end_date": utc_end_time(hours),
        "reservations": [
            {
                "resource_type": "physical:host",
                "resource_properties": json.dumps(["==", "$node_type", node_type]),
                "min": count,
                "max": count,
                "hypervisor_properties": "",
            }
        ],
        "events": [],
    }


def blazar_vlan_network_lease_payload(
    name: str,
    network_name: str,
    hours: int = 4,
) -> dict[str, Any]:
    """Payload for reserving a Chameleon network/VLAN with Blazar."""
    return {
        "name": name,
        "start_date": "now",
        "end_date": utc_end_time(hours),
        "reservations": [
            {
                "resource_type": "network",
                "network_name": network_name,
                "network_properties": "",
                "resource_properties": json.dumps([]),
            }
        ],
        "events": [],
    }


def nova_server_payload(
    name: str,
    image_ref: str,
    reservation_id: str,
    network_ids: list[str],
    *,
    key_name: str | None = None,
    security_groups: list[str] | None = None,
    flavor_ref: str = "baremetal",
    user_data: str | None = None,
) -> dict[str, Any]:
    """Payload for Nova `POST /servers` on a Chameleon reservation.

    Chameleon bare-metal servers need the Blazar reservation ID as a top-level
    Nova scheduler hint. Do not put `os:scheduler_hints` inside `server`.
    """
    payload: dict[str, Any] = {
        "server": {
            "name": name,
            "imageRef": image_ref,
            "flavorRef": flavor_ref,
            "min_count": 1,
            "max_count": 1,
            "networks": [{"uuid": network_id} for network_id in network_ids],
        },
        "os:scheduler_hints": {
            "reservation": reservation_id,
        },
    }
    if key_name:
        payload["server"]["key_name"] = key_name
    if security_groups:
        payload["server"]["security_groups"] = [{"name": sg} for sg in security_groups]
    if user_data:
        payload["server"]["user_data"] = nova_user_data_base64(user_data)
    return payload


def neutron_network_payload(name: str, *, vlan: int | None = None, physical_network: str | None = None) -> dict[str, Any]:
    """Payload for Neutron `POST /v2.0/networks`.

    Use provider VLAN fields only for authorized L2/facility-port workflows.
    Ordinary project networks should omit them.
    """
    network: dict[str, Any] = {"name": name, "admin_state_up": True}
    if vlan is not None:
        network["provider:network_type"] = "vlan"
        network["provider:segmentation_id"] = int(vlan)
        if physical_network:
            network["provider:physical_network"] = physical_network
    return {"network": network}


def neutron_subnet_payload(network_id: str, name: str, cidr: str) -> dict[str, Any]:
    """Payload for Neutron `POST /v2.0/subnets`."""
    return {
        "subnet": {
            "network_id": network_id,
            "name": name,
            "ip_version": 4,
            "cidr": cidr,
        }
    }


def neutron_floating_ip_payload(floating_network_id: str, port_id: str | None = None) -> dict[str, Any]:
    """Payload for Neutron `POST /v2.0/floatingips`."""
    body: dict[str, Any] = {"floating_network_id": floating_network_id}
    if port_id:
        body["port_id"] = port_id
    return {"floatingip": body}


def neutron_ssh_security_group_rule_payload(security_group_id: str, remote_ip_prefix: str = "0.0.0.0/0") -> dict[str, Any]:
    """Payload for Neutron `POST /v2.0/security-group-rules` allowing SSH."""
    return {
        "security_group_rule": {
            "security_group_id": security_group_id,
            "direction": "ingress",
            "ethertype": "IPv4",
            "protocol": "tcp",
            "port_range_min": 22,
            "port_range_max": 22,
            "remote_ip_prefix": remote_ip_prefix,
        }
    }


def direct_session_examples(site: str = DEFAULT_SITE) -> None:
    """Use LoomAI's authenticated Chameleon session inside backend-owned code.

    This pattern works inside the LoomAI backend container or code paths where
    `app.chameleon_manager` is importable and Chameleon credentials are already
    configured in LoomAI settings.
    """
    from app.chameleon_manager import get_session

    session = get_session(site)

    leases = session.api_get("reservation", "/leases")
    networks = session.api_get("network", "/v2.0/networks")
    images = session.api_get("image", "/v2/images?limit=20")
    servers = session.api_get("compute", "/servers/detail")

    print("leases:", len(leases.get("leases", [])))
    print("networks:", len(networks.get("networks", [])))
    print("images:", len(images.get("images", [])))
    print("servers:", len(servers.get("servers", [])))


def print_payload_examples() -> None:
    """Print representative payloads for RAG/search verification."""
    user_data = route_metric_cloud_init()
    examples = {
        "blazar_physical_host_lease": blazar_physical_host_lease_payload("loomai-example"),
        "blazar_network_lease": blazar_vlan_network_lease_payload("loomai-l2", "loomai-l2-net"),
        "nova_server_sharednet1_fabnetv4": nova_server_payload(
            "node1",
            "<image-uuid-or-name>",
            "<reservation-id>",
            ["<sharednet1-network-id>", "<fabnetv4-network-id>"],
            key_name="loomai-key",
            security_groups=["loomai-ssh"],
            user_data=user_data,
        ),
        "neutron_network": neutron_network_payload("loomai-private-net"),
        "neutron_subnet": neutron_subnet_payload("<network-id>", "loomai-subnet", "192.168.100.0/24"),
        "neutron_floating_ip": neutron_floating_ip_payload("<public-network-id>", "<server-port-id>"),
        "neutron_ssh_security_group_rule": neutron_ssh_security_group_rule_payload("<security-group-id>"),
    }
    print(json.dumps(examples, indent=2))


if __name__ == "__main__":
    print_payload_examples()
