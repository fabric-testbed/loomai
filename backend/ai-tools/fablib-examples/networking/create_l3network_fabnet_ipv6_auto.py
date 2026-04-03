# FABnet IPv6: Automatic IP Configuration
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: create_l3network_fabnet_ipv6_auto.ipynb
#
# FABRIC provides **FABnetv6**, a private IPv6 overlay network spanning every
# FABRIC site. Nodes at different geographic locations can route IPv6 packets to
# each other over FABRIC's high-performance ...

# # FABnet IPv6: Automatic IP Configuration
# ### FABlib API References
# ### Knowledge Base

# ## Step 1: Configure the Environment

# ## Step 2: Import the FABlib Library

from ipaddress import ip_address, IPv4Address, IPv6Address, IPv4Network, IPv6Network
import ipaddress

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()
                     
fablib.show_config();


# ## Step 3: Define Slice Parameters and Build the Topology

slice_name = 'MySlice'
[site1,site2] = fablib.get_random_sites(count=2)
print(f"Sites: {site1}, {site2}")

node1_name = 'Node1'
node2_name = 'Node2'

network1_name='net1'
network2_name='net2'

#Create Slice
slice = fablib.new_slice(name=slice_name)

# Networks created first so get_gateway() and get_subnet() are available for route pre-declaration
net1 = slice.add_l3network(name=network1_name, type='IPv6')
net2 = slice.add_l3network(name=network2_name, type='IPv6')

# Node1 — set_mode('auto') enables FABlib post-boot IPv6 assignment
node1 = slice.add_node(name=node1_name, site=site1)
iface1 = node1.add_component(model='NIC_Basic', name='nic1').get_interfaces()[0]
iface1.set_mode('auto')
net1.add_interface(iface1)
node1.add_route(subnet=net2.get_subnet(), next_hop=net1.get_gateway())

# Node2
node2 = slice.add_node(name=node2_name, site=site2)
iface2  = node2.add_component(model='NIC_Basic', name='nic1').get_interfaces()[0]
iface2.set_mode('auto')
net2.add_interface(iface2)
node2.add_route(subnet=net1.get_subnet(), next_hop=net2.get_gateway())

#Submit Slice Request — FABlib configures IPv6 addresses and routes at boot
slice.submit();


# ## Step 4: Run the Experiment

slice = fablib.get_slice(slice_name)

node1 = slice.get_node(name=node1_name)        
node2 = slice.get_node(name=node2_name)           

node2_addr = node2.get_interface(network_name=network2_name).get_ip_addr()

stdout, stderr = node1.execute(f'ping -c 5 {node2_addr}')


# ## Step 5: Continue Learning

# ## Step 6: Delete the Slice

slice = fablib.get_slice(name=slice_name)
slice.delete()
