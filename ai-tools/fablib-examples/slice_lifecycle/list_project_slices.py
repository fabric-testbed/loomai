# Sharing slices within a Project
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: list_project_slices.ipynb
#
# This guide outlines the procedure for a user to view or access a project slice
# owned by another user. In collaborative projects, situations often arise where
# it is necessary to access Virtual Machi...

# # Sharing slices within a Project

# ## Import FABlib

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()
                     
fablib.show_config();


# ## List All Project Slices

fablib.list_slices(user_only=False);


# ## List Your  Slices

fablib.list_slices();


# ## View collaborators slice details

project_slices = fablib.get_slices(user_only=False)

my_email = fablib.get_user_info().get('email')

slice_name = None
# Select a slice owned by a project member
for s in project_slices:
    if s.get_email() != my_email:
        slice_name = s.get_name()
        break

if not slice_name:
    print("No slices owned by other project members found!")
else:    
    if not len(project_slices):
        print("There are no Active Slices in the Project")
    else:
        slice = fablib.get_slice(name=slice_name, user_only=False)
        slice.show();


# ## View slice VMs

slice.list_nodes();


# ## View slice Networks

slice.list_networks();


# ## Run commands

for node in slice.get_nodes():
    stdout, stderr = node.execute('echo Hello, FABRIC from node `hostname -s`')


# ## Verify you cannot delete the slice

slice.delete()
