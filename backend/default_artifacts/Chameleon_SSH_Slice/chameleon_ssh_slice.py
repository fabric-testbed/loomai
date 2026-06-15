#!/usr/bin/env python3
"""Lifecycle helper for the Chameleon SSH Slice weave."""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


INSTANCE_TIMEOUT_SECONDS = 45 * 60
SSH_TIMEOUT_SECONDS = 15 * 60
DEFAULT_LOOMAI_URL = "http://localhost:8000"
DEFAULT_SITES = ["CHI@TACC", "CHI@UC"]
DEFAULT_NODE_TYPES = ["compute_cascadelake_r", "compute_skylake", "compute_haswell"]
TERMINAL_LEASE_STATUSES = {"ERROR", "FAILED", "DELETED", "TERMINATED"}


def state_path(slice_name: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9-]+", "-", slice_name).strip("-")
    return Path(f".state-{safe}.json")


def load_state(slice_name: str) -> dict[str, Any]:
    path = state_path(slice_name)
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def save_state(slice_name: str, state: dict[str, Any]) -> None:
    state_path(slice_name).write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def delete_state(slice_name: str) -> None:
    path = state_path(slice_name)
    if path.exists():
        path.unlink()


def _without_api_suffix(url: str) -> str:
    url = url.rstrip("/")
    if url.endswith("/api"):
        return url[:-4]
    return url


def loomai_base_url() -> str:
    configured = (
        os.environ.get("LOOMAI_API_URL")
        or os.environ.get("LOOMAI_URL")
        or DEFAULT_LOOMAI_URL
    )
    return _without_api_suffix(configured)


def loomai_api_base() -> str:
    return loomai_base_url().rstrip("/") + "/api"


def loomai_auth_headers() -> dict[str, str]:
    session_cookie = os.environ.get("LOOMAI_SESSION_COOKIE", "")
    if not session_cookie or "\n" in session_cookie or "\r" in session_cookie:
        return {}
    return {"Cookie": f"loomai_session={session_cookie}"}


def loomai_connection_hint() -> str:
    return (
        "Set LOOMAI_API_URL or LOOMAI_URL if this script is not running in the "
        "same network namespace as the backend. Use http://127.0.0.1:8000 on "
        "the Docker host or inside the backend container, http://backend:8000 "
        "from another docker-compose service, and make sure Codex/network "
        "sandboxing allows local HTTP access."
    )


def loomai_request(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    timeout: int = 120,
) -> Any:
    url = loomai_api_base() + path
    data = None
    headers = {"Accept": "application/json"}
    headers.update(loomai_auth_headers())
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LoomAI {method} {path} failed with HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            "Cannot connect to LoomAI backend at "
            f"{loomai_api_base()} for Chameleon slice registration. "
            f"{loomai_connection_hint()}"
        ) from exc

    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def list_chameleon_slice_records() -> list[dict[str, Any]]:
    data = loomai_request("GET", "/chameleon/slices")
    return data if isinstance(data, list) else data.get("slices", [])


def resolve_chameleon_key_name(site: str) -> str:
    try:
        settings = loomai_request("GET", "/settings", timeout=30)
        sites = settings.get("chameleon", {}).get("sites", {}) if isinstance(settings, dict) else {}
        site_cfg = sites.get(site, {}) if isinstance(sites, dict) else {}
        key_name = str(site_cfg.get("default_key_name", "") or "").strip()
        if key_name:
            return key_name
    except Exception as exc:
        progress(f"Chameleon SSH key default lookup skipped: {exc}")
    return "loomai-key"


def ensure_chameleon_keypair_for_launch(site: str, key_name: str) -> None:
    if key_name != "loomai-key":
        progress(f"Using configured Chameleon keypair '{key_name}' at {site}.")
        return
    result = loomai_request("POST", "/chameleon/keypairs/ensure", {"site": site}, timeout=330)
    if isinstance(result, dict) and result.get("error"):
        raise RuntimeError(f"Could not ensure Chameleon keypair 'loomai-key' at {site}: {result['error']}")
    status = result.get("status", "ready") if isinstance(result, dict) else "ready"
    progress(f"SSH keypair 'loomai-key' at {site}: {status}")


def find_chameleon_slice_record(name: str, site: str | None = None) -> dict[str, Any] | None:
    for item in list_chameleon_slice_records():
        if item.get("name") != name:
            continue
        if site and item.get("site") not in {site, None, ""}:
            continue
        return item
    return None


def ensure_chameleon_slice_record(slice_name: str, site: str) -> dict[str, Any]:
    existing = find_chameleon_slice_record(slice_name, site)
    if existing:
        return existing

    progress(f"Creating LoomAI Chameleon slice record '{slice_name}' at {site}...")
    record = loomai_request("POST", "/chameleon/slices", {"name": slice_name, "site": site})
    if not isinstance(record, dict) or not record.get("id"):
        raise RuntimeError(f"Chameleon slice create did not return an id: {record}")
    return record


