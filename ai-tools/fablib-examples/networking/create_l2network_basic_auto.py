# Create a Local Ethernet (Layer 2) Network: Automatic IP Configuration
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: create_l2network_basic_auto.ipynb
#
# This notebook demonstrates how to create an isolated Layer 2 Ethernet network
# connecting two virtual machines at the same FABRIC site, using FABlib's
# automatic IP configuration to assign addresses ...

# # Create a Local Ethernet (Layer 2) Network: Automatic IP Configuration
# ### FABlib API References

# ## Step 1: Configure the Environment

from ipaddress import ip_address, IPv4Address, IPv6Address, IPv4Network, IPv6Network
import ipaddress

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()
                     
fablib.show_config();


# ## Step 2: Define the Slice Topology
# ### About L2 Networks on FABRIC
# ### How Automatic Configuration Works
# ### NIC Component Models

slice_name = 'MySlice'
site = fablib.get_random_site()
print(f"Site: {site}")

node1_name = 'Node1'
node2_name = 'Node2'

network_name='net1'


# ## Step 4: Submit the Slice

slice.submit();


# ## Step 3: Run the Experiment

slice = fablib.get_slice(slice_name)

node1 = slice.get_node(name=node1_name)        
node2 = slice.get_node(name=node2_name)           

node2_addr = node2.get_interface(network_name=network_name).get_ip_addr()

stdout, stderr = node1.execute(f'ping -c 5 {node2_addr}')


# ## Continue Learning
# ## Step 4: Delete the Slice

slice.delete()
