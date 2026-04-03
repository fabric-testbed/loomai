# Execute Commands on FABRIC Nodes
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: execute_commands.ipynb
#
# Once your slice is running, you need to interact with its VMs — installing
# software, running experiments, collecting measurements. FABRIC provides two
# mechanisms for this: direct SSH from a termina...

# # Execute Commands on FABRIC Nodes
# ### FABlib API References
# ### Knowledge Base

# ## Step 1: Configure the Environment
# ## Step 2: Import the FABlib Library

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()
                     
fablib.show_config();


# ## Step 3: Create the Slice

slice_name="MySlice"
node1_name="Node1"
node2_name="Node2"

# Create a slice
slice = fablib.new_slice(name=slice_name)

# Add a node
slice.add_node(name=node1_name)
slice.add_node(name=node2_name)

# Submit the slice
slice.submit();


# ## Step 4: Retrieve Node References

slice = fablib.get_slice(slice_name)
slice.show()

node1 = slice.get_node(name=node1_name)
node1.show()

node2 = slice.get_node(name=node2_name)
node2.show();


# ## Step 5: SSH from a Terminal (Optional)

print(f"SSH Command: {node1.get_ssh_command()}")


# ## Step 6: Execute Commands Programmatically via FABlib
# ### Basic Execute

command = 'ping -c 10 www.google.com'

stdout, stderr = node1.execute(command)


# ### Capture Output Quietly

command = 'ping -c 10 www.google.com'

stdout, stderr = node1.execute(command, quiet=True)

print(f"stdout: {stdout}")
print(f"stderr: {stderr}")


# ### Write Output to a Log File

command = 'ping -c 10 www.google.com'

stdout, stderr = node1.execute(command, output_file='node1.log')

!cat node1.log


# ## Step 7: Execute Commands in Parallel with Threads

command = 'ping -c 10 www.google.com'

node1_thread = node1.execute_thread(command, output_file='node1.log')
node2_thread = node2.execute_thread(command, output_file='node2.log')

stdout1, stderr1 = node1_thread.result()
stdout2, stderr2 = node2_thread.result()

print(f"stdout1: {stdout1}")
print(f"stderr1: {stderr1}")
print(f"stdout2: {stdout2}")
print(f"stderr2: {stderr2}")

!cat node1.log

!cat node2.log


# ## Continue Learning
# ## Step 8: Delete the Slice

slice.delete()
