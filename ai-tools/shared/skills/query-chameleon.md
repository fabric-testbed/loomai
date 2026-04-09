---
name: query-chameleon
description: Browse Chameleon Cloud sites, leases, instances, and images
---

Help the user query Chameleon Cloud resources.

## Chameleon Sites
- CHI@TACC (Austin, TX) — bare-metal compute, GPUs
- CHI@UC (Chicago, IL) — bare-metal compute, GPUs
- CHI@Edge (Chicago, IL) — edge computing nodes
- KVM@TACC (Austin, TX) — KVM virtual machines

## Common Queries

**List leases:**
```
loomai chameleon leases list
loomai chameleon leases list --site CHI@TACC
```

**List instances:**
```
loomai chameleon instances list
```

**Browse sites:**
```
loomai chameleon sites
loomai chameleon sites CHI@TACC
```

**List images:**
```
loomai chameleon images CHI@TACC
```

**Test connection:**
```
loomai chameleon test
```

## Tool Calls (LoomAI assistant)
- `list_chameleon_leases` — all leases or filtered by site
- `list_chameleon_instances` — running instances
- `list_chameleon_sites` — site list with config status
- `chameleon_site_images` — OS images at a site

## Key Differences from FABRIC
- Chameleon uses **leases** (time-bounded reservations) instead of slices
- Must create a lease first, then launch instances on it
- Bare-metal nodes (not VMs) — full hardware access
- Each site has its own Keystone auth and API endpoints
