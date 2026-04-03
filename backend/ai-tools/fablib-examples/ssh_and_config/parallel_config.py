# Parallel Node Configuration
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: parallel_config.ipynb
#
# Many FABRIC experiments involve multiple nodes that all need the same software
# installed or the same configuration applied. Configuring them one at a time —
# `node.execute()` on Node0, wait, then No...

# # Parallel Node Configuration
# ### FABlib API References

# ## Step 1: Configure the Environment
# ## Step 2: Import the FABlib Library

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()

fablib.show_config();


# ## Step 3 (Optional): Query Available Sites

output = fablib.list_sites()


# ## Step 4: Create a 4-Node Slice

slice_name="MySlice130"

#Create a slice
slice = fablib.new_slice(name=slice_name)

for i in range(4):
    # Add a node
    node = slice.add_node(name=f"Node{i}")

#Submit the Request
slice.submit()


# ## Step 5: Observe the Slice Attributes

slice = fablib.get_slice(name=slice_name)
slice.show()
slice.list_nodes()
slice.list_networks()
slice.list_interfaces()


# ## Step 6: Configure All Nodes in Parallel

config_command = "sudo yum install -q -y net-tools"

#Create execute threads
execute_threads = {}
for node in slice.get_nodes():
    print(f"Starting config on node {node.get_name()}")
    execute_threads[node] = node.execute_thread(config_command, output_file=f"{node.get_name()}.log")


#Wait for results from threads
for node,thread in execute_threads.items():
    print(f"Waiting for result from node {node.get_name()}")
    stdout,stderr = thread.result()
    print(f"stdout: {stdout}")
    print(f"stderr: {stderr}")


# ## Continue Learning

for node in slice.get_nodes():
    stdout, stderr = node.execute('echo Hello, FABRIC from node `hostname -s` && netstat -i')
    print(stdout)


# ## Step 7: Delete the Slice

slice.delete()
