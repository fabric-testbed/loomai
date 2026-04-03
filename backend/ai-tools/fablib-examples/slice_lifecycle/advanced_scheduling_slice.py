# Advanced Scheduling of Slices
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: advanced_scheduling_slice.ipynb
#
# FABRIC supports **advance reservations** — you can request scarce resources
# (SmartNICs, GPUs, FPGAs) for a future time window, even when they are
# currently unavailable. This notebook demonstrates t...

# # Advanced Scheduling of Slices
# ### FABlib API References
# ### Knowledge Base

# ## Step 1: Import the FABlib Library

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager
from fabrictestbed_extensions.fablib.constants import Constants
from ipaddress import ip_address, IPv4Address, IPv6Address, IPv4Network, IPv6Network
import ipaddress

fablib = fablib_manager()

fablib.show_config();


# ## Step 2: Query Resource Availability in a Future Time Window

fields=['name','cores_available','ram_available','disk_available','nic_connectx_6_available', 'nic_connectx_5_available']

from datetime import datetime
from datetime import timezone
from datetime import timedelta

start = (datetime.now(timezone.utc) + timedelta(days=1))
end = start + timedelta(days=1)

print(f"Start Time: {start}")
print(f"End Time: {start}")

output_table = fablib.list_sites(start=start, end=end, fields=fields)


# ## Advanced Resource Scheduling

# ### Step 3: Set Experiment Parameters

# Define parameters (modify these as needed)
slice_name = "AdvancedSchedulingSlice"  # Name for the new slice

node1_name = 'Node1'
node2_name = 'Node2'

network1_name='net1'

model = "NIC_ConnectX_5"

site1 = "LOSA"
site2 = "ATLA"


# ### Step 4: Define the Lease Duration

from datetime import datetime
from datetime import timezone
from datetime import timedelta

start = (datetime.now(timezone.utc) + timedelta(days=1))
end = start + timedelta(days=3)
lease_in_hours = 6


# ## Step 3 Create the Experiment Slice with Post-Boot Tasks

#Create Slice
slice = fablib.new_slice(name=slice_name)

# Network
net1 = slice.add_l2network(name=network1_name, subnet="192.168.1.0/24")

node1 = slice.add_node(name=node1_name, site=site1)
node1_iface1 = node1.add_component(model=model, name='nic1').get_interfaces()[0]

node1_iface1.set_mode('config')
net1.add_interface(node1_iface1)
node1_iface1.set_ip_addr(IPv4Address("192.168.1.1"))

node2 = slice.add_node(name=node2_name, site=site2)
node2_iface1 = node2.add_component(model=model, name='nic1').get_interfaces()[0]

node2_iface1.set_mode('config')
net1.add_interface(node2_iface1)
node2_iface1.set_ip_addr(IPv4Address("192.168.1.2"))


# Add Post Boot Tasks to the Nodes to execute once Lease Start becomes current
node1.add_post_boot_execute('sudo dnf install -y git')
node1.add_post_boot_execute('git clone https://github.com/kthare10/fabric-recipes.git')
node1.add_post_boot_execute('sudo fabric-recipes/node_tools/host_tune.sh')
node1.add_post_boot_execute('fabric-recipes/node_tools/enable_docker.sh')
node1.add_post_boot_execute('docker pull fabrictestbed/slice-vm-rocky8-multitool:0.0.2 ')


node2.add_post_boot_execute('sudo dnf install -y git')
node2.add_post_boot_execute('git clone https://github.com/kthare10/fabric-recipes.git')
node2.add_post_boot_execute('sudo fabric-recipes/node_tools/host_tune.sh')
node2.add_post_boot_execute('fabric-recipes/node_tools/enable_docker.sh')
node2.add_post_boot_execute('docker pull fabrictestbed/slice-vm-rocky8-multitool:0.0.2 ')


node1.add_post_boot_execute("docker run -d --rm "
                            "--network host "
                            "fabrictestbed/slice-vm-rocky8-multitool:0.0.2 "
                            f"iperf3 -s -1 > {node1.get_name()}.log 2>&1");


node2.add_post_boot_execute("docker run --rm "
                            "--network host "
                            "fabrictestbed/slice-vm-rocky8-multitool:0.0.2 "
                            f"iperf3 -c 192.168.1.1 -P 4 -t 30 -i 10 -O 10 > {node2.get_name()}.log 2>&1");

slice.submit(lease_start_time=start, lease_end_time=end, lease_in_hours=lease_in_hours)


# ## Step 4 Wait for the Slice to Become Active (Optional, Blocking)

slice = fablib.get_slice(slice_name)

# Determine the wait timeout
timeout = (datetime.strptime(slice.get_lease_start(), Constants.LEASE_TIME_FORMAT) - datetime.now(timezone.utc)).total_seconds() + 1500

print(f"Waiting for timeout: {timeout} seconds")

slice.wait_ssh(timeout=timeout)

slice.post_boot_config()


# ## Step 5 Review Experiment Results

stdout, stderr = node1.execute(f"cat {node1.get_name()}.log")
stdout, stderr = node2.execute(f"cat {node2.get_name()}.log")


# ## Continue Learning
# ## Step 6 Delete the Slice

slice.delete()
