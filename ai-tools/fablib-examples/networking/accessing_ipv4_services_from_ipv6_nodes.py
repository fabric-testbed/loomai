# Accessing IPv4 Services from IPv6 FABRIC Nodes
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: accessing_ipv4_services_from_ipv6_nodes.ipynb
#
# Most FABRIC sites use IPv6 for their management network — the channel through
# which you SSH into your VMs. This is fine for communicating between FABRIC
# nodes, but it means your VMs cannot natively...

# # Accessing IPv4 Services from IPv6 FABRIC Nodes
# ### FABlib API References
# ### External References

# ## Step 1: Configure the Environment and Import FABlib

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()

fablib.show_config();


# ## Step 2: Create a Node at an IPv6 Site

slice_name = "IPv4FromIPv6"

#Create a slice
slice = fablib.new_slice(name=slice_name)

# Add a node. (We want an IPv6 site so avoid IPv4 sites)
# Add a node. TACC and MAX are both IPv4 sites. Since we
# want an IPv6 site, we will avoid those two sites.
slice.add_node(name="Node1", avoid=['TACC','MAX'])

slice.submit();


# ## Step 3: Confirm the Node Has an IPv6 Address

for node in slice.get_nodes():
    print(f"{node}")


# ## Step 4: Upload and Run the NAT64 Configuration Script

from ipaddress import ip_address, IPv6Address

node = slice.get_node(name="Node1")     

# If the node is an IPv6 Node then configure NAT64
if type(ip_address(node.get_management_ip())) is IPv6Address:
    node.upload_file('nat64.sh', 'nat64.sh')

    stdout, stderr = node.execute(f'chmod +x nat64.sh && ./nat64.sh')

# Access non-IPv6 Services
stdout, stderr = node.execute(f'sudo yum install -y -q git && git clone https://github.com/fabric-testbed/jupyter-examples.git')

stdout, stderr = node.execute(f'ls jupyter-examples')


# ## Step 5: Delete the Slice

slice.delete()

# ## Continue Learning
