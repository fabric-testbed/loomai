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

6. **Optional: Write tools/run.sh** — autonomous experiment script:
   A weave with `run.sh` becomes "runnable" — the WebUI shows a Run button.
   The run script executes after deployment and can perform automated experiments.
   ```bash
   #!/bin/bash
   set -e
   ### PROGRESS: Running experiment
   # ... experiment logic ...
   ### PROGRESS: Experiment complete
   ```

7. **Verify**: Read back all created files to confirm JSON is valid and interface
   wiring is consistent.

## Tips

- Never hardcode site names — use `@group` tags or `"auto"`
- Match `node_count` and `network_count` in metadata.json to actual counts
- Test with the WebUI: load the weave from Libraries → Local tab
- Study builtins in `/app/slice-libraries/slice_templates/` for patterns
