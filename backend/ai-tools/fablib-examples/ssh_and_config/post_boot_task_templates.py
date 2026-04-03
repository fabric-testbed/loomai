# Post Boot Task Templates
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: post_boot_task_templates.ipynb
#
# The [Post Boot Tasks](../post_boot_tasks/post_boot_tasks.ipynb) notebook shows
# how to run the same script on all nodes automatically at boot. But what if
# each node needs slightly different argument...

# # Post Boot Task Templates
# ### FABlib API References
# ### External Documentation

# ## Step 1: Configure the Environment and Import FABlib

# ## Step 1: Create the Slice with a Templated Post Boot Command

slice_name="MySlice2"

site=fablib.get_random_site()

#Create a slice
slice = fablib.new_slice(name=slice_name)


for i in range(4):
    # Add a node
    node = slice.add_node(name=f"Node{i}", site=site)
    node.add_fabnet()
    
    iface = node.get_interface(network_name=f'FABNET_IPv4_{node.get_site()}')
    
    node.add_post_boot_upload_directory('node_tools','.')
    node.add_post_boot_execute(f"chmod +x node_tools/config_script.sh && ./node_tools/config_script.sh {{{{ interfaces['{iface.get_name()}'].dev }}}}  ")

#Submit the Request
slice.submit()


# ## Step 3: Verify Results

# ## Step 2: Inspect the Available Template Variables

import json
node = slice.get_node('Node1')

print(json.dumps(node.get_template_context(), indent=4))


# ## Step 3: Test a Template Expression
# ## Continue Learning

import json
node = slice.get_node('Node1')

iface = node.get_interface(network_name=f'FABNET_IPv4_{node.get_site()}')

print(node.render_template(f"{{{{ interfaces['{iface.get_name()}'].dev }}}}"))


# ## Step 4: Delete the Slice

slice.delete()
