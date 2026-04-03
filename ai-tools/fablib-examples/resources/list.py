# FABlib List Methods: Querying FABRIC Resources
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: list.ipynb
#
# Nearly every FABlib object — sites, slices, nodes, networks, interfaces,
# components — exposes a `list_*()` method that displays a tabular summary of
# that object type. These methods are your primary...

# # FABlib List Methods: Querying FABRIC Resources
# ### FABlib API References

# ## Step 1: Import FABlib

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()


# ## Step 2: List Sites — Default Output

try:
    fablib.list_sites()
except Exception as e:
    print(f"Exception: {e}")


# ### Select Specific Columns

# ### Filter Rows with a Lambda Function

# ### Combine Fields and Filter Function

# ## Step 3: Show a Single Site's Properties

try:
    fablib.list_sites(filter_function=lambda x: x['RTX6000 Available'] > 3)
except Exception as e:
    print(f"Exception: {e}")

try:
    fablib.list_sites(fields=['Name','ConnectX-6 Available', 'RTX6000 Available'], filter_function=lambda x: x['RTX6000 Available'] > 3)
except Exception as e:
    print(f"Exception: {e}")


# ## Show a site's properties

# ## Continue Learning

try:
    site = fablib.get_random_site()
    
    fablib.show_site(site)
except Exception as e:
    print(f"Exception: {e}")

try:
    fablib.show_site(site, fields=['Name','ConnectX-6 Available', 'RTX6000 Available'])
except Exception as e:
    print(f"Exception: {e}")
