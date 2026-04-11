# Multi-Node Parallel Software Installation
# Source: LoomAI — proven pattern for installing packages on FABRIC VMs
#
# Shows how to install software on multiple nodes after provisioning.
# Uses sequential installation (parallel via threads is also possible
# but sequential is simpler and avoids SSH connection limits).

from fabrictestbed_extensions.fablib.fablib import FablibManager


def install_packages(slice_name: str, packages: list):
    """Install packages on all nodes in a slice.

    Args:
        slice_name: Name of a StableOK slice
        packages: List of apt package names (e.g., ["iperf3", "htop", "curl"])
    """
    fablib = FablibManager()

    # Always re-fetch the slice to get fresh node objects
    slice_obj = fablib.get_slice(name=slice_name)
    nodes = slice_obj.get_nodes()

    pkg_str = " ".join(packages)
    print(f"### PROGRESS: Installing {pkg_str} on {len(nodes)} nodes")

    for node in nodes:
        name = node.get_name()
        print(f"### PROGRESS: Installing on {name}...")
        try:
            # Use -qq for quiet output, -y for non-interactive
            stdout, stderr = node.execute(
                f"sudo apt-get update -qq && sudo apt-get install -y -qq {pkg_str}",
                timeout=600,
            )
            # Verify installation
            for pkg in packages:
                stdout_check, _ = node.execute(f"which {pkg} || dpkg -l {pkg} 2>/dev/null | grep ^ii",
                                                timeout=10)
                if stdout_check.strip():
                    print(f"  {name}: {pkg} OK")
                else:
                    print(f"  {name}: {pkg} FAILED — not found after install")
        except Exception as e:
            print(f"  {name}: ERROR — {e}")

    print("### PROGRESS: Installation complete")


# Example usage
if __name__ == "__main__":
    import sys
    slice_name = sys.argv[1] if len(sys.argv) > 1 else "my-slice"
    install_packages(slice_name, ["iperf3", "htop", "curl", "net-tools"])
