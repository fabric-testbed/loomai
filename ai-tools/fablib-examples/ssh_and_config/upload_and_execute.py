# Upload and Execute a Script on a FABRIC Node
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: upload_and_execute.ipynb
#
# Running inline shell commands with `node.execute()` works well for short
# operations. For more complex configuration — installing packages, tuning OS
# settings, configuring networking — it's cleaner ...

# # Upload and Execute a Script on a FABRIC Node
# ### FABlib API References

# ## Step 1: Configure the Environment
# ## Step 2: Import the FABlib Library

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()

fablib.show_config();


# ## Step 3: Create the Slice

slice_name='MySlice132'

#Create a slice
slice = fablib.new_slice(name=slice_name)

# Add a node
slice.add_node(name="Node1")

slice.submit();


# ## Step 4: Inspect the Node

slice = fablib.get_slice(name=slice_name)
slice.show()
slice.list_nodes()


# ## Step 5: Upload and Execute the Configuration Script
# ### Upload the Script

node = slice.get_node(name="Node1")        

# Using the upload_file method, you can upload a local file
# from a path relative to the notebook. config_script.sh is
# located in the same directory as this notebook!
result = node.upload_file('config_script.sh','config_script.sh')


# ### Execute the Script

# Some additional arguments to run our script with.
script_args="net-tools tcpdump vim"

node = slice.get_node(name="Node1")

# Using the execute method, we can run the script on the
# remote host. Additionaly, the standard output is being
# redirected to the config.log file and will not appear 
# in this cell.
stdout, stderr = node.execute(f'chmod +x config_script.sh && ./config_script.sh {script_args} >> config.log')


# ### Download the Log File

try:
    node = slice.get_node(name="Node1")        

    # This time using the download_file method, we can retrieve
    # the output stored in config.log and access it locally.
    node.download_file('config.log','config.log')
except Exception as e:
    print(f"Exception: {e}")


# ### View the Log
# ## Continue Learning

# Beginning a line with an exclamation point runs it as a bash command.
!cat config.log


# ## Step 6: Delete the Slice

slice.delete()
