name: query-fabric
description: Query FABRIC for slices, sites, users, and project information
---
Query FABRIC infrastructure using the built-in FABlib tools.

**Determine what the user wants to query, then use the right tool:**

### Slices
- List your slices: `fabric_list_slices`
- Detailed slice info: `fabric_get_slice(slice_name)`
- Node details: `fabric_node_info(slice_name, node_name)`
- Wait for readiness: `fabric_wait_slice(slice_name)`

### Sites & Resources
- All sites with availability: `fabric_list_sites`
- Site details: `fabric_list_sites(site_name="STAR")`
- Per-host resources: `fabric_list_hosts(site_name)`
- Find sites with hardware: `fabric_find_sites(component="GPU_RTX6000")`
- Available images: `fabric_list_images`
- Component catalog: `fabric_list_components`

### Projects & Configuration
- Your projects: `fabric_list_projects`
- Switch project: `fabric_set_project(project_name)`
- View config: `fabric_get_config`
- Update config: `fabric_set_config(key, value)`

### SSH & Files
- Run command on node: `fabric_slice_ssh(slice_name, node_name, command)`
- Upload file: `fabric_upload_file(slice_name, node_name, local, remote)`
- Download file: `fabric_download_file(slice_name, node_name, remote, local)`

**Format results** clearly: use tables for lists, highlight important fields
(state, IPs, availability). If results are empty, explain possible reasons
(wrong project, no active slices, token expired).

**Note:** For advanced queries (facility ports, backbone links, user/project
lookups), write a Python script using `FablibManager()`. For FABRIC-wide
usage statistics, the Reports API exists but requires staff/admin permissions.
