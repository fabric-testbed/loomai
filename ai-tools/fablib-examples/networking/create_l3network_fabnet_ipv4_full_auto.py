# FABnet IPv4: Fully Automatic Configuration
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: create_l3network_fabnet_ipv4_full_auto.ipynb
#
# FABRIC provides **FABnetv4**, a private IPv4 overlay network that spans every
# FABRIC site — a dedicated research internet connecting nodes across
# geographically distributed sites over FABRIC's high...

# # FABnet IPv4: Fully Automatic Configuration
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

#Create Slice
slice = fablib.new_slice(name=slice_name)

# Node1 — add_fabnet() adds the NIC, creates the site FABnet network, and enables auto config
node1 = slice.add_node(name=node1_name, site=site1)
node1.add_fabnet()

# Node2
node2 = slice.add_node(name=node2_name, site=site2)
node2.add_fabnet()

#Submit Slice Request — IPs and routes are configured automatically during boot
slice.submit();


# ## Step 4: Run the Experiment

slice = fablib.get_slice(slice_name)

node1 = slice.get_node(name=node1_name)        
node2 = slice.get_node(name=node2_name)           

# The FABnet network name is auto-generated as FABNET_IPv4_{site_name}
node2_addr = node2.get_interface(network_name=f'FABNET_IPv4_{node2.get_site()}').get_ip_addr()

stdout, stderr = node1.execute(f'ping -c 5 {node2_addr}')


# ## Step 5: Continue Learning

# ## Step 6: Delete the Slice

slice = fablib.get_slice(name=slice_name)
slice.delete()
