name: interact-slice
description: SSH to nodes, run commands, and transfer files on a running FABRIC slice
---
Help the user interact with nodes on a running FABRIC slice.

1. **Find the slice and node**:
   - If not specified: `list_slices` → pick the active one
   - `get_slice(slice_name)` — verify StableOK, list nodes with IPs
   - `get_slice(slice_name, node_name)` — get SSH command, management IP, components

2. **Run commands**:
   - `ssh_execute(slice_name, node_name, "command")` — execute on the node
   - For long commands, consider uploading a script instead
   - Use `sudo` for system operations

3. **Transfer files**:
   - Upload: `write_vm_file(slice_name, node_name, local_path, remote_path)`
   - Download: `read_vm_file(slice_name, node_name, remote_path, local_path)`
   - Local files live in `/home/fabric/work/` (persistent container storage)

4. **Common tasks**:
   - Check node health: `ssh_execute(s, n, "uptime && free -h && df -h")`
   - Check networking: `ssh_execute(s, n, "ip addr show && ip route show")`
   - Install software: `ssh_execute(s, n, "sudo apt-get update && sudo apt-get install -y <pkg>")`
   - Check GPU: `ssh_execute(s, n, "nvidia-smi")`
   - Run a script: upload it, then `ssh_execute(s, n, "chmod +x script.sh && ./script.sh")`

5. **Multi-node operations**:
   - Loop over nodes: get node list from `get_slice`, run same command on each
   - For complex orchestration, write a Python script using FABlib directly

**Errors:**
- SSH connection refused → node may still be booting; check state is StableOK
- Permission denied → SSH key mismatch; check config with `get_config`
- Command timeout → long-running command; consider running in background with `nohup`

## CLI Equivalent

```bash
loomai ssh my-exp node1 -- hostname               # Single command
loomai exec my-exp "apt update" --all --parallel  # All nodes in parallel
loomai exec my-exp "df -h" --nodes node1,node2    # Specific nodes
loomai scp my-exp node1 ./setup.sh /tmp/setup.sh  # Upload file
loomai scp my-exp node1 --download /tmp/out.csv ./out.csv  # Download
loomai scp my-exp ./config.sh /tmp/ --all --parallel  # Upload to all
```
