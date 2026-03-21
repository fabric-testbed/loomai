#!/usr/bin/env python3
"""
Hello FABRIC - A simple example of managing a FABRIC slice.

This script demonstrates the three core operations every weave needs:
  - start:   Create a slice, submit it, and wait until it's ready
  - stop:    Delete the slice and free the resources
  - monitor: Check that the slice is healthy and nodes are reachable

Usage:
    python3 hello_fabric.py start   my-slice-name
    python3 hello_fabric.py stop    my-slice-name
    python3 hello_fabric.py monitor my-slice-name

The weave.sh script calls these commands automatically.
"""
import sys

# FABlib is the Python library for managing FABRIC slices.
# We import it inside each function so the script loads quickly.
from fabrictestbed_extensions.fablib.fablib import FablibManager


def start(slice_name):
    """Create a single-node FABRIC slice and wait for it to be ready."""
    fablib = FablibManager()

    # Step 1: Create a new slice with one node
    print(f"### PROGRESS: Creating slice '{slice_name}'...")
    my_slice = fablib.new_slice(name=slice_name)

    # Add a small Ubuntu VM (site is omitted — FABRIC picks one automatically)
    my_slice.add_node(
        name="node1",
        cores=2,             # 2 CPU cores
        ram=8,               # 8 GB RAM
        disk=10,             # 10 GB disk
        image="default_ubuntu_22",
    )

    # Step 2: Submit the slice to FABRIC for provisioning
    print("### PROGRESS: Submitting slice to FABRIC...")
    my_slice.submit()

    # Step 3: Wait until we can SSH into all nodes
    print("### PROGRESS: Waiting for SSH access (this may take a few minutes)...")
    my_slice.wait_ssh(progress=True)

    # Done! Print the node info
    print(f"### PROGRESS: Slice '{slice_name}' is ready!")
    for node in my_slice.get_nodes():
        print(f"  {node.get_name()}: {node.get_management_ip()}")


def stop(slice_name):
    """Delete the slice and free all resources."""
    fablib = FablibManager()

    try:
        my_slice = fablib.get_slice(name=slice_name)
        print(f"### PROGRESS: Deleting slice '{slice_name}'...")
        my_slice.delete()
        print(f"### PROGRESS: Slice '{slice_name}' deleted.")
    except Exception as e:
        # It's OK if the slice is already gone
        print(f"### PROGRESS: Slice not found or already deleted: {e}")


def monitor(slice_name):
    """Check that the slice is healthy and all nodes respond to commands.

    Exits with code 0 if everything is OK, or code 1 if something is wrong.
    The weave.sh script uses this exit code to detect failures.
    """
    fablib = FablibManager()

    # Check 1: Is the slice in a good state?
    my_slice = fablib.get_slice(name=slice_name)
    state = str(my_slice.get_state())

    if "StableOK" not in state:
        print(f"ERROR: Slice state is {state} (expected StableOK)")
        sys.exit(1)

    # Check 2: Can we run a command on each node via SSH?
    for node in my_slice.get_nodes():
        try:
            stdout, stderr = node.execute("echo ok", quiet=True)
            if "ok" not in stdout:
                raise Exception("unexpected output from test command")
        except Exception as e:
            print(f"ERROR: Node {node.get_name()} health check failed: {e}")
            sys.exit(1)

    # All checks passed
    print(f"### PROGRESS: All nodes healthy (state: {state})")


# --- Main: parse the command-line arguments ---

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: hello_fabric.py {start|stop|monitor} SLICE_NAME")
        sys.exit(1)

    action = sys.argv[1]    # "start", "stop", or "monitor"
    slice_name = sys.argv[2]

    if action == "start":
        start(slice_name)
    elif action == "stop":
        stop(slice_name)
    elif action == "monitor":
        monitor(slice_name)
    else:
        print(f"Unknown action: {action}")
        print("Usage: hello_fabric.py {start|stop|monitor} SLICE_NAME")
        sys.exit(1)
