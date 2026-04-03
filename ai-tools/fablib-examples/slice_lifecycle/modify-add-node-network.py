# Modify a Slice: Add and Remove Nodes and Networks
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: modify-add-node-network.ipynb
#
# FABRIC supports **live slice modification** — you can add or remove nodes,
# components, and networks from a running slice without tearing it down and
# starting over. This is powerful for iterative ex...

# # Modify a Slice: Add and Remove Nodes and Networks
# ### FABlib API References

# ## Step 1: Import the FABlib Library

from ipaddress import ip_address, IPv4Address, IPv6Address, IPv4Network, IPv6Network
import ipaddress

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()
                     
fablib.show_config();


# ## Step 2: Create the Initial Slice

slice_name = 'MySlice-modify-add-node-network'
[site1, site2, site3] = fablib.get_random_sites(count=3)

print(f"Sites: {site1}, {site2}, {site3}")

node1_name = 'Node1'
node2_name = 'Node2'
node3_name = 'Node3'
node4_name = 'Node4'

network1_name='net1'
network2_name='net2'
network3_name='net3'

#Create Slice
slice = fablib.new_slice(name=slice_name)

# Networks
net1 = slice.add_l2network(name=network1_name, subnet=IPv4Network("192.168.1.0/24"))


# Node1
node1 = slice.add_node(name=node1_name, site=site1)
iface1 = node1.add_component(model='NIC_Basic', name='nic1').get_interfaces()[0]
iface1.set_mode('auto')
net1.add_interface(iface1)


# Node2
node2 = slice.add_node(name=node2_name, site=site2)
iface2 = node2.add_component(model='NIC_Basic', name='nic1').get_interfaces()[0]
iface2.set_mode('auto')
net1.add_interface(iface2)


#Submit Slice Request
slice.submit();


# ## Step 3: Verify Initial Connectivity

slice = fablib.get_slice(slice_name)
node1 = slice.get_node(name=node1_name)
node2 = slice.get_node(name=node2_name)

node2_addr = node2.get_interface(network_name=network1_name).get_ip_addr()

stdout, stderr = node1.execute(f'ping -c 5 {node2_addr}')


# ## Step 4: Expand the Slice (Add Nodes and Networks)

## NOTE: Always get the latest slice topolgy before requesting any updates
slice = fablib.get_slice(slice_name)

# Add a Layer2 Network
net2 = slice.add_l2network(name=network2_name, subnet=IPv4Network("192.168.2.0/24"))


# Add Node3
node3 = slice.add_node(name=node3_name, site=site3)
iface3 = node3.add_component(model='NIC_Basic', name='nic1').get_interfaces()[0]
iface3.set_mode('auto')
net2.add_interface(iface3)

# Add NIC to Node1 and add connect to Node3
node1 = slice.get_node(name=node1_name)
iface4 = node1.add_component(model='NIC_Basic', name='nic2').get_interfaces()[0]
iface4.set_mode('auto')
net2.add_interface(iface4)


# Add a Layer2 Network
net3 = slice.add_l2network(name=network3_name, subnet=IPv4Network("192.168.3.0/24"))

# Add Node4
node4 = slice.add_node(name=node4_name, site=site1)
iface5 = node4.add_component(model='NIC_Basic', name='nic1').get_interfaces()[0]
iface5.set_mode('auto')
net3.add_interface(iface5)

# Add NIC to Node1 and add connect to Node3
node1 = slice.get_node(name=node1_name)
iface6 = node1.add_component(model='NIC_Basic', name='nic3').get_interfaces()[0]
iface6.set_mode('auto')
net3.add_interface(iface6)


# ### Submit the Expansion

slice.submit()


# ## Step 5: Verify Connectivity to New Nodes

slice = fablib.get_slice(slice_name)
node1 = slice.get_node(name=node1_name)
node3 = slice.get_node(name=node3_name)

node3_addr = node3.get_interface(network_name=network2_name).get_ip_addr()

stdout, stderr = node1.execute(f'ping -c 5 {node3_addr}')

slice = fablib.get_slice(slice_name)
node1 = slice.get_node(name=node1_name)
node4 = slice.get_node(name=node4_name)

node4_addr = node4.get_interface(network_name=network3_name).get_ip_addr()

stdout, stderr = node1.execute(f'ping -c 5 {node4_addr}')


# ## Step 6: Shrink the Slice (Remove Nodes and Networks)

## NOTE: Always get the latest slice topolgy before requesting any updates
slice = fablib.get_slice(slice_name)


# Removing NIC1 from Node1
node1 = slice.get_node(name=node1_name)
node1_nic1 = node1.get_component(name="nic1")
node1_nic1.delete()


# Removing Node2 from Slice
node2 = slice.get_node(name=node2_name)
node2.delete()


# Net1 is a wide area network and no longer have two participants after Node1 being removed
# Removing the network
net1 = slice.get_network(name=network1_name)
net1.delete()


# ### Submit the Removal

slice.submit()


# ## Continue Learning
# ## Step 7: Delete the Slice

slice = fablib.get_slice(slice_name)
slice.delete()
