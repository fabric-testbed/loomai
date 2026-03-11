name: create-recipe
description: Create a new VM recipe for post-provisioning software installation
---
Create a new VM recipe based on the user's description. Recipes install software
on existing VMs after provisioning.

## Steps

1. **Understand**: What software? Which OS families to support?

2. **Create directory** in the user's artifacts directory:
   ```bash
   ARTIFACTS_DIR="/home/fabric/work/my_artifacts"
   mkdir -p "$ARTIFACTS_DIR/<dir_name>"
   ```
   Use snake_case for the directory name (e.g. `install_docker`).
   The recipe is identified by having a `recipe.json` inside.

3. **Write recipe.json**:
```json
{
  "name": "Install Docker",
  "version": "1.0.0",
  "description": "Installs Docker Engine and adds user to docker group.",
  "image_patterns": {
    "ubuntu": "install_docker_ubuntu.sh",
    "rocky": "install_docker_rocky.sh",
    "centos": "install_docker_centos.sh",
    "debian": "install_docker_debian.sh",
    "*": "install_docker_ubuntu.sh"
  },
  "steps": [
    { "type": "upload_scripts" },
    {
      "type": "execute",
      "command": "chmod +x ~/.fabric/recipes/install_docker/*.sh && sudo bash ~/.fabric/recipes/install_docker/{script}"
    }
  ],
  "post_actions": []
}
```

**Field reference:**
- `image_patterns` — Maps OS family substring to script filename. The VM's image
  name is matched against these keys. `"*"` is the fallback if no key matches.
- `steps` — Ordered execution list:
  - `upload_scripts`: copies recipe files to `~/.fabric/recipes/<dir_name>/` on the VM.
  - `execute`: runs a command. `{script}` is replaced with the matched script filename.
- `post_actions` — Reserved for future use (leave as `[]`).

4. **Write install scripts** for each OS:
   - Start with `#!/bin/bash` and `set -e`
   - Use `### PROGRESS: message` markers for WebUI status updates
   - Use the appropriate package manager (apt for Ubuntu/Debian, dnf for Rocky/CentOS)
   - Make scripts idempotent (safe to re-run)

5. **Verify**: Read back all created files to confirm correctness.

## Tips

- Always include a `"*"` fallback in `image_patterns`
- Test with both Debian-family (apt) and RHEL-family (dnf) scripts
- Keep scripts under 100 lines — recipes are meant to be lightweight
