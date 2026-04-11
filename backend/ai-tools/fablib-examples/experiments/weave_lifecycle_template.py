# Weave Lifecycle Template — Golden Pattern for start/stop/monitor
# Source: LoomAI — canonical weave script structure
#
# Every weave script needs three functions: start(), stop(), monitor().
# This template shows the correct FABlib patterns including:
# - MAC-based IP retrieval (NOT IP prefix filtering)
# - Re-fetching slice after submit (node objects go stale)
# - PROGRESS markers for WebUI status display
# - Graceful error handling in stop/monitor
#
# Use this as the base for any create_weave script_content.

import sys
import os

from fabrictestbed_extensions.fablib.fablib import FablibManager


def get_fabnet_ip(node):
    """Get the FABNetv4 IP for a node after re-fetching the slice.

    add_fabnet() returns None and MACs are empty before submit, so use
    the network name pattern: FABNET_IPv4_{site_name}.
    Do NOT use get_fabnet_name() (doesn't exist), MAC matching (MACs empty
    before submit), or IP prefix filtering (10.128.0.0/10 spans 10.128-10.191).
    """
    site = node.get_site()
    iface = node.get_interface(network_name=f"FABNET_IPv4_{site}")
    if iface:
        return str(iface.get_ip_addr())
    return None


def start(slice_name: str):
    """Create and provision the experiment slice."""
    fablib = FablibManager()

    print(f"### PROGRESS: Creating slice '{slice_name}'")
    slice_obj = fablib.new_slice(name=slice_name)

    # Add nodes — use site=None for auto-placement
    # add_node() valid params: name, site, cores, ram, disk, image
    # There is NO tags parameter.
    node1 = slice_obj.add_node(name="node1", site=None, cores=2, ram=8, disk=10,
                                image="default_ubuntu_22")
    node2 = slice_obj.add_node(name="node2", site=None, cores=2, ram=8, disk=10,
                                image="default_ubuntu_22")

    # Add FABNetv4 networking
    node1.add_fabnet()  # returns None — do NOT capture return value
    node2.add_fabnet()  # returns None

    # Submit and wait for provisioning
    print("### PROGRESS: Submitting slice (3-10 minutes)...")
    slice_obj.submit()
    slice_obj.wait_ssh(progress=True)

    # CRITICAL: Re-fetch slice — original node objects go stale after submit
    slice_obj = fablib.get_slice(name=slice_name)
    node1 = slice_obj.get_node(name="node1")
    node2 = slice_obj.get_node(name="node2")

    # Get FABNetv4 IPs by network name pattern
    ip1 = get_fabnet_ip(node1)
    ip2 = get_fabnet_ip(node2)
    print(f"### PROGRESS: node1={ip1}, node2={ip2}")

    # --- Your experiment logic goes here ---
    print("### PROGRESS: Running experiment...")
    stdout, _ = node1.execute(f"ping -c 5 {ip2}")
    print(stdout)

    print(f"### PROGRESS: Experiment complete. Slice '{slice_name}' is ready.")


def stop(slice_name: str):
    """Delete the slice and free all FABRIC resources."""
    fablib = FablibManager()
    print(f"### PROGRESS: Deleting slice '{slice_name}'...")
    try:
        slice_obj = fablib.get_slice(name=slice_name)
        slice_obj.delete()
        print("### PROGRESS: Slice deleted.")
    except Exception as e:
        print(f"### PROGRESS: Could not delete (may already be gone): {e}")


def monitor(slice_name: str):
    """Check slice health. Exit 1 on failure (triggers cleanup in weave.sh)."""
    fablib = FablibManager()
    try:
        slice_obj = fablib.get_slice(name=slice_name)
        state = str(slice_obj.get_state())
        if "StableOK" not in state:
            print(f"### PROGRESS: WARNING — slice state is {state}")
            sys.exit(1)
        # Verify SSH to all nodes
        for node in slice_obj.get_nodes():
            stdout, _ = node.execute("echo ok", quiet=True)
            if "ok" not in stdout:
                raise Exception(f"Node {node.get_name()} not responding")
        print(f"### PROGRESS: Healthy — {state}")
    except Exception as e:
        print(f"### PROGRESS: ERROR — {e}")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: script.py {start|stop|monitor} SLICE_NAME")
        sys.exit(1)
    action, name = sys.argv[1], sys.argv[2]
    {"start": start, "stop": stop, "monitor": monitor}[action](name)
