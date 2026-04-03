name: getting-started
description: Step-by-step onboarding for new FABRIC users
---
Guide a new user through their first FABRIC experience.

## Step 1: Check Configuration
- `get_config` — verify token, SSH keys, and project are set
- If token is missing/expired: direct to **Configure** view in the WebUI
- If no project selected: `list_projects` then `switch_project(name)`

## Step 2: Explore Resources
- `query_sites` — show available sites with resource counts
- `list_images` — show available VM images
- Explain: FABRIC has 30+ sites across US, Europe, and Asia

## Step 3: Create First Slice
- Use the **Hello FABRIC** template: `load_template("Hello_FABRIC", "my-first-slice")`
- Or create manually: `create_slice("my-first-slice", nodes=[{name: "node1", site: "auto", cores: 2, ram: 8, disk: 10, image: "default_ubuntu_22"}])`
- Explain what a "slice" is: an allocated set of VMs and networks — like a virtual lab

## Step 4: Deploy
- `submit_slice("my-first-slice", wait=true)` — submit and wait
- Explain state transitions: Nascent → Configuring → StableOK
- `get_slice("my-first-slice")` — show nodes, IPs, state

## Step 5: Connect
- `get_slice("my-first-slice", "node1")` — get SSH command and IPs
- `ssh_execute("my-first-slice", "node1", "uname -a")` — run first command
- Explain: you can also use the SSH terminal in the WebUI bottom panel

## Step 6: Next Steps
- Try a more complex template: `list_templates`
- Learn about networking: see AGENTS.md "Network Types" section
- Set up monitoring: `/monitor`
- When done: `delete_slice("my-first-slice")` (always clean up!)

## WebUI Guided Tour
- The WebUI has an interactive **Getting Started** tour on the Landing page
- Click "Take the Guided Tour" to walk through setup step-by-step
- The tour verifies each action (token upload, key setup, etc.) automatically
- 9 additional tours cover: Topology Editor, AI Tools, Artifacts, Map, Table View, Web Apps, JupyterLab, Console, File Manager
- Access all tours from the Help page

## If Something Goes Wrong
- Slice stuck in Configuring? → wait longer, or check `get_slice` for errors
- Can't SSH? → check slice state is StableOK, verify SSH keys in config
- Token expired? → refresh in Configure view or https://portal.fabric-testbed.net