def add_chameleon_slice_resource(
    state: dict[str, Any],
    resource_type: str,
    resource_id: str | None,
    resource_name: str = "",
    status: str = "",
) -> dict[str, Any]:
    if not resource_id:
        return state

    slice_id = state.get("chameleon_slice_id")
    if not slice_id:
        record = ensure_chameleon_slice_record(state["slice_name"], state["site"])
        slice_id = record["id"]
        state["chameleon_slice_id"] = slice_id
    else:
        record = next(
            (item for item in list_chameleon_slice_records() if item.get("id") == slice_id),
            {},
        )

    type_labels = {
        "instance": ("server", "Server"),
        "lease": ("lease", "Lease"),
        "network": ("network", "Network"),
        "floating_ip": ("floating_ip", "Floating IP"),
    }
    display_type, type_label = type_labels.get(
        resource_type,
        (resource_type, resource_type.replace("_", " ").title()),
    )
    body = {
        "type": resource_type,
        "resource_type": display_type,
        "type_label": type_label,
        "id": resource_id,
        "name": resource_name,
        "site": state.get("site"),
    }
    if status:
        body["status"] = status
    if resource_type == "instance":
        body.update({
            "planned_node_id": state.get("planned_node_id"),
            "planned_node_name": state.get("node_name"),
            "node_type": state.get("node_type"),
            "image": state.get("image"),
            "lease_id": lease_id_from_state(state),
            "reservation_id": state.get("reservation_id"),
            "key_name": state.get("key_name", ""),
            "ip_addresses": state.get("ip_addresses", []),
            "floating_ip": state.get("floating_ip_address"),
            "management_ip": state.get("floating_ip_address"),
            "ssh_user": state.get("ssh_user", "cc"),
            "ssh_command": (
                f"ssh {state.get('ssh_user', 'cc')}@{state['floating_ip_address']}"
                if state.get("floating_ip_address") else ""
            ),
            "port_id": state.get("port_id"),
            "ssh_ready": bool(state.get("ssh_ready")),
        })
    elif resource_type == "floating_ip":
        body["floating_ip"] = state.get("floating_ip_address") or resource_name
        body["floating_ip_id"] = resource_id
    elif resource_type == "lease":
        body["lease_id"] = resource_id
    progress(f"Updating {resource_type} {resource_id[:12]} in Chameleon slice view...")
    record = loomai_request("POST", f"/chameleon/slices/{slice_id}/add-resource", body)
    if isinstance(record, dict) and record.get("id"):
        state["chameleon_slice_id"] = record["id"]
    return state


def sync_chameleon_slice_resources(state: dict[str, Any]) -> dict[str, Any]:
    if not state:
        return state
    record = ensure_chameleon_slice_record(state["slice_name"], state["site"])
    state["chameleon_slice_id"] = record["id"]
    state = add_chameleon_slice_resource(state, "lease", lease_id_from_state(state), state.get("slice_name", ""), "ACTIVE")
    state = add_chameleon_slice_resource(state, "instance", state.get("instance_id"), state.get("instance_name", ""), "ACTIVE")
    state = add_chameleon_slice_resource(
        state,
        "floating_ip",
        state.get("floating_ip_id"),
        state.get("floating_ip_address", ""),
        "ACTIVE",
    )
    update_chameleon_slice_view(state)
    return state


def openstack_request(
    site: str,
    service_type: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    timeout: int = 120,
) -> Any:
    data = loomai_request(
        "POST",
        "/chameleon/openstack/request",
        {
            "site": site,
            "service_type": service_type,
            "method": method,
            "path": path,
            "body": body,
            "params": params,
            "timeout": timeout,
        },
        timeout=timeout + 30,
    )
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(f"OpenStack {service_type} {method} {path} failed: {data['error']}")
    return data


def progress(message: str) -> None:
    print(f"### PROGRESS: {message}", flush=True)


def wait_for(predicate, timeout: int, interval: int, waiting_message: str):
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = predicate()
        if result:
            return result
        progress(waiting_message)
        time.sleep(interval)
    raise TimeoutError(waiting_message)


def find_by_name_or_id(items: list[dict[str, Any]], name: str, item_id: str | None) -> dict[str, Any] | None:
    for item in items:
        if item_id and item.get("id") == item_id:
            return item
        if item.get("name") == name:
            return item
    return None


def list_instances(site: str) -> list[dict[str, Any]]:
    data = openstack_request(site, "compute", "GET", "/servers/detail")
    return data.get("servers", [])


def list_leases(site: str) -> list[dict[str, Any]]:
    data = openstack_request(site, "reservation", "GET", "/leases")
    return data.get("leases", [])


def list_networks(site: str) -> list[dict[str, Any]]:
    data = openstack_request(site, "network", "GET", "/networks")
    return data.get("networks", [])


def get_instance(site: str, instance_id: str, instance_name: str) -> dict[str, Any] | None:
    try:
        detail = openstack_request(site, "compute", "GET", f"/servers/{instance_id}")
        server = detail.get("server")
        if isinstance(server, dict) and server.get("id"):
            return server
    except Exception:
        pass
    return find_by_name_or_id(list_instances(site), instance_name, instance_id)


def get_lease(site: str, lease_id: str | None, lease_name: str) -> dict[str, Any] | None:
    return find_by_name_or_id(list_leases(site), lease_name, lease_id)


