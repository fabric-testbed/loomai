name: clone-export
description: Clone, export, and import FABRIC slices for reproducibility
---
Help the user clone, export, or import FABRIC slices.

**Determine what the user wants:**

### Clone a Slice
Create a copy of an existing slice as a new draft:
1. `fabric_get_slice(slice_name)` — verify the source exists
2. Clone creates a new draft with the same topology but a new name
3. The clone is a draft — it must be submitted separately
4. Useful for: creating variations, testing changes without affecting the original

### Export a Slice
Save the slice topology as a `.fabric.json` file:
1. `fabric_get_slice(slice_name)` — get current topology
2. Export produces a JSON file with nodes, networks, components, and boot config
3. File is saved to `/home/fabric/work/` for later use
4. Useful for: sharing topologies, version control, documentation

### Save as Template
Convert a working slice into a reusable template:
1. Get the slice topology
2. Save as template with metadata (name, description)
3. Template appears in the WebUI template browser
4. Useful for: making a proven setup reusable for yourself or others

### Import a Slice
Load a `.fabric.json` file as a new draft:
1. Place the JSON file in `/home/fabric/work/`
2. Import creates a draft from the file
3. Review and modify the draft as needed before submitting
4. Useful for: loading shared topologies, restoring previous experiments

**Tips:**
- Exported files capture topology but not VM state (installed software, files)
- To fully reproduce an experiment, also save deploy.sh scripts and recipes
- Clone + modify is safer than modifying a running slice directly
