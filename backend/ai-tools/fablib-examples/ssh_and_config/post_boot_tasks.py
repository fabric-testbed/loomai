# Automated Node Configuration with Post Boot Tasks
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: post_boot_tasks.ipynb
#
# When you submit a FABRIC slice, the orchestrator allocates hardware and boots
# your VMs. Normally, you then wait for `submit()` to return and run additional
# cells to configure the nodes.

# # Automated Node Configuration with Post Boot Tasks
# ### FABlib API References

# ## Step 1: Configure the Environment and Import FABlib

# ## Step 2: Create the Slice with Post Boot Tasks

slice_name="MySlice"

site=fablib.get_random_site()

#Create a slice
slice = fablib.new_slice(name=slice_name)


for i in range(4):
    # Add a node
    node = slice.add_node(name=f"Node{i}", site=site)
    
    node.add_post_boot_upload_directory('node_tools','.')
    node.add_post_boot_execute('chmod +x node_tools/config_script.sh && ./node_tools/config_script.sh')

#Submit the Request
slice.submit()


# ## Step 3: Verify Configuration Results
# ## Continue Learning

for node in slice.get_nodes():
    stdout, stderr = node.execute('echo -n `hostname -s`": " && cat post_boot_output.txt')


# ## Step 4: Delete the Slice

slice.delete()