def first_lease(deploy: dict[str, Any]) -> dict[str, Any] | None:
    leases = deploy.get("leases")
    if isinstance(leases, list) and leases:
        first = leases[0]
        if isinstance(first, dict):
            return first
    return None


def first_host_reservation(lease: dict[str, Any] | None) -> dict[str, Any] | None:
    if not lease:
        return None
    reservations = lease.get("reservations")
    if not isinstance(reservations, list):
        return None
    for reservation in reservations:
        if not isinstance(reservation, dict):
            continue
        if reservation.get("resource_type") == "physical:host":
            return reservation
    for reservation in reservations:
        if isinstance(reservation, dict):
            return reservation
    return None


def lease_id_from_state(state: dict[str, Any]) -> str | None:
    lease_id = state.get("lease_id")
    if isinstance(lease_id, str) and lease_id:
        return lease_id
    lease = state.get("deploy_result", {}).get("lease")
    if isinstance(lease, dict) and isinstance(lease.get("id"), str):
        return lease["id"]
    lease = first_lease(state.get("deploy_result", {}))
    if lease and isinstance(lease.get("lease_id"), str):
        return lease["lease_id"]
    if lease and isinstance(lease.get("id"), str):
        return lease["id"]
    return None


def wait_for_lease(site: str, lease_id: str | None, lease_name: str) -> dict[str, Any]:
    def check() -> dict[str, Any] | None:
        lease = get_lease(site, lease_id, lease_name)
        if not lease:
            return None

        status = str(lease.get("status", "")).upper()
        reservation_statuses = []
        reservations = lease.get("reservations", [])
        if isinstance(reservations, list):
            reservation_statuses = [
                str(res.get("status", "unknown"))
                for res in reservations
                if isinstance(res, dict)
            ]
        reservation_summary = ", ".join(reservation_statuses) or "none"
        progress(f"Lease {lease.get('name', lease_name)} status: {status or 'unknown'}; reservations: {reservation_summary}")
        if status == "ACTIVE":
            return lease
        if status in TERMINAL_LEASE_STATUSES:
            raise RuntimeError(f"Lease {lease.get('name', lease_name)} entered terminal status {status}")
        return None

    return wait_for(
        check,
        INSTANCE_TIMEOUT_SECONDS,
        30,
        "Waiting for Chameleon lease/reservation to become ACTIVE...",
    )


def resolve_network_id(site: str, network: str) -> str:
    if not network:
        return network
    networks = list_networks(site)
    for item in networks:
        if item.get("id") == network:
            return network
    for item in networks:
        if item.get("name") == network:
            network_id = item.get("id")
            if isinstance(network_id, str) and network_id:
                return network_id
    return network


def resolve_image_id(site: str, image: str) -> str:
    if re.fullmatch(r"[0-9a-fA-F-]{32,36}", image):
        return image
    data = openstack_request(site, "image", "GET", "/images", params={"name": image})
    images = data.get("images", [])
    if isinstance(images, list):
        for item in images:
            if isinstance(item, dict) and item.get("name") == image and isinstance(item.get("id"), str):
                return item["id"]
    raise RuntimeError(f"Could not resolve Chameleon image '{image}' at {site}")


def create_lease(site: str, name: str, node_type: str, hours: int) -> dict[str, Any]:
    start = datetime.now(timezone.utc) + timedelta(minutes=1)
    end = start + timedelta(hours=hours)
    body = {
        "name": name,
        "start_date": start.strftime("%Y-%m-%d %H:%M"),
        "end_date": end.strftime("%Y-%m-%d %H:%M"),
        "reservations": [
            {
                "resource_type": "physical:host",
                "min": 1,
                "max": 1,
                "hypervisor_properties": "",
                "resource_properties": json.dumps(["==", "$node_type", node_type]),
            }
        ],
        "events": [],
    }
    progress(f"Creating Blazar lease '{name}' at {site} ({node_type})...")
    data = openstack_request(site, "reservation", "POST", "/leases", body, timeout=300)
    lease = data.get("lease", data)
    if not isinstance(lease, dict) or not lease.get("id"):
        raise RuntimeError(f"Blazar lease create did not return a lease id: {data}")
    return lease


def create_instance_from_lease(
    site: str,
    instance_name: str,
    lease_id: str,
    reservation_id: str | None,
    image: str,
    network: str,
    key_name: str = "",
) -> dict[str, Any]:
    existing = find_by_name_or_id(list_instances(site), instance_name, None)
    if existing:
        progress(f"Instance '{instance_name}' already exists; monitoring it.")
        return existing

    network_id = resolve_network_id(site, network)
    image_id = resolve_image_id(site, image)
    progress(f"Launching instance '{instance_name}' on lease {lease_id[:12]}...")
    body = {
        "server": {
            "name": instance_name,
            "imageRef": image_id,
            "flavorRef": "baremetal",
            "networks": [{"uuid": network_id}],
        },
        "OS-SCH-HNT:scheduler_hints": {
            "reservation": reservation_id or lease_id,
        },
    }
    if key_name:
        body["server"]["key_name"] = key_name
    data = openstack_request(site, "compute", "POST", "/servers", body, timeout=300)
    server = data.get("server", data)
    if not isinstance(server, dict) or not server.get("id"):
        raise RuntimeError(f"Nova server create did not return an instance id: {data}")
    return server


