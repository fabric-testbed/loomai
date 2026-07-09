---
id: manage-sphere-xdc
name: manage-sphere-xdc
asset_type: skill
audience: end-user
description: Manage SPHERE XDCs (jump containers) and SSH/file access to experiment nodes
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

Help the user manage SPHERE XDCs and reach experiment nodes. An **XDC**
(Experiment Data Conduit) is a Merge-hosted jump container — the only path to
experiment nodes, which have no public IPs.

## SSH access model
```
jump host  →  XDC  →  node
```
- Node management DNS: `<node>.infra.<rname>.<exp>.<proj>`
- The XDC `fqdn` (e.g. `x0-fabricsphere.xdc.sphere-testbed.net`) is the
  **JupyterLab ingress**, NOT the SSH host — SSH targets the fqdn's leftmost
  label (`x0-fabricsphere`) via the jump host.
- Auth uses the portal-issued keypair + signed cert; LoomAI assembles the whole
  chain server-side, so no `mrg` binary is needed.

## XDC lifecycle
```bash
loomai sphere xdc list
loomai sphere xdc create <name> --type shared
loomai sphere xdc attach <name> <experiment> <realization>
loomai sphere xdc detach <name> <experiment> <realization>
loomai sphere xdc delete <name>
```

Rules:
- XDC names in API calls are **bare** (`^[a-z][a-z0-9]{0,62}$`), not `<name>.<project>`.
- In non-personal projects (e.g. `fabricsphere`) XDCs **must** be `shared` —
  personal XDCs are rejected.
- One shared XDC can serve many realizations — attach/detach rather than
  creating one per experiment.

## Node SSH
```bash
# Interactive (WebUI: Connect button on a topology node, or right-click → SSH)
loomai sphere ssh <experiment> <realization> <node> --xdc <xdc>
```

Tool calls: `list_sphere_xdcs`, `attach_sphere_xdc(xdc, experiment, realization)`.

## Files to/from nodes
The Storage tab (dual-panel file manager) transfers between LoomAI storage and
a node over scp through the XDC chain. REST equivalents:
- `GET  /api/sphere/files?experiment=&realization=&node=&xdc=&path=` — list
- `POST /api/sphere/upload` — upload to a node
- `GET  /api/sphere/files/download` — download from a node
- `POST /api/sphere/files/{read,write,mkdir,delete}` — file ops

The sentinel node `__xdc__` targets the **XDC's own home directory** instead of
an experiment node — use it to stage files where the XDC's JupyterLab can see
them. `POST /api/sphere/xdcs/{xdc}/seed-weave` copies a packaged weave's
notebook + scripts there.

## JupyterLab on the XDC
The Notebook tab opens the XDC's JupyterLab (its `fqdn`) in a new tab — the
most reliable way to run analysis next to the experiment.

## Troubleshooting
- "Host key verification failed" on a hop → the generated ssh config must apply
  relaxed host-key checking to **every** hop (`Host *`), not just the node.
- "Session open refused by peer" → a stale SSH multiplex socket; retry, or use
  the in-XDC notebook path.
- XDC not ready → `loomai sphere xdc list` (with status) and wait for readiness
  before SSH.
