name: extend-loomai-federation
description: Add or modify Federated Slice, FABRIC/Chameleon, FABNetv4, facility-port, or cross-provider behavior
---
Use this skill for Federated Slice features, cross-testbed weaves, member
management, FABNetv4 L3, facility-port L2, and future provider integration.

## Rules

- A Federated Slice is a grouping of provider slices. Empty groups are valid.
- Existing FABRIC and Chameleon slices can be attached.
- Multiple FABRIC and multiple Chameleon slices can be attached.
- Removing a member detaches it from the Federated Slice. It must not delete
  the provider slice unless the endpoint and user intent explicitly request it.
- Prefer generic `members` over provider-specific logic when possible.

## Implementation Path

1. Backend: inspect `backend/app/routes/composite.py`.
2. Frontend: inspect `frontend/src/App.tsx`, `CompositeEditorPanel`, and
   `frontend/src/api/client.ts`.
3. Tests:
   - API: empty create, add several members, remove one, graph still loads.
   - UI: Draft federated slice visible, expanded row shows members/resources.
4. Network-specific:
   - FABNetv4: require Chameleon route metrics for every `fabnetv4` server.
   - Facility port L2: show external facility port/VLAN object linked to provider networks.
5. Validate with `npm --prefix frontend run build` and focused backend checks.
