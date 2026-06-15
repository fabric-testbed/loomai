name: deploy-chameleon
description: Deploy a Chameleon experiment — lease, instances, networking, and SSH access
---
Guide the user through deploying a complete Chameleon experiment with SSH access.
For Python REST snippets, use the authenticated session pattern from
`chameleon-api.md`: honor `LOOMAI_API_URL`/`LOOMAI_URL` and attach
`LOOMAI_SESSION_COOKIE` as the `loomai_session` cookie when present.

## Full Deploy Workflow

### Step 1: Choose Site and Hardware
```bash
# List available sites
loomai chameleon sites

# Check node types at a site
loomai chameleon sites CHI@TACC

# Check images
loomai chameleon images CHI@TACC
```

Or use tools: `list_chameleon_sites`, `chameleon_site_images(site)`

### Step 2: Create Lease
```bash
loomai chameleon leases create \
  --site CHI@TACC \
  --name my-experiment \
  --type compute_haswell \
  --count 2 \
  --hours 8
```

Or: `create_chameleon_lease("CHI@TACC", "my-experiment", "compute_haswell", 2, 8)`

LoomAI REST equivalent for weaves:
```python
session.post(f"{BASE}/chameleon/leases", json={
    "site": "CHI@TACC",
    "name": "my-experiment",
    "node_type": "compute_haswell",
    "node_count": 2,
    "duration_hours": 8,
}, timeout=60)
```

Direct Blazar payload shape:
```json
{
  "name": "my-experiment",
  "start_date": "now",
  "end_date": "<UTC end time: YYYY-MM-DD HH:MM>",
  "reservations": [{
    "resource_type": "physical:host",
    "resource_properties": "[\"==\", \"$node_type\", \"compute_haswell\"]",
    "min": 2,
    "max": 2,
    "hypervisor_properties": ""
  }],
  "events": []
}
```

Wait for ACTIVE: `list_chameleon_leases("CHI@TACC")` — check status field.
Bare-metal leases take 1-5 minutes to become ACTIVE.

### Step 3: Launch Instances
Get the reservation ID from the lease, then:
```bash
loomai chameleon instances create \
  --site CHI@TACC \
  --lease <lease-id> \
  --reservation <reservation-id> \
  --image CC-Ubuntu22.04 \
  --name node1
```

Or: `create_chameleon_instance("CHI@TACC", lease_id, reservation_id, "CC-Ubuntu22.04", "node1")`

LoomAI REST equivalent:
```python
session.post(f"{BASE}/chameleon/instances", json={
    "site": "CHI@TACC",
    "name": "node1",
    "reservation_id": reservation_id,
    "image_id": "CC-Ubuntu24.04",
    "network_ids": [sharednet1_id, fabnetv4_id],
    "key_name": "loomai-key",
    "security_groups": ["loomai-ssh"],
    "user_data": route_metric_cloud_init,
}, timeout=60)
```

Direct Nova payload reminders:
- Use flavor `baremetal` unless the site requires its UUID.
- Put `os:scheduler_hints: {"reservation": "<reservation-id>"}` at the top
  level, not inside `server`.
- Put networks under `server.networks` as `{"uuid": "<network-id>"}`.
- Base64-encode `server.user_data` when calling Nova directly. LoomAI REST does
  this for you when you pass plain cloud-init in `user_data`.

Bare-metal instances take 5-15 minutes to boot.

If any launched instance attaches to `fabnetv4`, include cloud-init/netplan
route-metric userdata. Apply this to FABNet-only single-NIC servers too. For
the recommended public-SSH layout, attach `sharednet1` for management and
floating-IP SSH plus `fabnetv4` for FABNet traffic; set the `sharednet1` DHCP
route metric to `50` and the `fabnetv4` DHCP route metric to `500`. Preserve
the FABNet `10.128.0.0/10` route. Common Ubuntu 22/24 interface names are
`eno1np0` for `sharednet1` and `eno2np1` for `fabnetv4`; verify with `ip link`.

### Step 4: Network Access
```bash
# Allocate a floating IP
loomai chameleon ips allocate --site CHI@TACC

# Associate with instance
loomai chameleon ips associate --site CHI@TACC --ip <ip> --instance <instance-id>

# Ensure SSH security group exists
loomai chameleon security-groups list --site CHI@TACC
```

LoomAI REST shortcuts:
```python
# Allocate and associate a floating IP to an instance in one backend call.
session.post(
    f"{BASE}/chameleon/instances/{instance_id}/associate-ip",
    json={"site": "CHI@TACC"},
    timeout=60,
)

# Add an SSH ingress rule to an existing security group.
session.post(f"{BASE}/chameleon/security-groups/{sg_id}/rules", json={
    "site": "CHI@TACC",
    "direction": "ingress",
    "ethertype": "IPv4",
    "protocol": "tcp",
    "port_range_min": 22,
    "port_range_max": 22,
    "remote_ip_prefix": "0.0.0.0/0",
}, timeout=60)
```

For exact Blazar/Nova/Neutron payload builders, search RAG for
`chameleon/openstack_api_patterns.py`.

### Step 5: Connect
```bash
ssh cc@<floating-ip>
```

In WebUI: right-click instance in topology → SSH

## Important Notes
- SSH username is `cc` for all standard Chameleon images
- FABNet-only Chameleon nodes may accept floating IPs at some sites, but for reliable public SSH plus FABNet dataplane connectivity, prefer `sharednet1 + fabnetv4` with explicit route metrics
- Leases have a maximum duration (typically 7 days, extendable)
- Always delete instances before deleting leases
- Use `--format json` for scripting with CLI commands