def extract_floating_ip(instance: dict[str, Any]) -> str | None:
    for key in ("floating_ip", "floating_ip_address", "public_ip"):
        value = instance.get(key)
        if isinstance(value, str) and value:
            return value

    for value in instance.get("ip_addresses", []):
        if isinstance(value, str) and value and not value.startswith("10."):
            return value

    addresses = instance.get("addresses", {})
    if isinstance(addresses, dict):
        for entries in addresses.values():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                if entry.get("OS-EXT-IPS:type") == "floating" and entry.get("addr"):
                    return entry["addr"]
    return None


def extract_ip_addresses(instance: dict[str, Any]) -> list[str]:
    addresses: list[str] = []

    for value in instance.get("ip_addresses", []):
        if isinstance(value, str) and value:
            addresses.append(value)

    grouped = instance.get("addresses", {})
    if isinstance(grouped, dict):
        for entries in grouped.values():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if isinstance(entry, dict) and isinstance(entry.get("addr"), str):
                    addresses.append(entry["addr"])

    unique: list[str] = []
    for address in addresses:
        if address not in unique:
            unique.append(address)
    return unique


def local_chameleon_slices_path() -> Path | None:
    cwd = Path.cwd()
    for base in [cwd, *cwd.parents]:
        path = base / ".loomai" / "chameleon_slices.json"
        if path.exists():
            return path
    return None


def update_chameleon_slice_view_api(state: dict[str, Any]) -> None:
    slice_id = state.get("chameleon_slice_id")
    node_name = state.get("instance_name") or state.get("node_name")
    site = state.get("site")
    if not slice_id or not node_name or not site:
        return

    record = next(
        (item for item in list_chameleon_slice_records() if item.get("id") == slice_id),
        None,
    )
    if not isinstance(record, dict):
        return

    nodes = record.get("nodes", [])
    node = next((item for item in nodes if isinstance(item, dict) and item.get("name") == node_name), None)
    floating_ip = state.get("floating_ip_address")
    fixed_ips = [
        ip
        for ip in state.get("ip_addresses", [])
        if isinstance(ip, str) and ip and ip != floating_ip
    ]
    interface = {
        "nic": 0,
        "network": {
            "name": state.get("management_network", "sharednet1"),
            "port_id": state.get("port_id"),
            "ip_addresses": fixed_ips,
        },
    }
    if fixed_ips:
        interface["network"]["ip"] = fixed_ips[0]

    node_body = {
        "name": node_name,
        "node_type": state.get("node_type", "auto"),
        "image": state.get("image", "CC-Ubuntu22.04"),
        "count": 1,
        "site": site,
        "status": "ACTIVE" if state.get("instance_id") else "DEPLOYING",
        "instance_id": state.get("instance_id"),
        "floating_ip": floating_ip,
        "management_ip": floating_ip,
        "ip_addresses": state.get("ip_addresses", []),
        "ssh_user": state.get("ssh_user", "cc"),
        "ssh_command": f"ssh {state.get('ssh_user', 'cc')}@{floating_ip}" if floating_ip else "",
        "port_id": state.get("port_id"),
        "lease_id": lease_id_from_state(state),
        "reservation_id": state.get("reservation_id"),
        "key_name": state.get("key_name", ""),
    }
    if node and node.get("id"):
        node_id = node["id"]
        loomai_request("PUT", f"/chameleon/drafts/{slice_id}/nodes/{node_id}", node_body)
        loomai_request("PUT", f"/chameleon/drafts/{slice_id}/nodes/{node_id}/interfaces", [interface])
    else:
        created = loomai_request(
            "POST",
            f"/chameleon/drafts/{slice_id}/nodes",
            {**node_body, "interfaces": [interface]},
        )
        created_nodes = created.get("nodes", []) if isinstance(created, dict) else []
        node = next(
            (item for item in created_nodes if isinstance(item, dict) and item.get("name") == node_name),
            None,
        )
        node_id = node.get("id") if isinstance(node, dict) else None

    if node_id:
        state["planned_node_id"] = node_id

    if state.get("floating_ip_address") and node_id:
        loomai_request(
            "PUT",
            f"/chameleon/drafts/{slice_id}/floating-ips",
            {"entries": [{"node_id": node_id, "nic": 0}]},
        )

    if state.get("instance_id") and node_id:
        add_chameleon_slice_resource(state, "instance", state.get("instance_id"), node_name, "ACTIVE")


def update_chameleon_slice_view(state: dict[str, Any]) -> None:
    try:
        update_chameleon_slice_view_api(state)
    except Exception as exc:
        progress(f"Chameleon slice topology API update skipped: {exc}")
    update_local_chameleon_slice_view(state)


