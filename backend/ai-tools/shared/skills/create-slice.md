name: create-slice
description: Create a new FABRIC slice — from a weave, custom spec, or saved topology
---
Create a new FABRIC slice. There are multiple approaches:

## Option 1: From a Weave

If the user wants a pre-built topology:

1. `list_templates` — show available weaves
2. `load_template(template_name, slice_name)` — create the draft
3. Show the preview (nodes, sites, resources, networks)
4. Confirm with user, then `submit_slice(slice_name)` to deploy

## Option 2: Custom Specification

If the user describes a custom topology:

1. **Understand the request**: How many nodes? What topology? Resources? GPUs? Networks?

2. **Check resources**: `query_sites` to find sites with required hardware,
   or `query_sites` for a full overview.

3. **Create the draft**: `create_slice(slice_name, nodes, networks)` with full specs.

4. **Confirm**: Show the user what will be created. If they approve:
   `submit_slice(slice_name, wait=true)` for small slices (1-3 nodes),
   `wait=false` for larger ones.

5. **Verify**: `get_slice` or `refresh_slice` to confirm provisioning.

## Option 3: Easy L3 Networking with fabnet

For simple cross-site IP connectivity, use the `fabnet` shorthand on each node:

```
create_slice(
  slice_name="my-l3-slice",
  nodes=[
    {name: "node1", site: "STAR", fabnet: "v4"},
    {name: "node2", site: "TACC", fabnet: "v4"}
  ]
)
```

This auto-assigns IPv4 addresses and routes. No manual network definition needed.

## Node Spec Fields

| Field | Default | Description |
|-------|---------|-------------|
| name | required | Unique node name |
| site | "auto" | Site name, "auto", or "@group" tag for co-location |
| cores | 2 | CPU cores (1-128) |
| ram | 8 | RAM in GB (2-512) |
| disk | 10 | Disk in GB (10-500) |
| image | default_ubuntu_22 | VM image (use `list_images` for full list) |
| nic_model | NIC_Basic | NIC type for network connections |
| components | [] | Extra hardware: `[{model: "GPU_A40", name: "gpu1"}]` |
| fabnet | (none) | "v4", "v6", or "both" for auto L3 networking |
| post_boot_commands | [] | Shell commands to run after boot |

## Network Spec Fields (for `create_slice` tool)

| Field | Default | Description |
|-------|---------|-------------|
| name | required | Network name |
| type | L2Bridge | L2Bridge, L2STS, L2PTP, FABNetv4, FABNetv6, FABNetv4Ext, FABNetv6Ext |
| interfaces | required | List of **node names** to connect (tool auto-wires NICs) |
| subnet | (auto) | Optional CIDR for L2 networks (e.g. "192.168.1.0/24") |

**Note:** The `create_slice` tool takes simple node names in `interfaces`
and auto-creates NICs. When writing weave topology files directly, you
must define NIC components on each node and use the full interface naming pattern:
`{node-name}-{component-name}-p{port}` (e.g., `node1-nic1-p1`). See AGENTS.md
"Wiring Nodes to Networks" for details.

## Component Models

**NICs:** NIC_Basic, NIC_ConnectX_5, NIC_ConnectX_6, NIC_ConnectX_7_100, NIC_ConnectX_7_400, NIC_BlueField_2_ConnectX_6
**GPUs:** GPU_RTX6000, GPU_TeslaT4, GPU_A30, GPU_A40
**FPGAs:** FPGA_Xilinx_U280, FPGA_Xilinx_SN1022
**Storage:** NVME_P4510

## Draft Storage

Drafts created by `create_slice` or `load_template` are
automatically saved to `/home/fabric/work/my_slices/` and registered in the web UI.
They appear as "Draft" state in the slice selector and slice table after the
next refresh. Users can review, edit, or submit them from the web UI.

**Note:** For reusable topologies, create a weave instead (`/create-weave`).
Weaves can be run from the Artifacts panel with one click.

## Tips

- Use "auto" for sites unless the user specifies — picks the best available
- Use FABNetv4 or `fabnet: "v4"` for cross-site IP connectivity (simplest)
- Use L2Bridge for same-site Layer 2
- Use L2STS for cross-site Layer 2
- L2PTP is for exactly 2 interfaces (point-to-point)
- Minimum practical node: 2 cores, 4GB RAM, 10GB disk
- For GPU nodes: check availability first with `query_sites(component="GPU_A40")`
- Always confirm with the user before submitting — it allocates real resources

## CLI Equivalent

```bash
loomai slices create my-exp
loomai nodes add my-exp node1 --site auto --cores 4 --ram 16 --disk 50
loomai nodes add my-exp node2 --site auto --cores 4 --ram 16 --disk 50
loomai components add my-exp node1 nic1 --model NIC_Basic
loomai components add my-exp node2 nic1 --model NIC_Basic
loomai networks add my-exp net1 --type L2Bridge -i node1-nic1-p1,node2-nic1-p1
loomai slices validate my-exp
loomai slices submit my-exp --wait --timeout 600
```
