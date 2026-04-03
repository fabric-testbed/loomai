name: query-fabric
description: Query FABRIC for slices, sites, users, and project information
---
Query FABRIC infrastructure using the built-in FABlib tools.

**Determine what the user wants to query, then use the right tool:**

### Slices
- List your slices: `list_slices`
- Detailed slice info: `get_slice(slice_name)`
- Node details: `get_slice(slice_name, node_name)`
- Wait for readiness: `refresh_slice(slice_name)`

### Sites & Resources
- All sites with availability: `query_sites`
- Site details: `query_sites(site_name="STAR")`
- Per-host resources: `get_site_hosts(site_name)`
- Find sites with hardware: `query_sites(component="GPU_RTX6000")`
- Available images: `list_images`
- Component catalog: `list_component_models`

### Projects & Configuration
- Your projects: `list_projects`
- Switch project: `switch_project(project_name)`
- View config: `get_config`
- Update config: `update_settings(key, value)`

### SSH & Files
- Run command on node: `ssh_execute(slice_name, node_name, command)`
- Upload file: `write_vm_file(slice_name, node_name, local, remote)`
- Download file: `read_vm_file(slice_name, node_name, remote, local)`

**Format results** clearly: use tables for lists, highlight important fields
(state, IPs, availability). If results are empty, explain possible reasons
(wrong project, no active slices, token expired).

**Note:** For advanced queries (facility ports, backbone links, user/project
lookups), write a Python script using `FablibManager()`. For FABRIC-wide
usage statistics, the Reports API exists but requires staff/admin permissions.

## CLI Equivalent

```bash
loomai sites list --available                     # Active sites
loomai sites find --cores 8 --ram 32 --gpu GPU_RTX6000  # Find matching
loomai sites hosts RENC                           # Per-host availability
loomai images                                     # VM images
loomai component-models                           # NICs, GPUs, FPGAs
loomai slices list                                # All slices
loomai --format json slices show my-exp           # Slice detail as JSON
```
