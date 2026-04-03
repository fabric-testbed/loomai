# Specify Fields to be Included in FABRIC Lists
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: filters.ipynb
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
    fablib.list_sites(filter_function=lambda x: x['RTX6000 Available'] > 3 and x['ConnectX-5 Available'] > 2)
except Exception as e:
    print(f"Exception: {e}")

try:
    fablib.list_sites(fields=['Name','RTX6000 Available', 'ConnectX-5 Available'],
                      filter_function=lambda x: x['RTX6000 Available'] > 3 and x['ConnectX-5 Available'] > 2)
except Exception as e:
    print(f"Exception: {e}")
