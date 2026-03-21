name: debug
description: Debug common FABRIC issues — symptom-based troubleshooting flowchart
---
Debug FABRIC issues. Start by identifying the symptom, then follow the flowchart.

## Symptom: Slice stuck in Configuring / won't reach StableOK

1. `fabric_get_slice(slice_name)` — check per-node state and error messages.
2. If "InsufficientResources": site is full. Delete, pick different site, recreate.
3. If token error: user must refresh token in the Configure view.
4. If still Configuring after 15 min: `fabric_wait_slice(slice_name, timeout=900)`.

## Symptom: Can't SSH to a node

1. Check slice state: `fabric_get_slice(slice_name)` — must be StableOK.
2. `fabric_node_info(slice_name, node_name)` — get the SSH command and management IP.
3. Try: `fabric_slice_ssh(slice_name, node_name, "hostname")`.
4. If timeout: node may still be booting. Wait 2-3 min and retry.
5. Check bastion key: `ls -la /home/fabric/work/fabric_config/fabric_bastion_key`.
6. Check key permissions: `chmod 600` on bastion key and slice keys.
7. Check ssh_config has correct bastion ProxyJump (see `/ssh-config`).

## Symptom: Nodes can't communicate (network issues)

1. `fabric_slice_ssh(slice_name, node_name, "ip addr show")` — verify interfaces are up.
2. `fabric_slice_ssh(slice_name, node_name, "ip route show")` — check routing table.
3. **FABNetv4**: Must have route `10.128.0.0/10`. If missing:
   ```
   sudo ip route add 10.128.0.0/10 via <gateway> dev <interface>
   ```
   Gateway is the FABNetv4 interface's gateway (from `fabric_node_info`).
4. **L2 networks**: Check both endpoints have IPs in the same subnet.
5. **Cross-site L2STS**: Verify nodes are at different sites.

## Symptom: Boot config / setup script failed

1. SSH to the node: `fabric_slice_ssh(slice_name, node_name, "ls -la ~/tools/")`.
2. Check if script ran: `fabric_slice_ssh(slice_name, node_name, "ls -la ~/tools/")`.
3. Check output: `fabric_slice_ssh(slice_name, node_name, "cat /tmp/setup.log")`.
4. Common causes: missing packages, network not yet configured, wrong OS assumptions.
5. Fix the script and re-run: `fabric_slice_ssh(slice_name, node_name, "bash ~/tools/setup.sh")`.

## Symptom: Token / auth errors

1. Token expires every ~1 hour. Direct user to Configure view to refresh.
2. Check token: `ls -la ~/.tokens.json /home/fabric/work/fabric_config/id_token.json`.
   Primary location is `~/.tokens.json`; `fabric_config/id_token.json` is the FABlib fallback.
3. After refresh, retry the failed operation.

## Diagnostic Commands (run via fabric_slice_ssh)

```
ip addr show        # Interfaces and IPs
ip route show       # Routing table
ping -c 3 <target>  # Connectivity
df -h               # Disk usage
free -h             # Memory usage
dmesg | tail -20    # Kernel messages
```
