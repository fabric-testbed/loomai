# Show Individual Slice Details
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: show_slice.ipynb
#
# While `fablib.list_slices()` gives you a table of all your slices,
# `slice.show()` gives you a detailed view of a **single slice** — its current
# state, lease dates, all nodes, networks, and other at...

# # Show Individual Slice Details
# ### FABlib API References

# ## Step 1: Import the FABlib Library

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()
                     
fablib.show_config();


# ## Step 2: List Your Slices

fablib.list_slices();


# ## Step 3: Retrieve and Show a Slice by Name

slice_name='RCNF'

slice = fablib.get_slice(name=slice_name)
slice.show();

slice.list_nodes()
slice.list_networks()


# ## Step 4: Retrieve a Slice by ID

# Replace with valid slice ID
slice_id='VAILD_SLICE_ID'

try:
    slice = fablib.get_slice(slice_id=slice_id)
    slice.show();
except Exception as e:
    print(f"Slice ID '{slice_id}' not found, Exception: \n\n{e}")


# ## Step 5: Iterate Over All Slices

for slice in fablib.get_slices():
     slice.show()


# ## Step 6: Select Specific Fields

slice_name='MySlice'

slice = fablib.get_slice(name=slice_name)
    
slice.show(fields=['name','state']);


# ## Step 7: Output Formats for Programmatic Use

slice_name='MySlice'

slice = fablib.get_slice(name=slice_name)
    
output_string = slice.show(output='text')


# ### Output as JSON String

slice_name='MySlice'

slice = fablib.get_slice(name=slice_name)
    
output_json_string = slice.show(output='json')


# ### Output as Python Dictionary

slice_name='MySlice'

slice = fablib.get_slice(name=slice_name)
    
output_dict = slice.show(output='dict')

slice_name='MySlice'

slice = fablib.get_slice(name=slice_name)
    
output_dict = slice.show(output='dict', quiet=True)
    
print(f"{output_dict['name']}, {output_dict['state']}")

# ## Continue Learning
