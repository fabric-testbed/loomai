# Delete a Slice
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: delete_slice.ipynb
#
# Deleting a slice releases all its resources — VMs, network interfaces,
# storage, and hardware components — back to the FABRIC testbed for other
# researchers to use. FABRIC is a shared infrastructure,...

# # Delete a Slice
# ### FABlib API References

# ## Step 1: Import the FABlib Library

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()
                     
fablib.show_config();


# ## Step 2: Delete Options
# ### Option 1: Fetch the Slice Object and Delete It

slice_name='MySlice'

slice = fablib.get_slice(name=slice_name)
print(f"Slice: {slice.get_name()}")

slice.delete()


# ### Option 2: Delete a Slice by Name (One-Liner)

slice_name='MySlice'

fablib.delete_slice(slice_name)


# ### Option 3: Delete a Slice by ID

slice_id=<insert_known_slice_id>

fablib.delete_slice(slice_id=slice_id)


# ### Option 4: Delete ALL Your Slices
# ## Continue Learning

fablib.delete_all();
