name: create-weave
description: Create a new weave artifact with well-documented FABlib Python code
---
Create a new weave artifact. Weaves are multi-node topologies with
boot config, and deployment scripts that use the FABlib Python API.

**The Python lifecycle script is the heart of every weave.** It must be:
- **Well-documented**: Module docstring explaining what the weave does, how it works,
  and what FABlib concepts it demonstrates. Inline comments explaining each FABlib
  API call so users can learn by reading the code.
- **Educational**: Users should be able to open the .py file and understand how FABlib
  works — how to create slices, add nodes with specific hardware, configure networks,
  execute commands via SSH, and clean up resources.
- **Production-ready**: Proper error handling, progress messages, and clean shutdown.

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
   ├── weave.md                # Human-readable spec — edit to change the weave
   ├── weave.sh                # Orchestrator: calls Python lifecycle script
   ├── <name>.py               # Python lifecycle script (start/stop/monitor)
   ├── <name>.ipynb            # Jupyter notebook (optional, for analysis/learning)
   └── tools/                  # Scripts uploaded to ~/tools/ on VMs
       ├── setup-server.sh
       └── setup-worker.sh
   ```

   **weave.md** is the specification file. It describes the weave's topology, software,
   and lifecycle in human-readable markdown. Users can edit it in JupyterLab or any
   text editor and ask LoomAI to "update the weave based on weave.md". When modifying
   an existing weave, ALWAYS read weave.md first — it is the authoritative specification.

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
   slice name.

   **CRITICAL: The Python script must be well-documented and educational.**
   Users will read these scripts to learn how FABlib works. Every script should have:
   - A **module docstring** explaining what the weave does, what FABlib concepts it
     demonstrates, and how to use it
   - **Inline comments** on every FABlib API call explaining what it does and why
   - **FABlib concept explanations** (slice lifecycle, node types, network types,
     component models, SSH access patterns) where relevant
   - **Step numbers** in progress messages (e.g., "Step 2/5 — Adding nodes...")
   - A **READY!** message at the end with node IPs and SSH instructions

   **Python script structure:**
   - `start(name)` — create slice with FABlib, submit, `wait_ssh()`, configure, print IPs
   - `stop(name)` — get slice by name, delete it; handle "not found" gracefully
   - `monitor(name)` — check slice state is StableOK, execute test on each node; exit 1 on failure
   - Use `### PROGRESS:` markers for WebUI status updates
   - Import FABlib inside each function (avoids startup cost when not needed)

   **FABlib script pitfalls — avoid these common errors:**
   - `add_node(..., tags=["@cluster"])` — `tags` is NOT a valid parameter. Use `site="STAR"` or `site=None`.
   - After `submit()`, re-fetch the slice: `slice = fablib.get_slice(name=slice_name)` before accessing nodes.
   - `add_fabnet()` returns None. After re-fetch, get IP with: `node.get_interface(network_name=f"FABNET_IPv4_{node.get_site()}").get_ip_addr()`
   - No `node.write_file()`. Use `node.upload_file()` or `node.execute("echo ... > file")`.
   - No `import fablib`. Use `from fabrictestbed_extensions.fablib.fablib import FablibManager`.

   **Key FABlib API patterns to document in the script:**
   ```python
   # Initialize FABlib — reads credentials from FABRIC_CONFIG_DIR
   from fabrictestbed_extensions.fablib.fablib import FablibManager
   fablib = FablibManager()

   # Create a slice (draft — no resources allocated yet)
   slice_obj = fablib.new_slice(name="my-slice")

   # Add a node (VM) with resources
   node = slice_obj.add_node(name="node1", site=None,  # auto-placement
                              cores=4, ram=16, disk=100,
                              image="default_ubuntu_22")

   # Add hardware components to a node
   node.add_component(model="NIC_Basic", name="nic1")      # 25G shared NIC
   node.add_component(model="GPU_RTX6000", name="gpu1")     # NVIDIA GPU
   node.add_component(model="NVME_P4510", name="nvme1")     # 1TB NVMe SSD

   # Create networks and connect nodes
   ifaces = [node.get_interfaces()[0] for node in nodes]
   slice_obj.add_l2network(name="net1", interfaces=ifaces)  # Same-site L2

   # Submit and wait for provisioning (3-10 min)
   slice_obj.submit()
   slice_obj.wait_ssh(progress=True)

   # IMPORTANT: Re-fetch slice after submit — original node objects go stale
   slice_obj = fablib.get_slice(name="my-slice")

   # Execute commands on nodes via SSH
   node = slice_obj.get_node(name="node1")
   stdout, stderr = node.execute("hostname")

   # Upload/download files
   node.upload_file("local/path", "remote/path")
   node.download_file("remote/path", "local/path")

   # Get node info
   node.get_management_ip()    # SSH-accessible IP (via bastion)
   node.get_ssh_command()      # Full SSH command string
   node.get_interfaces()       # Network interfaces

   # Retrieve and delete
   slice_obj = fablib.get_slice(name="my-slice")
   slice_obj.delete()
   ```

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
