---
id: query-chameleon
name: query-chameleon
asset_type: skill
audience: end-user
description: Browse Chameleon Cloud sites, leases, instances, and images
domains:
  - chameleon
  - openstack
tools:
  - loomai
  - claude-code
  - opencode
  - crush
  - deepagents
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

## API Query Patterns

Prefer built-in tools for simple questions. When writing scripts or weaves, use
LoomAI REST so the script inherits the user's configured Chameleon auth:

```python
import os
import requests

BASE = os.environ.get("LOOMAI_API_URL") or os.environ.get("LOOMAI_URL") or "http://127.0.0.1:8000/api"
BASE = BASE.rstrip("/") if BASE.rstrip("/").endswith("/api") else BASE.rstrip("/") + "/api"
session = requests.Session()
if os.environ.get("LOOMAI_SESSION_COOKIE"):
    session.cookies.set("loomai_session", os.environ["LOOMAI_SESSION_COOKIE"])
site = "CHI@TACC"

leases = session.get(f"{BASE}/chameleon/leases", params={"site": site}, timeout=30).json()
instances = session.get(f"{BASE}/chameleon/instances", params={"site": site}, timeout=30).json()
networks = session.get(f"{BASE}/chameleon/networks", params={"site": site}, timeout=30).json()
images = session.get(f"{BASE}/chameleon/images/{site}", timeout=30).json()
```

For backend-owned code only, use the authenticated OpenStack session:

```python
from app.chameleon_manager import get_session

session = get_session("CHI@TACC")
leases = session.api_get("reservation", "/leases")
servers = session.api_get("compute", "/servers/detail")
networks = session.api_get("network", "/v2.0/networks")
images = session.api_get("image", "/v2/images?limit=20")
```

Search the RAG example `chameleon/openstack_api_patterns.py` for exact payloads
before writing direct Blazar, Nova, or Neutron API code.

## Key Differences from FABRIC
- Chameleon uses **leases** (time-bounded reservations) instead of slices
- Must create a lease first, then launch instances on it
- Bare-metal nodes (not VMs) — full hardware access
- Each site has its own Keystone auth and API endpoints
