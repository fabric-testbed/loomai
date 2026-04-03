# Save and Load Experiment Topologies
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: save_and_load.ipynb
#
# FABRIC slice topologies can be serialized to a **GraphML file** — a standard
# XML-based graph format. This lets you save a topology design to disk and
# reload it later, enabling several useful workfl...

# # Save and Load Experiment Topologies
# ### FABlib API References

# ## Step 1: Import the FABlib Library

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()
                     
fablib.show_config();


# ## Step 2: Design a Topology and Save It to a File

#Create a slice
saved_topology = fablib.new_slice(name="MySlice_Saved")

# Add a node
saved_topology.add_node(name="Node1")

# Save the topology requeest
saved_topology.save('hello_fabric.graphml')


# ## Step 3: Load the Topology and Submit as a New Slice

#Create a slice
loaded_topology = fablib.new_slice(name="MySlice_Loaded")

loaded_topology.load('hello_fabric.graphml')

loaded_topology.submit()


# ## Step 4: Inspect the Loaded Slice

loaded_topology.show()
loaded_topology.list_nodes();


# ## Continue Learning
# ## Step 5: Delete the Slice

loaded_topology.delete()