def update_local_chameleon_slice_view(state: dict[str, Any]) -> None:
    """Backfill topology fields because the public API only supports add-resource."""
    path = local_chameleon_slices_path()
    if not path or not state.get("chameleon_slice_id"):
        return

    try:
        records = json.loads(path.read_text())
    except Exception as exc:
        progress(f"Local Chameleon slice view update skipped: {exc}")
        return

    if not isinstance(records, dict):
        return

    slice_id = state["chameleon_slice_id"]
    record = records.get(slice_id)
    if not isinstance(record, dict):
        for candidate in records.values():
            if isinstance(candidate, dict) and candidate.get("name") == state.get("slice_name"):
                record = candidate
                slice_id = candidate.get("id", slice_id)
                break
    if not isinstance(record, dict):
        return

    site = state.get("site")
    node_name = state.get("instance_name") or state.get("node_name")
    floating_ip = state.get("floating_ip_address")
    fixed_ips = [
        ip
        for ip in state.get("ip_addresses", [])
        if isinstance(ip, str) and ip and ip != floating_ip
    ]

    record["state"] = "Active" if state.get("instance_id") else record.get("state", "Deploying")
    record["site"] = site or record.get("site")
    record["sites"] = [site] if site else record.get("sites", [])

    nodes = record.get("nodes")
    if not isinstance(nodes, list):
        nodes = []
        record["nodes"] = nodes

    node = next((item for item in nodes if isinstance(item, dict) and item.get("name") == node_name), None)
    if node is None:
        node = {"name": node_name, "count": 1}
        nodes.append(node)

    node.update(
        {
            "name": node_name,
            "node_type": state.get("node_type", node.get("node_type", "auto")),
            "image": state.get("image", node.get("image", "")),
            "count": node.get("count", 1),
            "site": site,
            "status": "ACTIVE" if state.get("instance_id") else node.get("status", "DEPLOYING"),
            "instance_id": state.get("instance_id"),
            "key_name": state.get("key_name", ""),
            "ssh_user": state.get("ssh_user", "cc"),
        }
    )
    if floating_ip:
        node["floating_ip"] = floating_ip
        node["management_ip"] = floating_ip
        node["ssh_command"] = f"ssh {state.get('ssh_user', 'cc')}@{floating_ip}"

    if state.get("management_network") or state.get("port_id") or fixed_ips:
        interface = {
            "name": state.get("management_network", "sharednet1"),
            "network": state.get("management_network", "sharednet1"),
            "network_name": state.get("management_network", "sharednet1"),
            "site": site,
            "port_id": state.get("port_id"),
            "ip_addresses": fixed_ips,
        }
        if fixed_ips:
            interface["ip"] = fixed_ips[0]
        node["interfaces"] = [interface]

    if state.get("management_network"):
        record["networks"] = [
            {
                "name": state["management_network"],
                "type": "sharednet",
                "site": site,
            }
        ]

    if floating_ip:
        record["floating_ips"] = [
            {
                "id": state.get("floating_ip_id"),
                "address": floating_ip,
                "floating_ip": floating_ip,
                "site": site,
                "instance_id": state.get("instance_id"),
                "instance_name": node_name,
                "port_id": state.get("port_id"),
                "status": "ACTIVE",
            }
        ]

    records[slice_id] = record
    path.write_text(json.dumps(records, indent=2, sort_keys=True) + "\n")


def candidate_port_ids(value: Any) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []

    def walk(obj: Any, score: int = 0) -> None:
        if isinstance(obj, dict):
            text = " ".join(str(v).lower() for v in obj.values() if isinstance(v, (str, int, float)))
            local_score = score
            if "sharednet" in text or "public" in text or "management" in text:
                local_score += 10
            if "fabnet" in text:
                local_score -= 5

            for key in ("port_id", "network_port_id", "sharednet_port_id", "management_port_id"):
                val = obj.get(key)
                if isinstance(val, str) and val:
                    found.append((local_score + 20, val))

            if isinstance(obj.get("id"), str) and (
                "fixed_ips" in obj or obj.get("device_owner") or "mac_address" in obj
            ):
                found.append((local_score + 5, obj["id"]))

            for child in obj.values():
                walk(child, local_score)
        elif isinstance(obj, list):
            for child in obj:
                walk(child, score)

    walk(value)
    unique: dict[str, int] = {}
    for score, port_id in found:
        unique[port_id] = max(score, unique.get(port_id, -999))
    return sorted(((score, port_id) for port_id, score in unique.items()), reverse=True)


def find_port_id(instance: dict[str, Any]) -> str | None:
    explicit = instance.get("port_id") or instance.get("management_port_id") or instance.get("sharednet_port_id")
    if isinstance(explicit, str) and explicit:
        return explicit

    candidates = candidate_port_ids(instance)
    if candidates:
        return candidates[0][1]
    return None


