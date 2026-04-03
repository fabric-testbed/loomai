# Get Nodes from an Existing Slice
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: get_nodes.ipynb
#
# Once a slice has been submitted and is running, you will often need to
# reconnect to it from a new notebook session — for example to run additional
# experiments, check node status, or retrieve result...

# # Get Nodes from an Existing Slice
# ### FABlib API References

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()
                     
fablib.show_config()


# ## Step 1: Configure the Environment and Import FABlib

try:
    slices = fablib.get_slices()
    for slice in slices:
        print(f"Slice: {slice}")
except Exception as e:
    print(f"Exception: {e}")


# ## Step 2: List All Your Active Slices

# ## Step 3: Retrieve a Specific Slice and Its Nodes

slice_name='MySlice'

try:
    slice = fablib.get_slice(name=slice_name)
    for node in slice.get_nodes():
        print(f"{node}")   
except Exception as e:
    print(f"Exception: {e}")

# ## Continue Learning
