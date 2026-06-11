name: manage-federated-slice
description: Create and manage Federated Slices spanning FABRIC, Chameleon, and future facilities
---
Use this skill when the user asks for a Federated Slice, cross-testbed slice,
cross-facility experiment, FABRIC+Chameleon experiment, FABNetv4 Chameleon
experiment, facility-port L2 connection, or a weave that should show up in the
Federated Slice view.

## Concept

A Federated Slice is a LoomAI meta-slice. It groups provider slices/resources
and cross-facility connection intent. It currently supports FABRIC and
Chameleon, and the member schema is intentionally generic for future facilities:

```json
{
  "members": [
    {"provider": "fabric", "slice_id": "draft-or-uuid", "name": "fabric-part"},
    {"provider": "chameleon", "slice_id": "chi-slice-id", "name": "chi-part"}
  ]
}
```

The old "Composite Slice" name is a compatibility alias. Use "Federated Slice"
in user-facing text.

## Recommended Workflow

1. Create provider resources first:
   - FABRIC: create a FABRIC draft/slice with the needed nodes and networks.
   - Chameleon: create a LoomAI Chameleon slice/draft with servers, networks,
     reservations, and floating IP intent.
2. Create the Federated Slice:
   ```bash
   curl -s -X POST http://localhost:8000/api/federated/slices \
     -H "Content-Type: application/json" \
     -d '{"name":"my-federated-exp"}'
   ```
3. Add provider members:
   ```bash
   curl -s -X PUT http://localhost:8000/api/federated/slices/$FED_ID/members \
     -H "Content-Type: application/json" \
     -d '{"members":[
       {"provider":"fabric","slice_id":"draft-or-uuid","name":"fabric-part"},
       {"provider":"chameleon","slice_id":"chi-slice-id","name":"chameleon-part"}
     ]}'
   ```
4. Add connection intent:
   - L3 FABNetv4: `type: "fabnetv4_l3"`
   - L2 facility port/VLAN: `type: "facility_port_l2"`
5. Fetch the connection plan and graph:
   ```bash
   curl -s http://localhost:8000/api/federated/slices/$FED_ID/connection-plan
   curl -s http://localhost:8000/api/federated/slices/$FED_ID/graph
   ```
6. Submit only when the user explicitly asks to run/deploy:
   ```bash
   curl -s -X POST http://localhost:8000/api/federated/slices/$FED_ID/submit \
     -H "Content-Type: application/json" \
     -d '{"lease_hours":24}'
   ```

## FABNetv4 L3 Connection

Use this for routed IP connectivity between FABRIC and Chameleon:

```json
{
  "type": "fabnetv4_l3",
  "endpoint_a": {
    "provider": "fabric",
    "slice_id": "fabric-slice-id",
    "node": "fabric-node"
  },
  "endpoint_b": {
    "provider": "chameleon",
    "slice_id": "chi-slice-id",
    "node": "chi-node"
  }
}
```

Rules:
- FABRIC nodes need FABNetv4.
- Chameleon servers need a NIC on `fabnetv4`.
- Every Chameleon server attached to `fabnetv4` needs route-metric cloud-init,
  even FABNet-only or single-NIC servers.
- For reliable public SSH, prefer `sharednet1 + fabnetv4`, with `sharednet1`
  metric `50` and `fabnetv4` metric `500`.
- Preserve `10.128.0.0/10`.

## Facility Port L2 Connection

Use this for VLAN-backed Layer 2 connectivity through facility ports:

```json
{
  "type": "facility_port_l2",
  "vlan": "3301",
  "facility_port": "Chameleon-TACC",
  "fabric_site": "TACC",
  "chameleon_site": "CHI@TACC",
  "endpoint_a": {
    "provider": "fabric",
    "slice_id": "fabric-slice-id",
    "node": "fabric-router"
  },
  "endpoint_b": {
    "provider": "chameleon",
    "slice_id": "chi-slice-id",
    "node": "chi-router"
  }
}
```

Before choosing a VLAN, query the facility port APIs or use the WebUI selectors.

## Weave Requirement

Cross-facility weaves must create or update a Federated Slice entry when they
run. The UI should show the Federated Slice immediately with sub-slice states.

Two valid patterns:
- **Backend-assisted legacy pattern**: a FABRIC draft with attached Chameleon
  nodes calls `/api/slices/{slice_name}/submit-composite`. LoomAI creates the
  Federated Slice entry automatically.
- **Explicit pattern for new weaves**: the weave script calls the
  `/api/federated/slices` APIs directly after creating provider drafts/slices.

Prefer the explicit pattern for new weaves because it supports future providers.

## Cleanup

Deleting a Federated Slice normally removes the grouping only. Provider slices
or Chameleon resources remain unless a weave `stop()` function or a user action
explicitly deletes them.
