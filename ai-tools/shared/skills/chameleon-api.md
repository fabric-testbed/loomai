name: chameleon-api
description: Use Chameleon Cloud APIs from LoomAI agents, weaves, or backend-owned code
---
Help the user write correct Chameleon Cloud API code.

## API Choice
Use the highest-level working API:

1. **Built-in LoomAI tools** for normal chat operations:
   `list_chameleon_sites`, `list_chameleon_leases`, `create_chameleon_lease`,
   `create_chameleon_instance`, `delete_chameleon_instance`.
2. **LoomAI REST** for weaves and scripts. This reuses the user's Chameleon
   credentials configured in LoomAI.
3. **Backend direct OpenStack** only inside backend-owned code where
   `app.chameleon_manager` is importable.
4. **python-chi/OpenStack SDK** only when the user explicitly wants external
   Chameleon code and has Keystone/clouds.yaml auth configured.

Search the RAG example `chameleon/openstack_api_patterns.py` before writing
new code. It contains syntax-checkable examples for Blazar leases, Nova
servers, Neutron networks, floating IPs, security groups, and FABNetv4
route-metric userdata.

## LoomAI REST Pattern
```python
import os
import requests

BASE = os.environ.get("LOOMAI_API_URL") or "http://127.0.0.1:8000/api"
site = "CHI@TACC"

lease = requests.post(f"{BASE}/chameleon/leases", json={
    "site": site,
    "name": "my-chameleon-exp",
    "node_type": "compute_haswell",
    "node_count": 1,
    "duration_hours": 4,
}, timeout=60).json()

reservation_id = lease["reservations"][0]["id"]

server = requests.post(f"{BASE}/chameleon/instances", json={
    "site": site,
    "name": "node1",
    "reservation_id": reservation_id,
    "image_id": "CC-Ubuntu24.04",
    "network_ids": ["<sharednet1-id>", "<fabnetv4-id>"],
    "key_name": "loomai-key",
    "security_groups": ["loomai-ssh"],
    "user_data": "<cloud-init text>",
}, timeout=60).json()

fip = requests.post(
    f"{BASE}/chameleon/instances/{server['id']}/associate-ip",
    json={"site": site},
    timeout=60,
).json()
```

## Backend Direct OpenStack Pattern
```python
from app.chameleon_manager import get_session

session = get_session("CHI@TACC")
leases = session.api_get("reservation", "/leases")
servers = session.api_get("compute", "/servers/detail")
networks = session.api_get("network", "/v2.0/networks")

server = session.api_post("compute", "/servers", {
    "server": {
        "name": "node1",
        "imageRef": "<image-uuid>",
        "flavorRef": "baremetal",
        "networks": [{"uuid": "<network-id>"}],
    },
    "os:scheduler_hints": {"reservation": "<reservation-id>"},
})
```

## Payload Rules
- Blazar physical-host leases use `resource_type: "physical:host"` and
  `resource_properties` as a JSON string, commonly
  `["==", "$node_type", "compute_haswell"]`.
- Nova server create needs top-level `os:scheduler_hints.reservation`.
- Nova direct API expects base64 `server.user_data`; LoomAI REST accepts plain
  cloud-init and encodes it.
- Neutron floating IPs are associated by `floatingip.port_id`.
- Neutron SSH rules are security-group rules: ingress, IPv4, TCP, port 22.
- Any server attached to `fabnetv4` needs route-metric cloud-init. Prefer
  `sharednet1` metric `50` and `fabnetv4` metric `500` for public SSH plus
  FABNet dataplane.

## Safety
- Confirm before deleting leases, servers, floating IPs, networks, or security groups.
- Delete servers before deleting their Blazar lease.
- Surface partial failures: a lease can be deleted while floating IP cleanup or
  server deletion fails.
