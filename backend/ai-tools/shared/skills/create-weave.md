name: create-weave
description: Create a new weave artifact on the filesystem
---
Create a new weave artifact. Weaves are multi-node topologies with
boot config, and optional deployment scripts.

## Steps

1. **Understand**: How many nodes? What roles? What networks? What software?

2. **Create directory** in the user's artifacts directory:
   ```bash
   ARTIFACTS_DIR="/home/fabric/work/my_artifacts"
   mkdir -p "$ARTIFACTS_DIR/<DirName>/tools"
   ```
   Use PascalCase or descriptive names for the directory (e.g. `K8s_Cluster`).

   **Weave directory structure:**
   ```
   <DirName>/
   ├── weave.json              # Required: ALL weave metadata, args, topology
   ├── weave.sh                # Orchestrator: calls Python lifecycle script
   ├── <name>.py               # Python lifecycle script (start/stop/monitor)
   └── tools/                  # Scripts uploaded to ~/tools/ on VMs
       ├── setup-server.sh
       └── setup-worker.sh
   ```

3. **Write weave.json** — the ONLY required file for a weave. It contains ALL metadata,
   run configuration, argument definitions, and topology:
```json
{
  "run_script": "weave.sh",
  "log_file": "weave.log",
  "name": "My Weave Name",
  "description": "Brief one-sentence summary of this weave (5-255 chars, shown on UI cards)",
  "description_long": "Full detailed description of what this weave deploys, how the components interact, prerequisites, expected runtime, and any configuration notes. This is shown when users view artifact details.",
  "args": [
    {"name": "SLICE_NAME", "label": "Slice Name", "type": "string", "required": true, "default": "my-weave", "description": "Name for the FABRIC slice"},
    {"name": "MONITOR_INTERVAL", "label": "Monitor Interval (seconds)", "type": "number", "required": false, "default": 30, "description": "How often to check slice health"}
  ]
}
```
   - `run_script`: the script to execute when the user clicks Run (default: `weave.sh`)
   - `log_file`: where stdout/stderr are captured (default: `weave.log`)
   - `name`: human-readable display name
   - `description`: short summary (5–255 chars) shown on artifact cards in the UI
   - `description_long`: full detailed description of the weave — what it deploys, how
     it works, prerequisites, and configuration. Shown in artifact detail views and used
     when publishing. Write thorough documentation here.
   - `args`: argument definitions for the Run modal (each becomes an env var).
     **Every arg must have a meaningful `default` value.** The WebUI prepopulates
     the Run popup with these defaults so users can click Run immediately.
     For `SLICE_NAME`, use a short lowercase-kebab-case name derived from the weave
     name (e.g., `"k8s-cluster"`, `"prom-grafana"`). The popup appends a random suffix
     to make it unique. For numeric args, set a sensible default (e.g., `30` for intervals).
   - The WebUI reads this to determine what script to run and where to find logs
   - `weave.json` is the required marker file for a weave
   - **Runtime field**: When running, an `active_run` object is added with `run_id`, `pid`, `pgid`, `started_at`, `script`, and `args` (the actual values used). It is cleared when the run finishes.

4. **Define topology** in `weave.json` or as a separate topology file. The topology includes nodes, components, and networks:

### Key topology rules:

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

5. **Write tools/ scripts** — per-VM setup scripts that run on each node at boot:
   - Start with `#!/bin/bash` and `set -e`
   - Use `### PROGRESS: message` markers — these appear as teal status lines in the WebUI console
   - Use quiet flags: `-qq` for apt-get, `-q` for pip
   - Make scripts idempotent (safe to re-run)
   - For multi-role weaves, dispatch on hostname:
   ```bash
   HOSTNAME=$(hostname)
   if [[ "$HOSTNAME" == *"server"* ]]; then
       # server setup
   elif [[ "$HOSTNAME" == *"worker"* ]]; then
       # worker setup
   fi
   ```
   - Update boot_config in the topology to run the script:
     `"commands": [{"id": "1", "command": "chmod +x ~/tools/setup.sh && ~/tools/setup.sh", "order": 0}]`

