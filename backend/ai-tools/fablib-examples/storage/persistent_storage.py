# Persistent Storage on FABRIC
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: persistent_storage.ipynb
#
# Every FABRIC slice is ephemeral — when you delete it, all data on the nodes'
# local disks disappears. **Persistent storage** is a project-level block volume
# that lives independently of any individua...

# # Persistent Storage on FABRIC
# ### FABlib API References

# ## Step 1: Configure the Environment
# ## Step 2: Import the FABlib Library

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()
                         
fablib.show_config();


# ## Step 3: Create the Experiment Slice

# Replace with your project's volume name and the site where it was provisioned
site = fablib.get_random_site()
storage_name = 'FABRIC_Staff_star_50G_1'   # <-- change this to your volume's name

slice_name = 'PersistentStorage'

# Create a slice
slice = fablib.new_slice(name=slice_name)

# Add a node and attach the persistent volume
node = slice.add_node(name="Node1", site=site)
node.add_storage(name=storage_name)

# Submit the slice
slice.submit();


# ## Step 4: Inspect the Slice

slice.show()
slice.list_nodes();


# ## Step 5: Format the Volume (First Use Only)

node = slice.get_node('Node1')

storage = node.get_storage(storage_name)

print(f"Storage Device Name: {storage.get_device_name()}")  

stdout,stderr = node.execute(f"sudo mkfs.ext4 {storage.get_device_name()}")


# ## Step 6: Mount the Volume

stdout,stderr = node.execute(f"sudo mkdir /mnt/fabric_storage; "
                     f"sudo mount {storage.get_device_name()} /mnt/fabric_storage; "
                     f"df -h")


# ## Continue Learning
# ## Step 7: Delete the Slice

slice.delete()
