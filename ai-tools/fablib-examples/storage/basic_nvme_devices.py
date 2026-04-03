# Using NVMe Storage Devices on FABRIC
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: basic_nvme_devices.ipynb
#
# FABRIC nodes can be equipped with dedicated **NVMe PCIe storage devices** —
# enterprise-grade solid-state drives that are passed through directly to your
# VM as a raw PCI block device. Unlike the loc...

# # Using NVMe Storage Devices on FABRIC
# ### FABlib API References

# ## Step 1: Configure the Environment
# ## Step 2: Import the FABlib Library

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()

fablib.show_config();


# ## Step 3: Select a Site and Define Slice Parameters
# ### Set the Slice Name and Target Site

slice_name = 'NVMeStorage'

# Select a site that has NVMe devices available right now
site = fablib.get_random_site(filter_function=lambda x: x['nvme_available'] > 0)
print(f"site: {site}")

node_name = 'Node1'
nvme_name = 'nvme1'


# ## Step 4: Create the Slice

# Create the slice
slice = fablib.new_slice(name=slice_name)

# Add a node at the selected site
node = slice.add_node(name=node_name, site=site)

# Attach a 1 TB NVMe PCIe device to the node
node.add_component(model='NVME_P4510', name=nvme_name)

# Submit the slice — this blocks until all resources are ready
slice.submit();


# ## Step 5: Retrieve the Slice

slice = fablib.get_slice(name=slice_name)

slice.show();


# ## Step 6: Inspect the Node and NVMe Component

node = slice.get_node(node_name) 
node.show()

nvme1 = node.get_component(nvme_name)
nvme1.show();


# ## Step 7: Configure the NVMe Device

nvme1.configure_nvme();


# ## Continue Learning
# ## Step 8: Delete the Slice

slice = fablib.delete_slice(slice_name)
