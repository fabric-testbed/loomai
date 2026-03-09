name: getting-started
description: Step-by-step onboarding for new FABRIC users
---
Guide a new user through their first FABRIC experience.

## Step 1: Check Configuration
- `fabric_get_config` — verify token, SSH keys, and project are set
- If token is missing/expired: direct to **Configure** view in the WebUI
- If no project selected: `fabric_list_projects` then `fabric_set_project(name)`

## Step 2: Explore Resources
- `fabric_list_sites` — show available sites with resource counts
- `fabric_list_images` — show available VM images
- Explain: FABRIC has 30+ sites across US, Europe, and Asia

## Step 3: Create First Slice
- Use the **Hello FABRIC** template: `fabric_create_from_template("Hello_FABRIC", "my-first-slice")`
- Or create manually: `fabric_create_slice("my-first-slice", nodes=[{name: "node1", site: "auto", cores: 2, ram: 8, disk: 10, image: "default_ubuntu_22"}])`
- Explain what a "slice" is: an allocated set of VMs and networks — like a virtual lab

## Step 4: Deploy
- `fabric_submit_slice("my-first-slice", wait=true)` — submit and wait
- Explain state transitions: Nascent → Configuring → StableOK
- `fabric_get_slice("my-first-slice")` — show nodes, IPs, state

## Step 5: Connect
- `fabric_node_info("my-first-slice", "node1")` — get SSH command and IPs
- `fabric_slice_ssh("my-first-slice", "node1", "uname -a")` — run first command
- Explain: you can also use the SSH terminal in the WebUI bottom panel

## Step 6: Next Steps
- Try a more complex template: `fabric_list_templates`
- Learn about networking: see AGENTS.md "Network Types" section
- Set up monitoring: `/monitor`
- When done: `fabric_delete_slice("my-first-slice")` (always clean up!)

## WebUI Guided Tour
- The WebUI has an interactive **Getting Started** tour on the Landing page
- Click "Take the Guided Tour" to walk through setup step-by-step
- The tour verifies each action (token upload, key setup, etc.) automatically
- 9 additional tours cover: Topology Editor, AI Tools, Artifacts, Map, Table View, Web Apps, JupyterLab, Console, File Manager
- Access all tours from the Help page

## If Something Goes Wrong
- Slice stuck in Configuring? → wait longer, or check `fabric_get_slice` for errors
- Can't SSH? → check slice state is StableOK, verify SSH keys in config
- Token expired? → refresh in Configure view or https://portal.fabric-testbed.net
