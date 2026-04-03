# Specify Fields to be Included in FABRIC Lists
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: fields.ipynb
#
# Many FABlib objects have `list` and `show` methods that display and return
# tables of other object and their properties. This notebook shows how you can
# choose to display specific fields when displa...

# # Specify Fields to be Included in FABRIC Lists

# ## Import FABlib

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()


# ## Display Full List of Sites

try:
    fablib.list_sites()
except Exception as e:
    print(f"Exception: {e}")


# ## Display Specific Fields

try:
    fablib.list_sites(fields=['Name','Address', 'ConnectX-6 Available', 'RTX6000 Available'])
except Exception as e:
    print(f"Exception: {e}")

try:
    fablib.list_sites(fields=['RTX6000 Available', 'Name', 'ConnectX-6 Available', 'Address'])
except Exception as e:
    print(f"Exception: {e}")
