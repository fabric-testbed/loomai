---
id: query-sphere
name: query-sphere
asset_type: skill
audience: end-user
description: Browse SPHERE/MergeTB projects, experiments, realizations, materializations, XDCs, and inventory
domains:
  - sphere
  - mergetb
tools:
  - loomai
  - claude-code
  - opencode
  - crush
  - deepagents
---

Help the user query SPHERE (MergeTB) testbed resources. SPHERE is a
security-research testbed: experiments are defined as `mergexp` Python models,
reserved via **realize**, and powered on via **materialize**.

## Naming
Everything is dotted and right-anchored to the project:
- Experiment: `<exp>.<proj>` — Realization: `<rname>.<exp>.<proj>` — XDC: `<xdc>.<proj>`
- In API/CLI calls pass the **bare** names (`^[a-z][a-z0-9]{0,62}$`), never the qualified form.

## Common Queries

**Status / configuration:**
```
loomai sphere status
loomai sphere projects
```

**Experiments and realizations:**
```
loomai sphere experiments
loomai sphere realizations
loomai sphere realization <experiment> <realization>
loomai sphere graph <experiment> <realization>       # Cytoscape topology JSON
```

**Materialization status (is my experiment up?):**
```
loomai sphere materialization <experiment> <realization>
```
Poll until `taskSummary.HighestStatus == "Success"` — that means nodes are
imaged, wired, and reachable.

**XDCs (jump containers for node access):**
```
loomai sphere xdc list
```

## Tool Calls (LoomAI assistant)
- `sphere_status` — integration enabled/configured, default project
- `list_sphere_experiments` — experiments in the project
- `list_sphere_realizations` — realizations with derived state (complete/failed/pending)
- `get_sphere_materialization(experiment, realization)` — task status; ready when HighestStatus is Success
- `list_sphere_xdcs` — XDCs and what they're attached to

## API Query Patterns

Prefer built-in tools/CLI. From weaves or scripts, use LoomAI REST so the
script inherits the backend's SPHERE credentials:

```python
import os, requests

BASE = os.environ.get("LOOMAI_API_URL") or os.environ.get("LOOMAI_URL") or "http://127.0.0.1:8000/api"
BASE = BASE.rstrip("/") if BASE.rstrip("/").endswith("/api") else BASE.rstrip("/") + "/api"
session = requests.Session()
if os.environ.get("LOOMAI_SESSION_COOKIE"):
    session.cookies.set("loomai_session", os.environ["LOOMAI_SESSION_COOKIE"])

status = session.get(f"{BASE}/sphere/status", timeout=30).json()
experiments = session.get(f"{BASE}/sphere/experiments", timeout=30).json()
realizations = session.get(f"{BASE}/sphere/realizations", params={"state": True}, timeout=60).json()
mat = session.get(f"{BASE}/sphere/materializations/myexp/r0", timeout=60).json()
inventory = session.get(f"{BASE}/sphere/inventory", timeout=60).json()
```

## Reading realization JSON
- `results[].realization` → `{complete, id (rname), eid (exp), pid (proj), nodes, links, expires}`
- `nodes` is keyed `"<module>/<name>"` (e.g. `"moddeter/a"`); each node has
  `sockets[].addrs` like `["10.0.0.1/24"]`
- `links` keyed `"a.0~b.0"` with `endpoints[].socket.element`

## Key Differences from FABRIC
- **Realize then materialize** — reserving resources and powering them on are separate steps
- Topologies are Python `mergexp` models pushed to an experiment, not FABlib slices
- Nodes are reachable only through an **XDC** jump container (no public IPs)
- Facility entitlement matters: a project may only be able to realize on some
  facilities (e.g. `fabricsphere` → `moddeter` only)
