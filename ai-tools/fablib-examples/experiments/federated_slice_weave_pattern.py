#!/usr/bin/env python3
"""Federated Slice and weave registration pattern.

This example shows how a LoomAI weave or automation script should create a
Federated Slice entry so the Federated Slice view immediately shows a
cross-facility experiment and the state of its provider sub-slices.

Key ideas:
- A Federated Slice is a meta-slice. Provider resources live in FABRIC,
  Chameleon, or future facilities; the Federated Slice groups them.
- Use `/api/federated/...` for new code. `/api/composite/...` is a compatibility
  alias for older scripts and UI paths.
- Add provider members as soon as drafts/slices exist, before long provisioning.
- Add cross-facility connection intent (`fabnetv4_l3` or `facility_port_l2`) so
  the graph and connection plan can explain the design.
- Cross-facility weaves should create/update this record during `start()`.

This file is intentionally written as a small REST helper rather than a full
experiment. Combine it with the standard weave lifecycle template:
`experiments/weave_lifecycle_template.py`.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


def _with_api_suffix(url: str) -> str:
    url = url.rstrip("/")
    return url if url.endswith("/api") else f"{url}/api"


def loomai_api_url() -> str:
    configured = os.environ.get("LOOMAI_API_URL") or os.environ.get("LOOMAI_URL") or "http://localhost:8000/api"
    return _with_api_suffix(configured)


def loomai_auth_headers() -> dict[str, str]:
    session_cookie = os.environ.get("LOOMAI_SESSION_COOKIE", "")
    if not session_cookie or "\n" in session_cookie or "\r" in session_cookie:
        return {}
    return {"Cookie": f"loomai_session={session_cookie}"}


def _request(method: str, path: str, body: dict[str, Any] | list[Any] | None = None) -> Any:
    """Call the LoomAI backend with stdlib urllib so no extra dependency is needed."""
    data = None
    headers = {"Content-Type": "application/json"}
    headers.update(loomai_auth_headers())
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(f"{loomai_api_url()}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = resp.read().decode("utf-8")
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: HTTP {exc.code}: {detail}") from exc


def create_federated_slice(name: str) -> dict[str, Any]:
    """Create a Federated Slice grouping record."""
    return _request("POST", "/federated/slices", {"name": name})


def set_members(
    federated_id: str,
    *,
    fabric_slice_id: str,
    chameleon_slice_id: str,
    fabric_name: str = "fabric-member",
    chameleon_name: str = "chameleon-member",
) -> dict[str, Any]:
    """Attach current provider members.

    `slice_id` can be a FABRIC draft ID, a submitted FABRIC UUID, or a LoomAI
    Chameleon slice ID. Future facilities should add records with their own
    provider string and metadata.
    """
    return _request(
        "PUT",
        f"/federated/slices/{federated_id}/members",
        {
            "members": [
                {
                    "provider": "fabric",
                    "slice_id": fabric_slice_id,
                    "name": fabric_name,
                    "role": "fabric-sub-slice",
                },
                {
                    "provider": "chameleon",
                    "slice_id": chameleon_slice_id,
                    "name": chameleon_name,
                    "role": "chameleon-sub-slice",
                },
            ]
        },
    )


def add_fabnetv4_l3_connection(
    federated_id: str,
    *,
    fabric_slice_id: str,
    fabric_node: str,
    chameleon_slice_id: str,
    chameleon_node: str,
) -> dict[str, Any]:
    """Record routed L3 connectivity over FABNetv4."""
    return _request(
        "POST",
        f"/federated/slices/{federated_id}/connections/add",
        {
            "type": "fabnetv4_l3",
            "endpoint_a": {
                "provider": "fabric",
                "slice_id": fabric_slice_id,
                "node": fabric_node,
                "network": "FABNetv4",
            },
            "endpoint_b": {
                "provider": "chameleon",
                "slice_id": chameleon_slice_id,
                "node": chameleon_node,
                "network": "fabnetv4",
            },
        },
    )


def add_facility_port_l2_connection(
    federated_id: str,
    *,
    fabric_slice_id: str,
    fabric_node: str,
    chameleon_slice_id: str,
    chameleon_node: str,
    facility_port: str,
    vlan: str,
    fabric_site: str,
    chameleon_site: str,
) -> dict[str, Any]:
    """Record VLAN-backed L2 connectivity through a facility port."""
    return _request(
        "POST",
        f"/federated/slices/{federated_id}/connections/add",
        {
            "type": "facility_port_l2",
            "facility_port": facility_port,
            "vlan": vlan,
            "fabric_site": fabric_site,
            "chameleon_site": chameleon_site,
            "endpoint_a": {
                "provider": "fabric",
                "slice_id": fabric_slice_id,
                "node": fabric_node,
            },
            "endpoint_b": {
                "provider": "chameleon",
                "slice_id": chameleon_slice_id,
                "node": chameleon_node,
            },
        },
    )


def start_example() -> None:
    """Example sequence for a weave start() function.

    Replace the placeholder IDs with IDs returned by your provider creation
    logic. For a full weave:
    1. Create the FABRIC draft/slice.
    2. Create the Chameleon draft/slice.
    3. Call the helpers below immediately.
    4. Submit/run provider resources or call `/federated/slices/{id}/submit`.
    """
    federated_name = os.environ.get("FEDERATED_SLICE_NAME", "example-federated-slice")
    fabric_id = os.environ.get("FABRIC_SLICE_ID", "draft-fabric-placeholder")
    chameleon_id = os.environ.get("CHAMELEON_SLICE_ID", "chi-slice-placeholder")

    print(f"### PROGRESS: Creating Federated Slice record '{federated_name}'...")
    fed = create_federated_slice(federated_name)
    fed_id = fed["id"]
    print(f"### PROGRESS: Federated Slice ID: {fed_id}")

    print("### PROGRESS: Adding FABRIC and Chameleon provider members...")
    set_members(
        fed_id,
        fabric_slice_id=fabric_id,
        chameleon_slice_id=chameleon_id,
        fabric_name=f"{federated_name}-fabric",
        chameleon_name=f"{federated_name}-chameleon",
    )

    print("### PROGRESS: Recording FABNetv4 L3 connection intent...")
    add_fabnetv4_l3_connection(
        fed_id,
        fabric_slice_id=fabric_id,
        fabric_node="fabric-node",
        chameleon_slice_id=chameleon_id,
        chameleon_node="chameleon-node",
    )

    print("### PROGRESS: Checking connection plan...")
    plan = _request("GET", f"/federated/slices/{fed_id}/connection-plan")
    print(json.dumps(plan, indent=2))
    print("READY: Federated Slice is visible in the Federated Slice view.")


def legacy_backend_assisted_note() -> None:
    """Document the older automatic materialization path.

    If a LoomAI FABRIC draft has Chameleon nodes attached through the legacy
    Chameleon node editor and the script runs:

        POST /api/slices/{slice_name}/submit-composite

    LoomAI automatically creates a Federated Slice entry and a Chameleon member
    record. New weaves should prefer the explicit `/api/federated` pattern above.
    """
    print("Legacy path: POST /api/slices/{slice_name}/submit-composite")


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "start-example"
    if command == "start-example":
        start_example()
    elif command == "legacy-note":
        legacy_backend_assisted_note()
    else:
        raise SystemExit(f"Unknown command: {command}")