6. **Write the Python lifecycle script** — the core logic for slice management.
   Each weave has a Python script (e.g. `hello_fabric.py`, `k8s_cluster.py`) that
   uses FABlib directly. It takes a command (`start`, `stop`, or `monitor`) and a
   slice name:

   **Hello FABRIC example** (`hello_fabric.py`):
   ```python
   #!/usr/bin/env python3
   """Hello FABRIC — single-node slice lifecycle."""
   import sys

   def start(slice_name):
       from fabrictestbed_extensions.fablib.fablib import FablibManager
       fablib = FablibManager()

       print(f"### PROGRESS: Creating slice '{slice_name}'...")
       slice_obj = fablib.new_slice(name=slice_name)
       node = slice_obj.add_node(name="node1", site="random",
                                  cores=2, ram=8, disk=10,
                                  image="default_ubuntu_22")

       print("### PROGRESS: Submitting slice...")
       slice_obj.submit()

       print("### PROGRESS: Waiting for SSH access...")
       slice_obj.wait_ssh(progress=True)

       print(f"### PROGRESS: Slice '{slice_name}' is ready!")
       for n in slice_obj.get_nodes():
           print(f"  {n.get_name()}: {n.get_management_ip()}")

   def stop(slice_name):
       from fabrictestbed_extensions.fablib.fablib import FablibManager
       fablib = FablibManager()
       try:
           slice_obj = fablib.get_slice(name=slice_name)
           print(f"### PROGRESS: Deleting slice '{slice_name}'...")
           slice_obj.delete()
           print(f"### PROGRESS: Slice '{slice_name}' deleted.")
       except Exception as e:
           print(f"### PROGRESS: Slice not found or already deleted: {e}")

   def monitor(slice_name):
       from fabrictestbed_extensions.fablib.fablib import FablibManager
       fablib = FablibManager()
       slice_obj = fablib.get_slice(name=slice_name)
       state = str(slice_obj.get_state())

       if "StableOK" not in state:
           print(f"ERROR: Slice state is {state}")
           sys.exit(1)

       for node in slice_obj.get_nodes():
           try:
               stdout, stderr = node.execute("echo ok", quiet=True)
               if "ok" not in stdout:
                   raise Exception("unexpected output")
           except Exception as e:
               print(f"ERROR: Node {node.get_name()} health check failed: {e}")
               sys.exit(1)

       print(f"### PROGRESS: All nodes healthy — state: {state}")

   if __name__ == "__main__":
       if len(sys.argv) < 3:
           print("Usage: hello_fabric.py {start|stop|monitor} SLICE_NAME")
           sys.exit(1)
       action, name = sys.argv[1], sys.argv[2]
       {"start": start, "stop": stop, "monitor": monitor}[action](name)
   ```

   **Python script rules:**
   - `start(name)` — create slice with FABlib, submit, `wait_ssh()`, print node IPs
   - `stop(name)` — get slice by name, delete it; handle "not found" gracefully
   - `monitor(name)` — check slice state is StableOK, execute test command on each node; exit 1 on failure
   - Use `### PROGRESS:` markers for WebUI status updates
   - Import FABlib inside each function (avoids startup cost when not needed)
   - For multi-node weaves, add nodes/networks/components in `start()`

7. **Write weave.sh** — thin orchestrator that calls the Python script:
   A weave with `weave.sh` becomes "runnable" — the WebUI shows a Run button.
   `weave.sh` is a **thin shell** that handles argument parsing, the SIGTERM trap
   (Stop button), and the monitor loop. All slice logic lives in the Python script.

   ```bash
   #!/bin/bash
   SLICE_NAME="${SLICE_NAME:-${1:-hello-fabric}}"
   SLICE_NAME=$(echo "$SLICE_NAME" | sed 's/[^a-zA-Z0-9-]/-/g' | sed 's/--*/-/g' | sed 's/^-//;s/-$//')
   if [ -z "$SLICE_NAME" ]; then echo "ERROR: SLICE_NAME not set" >&2; exit 1; fi
   SCRIPT="hello_fabric.py"

   # Graceful shutdown: stop slice and exit
   # Triggered by WebUI Stop button (sends SIGTERM)
   cleanup() {
     echo ""
     echo "### PROGRESS: Stop requested — cleaning up..."
     python3 "$SCRIPT" stop "$SLICE_NAME" 2>&1 || true
     echo "### PROGRESS: Done."
     exit 0
   }
   trap cleanup SIGTERM SIGINT

   # Start the slice
   if ! python3 "$SCRIPT" start "$SLICE_NAME"; then
     echo "ERROR: Failed to start slice"
     exit 1
   fi

   # Monitor until Stop or failure
   echo "### PROGRESS: Monitoring (click Stop to tear down)..."
   while true; do
     if ! python3 "$SCRIPT" monitor "$SLICE_NAME"; then
       echo "ERROR: Monitor detected failure — cleaning up..."
       python3 "$SCRIPT" stop "$SLICE_NAME" || true
       exit 1
     fi
     sleep 30 &
   wait $! 2>/dev/null || true
   done
   ```

   **Key patterns:**
   - `weave.sh` is a **thin orchestrator** — all slice logic is in the Python script
   - Python script uses **FABlib directly** (not curl/REST API)
   - `trap cleanup SIGTERM SIGINT` — Stop button triggers `stop()` then clean exit
   - **Monitor loop** uses `sleep N & wait $!` so SIGTERM is handled immediately
   - `### PROGRESS:` markers for WebUI status in Build Log
   - All args from `weave.json` are passed as environment variables
   - `SLICE_NAME` is also passed as `$1` for backward compatibility
   - The script runs in the weave directory as its working directory
   - Output captured to `weave.log` — browser can disconnect and reconnect
   - **Do NOT use `set -e`** in weave.sh — it interferes with signal handling

   **Logging best practices** — the Build Log is the user's only window into what
   the weave is doing. Print clear, helpful messages so users know:
   - What step the weave is on and how many steps remain (e.g. `Step 2/5 — Installing software...`)
   - What is happening right now and roughly how long it takes (e.g. `Submitting slice (3-5 minutes)...`)
   - When each major step completes (e.g. `All 3 nodes are up and SSH-accessible!`)
   - When the weave is **fully ready** for the user (e.g. `READY! Slice is provisioned. Click Stop to tear down.`)
   - At the start, print a summary of what the weave will do and how long it typically takes

8. **Verify**: Read back all created files to confirm JSON is valid, interface
   wiring is consistent, and the Python script syntax is correct.

## Managing Background Runs

Runs can be managed via the backend REST API:
```bash
# Start a background run with args from weave.json
curl -X POST http://localhost:8000/api/templates/My_Weave/start-run/weave.sh \
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
- Test with the WebUI: load the weave from Artifacts → Local tab
- Study the Hello FABRIC weave in my_artifacts/ for patterns
- For long experiments, use `weave.sh` — it runs in the background and survives disconnects
