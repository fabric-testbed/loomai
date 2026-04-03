# VLAN Sub-Interfaces on Dedicated NIC Cards
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: sub_interfaces.ipynb
#
# **Sub-interfaces** (also called VLAN sub-interfaces or virtual interfaces)
# allow a single physical network port to carry multiple independent logical
# networks simultaneously by tagging each frame w...

# # VLAN Sub-Interfaces on Dedicated NIC Cards
# ### FABlib API References
# ### Knowledge Base

# ## Step 1: Configure the Environment

from ipaddress import ip_address, IPv4Address, IPv6Address, IPv4Network, IPv6Network
import ipaddress

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()
                     
fablib.show_config();


# ## Step 2: Create the Experiment Slice
# ### Topology Overview

# ### Step 3a: Define Variables

slice_name = 'MySlice'

node1_name = 'Node1'
node2_name = 'Node2'

network1_name='net1'
network2_name='net2'
network3_name='net3'

model = "NIC_ConnectX_6"


# ### Step 3b: Find Sites with ConnectX-6 Availability

# we will use CX5 to generate traffic and CX6 to mirror traffic into so need sites that have both for this example.
cx5_column_name = 'nic_connectx_5_available'
cx6_column_name = 'nic_connectx_6_available'

# find two sites with available ConnectX-5 and ConnectX-6 cards
(site1, site2) = fablib.get_random_sites(count=2, filter_function=lambda x: x[cx6_column_name] > 0)

print(f"Sites chosen: {site1} {site2}")


# ### Step 3c: Create the Slice and Define the Networks

#Create Slice
slice = fablib.new_slice(name=slice_name)


# ### Network Setup

# Networks
net1 = slice.add_l3network(name=network1_name, type='IPv4')
net2 = slice.add_l3network(name=network2_name, type='IPv4')
net3 = slice.add_l2network(name=network3_name, subnet="192.168.1.0/24")


# ### Step 3d: Configure Node1

node1 = slice.add_node(name=node1_name, site=site1)
node1_iface1 = node1.add_component(model=model, name='nic1').get_interfaces()[0]

node1_ch_iface1 = node1_iface1.add_sub_interface("child1", vlan="100")
node1_ch_iface1.set_mode('auto')
net1.add_interface(node1_ch_iface1)
node1.add_route(subnet=fablib.FABNETV4_SUBNET, next_hop=net1.get_gateway())


node1_ch_iface2 = node1_iface1.add_sub_interface("child2", vlan="200")
node1_ch_iface2.set_mode('auto')
net3.add_interface(node1_ch_iface2)


# ### Step 3e: Configure Node2

node2 = slice.add_node(name=node2_name, site=site2)
node2_iface1 = node2.add_component(model=model, name='nic1').get_interfaces()[0]

node2_ch_iface1 = node2_iface1.add_sub_interface("child1", vlan="100")
node2_ch_iface1.set_mode('auto')
net2.add_interface(node2_ch_iface1)
node2.add_route(subnet=fablib.FABNETV4_SUBNET, next_hop=net2.get_gateway())

node2_ch_iface2 = node2_iface1.add_sub_interface("child2", vlan="200")
node2_ch_iface2.set_mode('auto')
net3.add_interface(node2_ch_iface2)


# ### Step 3f: Submit the Slice

slice.submit()


# ## Step 3: Run the Experiment

slice = fablib.get_slice(slice_name)

node1 = slice.get_node(name=node1_name)        
node2 = slice.get_node(name=node2_name)           

node2_addr = node2.get_interface(network_name=network2_name).get_ip_addr()

stdout, stderr = node1.execute(f'ping -c 5 {node2_addr}')

slice = fablib.get_slice(slice_name)

node1 = slice.get_node(name=node1_name)        
node2 = slice.get_node(name=node2_name)           

node2_addr = node2.get_interface(network_name=network3_name).get_ip_addr()

stdout, stderr = node1.execute(f'ping -c 5 {node2_addr}')


# ## Continue Learning
# ## Step 4: Delete the Slice

slice.delete()
