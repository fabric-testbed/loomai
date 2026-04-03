# Customizing Nodes
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: customizing_nodes.ipynb
#
# The [Hello, FABRIC](../hello_fabric/hello_fabric.ipynb) notebook creates a
# node on a randomly selected site with default resource sizes. Most real
# experiments require more control: you may need a s...

# # Customizing Nodes
# ### FABlib API References
# ### Knowledge Base

# ## Step 1: Configure the Environment
# ## Step 2: Import the FABlib Library

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()
                     
fablib.show_config();


# ## Step 3: Create a Slice with Explicit Resource Sizes

slice_name = 'MySlice1'

#Create Slice
slice = fablib.new_slice(slice_name)

# Add node
node = slice.add_node(name='Node1', 
                      site=fablib.get_random_site(),
                      cores=4, 
                      ram=16, 
                      disk=100, 
                      image='default_ubuntu_20')

#Submit Slice Request
slice.submit()


# ## Step 4: Create a Slice Using a Named Instance Type

available_images = fablib.get_image_names()

print(f'Available images are: {available_images}')

slice_name = 'MySlice2'

#Create Slice
slice = fablib.new_slice(slice_name)

# Add node
node = slice.add_node(name='Node1', 
                      site=fablib.get_random_site(),
                      instance_type='fabric.c8.m32.d100',
                      image='default_ubuntu_20')

#Submit Slice Request
slice.submit()


# ## Step 5: Pin a Node to a Specific Worker Host

slice_name = 'MySlice3'

#Create Slice
slice = fablib.new_slice(slice_name)

# Add node
node = slice.add_node(name='Node1', 
                      site='MAX',
                      # use the host parameter to force a specific worker
                      host='max-w2.fabric-testbed.net',
                      cores=4, 
                      ram=16, 
                      disk=100, 
                      image='default_ubuntu_20')

#Submit Slice Request
slice.submit()


# ## Continue Learning

# ## Step 6: Delete the Slices

for slice_index in range(1,4):
    print(f'Deleting slice MySlice{slice_index}')
    try:
        fablib.delete_slice("MySlice" + str(slice_index))
    except:
        pass
