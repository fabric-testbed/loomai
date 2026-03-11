name: create-weave
description: Create a new weave (multi-node slice template) artifact on the filesystem
---
Create a new weave artifact. Weaves are multi-node slice templates with topology,
boot config, and optional deployment scripts.

## Steps

1. **Understand**: How many nodes? What roles? What networks? What software?

2. **Create directory** in the user's artifacts directory:
   ```bash
   ARTIFACTS_DIR="/home/fabric/work/my_artifacts"
   mkdir -p "$ARTIFACTS_DIR/<DirName>/tools"
   ```
   Use PascalCase or descriptive names for the directory (e.g. `K8s_Cluster`).

3. **Write metadata.json**:
```json
{
  "name": "My Weave Name",
  "description": "What this weave deploys and configures",
  "node_count": 3,
  "network_count": 1
}
```

4. **Write slice.json** — the topology definition:
```json
{
  "nodes": [
    {
      "name": "server",
      "site": "@cluster",
      "cores": 4,
      "ram": 16,
      "disk": 40,
      "image": "default_ubuntu_22",
      "components": [
        {"name": "nic1", "model": "NIC_Basic"}
      ],
      "boot_config": {
        "uploads": [
          {"id": "deploy", "source": "tools/deploy.sh", "destination": "~/tools/deploy.sh"}
        ],
        "commands": [
          {"id": "1", "command": "chmod +x ~/tools/deploy.sh && ~/tools/deploy.sh", "order": 0}
        ],
        "network": []
      }
    }
  ],
  "networks": [
    {
      "name": "lan",
      "type": "L2Bridge",
      "interfaces": ["server-nic1-p1"]
    }
  ]
}
```

### Key rules for slice.json:

**Site groups**: Same `@tag` → co-located. Different tags → different sites. Use `"auto"` for independent nodes.

**Wiring**: Every node connecting to a network needs a NIC component.
Interface naming: `{node-name}-{component-name}-p{port-number}`.
- `NIC_Basic` → 1 port (`p1`)
- Dedicated NICs (ConnectX) → 2 ports (`p1`, `p2`)

**FABNetv4**: Each node gets its own FABNet network entry:
```json
{"name": "fabnet-node1", "type": "FABNetv4", "interfaces": ["node1-nic1-p1"],
 "l3_config": {"mode": "auto", "route_mode": "default_fabnet", "custom_routes": [], "default_fabnet_subnet": "10.128.0.0/10"}}
```

5. **Write tools/deploy.sh** — deployment script:
   - Start with `#!/bin/bash` and `set -e`
   - Use `### PROGRESS: message` markers for WebUI status updates
   - For multi-role weaves, dispatch on `$(hostname)`
   - Make scripts idempotent

6. **Optional: Write run.sh** — autonomous experiment script (in the weave root, not tools/):
   A weave with `run.sh` becomes "runnable" — the WebUI shows a Run button.
   Run scripts are **fully autonomous** — they create their own slices, deploy
   software, run experiments, collect results, and optionally clean up. They
   execute as **background runs** that survive browser disconnects.

   **Key principle**: `run.sh` manages its own slice lifecycle. It may create
   one slice, multiple slices in sequence, or parallel slices over time. The
   user provides parameters (slice name/prefix, test config) and the script
   handles everything else.

   ```bash
   #!/bin/bash
   set -e
   SLICE_NAME="${1:-${SLICE_NAME}}"
   DURATION="${DURATION:-30}"
   DELETE_AFTER="${DELETE_AFTER:-true}"
   if [ -z "$SLICE_NAME" ]; then echo "ERROR: SLICE_NAME not set" >&2; exit 1; fi
   TEMPLATE_DIR="$(cd "$(dirname "$0")" && pwd)"

   ### PROGRESS: Creating slice '$SLICE_NAME' from template...
   # Use FABlib to create slice from this weave's slice.json
   # ... create, submit, wait for provisioning ...

   ### PROGRESS: Deploying software
   # ... install and configure ...

   ### PROGRESS: Running experiment
   # ... collect data ...

   ### PROGRESS: Saving results
   # Save to /home/fabric/work/my_artifacts/ for persistence

   if [ "$DELETE_AFTER" = "true" ]; then
     ### PROGRESS: Cleaning up slice
     # ... delete slice ...
   fi
   ### PROGRESS: Experiment complete
   ```
   - All args from `run.json` are passed as environment variables
   - `SLICE_NAME` is also passed as `$1` for backward compatibility
   - The script reads `slice.json` from its own directory to create slices
   - Use `### PROGRESS:` markers for WebUI status updates in the Build Log
   - The script runs in the weave directory as its working directory
   - Output is captured to a log file — the browser can disconnect and reconnect
   - No timeout: runs until completion (or until explicitly stopped)
   - For multi-slice experiments, use SLICE_NAME as a prefix (e.g. `${SLICE_NAME}-1`)

6b. **Optional: Write run.json** — argument manifest for run.sh:
   If `run.sh` needs user-provided parameters, create a `run.json` in the weave root.
   The WebUI Run modal dynamically renders input fields from this file.
   Each arg becomes an environment variable passed to the script.
   ```json
   {
     "description": "What this run does",
     "args": [
       {
         "name": "SLICE_NAME",
         "label": "Slice Name",
         "type": "string",
         "required": true,
         "default": "",
         "description": "Name of the slice to use"
       },
       {
         "name": "DURATION",
         "label": "Test Duration (seconds)",
         "type": "number",
         "required": false,
         "default": "30",
         "description": "Duration of each test run"
       }
     ]
   }
   ```
   Supported types: `"string"`, `"number"`, `"boolean"`.
   If no `run.json` exists, the modal defaults to a single "Slice Name" field.

6c. **Optional: Write deploy.json** — argument manifest for deploy.sh:
   Same format as `run.json`. Defines args shown in the Deploy modal.
   If omitted, the Deploy modal shows a single "Slice Name" field.

7. **Verify**: Read back all created files to confirm JSON is valid and interface
   wiring is consistent.

## Managing Background Runs

Runs can be managed via the backend REST API:
```bash
# Start a background run with args from run.json
curl -X POST http://localhost:8000/api/templates/My_Weave/start-run/run.sh \
  -H "Content-Type: application/json" \
  -d '{"args": {"SLICE_NAME": "my-exp", "DURATION": "60"}}'

# Poll for output (incremental — pass last offset)
curl "http://localhost:8000/api/templates/runs/{run_id}/output?offset=0"

# List all runs (active + completed)
curl http://localhost:8000/api/templates/runs

# Stop a running run
curl -X POST http://localhost:8000/api/templates/runs/{run_id}/stop

# Delete a completed run
curl -X DELETE http://localhost:8000/api/templates/runs/{run_id}
```

## Tips

- Never hardcode site names — use `@group` tags or `"auto"`
- Match `node_count` and `network_count` in metadata.json to actual counts
- Test with the WebUI: load the weave from Libraries → Local tab
- Study examples in `/app/slice-libraries/slice_templates/` for patterns
- For long experiments, use `run.sh` — it runs in the background and survives disconnects
