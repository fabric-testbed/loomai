# Specify Fields to be Included in FABRIC Lists
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: list_selected_resources.ipynb
#
# Many FABlib objects have `list` and `show` methods that display and return
# tables of other objects and their properties. This notebook shows how you can
# choose to display specific fields when displ...

# # Specify Fields to be Included in FABRIC Lists

# ## Import FABlib

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

try: 
    fablib = fablib_manager()
                     
    fablib.show_config()
except Exception as e:
    print(f"Exception: {e}")


# ## Display Full List of Sites

try:
    fablib.list_sites()
except Exception as e:
    print(f"Exception: {e}")


# ## Display Specific Fields

try:
    fablib.list_sites(fields=['name','address', 'nic_connectx_6_available', 'rtx6000_available'])
except Exception as e:
    print(f"Exception: {e}")


# ## Choose the Order of the Fields

try:
    fablib.list_sites(fields=['rtx6000_available', 'name', 'nic_connectx_6_available', 'address'])
except Exception as e:
    print(f"Exception: {e}")
