name: sites
description: Query FABRIC site information, resource availability, and find sites with specific hardware
---
Help the user find FABRIC sites with available resources. Always use tools for
live data — never rely on hardcoded site lists (hardware changes frequently).

## Tools

1. **List all sites**: `fabric_list_sites` — every site with cores/RAM/disk availability,
   state, and special components (GPUs, FPGAs, SmartNICs, NVMe).

2. **Site details**: `fabric_list_sites(site_name="STAR")` — detailed info
   including per-host breakdown.

3. **Per-host resources**: `fabric_list_hosts(site_name="STAR")` — individual host machines.

4. **Find by hardware**: `fabric_find_sites(component="GPU_A40")` — sites with
   specific components and minimum resources.

5. **Available images**: `fabric_list_images` — all VM images with default users.

6. **Component catalog**: `fabric_list_components` — all NIC, GPU, FPGA, NVMe models.

## Recommendations

Based on the user's needs:
- **Most capacity**: Sort `fabric_list_sites` by `cores_available` descending.
- **GPUs**: `fabric_find_sites(component="GPU_A40")` (or GPU_RTX6000, GPU_TeslaT4, GPU_A30).
- **FPGAs**: `fabric_find_sites(component="FPGA_Xilinx_U280")`.
- **High bandwidth**: Look for sites with ConnectX-6/7 SmartNICs.
- **Co-location**: Nodes needing low latency should be at the same site (use `@group` tags).
- **Geographic diversity**: For wide-area experiments, pick sites in different regions.
- **Cross-site L3**: Use FABNetv4 or `fabnet: "v4"` for easy routing between sites.

## Tips

- Use `"auto"` for site selection unless the user has a preference — picks the best available.
- Always check availability before creating GPU/FPGA slices — inventory is limited.
- Some sites may be in maintenance — `fabric_list_sites` shows site state.
