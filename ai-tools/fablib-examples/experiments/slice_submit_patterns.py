# Slice Submit Patterns — What submit() Actually Does
# Source: LoomAI — ground truth from FABlib API
#
# The submit() method has many parameters that control its behavior.
# This example shows the different patterns and when to use each.

from fabrictestbed_extensions.fablib.fablib import FablibManager


def submit_and_wait(slice_name: str):
    """Default pattern: submit, wait for ready, configure everything.

    submit(wait=True) blocks until StableOK, runs post_boot_config,
    waits for SSH, and returns when everything is ready.
    This is the simplest and recommended approach for small slices.
    """
    fablib = FablibManager()
    slice_obj = fablib.new_slice(name=slice_name)
    node = slice_obj.add_node(name="node1", site=None, cores=2, ram=8, disk=10)

    # Default: wait=True, post_boot_config=True, wait_ssh=True
    # This blocks for 5-15 minutes until everything is ready
    slice_obj.submit()

    # After submit with wait=True, the slice is ready to use
    # BUT: still re-fetch for fresh node objects
    slice_obj = fablib.get_slice(name=slice_name)
    node = slice_obj.get_node(name="node1")
    stdout, _ = node.execute("hostname")
    print(f"Node hostname: {stdout.strip()}")


def submit_no_wait(slice_name: str):
    """Non-blocking pattern: submit and poll separately.

    Use for large slices (>4 nodes) to avoid timeouts, or when you
    want to do other work while waiting.
    """
    fablib = FablibManager()
    slice_obj = fablib.new_slice(name=slice_name)
    for i in range(1, 5):
        slice_obj.add_node(name=f"node{i}", site=None, cores=2, ram=8, disk=10)

    # submit(wait=False) returns immediately after FABRIC accepts the request
    slice_obj.submit(wait=False)

    # Poll manually
    import time
    while True:
        slice_obj = fablib.get_slice(name=slice_name)
        state = str(slice_obj.get_state())
        print(f"### PROGRESS: State = {state}")
        if "StableOK" in state:
            break
        if "Error" in state or "Dead" in state:
            raise Exception(f"Slice failed: {state}")
        time.sleep(15)

    # Wait for SSH separately
    slice_obj.wait_ssh(progress=True)

    # Run post-boot config if needed
    slice_obj.post_boot_config()

    # Now ready to use
    for node in slice_obj.get_nodes():
        print(f"  {node.get_name()}: {node.get_management_ip()}")


def submit_with_lease(slice_name: str, hours: int = 24):
    """Submit with a specific lease duration."""
    fablib = FablibManager()
    slice_obj = fablib.new_slice(name=slice_name)
    slice_obj.add_node(name="node1", site=None, cores=2, ram=8, disk=10)

    # Set lease duration in hours
    slice_obj.submit(lease_in_hours=hours)

    slice_obj = fablib.get_slice(name=slice_name)
    print(f"Lease ends: {slice_obj.get_lease_end()}")


if __name__ == "__main__":
    import sys
    slice_name = sys.argv[1] if len(sys.argv) > 1 else "submit-test"
    submit_and_wait(slice_name)
