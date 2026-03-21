name: interact-slice
description: SSH to nodes, run commands, and transfer files on a running FABRIC slice
---
Help the user interact with nodes on a running FABRIC slice.

1. **Find the slice and node**:
   - If not specified: `fabric_list_slices` → pick the active one
   - `fabric_get_slice(slice_name)` — verify StableOK, list nodes with IPs
   - `fabric_node_info(slice_name, node_name)` — get SSH command, management IP, components

2. **Run commands**:
   - `fabric_slice_ssh(slice_name, node_name, "command")` — execute on the node
   - For long commands, consider uploading a script instead
   - Use `sudo` for system operations

3. **Transfer files**:
   - Upload: `fabric_upload_file(slice_name, node_name, local_path, remote_path)`
   - Download: `fabric_download_file(slice_name, node_name, remote_path, local_path)`
   - Local files live in `/home/fabric/work/` (persistent container storage)

4. **Common tasks**:
   - Check node health: `fabric_slice_ssh(s, n, "uptime && free -h && df -h")`
   - Check networking: `fabric_slice_ssh(s, n, "ip addr show && ip route show")`
   - Install software: `fabric_slice_ssh(s, n, "sudo apt-get update && sudo apt-get install -y <pkg>")`
   - Check GPU: `fabric_slice_ssh(s, n, "nvidia-smi")`
   - Run a script: upload it, then `fabric_slice_ssh(s, n, "chmod +x script.sh && ./script.sh")`

5. **Multi-node operations**:
   - Loop over nodes: get node list from `fabric_get_slice`, run same command on each
   - For complex orchestration, write a Python script using FABlib directly

**Errors:**
- SSH connection refused → node may still be booting; check state is StableOK
- Permission denied → SSH key mismatch; check config with `fabric_get_config`
- Command timeout → long-running command; consider running in background with `nohup`
