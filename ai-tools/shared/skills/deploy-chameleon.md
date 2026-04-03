name: deploy-chameleon
description: Deploy a Chameleon experiment — lease, instances, networking, and SSH access
---
Guide the user through deploying a complete Chameleon experiment with SSH access.

## Full Deploy Workflow

### Step 1: Choose Site and Hardware
```bash
# List available sites
loomai chameleon sites

# Check node types at a site
loomai chameleon sites CHI@TACC

# Check images
loomai chameleon images CHI@TACC
```

Or use tools: `list_chameleon_sites`, `chameleon_site_images(site)`

### Step 2: Create Lease
```bash
loomai chameleon leases create \
  --site CHI@TACC \
  --name my-experiment \
  --type compute_haswell \
  --count 2 \
  --hours 8
```

Or: `create_chameleon_lease("CHI@TACC", "my-experiment", "compute_haswell", 2, 8)`

Wait for ACTIVE: `list_chameleon_leases("CHI@TACC")` — check status field.
Bare-metal leases take 1-5 minutes to become ACTIVE.

### Step 3: Launch Instances
Get the reservation ID from the lease, then:
```bash
loomai chameleon instances create \
  --site CHI@TACC \
  --lease <lease-id> \
  --reservation <reservation-id> \
  --image CC-Ubuntu22.04 \
  --name node1
```

Or: `create_chameleon_instance("CHI@TACC", lease_id, reservation_id, "CC-Ubuntu22.04", "node1")`

Bare-metal instances take 5-15 minutes to boot.

### Step 4: Network Access
```bash
# Allocate a floating IP
loomai chameleon ips allocate --site CHI@TACC

# Associate with instance
loomai chameleon ips associate --site CHI@TACC --ip <ip> --instance <instance-id>

# Ensure SSH security group exists
loomai chameleon security-groups list --site CHI@TACC
```

### Step 5: Connect
```bash
ssh cc@<floating-ip>
```

In WebUI: right-click instance in topology → SSH

## Important Notes
- SSH username is `cc` for all standard Chameleon images
- Leases have a maximum duration (typically 7 days, extendable)
- Always delete instances before deleting leases
- Use `--format json` for scripting with CLI commands
