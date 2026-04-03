name: install-software
description: Install software tools on FABRIC VMs with OS detection and proper packaging
---
Help the user install software on FABRIC VM nodes.

1. **Identify the target**:
   - `get_slice(slice_name)` — verify slice is StableOK
   - `get_slice(slice_name, node_name)` — get node image/OS

2. **Detect OS** on the node:
   ```
   ssh_execute(slice, node, "cat /etc/os-release | head -5")
   ```
   - Ubuntu/Debian → `apt-get`
   - Rocky/CentOS/Fedora → `dnf` (or `yum` for older)
   - FreeBSD → `pkg`

3. **Install** using the correct package manager:
   - Always use `-y` for non-interactive
   - Use `-qq` (apt) or `-q` (dnf) for quiet output
   - Prefer upstream repos over distro packages for latest versions
   - Run `sudo apt-get update` or `sudo dnf makecache` first

4. **Common installs** (use upstream sources):
   - **Docker**: `curl -fsSL https://get.docker.com | sudo bash`
   - **NVIDIA drivers**: `sudo apt install -y nvidia-driver-535` (Ubuntu)
   - **Python packages**: `pip install --user <package>`
   - **Node.js**: `curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash -`

5. **Make it reusable** — offer to save as:
   - **Recipe**: OS-specific install scripts in user's `work/my_artifacts/` directory
   - **Weave script**: `tools/setup.sh` with `### PROGRESS:` markers for weaves
   - **Boot config command**: inline command for simple installs

6. **Verify installation**:
   ```
   ssh_execute(slice, node, "<tool> --version")
   ```

**Tips:**
- For multi-node installs, write a script and upload to all nodes
- Use `set -e` in scripts so failures are caught early
- Check if already installed before re-installing (idempotent)
- GPU software (CUDA, drivers) needs a reboot after install
