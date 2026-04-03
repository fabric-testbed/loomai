# FABRIC Userdata: Attaching Custom Metadata to Slice Objects
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: userdata.ipynb
#
# FABRIC allows you to store a small amount of arbitrary JSON data on any FABlib
# object — slices, nodes, networks, and interfaces. This **userdata** is
# persisted in the FABRIC slice model, which mean...

# # FABRIC Userdata: Attaching Custom Metadata to Slice Objects
# ### FABlib API References

# ## Step 1: Configure the Environment and Import FABlib

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()
                     
fablib.show_config();


# ## Step 2: Create the Experiment Slice

slice_name = 'MySlice100'
[site1,site2] = fablib.get_random_sites(count=2)
print(f"Sites: {site1}, {site2}")

node1_name = 'Node1'
node2_name = 'Node2'

network1_name='net1'
network2_name='net2'

#Create Slice
slice = fablib.new_slice(name=slice_name)

# Networks
net1 = slice.add_l3network(name=network1_name, type='IPv4')
net2 = slice.add_l3network(name=network2_name, type='IPv4')

# Node1
node1 = slice.add_node(name=node1_name, site=site1)
iface1 = node1.add_component(model='NIC_Basic', name='nic1').get_interfaces()[0]
iface1.set_mode('auto')
net1.add_interface(iface1)
node1.add_route(subnet=fablib.FABNETV4_SUBNET, next_hop=net1.get_gateway())

# Node2
node2 = slice.add_node(name=node2_name, site=site2)
iface2  = node2.add_component(model='NIC_Basic', name='nic1').get_interfaces()[0]
iface2.set_mode('auto')
net2.add_interface(iface2)
node2.add_route(subnet=fablib.FABNETV4_SUBNET, next_hop=net2.get_gateway())

# Add Userdata
userdata = node1.get_user_data()

print(userdata)

#Submit Slice Request
#slice.submit();


# ## Step 3: View the Userdata

node 
print


# ## Step 4: Edit and Save Userdata

# ## Step 5: Run the Experiment

slice = fablib.get_slice(slice_name)

node1 = slice.get_node(name=node1_name)        
node2 = slice.get_node(name=node2_name)           

node2_addr = node2.get_interface(network_name=network2_name).get_ip_addr()

stdout, stderr = node1.execute(f'ping -c 5 {node2_addr}')


# ## Step 6: Delete the Slice

slice.delete()

# ## Continue Learning
