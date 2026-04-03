# Hello, FABRIC: Create Your First Experiment
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: hello_fabric.ipynb
#
# FABRIC is a nationwide programmable network testbed — a distributed research
# infrastructure spanning universities and research institutions across the
# United States. It gives researchers dedicated ...

# # Hello, FABRIC: Create Your First Experiment
# ### FABlib API References
# ### Knowledge Base

# ## Step 1: Configure the Environment

# ## Step 2: Import the FABlib Library

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()

fablib.show_config();


# ## Step 3 (Optional): Query for Available Testbed Resources and Settings

fablib.list_sites();


# ## Step 4: Create the Experiment Slice

# Create a slice
slice_name = "HelloFabric"
slice = fablib.new_slice(name=slice_name)

# Add a node (FABRIC will choose a random available site)
node = slice.add_node(name="Node1")

# Submit the slice request and wait for it to be ready
slice.submit();


# ## Step 5: Observe the Slice's Attributes
# ### Show the slice attributes

slice.show();


# ### List the nodes

slice.list_nodes();


# ## Step 6: Run the Experiment

#node = slice.get_node('Node1')
 
for node in slice.get_nodes():
    stdout, stderr = node.execute('echo Hello, FABRIC from node `hostname -s`')


# ## Continue Learning

# ## Step 7: Delete the Slice

slice.delete()
