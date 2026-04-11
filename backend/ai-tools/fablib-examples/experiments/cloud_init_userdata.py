# Node Configuration with Cloud-Init Userdata
# Source: LoomAI — proven pattern for first-boot VM configuration
#
# Shows how to use FABlib's userdata feature to run cloud-init scripts on
# first boot. This is an alternative to post_boot_config for automated setup.
# Userdata runs before SSH is available, so the node is pre-configured when
# you first connect.

import sys

from fabrictestbed_extensions.fablib.fablib import FablibManager


def start(slice_name: str):
    """Create a slice with cloud-init userdata for automatic configuration."""
    fablib = FablibManager()

    # Cloud-init script — runs on first boot before SSH is ready
    userdata = """#!/bin/bash
set -e

# Update packages
apt-get update -qq
apt-get install -y -qq htop curl net-tools iperf3 jq

# Create a status file for verification
echo "cloud-init completed at $(date)" > /home/ubuntu/cloud-init-status.txt

# Configure a custom MOTD
cat > /etc/motd << 'MOTD'
=====================================
  FABRIC Experiment Node
  Configured by cloud-init
=====================================
MOTD

# Set up a simple system monitoring cron job
echo "*/5 * * * * root echo $(date) $(uptime) >> /var/log/system-health.log" > /etc/cron.d/health-monitor
"""

    print(f"### PROGRESS: Creating slice '{slice_name}' with cloud-init")
    slice_obj = fablib.new_slice(name=slice_name)

    node = slice_obj.add_node(
        name="configured-node",
        site=None,
        cores=2,
        ram=8,
        disk=10,
        image="default_ubuntu_22",
    )

    # Attach userdata — this is the cloud-init script
    node.set_user_data(userdata)

    print("### PROGRESS: Submitting slice with userdata...")
    slice_obj.submit()
    slice_obj.wait_ssh(progress=True)

    # Re-fetch (REQUIRED)
    slice_obj = fablib.get_slice(name=slice_name)
    node = slice_obj.get_node(name="configured-node")

    # Verify cloud-init ran
    print("### PROGRESS: Verifying cloud-init configuration...")
    stdout, _ = node.execute("cat /home/ubuntu/cloud-init-status.txt 2>/dev/null || echo 'not found'",
                              timeout=15)
    print(f"  Status: {stdout.strip()}")

    # Verify packages were installed
    for pkg in ["htop", "curl", "iperf3", "jq"]:
        stdout, _ = node.execute(f"which {pkg}", timeout=5)
        status = "OK" if stdout.strip() else "MISSING"
        print(f"  {pkg}: {status}")

    print("### PROGRESS: Cloud-init configuration verified!")


def stop(slice_name: str):
    fablib = FablibManager()
    try:
        fablib.get_slice(name=slice_name).delete()
        print("### PROGRESS: Slice deleted.")
    except Exception as e:
        print(f"### PROGRESS: {e}")


def monitor(slice_name: str):
    fablib = FablibManager()
    try:
        s = fablib.get_slice(name=slice_name)
        if "StableOK" not in str(s.get_state()):
            sys.exit(1)
        node = s.get_node(name="configured-node")
        node.execute("echo ok", quiet=True)
        print("### PROGRESS: Healthy")
    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: script.py {start|stop|monitor} SLICE_NAME")
        sys.exit(1)
    {"start": start, "stop": stop, "monitor": monitor}[sys.argv[1]](sys.argv[2])
