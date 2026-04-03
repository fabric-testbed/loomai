# Add and Remove SSH Keys on Running Slice Nodes
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: ssh_keys.ipynb
#
# SSH access to FABRIC VMs is controlled by the `~/.ssh/authorized_keys` file on
# each node. FABRIC's **Perform Operational Actions (POA)** mechanism allows you
# to add or remove SSH keys on VMs that a...

# # Add and Remove SSH Keys on Running Slice Nodes
# ### FABlib API References
# ### Knowledge Base

# ## Step 1: Configure the Environment
# ## Step 2: Import the FABlib Library

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()

fablib.show_config();


# ## Step 3: Select Your Slice

my_existing_slice = True
slice_name = 'MySlice-lan'


# ## Step 4 (Optional): Create a Demonstration Slice

if not my_existing_slice:
    slice_name = 'SSH-Keys'
    site = fablib.get_random_site()
    print(f"Sites: {site}")
    
    node1_name='Node1'
    node2_name='Node2'
    
    network_name='net1'
    
    from ipaddress import IPv4Network
    
    subnet = IPv4Network("192.168.1.0/24")
    
    #Create Slice
    slice = fablib.new_slice(name=slice_name)
    
    net1 = slice.add_l2network(name=network_name, subnet=subnet)
    
    # Node1
    node1 = slice.add_node(name=node1_name, site=site)
    iface1 = node1.add_component(model='NIC_Basic', name='nic1').get_interfaces()[0]
    iface1.set_mode('auto')
    net1.add_interface(iface1)
    
    # Node2
    node2 = slice.add_node(name=node2_name, site=site)
    iface2 = node2.add_component(model='NIC_Basic', name='nic1').get_interfaces()[0]
    iface2.set_mode('auto')
    net1.add_interface(iface2)
    
    
    #Submit Slice Request
    slice.submit();


# ## Step 5: Retrieve the Slice

slice = fablib.get_slice(slice_name)


# ## Step 6: Add SSH Keys
# ### Option 1: Add a Key by Sliver Key Name (Recommended)

# ### **Option 1: Grant a User Access to Your Slice by Adding Their SSH Keys**
# #### Adding Your Own SSH Key
# #### Adding Another User's SSH Key

sliver_key_name = "REPLACE_WITH_COLLABORATOR_SLIVER_KEY_NAME"
email = "REPLACE_WITH_COLLABORATOR_EMAIL"

for node in slice.get_nodes():
    node.add_public_key(sliver_key_name=sliver_key_name, email=email)


# ### Option 2: Add a Key by Public Key String

public_key_string = "REPLACE_WITH_PUBLIC_KEY_STRING"

# Comment it when using the public key string, set to None to ensure the next cell is skipped
public_key_string = None

if public_key_string:
    for node in slice.get_nodes():
        node.add_public_key(public_key_string=public_key_string)


# ### Verify Key Installation

for node in slice.get_nodes():
    node.execute("cat ~/.ssh/authorized_keys")
    print("XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX")


# ## Step 7: Remove SSH Keys
# ### Option 1: Remove a Key by Sliver Key Name

# ## **Option 1: Remove an SSH Key Using `sliver_key_name`**
# ### Removing Your Own SSH Key
# ### Removing Another User’s SSH Key

sliver_key_name = "REPLACE_WITH_COLLABORATOR_SLIVER_KEY_NAME"
email = "REPLACE_WITH_COLLABORATOR_EMAIL"

for node in slice.get_nodes():
    # Add Collaborator's Portal Public Key to the Node by passing the sliver key name and email
    node.remove_public_key(sliver_key_name=sliver_key_name, email=email)


# ### Option 2: Remove a Key by Public Key String

public_key_string = "REPLACE_WITH_PUBLIC_KEY_STRING"

# Comment it when using the public key string, set to None to ensure the next cell is skipped
public_key_string = None

if public_key_string:
    for node in slice.get_nodes():
        
        # Add Public Key to the Node by passing the public key string
        node.remove_public_key(sliver_public_key=public_key_string)


# ### Verify Key Removal
# ## Continue Learning

for node in slice.get_nodes():
    node.execute("cat ~/.ssh/authorized_keys")
    print("XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX")


# ## Step 8: Delete the Slice

if not my_existing_slice:
    slice = fablib.get_slice(slice_name)
    slice.delete()
