name: modify-slice
description: Add or remove nodes, networks, and components on a running FABRIC slice
---
Modify a running FABRIC slice. Always get the current topology first.

1. **Get current state**:
   - `fabric_get_slice(slice_name)` — verify state is StableOK or ModifyOK
   - If not StableOK, warn the user and explain the current state

2. **Plan modifications** based on user request:
   - **Add node**: `fabric_modify_slice(slice_name, add_nodes=[{name, site, cores, ram, disk, image, components}])`
   - **Remove node**: `fabric_modify_slice(slice_name, remove_nodes=["node-name"])`
   - **Add network**: `fabric_modify_slice(slice_name, add_networks=[{name, type, interfaces}])`
   - **Remove network**: `fabric_modify_slice(slice_name, remove_networks=["net-name"])`
   - **Add component**: Use `fabric_modify_slice` with node updates

3. **Confirm with user** before submitting:
   - Show what will be added/removed
   - Warn: modifications allocate/release real resources

4. **Submit and verify**:
   - After modify, state transitions: StableOK → ModifyOK → Configuring → StableOK
   - `fabric_get_slice(slice_name)` — check new nodes are up, networks connected
   - If new nodes added, they may need boot config / software installation

**Common patterns:**
- Scale out: add worker nodes to an existing cluster
- Add monitoring: add a NIC + FABNetv4 network to enable cross-node communication
- Replace failed node: remove the broken node, add a fresh one

**Errors:**
- "No resources available" → try a different site, or reduce resource request
- ModifyError → check `fabric_get_slice` for which slivers failed
- Can't modify a slice in Configuring state — wait for it to stabilize first
