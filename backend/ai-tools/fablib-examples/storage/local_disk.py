# Customizing Local Disk Size
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: local_disk.ipynb
#
# Every FABRIC node is backed by a **local virtual disk** — the block device
# that holds the operating system and provides scratch space for your
# experiment. By default, FABlib assigns a modest disk a...

# # Customizing Local Disk Size
# ### FABlib API References

# ## Step 1: Configure the Environment
# ## Step 2: Import the FABlib Library

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()
                     
fablib.show_config();


# ## Step 3: Create the Experiment Slice

slice_name = 'LocalDiskSizing'

# Create Slice
slice = fablib.new_slice(name=slice_name)

# Add nodes with different requested disk sizes
# The disk value is a hint — FABRIC rounds up to the nearest available instance type
slice.add_node(name='NodeDefault')          # default allocation
slice.add_node(name='Node10',  disk=10)     # request at least 10 GB
slice.add_node(name='Node50',  disk=50)     # request at least 50 GB
slice.add_node(name='Node100', disk=100)    # request at least 100 GB
slice.add_node(name='Node500', disk=500)    # request at least 500 GB

# Submit all five nodes in one request
slice.submit()


# ## Step 4: Observe the Actual Disk Sizes

for node in slice.get_nodes():
    print(f"\n{node.get_name()}\n")
    node.execute('df -h')


# ## Continue Learning

# ## Step 5: Delete the Slice

slice.delete()
