# Create a Local Ethernet (Layer 2) Network: Manual IP Configuration
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: create_l2network_basic_manual.ipynb
#
# This notebook demonstrates how to create an isolated Layer 2 Ethernet network
# connecting two virtual machines at the same FABRIC site, then manually assign
# IP addresses and verify connectivity with...

# # Create a Local Ethernet (Layer 2) Network: Manual IP Configuration
# ### FABlib API References

# ## Step 1: Configure the Environment

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()
                     
fablib.show_config();


# ## Step 2: Define the Slice Topology
# ### About L2 Networks on FABRIC
# ### NIC Component Models

slice_name = 'MySlice'

site = fablib.get_random_site()
print(f"Site: {site}")

node1_name = 'Node1'
node2_name = 'Node2'
network_name='net1'
node1_nic_name = 'nic1'
node2_nic_name = 'nic2'


# ## Step 4: Submit the Slice

slice.submit();


# ## Step 3: Configure IP Addresses Manually
# ### Why Manual Configuration?
# ### Pick a Subnet

from ipaddress import ip_address, IPv4Address, IPv6Address, IPv4Network, IPv6Network

subnet = IPv4Network("192.168.1.0/24")
available_ips = list(subnet)[1:]


# ### Configure Node1

node1 = slice.get_node(name=node1_name)        
node1_iface = node1.get_interface(network_name=network_name) 
node1_addr = available_ips.pop(0)
node1_iface.ip_addr_add(addr=node1_addr, subnet=subnet)

stdout, stderr = node1.execute(f'ip addr show {node1_iface.get_device_name()}')


# ### Configure Node2

node2 = slice.get_node(name=node2_name)        
node2_iface = node2.get_interface(network_name=network_name)  
node2_addr = available_ips.pop(0)
node2_iface.ip_addr_add(addr=node2_addr, subnet=subnet)

stdout, stderr = node2.execute(f'ip addr show {node2_iface.get_device_name()}')


# ## Step 4: Run the Experiment

node1 = slice.get_node(name=node1_name)        

stdout, stderr = node1.execute(f'ping -c 5 {node2_addr}')


# ## Continue Learning
# ## Step 5: Delete the Slice

slice = fablib.get_slice(name=slice_name)
slice.delete()
