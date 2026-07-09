---
id: create-sphere-experiment
name: create-sphere-experiment
asset_type: skill
audience: end-user
description: Create and deploy a SPHERE experiment — mergexp model, create, push, realize, materialize
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

Help the user create and deploy a SPHERE (MergeTB) experiment end to end.

## Lifecycle
```
write mergexp model → create experiment → push model (tag) → realize (reserve)
  → materialize (power on) → poll status → access nodes via XDC
```

## 1. Write the mergexp model

`mergexp` is SPHERE's Python topology DSL. Node names must be valid Python
identifiers; experiment names must match `^[a-z][a-z0-9]{0,62}$` (lowercase
letters + digits only — no hyphens, underscores, or uppercase).

```python
from mergexp import *

net = Network('myexp')

a = net.node('a', facility == 'moddeter')
b = net.node('b', facility == 'moddeter')

link0 = net.connect([a, b])
link0[a].socket.addrs = ip4('10.0.0.1/24')
link0[b].socket.addrs = ip4('10.0.0.2/24')

experiment(net)
```

Notes:
- `net.connect([a, b, c])` makes a LAN; assign per-member addresses via
  `link[node].socket.addrs = ip4('cidr')`.
- Pin the facility with `facility == '<name>'` — check entitlement first (the
  `fabricsphere` project can only realize on `moddeter`).

## 2. Create, push, realize, materialize

### Via CLI
```bash
loomai sphere create-experiment myexp --description "two-node demo"
loomai sphere compile-model model.py          # validate before pushing
loomai sphere push-model myexp model.py --tag v1
loomai sphere realize myexp r0 --tag v1
loomai sphere materialize myexp r0
loomai sphere materialization myexp r0        # poll status
```

### Via Tool Calls (LoomAI assistant)
1. `create_sphere_experiment(experiment, description?)` — name must be lowercase alnum
2. `push_sphere_model(experiment, model, tag)` — pass the mergexp source as `model`; always tag (e.g. `v1`)
3. `sphere_realize(experiment, realization, tag)` — realization name like `r0`; reserves resources
4. `sphere_materialize(experiment, realization)` — powers on, images, wires the network
5. `get_sphere_materialization(experiment, realization)` — poll until
   `taskSummary.HighestStatus == "Success"` (typically a few minutes)

### Via LoomAI REST (weaves / scripts)
```python
import os, time, requests

BASE = os.environ.get("LOOMAI_API_URL") or os.environ.get("LOOMAI_URL") or "http://127.0.0.1:8000/api"
BASE = BASE.rstrip("/") if BASE.rstrip("/").endswith("/api") else BASE.rstrip("/") + "/api"
session = requests.Session()
if os.environ.get("LOOMAI_SESSION_COOKIE"):
    session.cookies.set("loomai_session", os.environ["LOOMAI_SESSION_COOKIE"])

model_src = open("model.py").read()
session.post(f"{BASE}/sphere/experiments", json={"experiment": "myexp", "description": "demo"}, timeout=60)
session.post(f"{BASE}/sphere/models", json={"model": model_src, "experiment": "myexp", "tag": "v1"}, timeout=120)
session.post(f"{BASE}/sphere/realizations", json={"experiment": "myexp", "realization": "r0", "tag": "v1"}, timeout=120)
session.post(f"{BASE}/sphere/materializations", json={"experiment": "myexp", "realization": "r0"}, timeout=120)

while True:
    mat = session.get(f"{BASE}/sphere/materializations/myexp/r0", timeout=60).json()
    if (mat.get("taskSummary") or {}).get("HighestStatus") == "Success":
        break
    time.sleep(15)
```

## 3. Access nodes
Nodes have no public IPs — attach an XDC and SSH through it (see the
`manage-sphere-xdc` skill):
```bash
loomai sphere xdc attach <xdc> <experiment> <realization>
loomai sphere ssh <experiment> <realization> <node> --xdc <xdc>
```

## Teardown
Reverse order — dematerialize, then relinquish (both destructive; confirm first):
```bash
loomai sphere dematerialize myexp r0
loomai sphere relinquish myexp r0
loomai sphere delete-experiment myexp     # optional
```

## Gotchas
- **Realize grammar**: a realization is `<rname>.<exp>.<proj>` and realizes a
  specific model reference — always push with `--tag` and realize with the same tag.
- **Model revisions have no ordering** — they are content-hash keyed, so
  "latest model" is ambiguous. Tags are the only reliable reference.
- A failed realization reports `state: failed` with an error in
  `list_sphere_realizations` — don't wait on a failed one; relinquish and re-realize.
- Realizations expire — check `expires` and re-realize if needed.
