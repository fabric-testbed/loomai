name: deploy-script
description: Create a deploy.sh script for an existing slice template
---
Create or update a deploy.sh script for a slice template. The script runs on
each VM at boot time and handles software installation and configuration.

1. **Check existing template**: Read the slice.json to understand the
   topology, node roles, and what software needs to be deployed.

2. **Write the deploy.sh script** in the template's `tools/` directory:
   - Start with `#!/bin/bash` and `set -e`
   - Use `### PROGRESS:` markers for WebUI status updates
   - For multi-role templates, dispatch based on hostname
   - Make the script idempotent (safe to re-run)
   - Use quiet flags (-qq for apt, -q for pip) to reduce noise

3. **Update boot_config** in slice.json if needed:
   - Add the command: `"chmod +x ~/tools/deploy.sh && ~/tools/deploy.sh"`

4. **Verify**: Read back the script to confirm it's correct.

5. **Optional: Write deploy.json** — argument manifest:
   If the deploy script needs user-provided parameters beyond the default
   slice name, create a `deploy.json` in the template's root directory:
   ```json
   {
     "description": "Deploy an iPerf3 test",
     "args": [
       {"name": "SLICE_NAME", "label": "Slice Name", "type": "string", "required": true, "default": ""},
       {"name": "NUM_WORKERS", "label": "Worker Count", "type": "number", "required": false, "default": "2"}
     ]
   }
   ```
   Each arg becomes an environment variable. The WebUI Deploy modal renders
   input fields dynamically. If no `deploy.json` exists, the modal defaults
   to a single "Slice Name" field.

### PROGRESS marker format:
```bash
### PROGRESS: Installing dependencies
sudo apt-get update -qq
```
These lines appear as teal status indicators in the WebUI boot console.

Multi-role pattern:
```bash
HOSTNAME=$(hostname)
if [[ "$HOSTNAME" == *"monitor"* ]]; then
    # monitor setup
elif [[ "$HOSTNAME" == *"worker"* ]]; then
    # worker setup
fi
```
