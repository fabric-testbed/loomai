# FABnet IPv6: Manual IP Configuration
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: create_l3network_fabnet_ipv6_manual.ipynb
#
# FABRIC provides **FABnetv6**, a private IPv6 overlay network that spans every
# FABRIC site — analogous to FABnetv4 but using IPv6 addressing. Nodes at
# different geographic sites can route IPv6 packe...

# # FABnet IPv6: Manual IP Configuration
# ### FABlib API References
# ### Knowledge Base

# ## Step 1: Configure the Environment

# ## Step 2: Import the FABlib Library

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

node1_nic_name = 'nic1'
node2_nic_name = 'nic2'

#Create Slice
slice = fablib.new_slice(name=slice_name)

# Node1
node1 = slice.add_node(name=node1_name, site=site1)
iface1 = node1.add_component(model='NIC_Basic', name=node1_nic_name).get_interfaces()[0]

# Node2
node2 = slice.add_node(name=node2_name, site=site2)
iface2  = node2.add_component(model='NIC_Basic', name=node2_nic_name).get_interfaces()[0]

# Networks — type='IPv6' requests FABnetv6 service
net1 = slice.add_l3network(name=network1_name, interfaces=[iface1], type='IPv6')
net2 = slice.add_l3network(name=network2_name, interfaces=[iface2], type='IPv6')

#Submit Slice Request
slice.submit();


# ## Step 4: Manually Configure IPv6 Addresses
# ### Get the Assigned Prefixes

network1 = slice.get_network(name=network1_name)
network1_available_ips = network1.get_available_ips()
network1.show()

network2 = slice.get_network(name=network2_name)
network2_available_ips =  network2.get_available_ips()
network2.show();


# ### Configure Node1

node1 = slice.get_node(name=node1_name)        
node1_iface = node1.get_interface(network_name=network1_name)  
node1_addr = network1_available_ips.pop(0)
node1_iface.ip_addr_add(addr=node1_addr, subnet=network1.get_subnet())

node1.ip_route_add(subnet=network2.get_subnet(), gateway=network1.get_gateway())

stdout, stderr = node1.execute(f'ip addr show {node1_iface.get_device_name()}')
stdout, stderr = node1.execute(f'ip route list')


# ### Configure Node2

node2 = slice.get_node(name=node2_name)        
node2_iface = node2.get_interface(network_name=network2_name) 
node2_addr = network2_available_ips.pop(0)
node2_iface.ip_addr_add(addr=node2_addr, subnet=network2.get_subnet())

node2.ip_route_add(subnet=network1.get_subnet(), gateway=network2.get_gateway())

stdout, stderr = node2.execute(f'ip addr show {node2_iface.get_device_name()}')
stdout, stderr = node2.execute(f'ip route list')


# ## Step 5: Run the Experiment

node1 = slice.get_node(name=node1_name)        

stdout, stderr = node1.execute(f'ping -c 5 {node2_addr}')


# ## Step 6: Continue Learning

# ## Step 7: Delete the Slice

slice = fablib.get_slice(name=slice_name)
slice.delete()
