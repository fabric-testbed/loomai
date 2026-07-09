---
id: package-sphere-weave
name: package-sphere-weave
asset_type: skill
audience: end-user
description: Package a SPHERE experiment as a reproducible weave (sphere-experiment-v1) and publish it
domains:
  - sphere
  - mergetb
  - weave
tools:
  - loomai
  - claude-code
  - opencode
  - crush
  - deepagents
---

Help the user package a live SPHERE experiment into a reproducible LoomAI weave
(`format: sphere-experiment-v1`) under `my_artifacts/`, runnable by others and
publishable to the FABRIC Artifact Manager.

## What the bundle contains
- `model.py` — mergexp source regenerated from the **materialized realization**
  (the deployed truth), falling back to the pushed model only when unrealized
- `experiment.py` — lifecycle driver: Run = create → push → realize →
  materialize (polling); Stop = dematerialize + relinquish. Calls the local
  LoomAI API; does **not** create an XDC (XDCs stay shared, manually attached)
- `weave.sh` — Run/Stop orchestrator (same contract as FABRIC/Chameleon weaves)
- `scripts/*.sh` — per-node setup scripts (each has a `target`: node name or `all`)
- `analysis.ipynb` — starter notebook: connect via XDC, deploy scripts, verify, analyze
- `weave.json` — the `sphere-experiment-v1` manifest with a `sphere` block
  (experiment/realization/project/network/nodes/links/scripts/notebook)

## How to package

### Via WebUI
Editor → **Package** tab: fill title/description, add per-node scripts, package.

### Via REST
```python
import os, requests

BASE = os.environ.get("LOOMAI_API_URL") or "http://127.0.0.1:8000/api"
BASE = BASE.rstrip("/") if BASE.rstrip("/").endswith("/api") else BASE.rstrip("/") + "/api"

requests.post(f"{BASE}/sphere/experiments/myexp/package", json={
    "name": "My IDS Lab",                # human title (decoupled from dir_name)
    "description": "Short summary",
    "description_short": "Max 255 chars for the marketplace card",
    "description_long": "<p>HTML long description</p>",
    "dir_name": "my-ids-lab",            # stable on-disk directory name
    "realization": "r0",
    "scripts": [
        {"name": "gw-setup.sh", "target": "gw", "content": "#!/bin/bash\n..."},
        {"name": "all-setup.sh", "target": "all", "content": "#!/bin/bash\n..."},
    ],
    "include_notebook": True,
}, timeout=120)
```
The experiment must have a realization or a pushed model; script filenames are
validated (no path traversal).

## Publishing
Use `publish_artifact(dir_name, title, description, category="weave", tags)` or
the Publish dialog. **Tags must come from the Artifact Manager's controlled
vocabulary** — `loomai:weave`, `experiment pattern`, `sphere` are accepted;
free-form tags like `ids` or `edge` are rejected. Add a `.weaveignore` for
publish exclusions.

## Running a packaged SPHERE weave
Load it from Libraries and Run — `weave.sh` drives the lifecycle as a
background run (`start_background_run`, watch with `get_background_run_output`).
Then attach a shared XDC to the new realization and seed the notebook:
```bash
loomai sphere xdc attach <xdc> <experiment> <realization>
curl -X POST $BASE/sphere/xdcs/<xdc>/seed-weave -d '{"dir_name": "my-ids-lab"}'
```
Open the XDC's JupyterLab (Notebook tab) and run `analysis.ipynb`.

## Reference example
`edgeids-weave` ships as a default artifact — a 4-node IDS/IPS lab
(`edge` attacker, `edge2` benign, `gw` victim gateway with traffic mirror,
`mon` Suricata sensor) on `moddeter`. Read its `weave.json`, `experiment.py`,
and `scripts/` as the ground-truth pattern before authoring a new SPHERE weave.
