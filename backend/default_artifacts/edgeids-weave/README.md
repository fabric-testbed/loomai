# SPHERE Edge IDS/IPS Lab

A reproducible SPHERE experiment packaged as a LoomAI weave.

## Topology
**Experiment:** `edgeids`  **Realization:** `ids`

### Nodes
- **gw** — facility `moddeter`
- **edge** — facility `moddeter`
- **edge2** — facility `moddeter`
- **mon** — facility `moddeter`

### Links
- edge ↔ edge2 ↔ gw
- gw ↔ mon

### Setup scripts
- `scripts/gw-setup.sh` → `gw`
- `scripts/mon-setup.sh` → `mon`
- `scripts/edge-setup.sh` → `edge`
- `scripts/edge2-setup.sh` → `edge2`

## Recreate it
1. **Run** this weave from the LoomAI Libraries panel (or `loomai weaves run`).
   It will recreate the experiment, push `model.py`, realize, and materialize.
2. Attach an XDC to the realization (Editor → XDC), then **Notebook → Send weave
   → XDC** and **Open JupyterLab**, and run `analysis.ipynb`.
3. Click **Stop** to dematerialize and relinquish the realization.

> The mergexp source in `model.py` was regenerated from the compiled topology.