def find_port_id_with_openstack(site: str, instance: dict[str, Any]) -> str | None:
    instance_id = instance.get("id")
    if not isinstance(instance_id, str) or not instance_id:
        return None

    data = openstack_request(site, "network", "GET", "/ports", params={"device_id": instance_id})
    ports = data.get("ports", [])
    if not isinstance(ports, list):
        return None

    instance_ips = {
        value
        for value in instance.get("ip_addresses", [])
        if isinstance(value, str) and value
    }
    addresses = instance.get("addresses", {})
    if isinstance(addresses, dict):
        for entries in addresses.values():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if isinstance(entry, dict) and isinstance(entry.get("addr"), str):
                    instance_ips.add(entry["addr"])

    for port in ports:
        if not isinstance(port, dict):
            continue
        fixed_ips = port.get("fixed_ips", [])
        if not isinstance(fixed_ips, list):
            continue
        for fixed_ip in fixed_ips:
            if not isinstance(fixed_ip, dict):
                continue
            if fixed_ip.get("ip_address") in instance_ips and isinstance(port.get("id"), str):
                return port["id"]

    for port in ports:
        if isinstance(port, dict) and isinstance(port.get("id"), str):
            return port["id"]
    return None


def wait_for_instance(site: str, instance_id: str | None, instance_name: str) -> dict[str, Any]:
    def check() -> dict[str, Any] | None:
        instance = None
        if instance_id:
            instance = get_instance(site, instance_id, instance_name)
        if not instance:
            instance = find_by_name_or_id(list_instances(site), instance_name, instance_id)
        if not instance:
            return None
        status = str(instance.get("status", "")).upper()
        progress(f"Instance {instance.get('name', instance_name)} status: {status or 'unknown'}")
        if status in {"ACTIVE", "RUNNING"}:
            return instance
        return None

    return wait_for(
        check,
        INSTANCE_TIMEOUT_SECONDS,
        30,
        "Waiting for Chameleon instance to become ACTIVE...",
    )


def allocate_floating_ip(site: str, network: str) -> dict[str, Any]:
    progress(f"Allocating floating IP from {network} at {site}...")
    network_id = resolve_network_id(site, network)
    data = openstack_request(
        site,
        "network",
        "POST",
        "/floatingips",
        {"floatingip": {"floating_network_id": network_id}},
    )
    fip = data.get("floatingip", data)
    if not isinstance(fip, dict) or not fip.get("id"):
        raise RuntimeError(f"Floating IP allocation did not return an id: {data}")
    return fip


def associate_floating_ip(site: str, floating_ip_id: str, port_id: str) -> dict[str, Any]:
    progress(f"Associating floating IP with port {port_id[:12]}...")
    data = openstack_request(
        site,
        "network",
        "PUT",
        f"/floatingips/{floating_ip_id}",
        {"floatingip": {"port_id": port_id}},
    )
    return data.get("floatingip", data)


def wait_for_ssh(ip_address: str, ssh_user: str) -> bool:
    def check() -> bool:
        try:
            with socket.create_connection((ip_address, 22), timeout=10):
                return True
        except OSError:
            return False

    try:
        wait_for(
            check,
            SSH_TIMEOUT_SECONDS,
            20,
            f"Waiting for SSH on {ip_address}:22...",
        )
    except TimeoutError:
        progress(
            "Provisioned, but SSH did not become reachable from this environment. "
            f"Try from a routed network: ssh {ssh_user}@{ip_address}"
        )
        return False

    progress(f"READY! SSH is reachable: ssh {ssh_user}@{ip_address}")
    return True


def selected_sites(site: str) -> list[str]:
    if site.lower() == "auto":
        return DEFAULT_SITES
    return [site]


def selected_node_types(node_type: str) -> list[str]:
    if node_type.lower() == "auto":
        return DEFAULT_NODE_TYPES
    return [node_type]


def is_capacity_error(exc: Exception) -> bool:
    text = str(exc).lower()
    capacity_markers = (
        "not enough resources",
        "resources available",
        "no valid host",
        "quota",
        "reservation",
    )
    return any(marker in text for marker in capacity_markers)


def deploy_once(args: argparse.Namespace, site: str, node_type: str) -> dict[str, Any]:
    slice_name = args.slice_name
    node_name = f"{slice_name}-node1"
    key_name = resolve_chameleon_key_name(site)
    ensure_chameleon_keypair_for_launch(site, key_name)
    slice_record = ensure_chameleon_slice_record(slice_name, site)
    state = {
        "slice_name": slice_name,
        "site": site,
        "chameleon_slice_id": slice_record["id"],
        "node_name": node_name,
        "instance_name": node_name,
        "node_type": node_type,
        "image": args.image,
        "management_network": args.management_network,
        "ssh_user": args.ssh_user,
        "key_name": key_name,
    }
    save_state(slice_name, state)

    lease = create_lease(site, slice_name, node_type, args.hours)
    reservation = first_host_reservation(lease)

    state["lease_id"] = lease.get("id")
    state["deploy_result"] = {"lease": lease}
    if reservation and reservation.get("id"):
        state["reservation_id"] = reservation["id"]
    state = add_chameleon_slice_resource(state, "lease", state.get("lease_id"), slice_name, "DEPLOYING")
    save_state(slice_name, state)
    return state


