name: deploy-slice
description: Submit a draft slice for provisioning on FABRIC
---
Deploy a FABRIC slice — submit a draft (from template or custom) for provisioning.

## Steps

1. **Find or create the draft**:
   - If the user wants a template: `fabric_list_templates`, then
     `fabric_create_from_template(template_name, slice_name)`.
   - If a draft already exists: `fabric_get_slice(slice_name)` to verify.
   - If custom: use `/create-slice` first.

2. **Show the draft**: Report nodes, sites, components, networks.
   Ask the user to confirm before submitting.

3. **Submit**:
   - <=3 nodes: `fabric_submit_slice(slice_name, wait=true)` — blocks until ready.
   - >3 nodes: `fabric_submit_slice(slice_name, wait=false)` — returns immediately.

4. **Wait & verify**:
   - For `wait=false`: `fabric_wait_slice(slice_name)` or poll with `fabric_get_slice`.
   - State transitions: Configuring -> StableOK (ready) or StableError (failed).

5. **After StableOK — run boot configs**:
   - `fabric_node_info(slice_name, node_name)` — get SSH commands, IPs.
   - `fabric_slice_ssh(slice_name, node_name, command)` — run setup commands.
   - Upload files: `fabric_upload_file(slice_name, node_name, local, remote)`.

## Error Handling

- **StableError**: `fabric_get_slice` shows error details per node. Common causes:
  - Site capacity exhausted — try different site or reduce resources.
  - Token expired — user must refresh in Configure view.
  - Quota exceeded — reduce resources or contact project admin.
- **Timeout**: Large slices (5+ nodes) can take 10-15 min. Use `fabric_wait_slice(timeout=900)`.
- **Partial failure**: Some nodes OK, others failed. Delete and recreate, or modify the slice.

## Lease Duration

- Default lease: 24 hours from submission.
- Renew: `fabric_renew_slice(slice_name, days=7)` (max depends on project allocation).
- Slices are automatically deleted when the lease expires.

## Tips

- Always show the draft before submitting — it allocates real resources.
- If site is "auto", mention which sites were auto-selected.
- For GPU/FPGA nodes, verify availability first with `fabric_find_sites`.
- After deployment, suggest `/ssh-config` if the user needs manual SSH access.
