name: create-vm-template
description: Create a new VM template for a single-node configuration
---
Create a new VM template. VM templates define single-node configurations
that can be added to any slice.

## Steps

1. **Understand**: What software/config? Which OS images? What resources?

2. **Create directory** in the user's artifacts directory. Discover it first:
   ```bash
   ARTIFACTS_DIR="/home/fabric/work/my_artifacts"
   mkdir -p "$ARTIFACTS_DIR/<DirName>"
   ```

3. **Choose format**:

### Simple (boot_config) — same setup for all OS images

```json
{
  "name": "My Template",
  "version": "1.0.0",
  "description": "What this template configures",
  "image": "default_ubuntu_22",
  "boot_config": {
    "uploads": [
      {"id": "setup", "source": "tools/setup.sh", "destination": "~/tools/setup.sh"}
    ],
    "commands": [
      {"id": "1", "command": "sudo apt-get update && sudo apt-get install -y package", "order": 0},
      {"id": "2", "command": "chmod +x ~/tools/setup.sh && ~/tools/setup.sh", "order": 1}
    ],
    "network": []
  }
}
```

**Fields:**
- `name` — Display name in the UI
- `version` — Semver version string
- `description` — Shown in template browser
- `image` — Default VM image (user can override)
- `cores`, `ram`, `disk` — Recommended resources (optional, applied when template is selected)
- `site` — Preferred FABRIC site (optional)
- `host` — Specific physical host (optional)
- `image_type` — Image format, e.g. `qcow2` (optional)
- `username` — SSH user (optional)
- `instance_type` — VM flavor (optional)
- `components` — Hardware to attach: `[{"name": "gpu1", "model": "GPU_RTX6000"}]` (optional)
- `boot_config.uploads` — Files to upload before running commands
  - `source`: path relative to template directory
  - `dest`: path on the VM
- `boot_config.commands` — Shell commands, executed in `order`
- `boot_config.network` — Network config entries (rarely needed)

### Multi-variant — different setup per OS

```json
{
  "name": "Docker Host",
  "version": "1.0.0",
  "description": "Installs Docker Engine",
  "variants": {
    "default_ubuntu_22": { "label": "Ubuntu 22.04", "dir": "ubuntu_22" },
    "default_ubuntu_24": { "label": "Ubuntu 24.04", "dir": "ubuntu_24" },
    "default_rocky_9": { "label": "Rocky Linux 9", "dir": "rocky_9" }
  },
  "setup_script": "setup.sh",
  "remote_dir": "~/.fabric/vm-templates/docker_host"
}
```

Directory structure:
```
DockerHost/
  vm-template.json
  ubuntu_22/setup.sh
  ubuntu_24/setup.sh
  rocky_9/setup.sh
```

Each variant's `setup.sh` is uploaded and executed for the matching OS image.

4. **Write scripts** with `#!/bin/bash`, `set -e`, and `### PROGRESS:` markers.

5. **Verify**: Read back all created files.
