name: manage-chameleon-slice
description: Create and manage Chameleon slices — LoomAI's grouping of bare-metal servers
---
Help the user manage Chameleon slices. A slice is a LoomAI concept that groups
Chameleon servers into a logical unit for managing together.

## Create a Chameleon Slice

### Option 1: Via WebUI
1. Switch to the Chameleon view
2. Click "New" in the Chameleon bar → name the slice
3. Add nodes in the editor: pick site, node type, image, NIC networks
4. Configure leases in the Leases tab: check existing leases or set duration for new one
5. Click Submit to deploy

### Option 2: Via CLI
```bash
# Create a draft
loomai chameleon drafts create --name my-experiment --site CHI@TACC

# Add nodes
loomai chameleon drafts add-node --id <draft-id> \
  --name node1 --type compute_haswell --image CC-Ubuntu22.04

loomai chameleon drafts add-node --id <draft-id> \
  --name node2 --type compute_haswell --image CC-Ubuntu22.04

# Deploy (creates lease + launches instances)
loomai chameleon drafts deploy --id <draft-id> --hours 4
```

### Option 3: Via Tool Calls
1. `create_chameleon_lease(site, name, node_type, count, hours)` — reserve nodes
2. Wait for lease ACTIVE: `list_chameleon_leases(site)` — check status
3. `create_chameleon_instance(site, lease_id, reservation_id, image, name)` — launch each
4. Associate floating IPs for SSH access (via CLI)

## Multi-NIC Configuration
Each bare-metal node typically has 2 NICs:
- **NIC 0** → `sharednet1` (external SSH via floating IP)
- **NIC 1** → `fabnetv4` (cross-testbed traffic to FABRIC) or experiment network

Configure per-NIC networks in the WebUI editor's Servers tab.

## SSH Access
```bash
# After floating IP is associated:
ssh cc@<floating-ip>

# Via LoomAI terminal: right-click instance in topology → SSH
```

## Slice Lifecycle
- **Draft** → **Deploying** → **Active** → **Delete**
- Extend leases before they expire: `loomai chameleon leases extend --site <site> --id <lease-id> --hours 24`
- Delete: removes instances and releases leases
