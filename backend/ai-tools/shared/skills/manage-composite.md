name: manage-composite
description: Compatibility alias for creating and managing Federated Slices
---
Help the user create and manage **Federated Slices**. "Composite Slice" is the
old compatibility name; use "Federated Slice" in user-facing answers.

## What Is a Federated Slice?
A meta-slice that references provider slices/resources and connection intent.
It provides:
- Unified topology view across facilities
- Immediate visibility of member/sub-slice state
- One-click parallel deployment of un-deployed members
- Cross-facility connectivity via FABNetv4 L3 or Facility Port L2
- A generic member model for future facilities

## Create a Federated Experiment

### Via WebUI (Recommended)
1. Enable Federated Slices view in Settings if it is hidden.
2. Switch to the "Federated Slice" view.
3. Click "New" and name the Federated Slice.
4. In the editor:
   - Check FABRIC slices to include as members
   - Check Chameleon slices to include as members
5. In the **FABRIC** tab: edit FABRIC members inline (add nodes, networks)
6. In the **Chameleon** tab: edit Chameleon members inline (add servers, configure NICs)
7. Click "Submit" → all member slices deploy in parallel

### Via CLI + Tools
1. Create a FABRIC slice with FABNetv4:
   ```
   create_slice("my-fabric", nodes=[...], networks=[{type: "FABNetv4", ...}])
   submit_slice("my-fabric")
   ```

2. Create Chameleon servers with a NIC on fabnetv4:
   ```
   create_chameleon_lease("CHI@TACC", "my-chameleon", "compute_haswell", 2, 8)
   # Wait for ACTIVE, then launch instances with fabnetv4 network and route-metric userdata
   ```

3. Group in Federated Slice via WebUI or `/api/federated/slices`

### Via REST API
```bash
FED_ID=$(
  curl -s -X POST http://localhost:8000/api/federated/slices \
    -H "Content-Type: application/json" \
    -d '{"name":"my-federated-exp"}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])'
)

curl -s -X PUT "http://localhost:8000/api/federated/slices/$FED_ID/members" \
  -H "Content-Type: application/json" \
  -d '{"members":[
    {"provider":"fabric","slice_id":"draft-or-uuid","name":"fabric-part"},
    {"provider":"chameleon","slice_id":"chi-slice-id","name":"chameleon-part"}
  ]}'
```

## Cross-Testbed Connectivity

### FABNetv4 (Standard Method)
Both FABRIC and Chameleon support FABNetv4 networks:
- FABRIC nodes: add FABNetv4 network → auto-assigned 10.128.x.x IP
- Chameleon nodes: connect a NIC to `fabnetv4` → gets FABNet IP
- All nodes on FABNet can reach each other via the FABRIC backbone

Apply route-metric cloud-init/netplan userdata to every Chameleon server that
uses `fabnetv4`, even FABNet-only single-NIC servers. For reliable public SSH
plus FABNet dataplane connectivity, prefer `sharednet1 + fabnetv4`:
- `sharednet1` / management / floating-IP SSH: DHCP route metric `50`
- `fabnetv4` / FABNet dataplane: DHCP route metric `500`
- Preserve the FABNet `10.128.0.0/10` route and verify with `ip route | grep 10.128`
- Common Ubuntu 22/24 names are `eno1np0` for `sharednet1` and `eno2np1` for `fabnetv4`; verify with `ip link`

FABNet-only Chameleon nodes may accept floating IPs at some sites, but for
reliable public SSH plus FABNet dataplane connectivity, prefer
`sharednet1 + fabnetv4` with explicit route metrics.

Connection intent:
```json
{
  "type": "fabnetv4_l3",
  "endpoint_a": {"provider": "fabric", "slice_id": "fabric-id", "node": "fabric-node"},
  "endpoint_b": {"provider": "chameleon", "slice_id": "chi-id", "node": "chi-node"}
}
```

### Facility Port L2
For VLAN-backed L2 connectivity, use `facility_port_l2` connection intent. Query
facility ports and VLAN availability before selecting a VLAN.

```json
{
  "type": "facility_port_l2",
  "facility_port": "Chameleon-TACC",
  "vlan": "3301",
  "fabric_site": "TACC",
  "chameleon_site": "CHI@TACC",
  "endpoint_a": {"provider": "fabric", "slice_id": "fabric-id", "node": "fabric-router"},
  "endpoint_b": {"provider": "chameleon", "slice_id": "chi-id", "node": "chi-router"}
}
```

## Weaves

Cross-facility weaves must create or update a Federated Slice entry when they
run. This is what makes the Federated Slice view show the experiment immediately
with provider sub-slice state.

Use one of two patterns:
- **Explicit pattern for new weaves**: create provider drafts/slices, call
  `/api/federated/slices`, add members, add connections, then submit/run.
- **Legacy backend-assisted pattern**: if a FABRIC draft has attached Chameleon
  nodes, `POST /api/slices/{slice_name}/submit-composite` now creates the
  Federated Slice entry automatically.

### Verify Connectivity
```bash
# From FABRIC VM:
ssh_execute("my-fabric", "node1", "ping -c 3 10.128.x.x")

# From Chameleon server:
ssh cc@<floating-ip> "ping -c 3 10.128.y.y"
```

## Design Guidelines
- **FABRIC for**: VMs, GPUs, SmartNICs, FPGAs, complex networking, quick iterations
- **Chameleon for**: Bare-metal access, specific hardware platforms, OS-level experiments
- **Both**: Use FABNetv4 on both sides for seamless connectivity
- **Future facilities**: use the generic `members` array; do not hard-code only FABRIC and Chameleon
- **Monitoring**: WebUI Federated Slice topology shows live state from all testbeds
