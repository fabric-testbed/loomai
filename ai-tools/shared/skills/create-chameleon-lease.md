---
name: create-chameleon-lease
description: Create and manage Chameleon Cloud leases and instances
---

Help the user create Chameleon leases and launch instances.

## Workflow
1. **Create a lease** — reserve bare-metal nodes for a time window
2. **Launch instances** — deploy OS images on reserved nodes
3. **Connect** — SSH to instances via floating IP
4. **Clean up** — delete instances and lease when done

## Create a Lease

```
loomai chameleon leases create \
  --site CHI@TACC \
  --name my-experiment \
  --type compute_haswell \
  --count 2 \
  --hours 4
```

Common node types:
- `compute_haswell` — Intel Haswell compute nodes
- `compute_skylake` — Intel Skylake compute nodes
- `gpu_p100` — NVIDIA P100 GPU nodes
- `gpu_v100` — NVIDIA V100 GPU nodes
- `gpu_rtx_6000` — NVIDIA RTX 6000 GPU nodes
- `storage` — Storage nodes with large disks
- `fpga` — FPGA nodes

## Launch an Instance

```
loomai chameleon instances create \
  --site CHI@TACC \
  --lease <lease-id> \
  --reservation <reservation-id> \
  --image CC-Ubuntu22.04 \
  --name my-instance
```

Common images: `CC-Ubuntu22.04`, `CC-Ubuntu20.04`, `CC-CentOS8-Stream`

## Tool Calls (LoomAI assistant)
- `create_chameleon_lease` — create a lease with site, name, node_type, count, hours
- `create_chameleon_instance` — launch an instance on a lease
- `delete_chameleon_lease` — delete a lease
- `delete_chameleon_instance` — terminate an instance

## Important Notes
- Leases have a maximum duration (usually 7 days, extendable)
- Active leases consume your project's allocation
- Always delete instances before deleting the lease
- Floating IPs must be associated for external SSH access
