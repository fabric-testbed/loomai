# Adding Extra SSH Keys to a Slice
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: add_keys_into_slice.ipynb
#
# By default, FABRIC installs only your own slice public key in the
# `~/.ssh/authorized_keys` file of each VM you create. This is fine for
# single-user experiments, but collaborative research often req...

# # Adding Extra SSH Keys to a Slice
# ### FABlib API References
# ### Knowledge Base

# ## Step 2: Import the FABlib Library

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()

fablib.show_config();


# ## Step 3: Create the Slice with Extra SSH Keys

# Create a slice
slice = fablib.new_slice(name="MySlice with extra SSH keys")

# Add a node
node = slice.add_node(name="Node1")

# Submit the slice by providing two extra keys
extra_ssh_keys=['ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBI1scIhcI0VLxiTZlI4Zt1rxUFfU3nISDZhDm2fk4CZbdMAsOec/5Oq2UjN7yu7hibsVprysMMPoxXc7OfjQfXk= userkey1',
                'ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBH+0ua+cFUwR23rcuTRHB7IpbSof5c3qQuQlKb6vaEgqLuNe+9EM7nJKwQVJqr2glSN+qZeXfXSRqkcqLQLZ4uA= userkey2']
# keys are added by using an optional named parameter 'extra_ssh_keys'
slice.submit(extra_ssh_keys=extra_ssh_keys);


# ## Step 4: Verify the Slice Attributes

slice.show();


# ## Step 5: Verify the Keys Are Installed

node = slice.get_node('Node1')
 
command = 'cat .ssh/authorized_keys'

stdout, stderr = node.execute(command)


# ## Step 6: Add Keys via POA (on a Running Slice)

# ## Continue Learning
# ## Step 7: Delete the Slice

slice.delete()