def start(args: argparse.Namespace) -> None:
    slice_name = args.slice_name
    state = load_state(slice_name)
    if state.get("instance_id"):
        progress(f"Existing state found for {slice_name}; monitoring existing deployment.")
        state = sync_chameleon_slice_resources(state)
        save_state(slice_name, state)
        monitor(args)
        return

    attempts = [
        (site, node_type)
        for site in selected_sites(args.site)
        for node_type in selected_node_types(args.node_type)
    ]
    errors: list[str] = []

    for index, (site, node_type) in enumerate(attempts, start=1):
        progress(f"Deployment attempt {index}/{len(attempts)}: site={site}, node_type={node_type}")
        try:
            state = deploy_once(args, site, node_type)
            break
        except Exception as exc:
            errors.append(f"{site}/{node_type}: {exc}")
            progress(f"Deployment attempt failed at {site}/{node_type}: {exc}")
            stop(argparse.Namespace(slice_name=slice_name, site=site, ssh_user=args.ssh_user))
            if not is_capacity_error(exc):
                raise
    else:
        joined = "\n".join(f"  - {error}" for error in errors)
        raise RuntimeError(f"All Chameleon deployment attempts failed:\n{joined}")

    site = state["site"]
    lease_id = lease_id_from_state(state)
    if lease_id:
        lease = wait_for_lease(site, lease_id, slice_name)
        state["lease_id"] = lease.get("id", lease_id)
        reservation = first_host_reservation(lease)
        if reservation and reservation.get("id"):
            state["reservation_id"] = reservation["id"]
        state = add_chameleon_slice_resource(state, "lease", state.get("lease_id"), slice_name, "ACTIVE")
        save_state(slice_name, state)

    if not state.get("instance_id"):
        existing = find_by_name_or_id(list_instances(site), state["instance_name"], None)
        if existing:
            state["instance_id"] = existing.get("id")
            state["instance_name"] = existing.get("name", state["instance_name"])
            state = add_chameleon_slice_resource(state, "instance", state.get("instance_id"), state["instance_name"], "ACTIVE")
            save_state(slice_name, state)
        elif state.get("lease_id"):
            launched = create_instance_from_lease(
                site,
                state["instance_name"],
                state["lease_id"],
                state.get("reservation_id"),
                state["image"],
                state.get("management_network") or args.management_network,
                state.get("key_name", ""),
            )
            state["instance_id"] = launched.get("id")
            state["instance_name"] = launched.get("name") or state["instance_name"]
            state["key_name"] = str(launched.get("key_name") or launched.get("OS-EXT-SRV-ATTR:key_name") or state.get("key_name", "") or "").strip()
            state = add_chameleon_slice_resource(state, "instance", state.get("instance_id"), state["instance_name"], "DEPLOYING")
            save_state(slice_name, state)

    instance = wait_for_instance(site, state.get("instance_id"), state["instance_name"])
    state["instance_id"] = instance.get("id", state.get("instance_id"))
    state["instance_name"] = instance.get("name", state["instance_name"])
    state["key_name"] = str(instance.get("key_name") or instance.get("OS-EXT-SRV-ATTR:key_name") or state.get("key_name", "") or "").strip()
    state["ip_addresses"] = extract_ip_addresses(instance)
    state = add_chameleon_slice_resource(state, "instance", state.get("instance_id"), state["instance_name"], "ACTIVE")

    floating_ip = extract_floating_ip(instance)
    if floating_ip:
        state["floating_ip_address"] = floating_ip
        save_state(slice_name, state)
        update_chameleon_slice_view(state)
        progress(f"Instance already has floating IP {floating_ip}.")
        wait_for_ssh(floating_ip, args.ssh_user)
        return

    port_id = find_port_id(instance)
    if not port_id:
        progress("Looking up management port id from OpenStack...")
        port_id = find_port_id_with_openstack(site, instance)
    if not port_id:
        save_state(slice_name, state)
        raise RuntimeError(
            "Could not find the instance management port id needed for floating IP association. "
            f"Instance data keys: {sorted(instance.keys())}"
        )
    state["port_id"] = port_id

    fip = allocate_floating_ip(site, args.floating_network)
    state["floating_ip_id"] = fip.get("id")
    state["floating_ip_address"] = fip.get("floating_ip_address")
    state = add_chameleon_slice_resource(
        state,
        "floating_ip",
        state.get("floating_ip_id"),
        state.get("floating_ip_address", ""),
        "DEPLOYING",
    )
    save_state(slice_name, state)

    associated = associate_floating_ip(site, state["floating_ip_id"], port_id)
    state["floating_ip_address"] = (
        associated.get("floating_ip_address")
        or state.get("floating_ip_address")
    )
    state = sync_chameleon_slice_resources(state)
    save_state(slice_name, state)
    update_chameleon_slice_view(state)

    if not state.get("floating_ip_address"):
        raise RuntimeError(f"Floating IP association did not return an address: {associated}")

    wait_for_ssh(state["floating_ip_address"], args.ssh_user)


