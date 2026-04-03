# List Slice Nodes, Networks, Interfaces, and Components
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: list_node_and_networks.ipynb
#
# Once a slice is running, you need ways to inspect its internal topology —
# which nodes exist, which networks connect them, which interfaces attach to
# which networks, and which hardware components (N...

# # List Slice Nodes, Networks, Interfaces, and Components
# ### FABlib API References

# ## Step 1: Import the FABlib Library

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()
                     
fablib.show_config();


# ## Step 2: Find a Slice to Inspect

fablib.list_slices();


# ## Step 3: Retrieve the Slice

slice_name='MySlice'

slice = fablib.get_slice(name=slice_name)
slice.show();


# ## Step 4: List Nodes

output = slice.list_nodes()


# ## Step 5: List Networks

output = slice.list_networks()


# ## Step 6: List Interfaces

output = slice.list_interfaces()


# ## Step 7: List Components
# ## Continue Learning

output = slice.list_components()
