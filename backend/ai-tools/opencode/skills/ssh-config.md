name: ssh-config
description: Configure and troubleshoot SSH access to FABRIC slice VMs
---
Help the user configure or troubleshoot SSH access to FABRIC VMs.

## Quick Access (Recommended)

Use the built-in tool — no manual SSH config needed:
- `fabric_node_info(slice_name, node_name)` — returns the full SSH command, management IP, and username.
- `fabric_slice_ssh(slice_name, node_name, command)` — run commands directly.

## SSH Architecture

All FABRIC VMs are behind a bastion host. SSH connections proxy through it:
```
You -> bastion-1.fabric-testbed.net -> VM management IP
```

## Config Files

Located in `/home/fabric/work/fabric_config/`:
- `fabric_bastion_key` — SSH key for the bastion host
- `ssh_config` — SSH config with ProxyJump through bastion
- `slice_keys/default/slice_key` — Private key for slice VMs
- `slice_keys/default/slice_key.pub` — Public key for slice VMs

## ssh_config Content

The ssh_config should look like:
```
Host bastion-1.fabric-testbed.net
    User <bastion_username>
    IdentityFile /home/fabric/work/fabric_config/fabric_bastion_key
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null

Host 10.* 192.168.* 2001:*
    ProxyJump bastion-1.fabric-testbed.net
    IdentityFile /home/fabric/work/fabric_config/slice_keys/default/slice_key
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
```

## Manual SSH Command

```bash
ssh -F /home/fabric/work/fabric_config/ssh_config \
    -i /home/fabric/work/fabric_config/slice_keys/default/slice_key \
    <user>@<management_ip>
```

Where `<user>` depends on the image (ubuntu, rocky, debian, etc.) and `<management_ip>` comes from `fabric_node_info`.

## Generate New Slice Keys

```bash
mkdir -p /home/fabric/work/fabric_config/slice_keys/default
ssh-keygen -t rsa -b 3072 -f /home/fabric/work/fabric_config/slice_keys/default/slice_key -N "" -C "fabric-slice-key"
```

## Common Issues

- **Permission denied**: `chmod 600` on both bastion key and slice key.
- **Connection timeout**: Check slice is StableOK, VM may still be booting.
- **Host key changed**: The `StrictHostKeyChecking no` in ssh_config prevents this.
- **Wrong user**: Ubuntu images use `ubuntu`, Rocky uses `rocky`, Debian uses `debian`. Check with `fabric_node_info`.