def monitor(args: argparse.Namespace) -> None:
    state = load_state(args.slice_name)
    if not state:
        raise RuntimeError(f"No state file found for {args.slice_name}")
    state = sync_chameleon_slice_resources(state)
    save_state(args.slice_name, state)

    site = state.get("site") or args.site
    instance_id = state.get("instance_id")
    instance_name = state.get("instance_name") or state.get("node_name") or f"{args.slice_name}-node1"
    instance = get_instance(site, instance_id, instance_name) if instance_id else None
    if not instance:
        instance = find_by_name_or_id(list_instances(site), instance_name, instance_id)
    if not instance:
        raise RuntimeError(f"Instance {instance_name} not found at {site}")

    status = str(instance.get("status", "")).upper()
    if status not in {"ACTIVE", "RUNNING"}:
        raise RuntimeError(f"Instance {instance_name} is {status or 'unknown'}")

    ip_address = state.get("floating_ip_address") or extract_floating_ip(instance)
    if not ip_address:
        raise RuntimeError(f"Instance {instance_name} has no floating IP")
    state["instance_id"] = instance.get("id", instance_id)
    state["instance_name"] = instance.get("name", instance_name)
    state["key_name"] = str(instance.get("key_name") or instance.get("OS-EXT-SRV-ATTR:key_name") or state.get("key_name", "") or "").strip()
    state["ip_addresses"] = extract_ip_addresses(instance)
    state["floating_ip_address"] = ip_address
    save_state(args.slice_name, state)
    update_chameleon_slice_view(state)

    try:
        with socket.create_connection((ip_address, 22), timeout=10):
            progress(f"Healthy: {instance_name} is {status}; SSH: ssh {args.ssh_user}@{ip_address}")
            return
    except OSError as exc:
        progress(
            f"Healthy OpenStack state: {instance_name} is {status}; "
            f"SSH port check failed for {ip_address}:22 from here: {exc}"
        )


def stop(args: argparse.Namespace) -> None:
    state = load_state(args.slice_name)
    if not state:
        progress(f"No saved state for {args.slice_name}; nothing to clean up.")
        return

    site = state.get("site") or args.site
    instance_id = state.get("instance_id")
    instance_name = state.get("instance_name") or state.get("node_name") or f"{args.slice_name}-node1"
    floating_ip_id = state.get("floating_ip_id")
    floating_ip_address = state.get("floating_ip_address")

    if not instance_id:
        instance = find_by_name_or_id(list_instances(site), instance_name, None)
        if instance:
            instance_id = instance.get("id")
            floating_ip_address = floating_ip_address or extract_floating_ip(instance)

    if instance_id and floating_ip_address:
        try:
            progress(f"Disassociating floating IP {floating_ip_address}...")
            if floating_ip_id:
                openstack_request(
                    site,
                    "network",
                    "PUT",
                    f"/floatingips/{floating_ip_id}",
                    {"floatingip": {"port_id": None}},
                )
        except Exception as exc:
            progress(f"Floating IP disassociate skipped: {exc}")

    if floating_ip_id:
        try:
            progress(f"Releasing floating IP {floating_ip_id}...")
            openstack_request(site, "network", "DELETE", f"/floatingips/{floating_ip_id}")
        except Exception as exc:
            progress(f"Floating IP release skipped: {exc}")

    if instance_id:
        try:
            progress(f"Deleting instance {instance_id}...")
            openstack_request(site, "compute", "DELETE", f"/servers/{instance_id}", timeout=300)
        except Exception as exc:
            progress(f"Instance delete skipped: {exc}")

    lease_id = lease_id_from_state(state)
    if lease_id:
        try:
            progress(f"Deleting lease {lease_id}...")
            openstack_request(site, "reservation", "DELETE", f"/leases/{lease_id}", timeout=300)
        except Exception as exc:
            progress(f"Lease delete skipped: {exc}")

    if state.get("draft_id"):
        progress("Legacy LoomAI draft state ignored; this weave now uses OpenStack APIs directly.")

    if state.get("chameleon_slice_id"):
        try:
            progress(f"Deleting Chameleon slice record {state['chameleon_slice_id']}...")
            loomai_request("DELETE", f"/chameleon/slices/{state['chameleon_slice_id']}")
        except Exception as exc:
            progress(f"Chameleon slice record delete skipped: {exc}")

    delete_state(args.slice_name)
    progress(f"Cleanup complete for {args.slice_name}.")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Deploy and manage a Chameleon SSH slice.")
    sub = p.add_subparsers(dest="action", required=True)

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("slice_name")
        sp.add_argument("--site", default="auto")
        sp.add_argument("--ssh-user", default="cc")

    start_p = sub.add_parser("start")
    common(start_p)
    start_p.add_argument("--node-type", default="auto")
    start_p.add_argument("--image", default="CC-Ubuntu22.04")
    start_p.add_argument("--hours", type=int, default=4)
    start_p.add_argument("--floating-network", default="public")
    start_p.add_argument("--management-network", default="sharednet1")

    monitor_p = sub.add_parser("monitor")
    common(monitor_p)

    stop_p = sub.add_parser("stop")
    common(stop_p)

    return p


def main() -> int:
    args = parser().parse_args()
    try:
        if args.action == "start":
            start(args)
        elif args.action == "monitor":
            monitor(args)
        elif args.action == "stop":
            stop(args)
        else:
            raise RuntimeError(f"Unknown action {args.action}")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
