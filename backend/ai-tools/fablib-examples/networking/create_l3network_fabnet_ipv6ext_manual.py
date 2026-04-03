# FABnet IPv6Ext: External Access with Manual Configuration
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: create_l3network_fabnet_ipv6ext_manual.ipynb
#
# FABRIC provides **FABnetv6Ext**, a routed IPv6 service that spans every FABRIC
# site and additionally provides **publicly routable IPv6 addresses** — enabling
# your experiment nodes to communicate wi...

# # FABnet IPv6Ext: External Access with Manual Configuration
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

# External IPv6 network to route to — replace with your target external subnet
# Example: Caltech IPv6 subnet
external_network_subnet = '2605:d9c0:2:10::2:210/64'

#Create Slice
slice = fablib.new_slice(name=slice_name)

# Node1
node1 = slice.add_node(name=node1_name, site=site1)
iface1 = node1.add_component(model='NIC_Basic', name=node1_nic_name).get_interfaces()[0]

# Node2
node2 = slice.add_node(name=node2_name, site=site2)
iface2  = node2.add_component(model='NIC_Basic', name=node2_nic_name).get_interfaces()[0]

# Networks — type='IPv6Ext' enables external internet access via publicly routable IPv6
net1 = slice.add_l3network(name=network1_name, interfaces=[iface1], type='IPv6Ext')
net2 = slice.add_l3network(name=network2_name, interfaces=[iface2], type='IPv6Ext')

#Submit Slice Request
slice.submit();


# ## Step 4: Inspect Assigned IPv6 Prefixes

slice=fablib.get_slice(name=slice_name)
network1 = slice.get_network(name=network1_name)
network1_available_ips = network1.get_available_ips()
network1.show()

network2 = slice.get_network(name=network2_name)
network2_available_ips =  network2.get_available_ips()
network2.show();


# ## Step 5: Request Publicly Routable IPv6 Addresses

try:
    
    # Request public IPv6 routing for the first available address on each network
    network1.make_ip_publicly_routable(ipv6=[str(network1_available_ips[0])])
    network2.make_ip_publicly_routable(ipv6=[str(network2_available_ips[0])])

    slice.submit()

except Exception as e:
    print(f"Exception: {e}")
    import traceback
    traceback.print_exc()


# ## Step 6: Configure IPv6 Addresses and Routes on Each Node
# ### Configure Node1

node1 = slice.get_node(name=node1_name)        
node1_iface = node1.get_interface(network_name=network1_name)  
node1_addr = network1.get_public_ips()[0]
node1_iface.ip_addr_add(addr=node1_addr, subnet=network1.get_subnet())

# Route to the other FABRIC site's subnet
node1.ip_route_add(subnet=network2.get_subnet(), gateway=network1.get_gateway())

# Route to specific external IPv6 subnet — NOT a default route
# Replace external_network_subnet with your external destination
stdout, stderr = node1.execute(f'ip route add {external_network_subnet} via {network1.get_gateway()} dev {node1_iface.get_device_name()}')

stdout, stderr = node1.execute(f'ip addr show {node1_iface.get_device_name()}')    
stdout, stderr = node1.execute(f'ip -6 route list')


# ### Configure Node2

node2 = slice.get_node(name=node2_name)        
node2_iface = node2.get_interface(network_name=network2_name) 
node2_addr = network2.get_public_ips()[0]
node2_iface.ip_addr_add(addr=node2_addr, subnet=network2.get_subnet())

node2.ip_route_add(subnet=network1.get_subnet(), gateway=network2.get_gateway())

# Route to specific external IPv6 subnet
stdout, stderr = node2.execute(f'ip route add {external_network_subnet} via {network2.get_gateway()} dev {node2_iface.get_device_name()}')

stdout, stderr = node2.execute(f'ip addr show {node2_iface.get_device_name()}')
stdout, stderr = node2.execute(f'ip -6 route list')


# ## Step 7: Run the Experiment

slice = fablib.get_slice(slice_name)

node1 = slice.get_node(name=node1_name)        
node2 = slice.get_node(name=node2_name)           

node2_addr = node2.get_interface(network_name=network2_name).get_ip_addr()

# Verify FABRIC inter-site IPv6 connectivity
stdout, stderr = node1.execute(f'ping -c 5 {node2_addr}')  

# Verify external IPv6 internet connectivity from Node1
stdout, stderr = node1.execute(f'sudo ping -c 5 -I {node1_iface.get_device_name()} bing.com')  

# Verify external IPv6 internet connectivity from Node2
stdout, stderr = node2.execute(f'sudo ping -c 5 -I {node2_iface.get_device_name()} bing.com')


# ## Step 8: Continue Learning

# ## Step 9: Delete the Slice

slice = fablib.get_slice(name=slice_name)
slice.delete()
