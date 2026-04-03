# FABlib Show Methods: Inspecting Individual Objects
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: show.ipynb
#
# While `list_*()` methods give you a broad table view across many objects,
# `show_*()` methods give a deep vertical view of a single object's complete
# properties. Every FABlib resource type that has ...

# # FABlib Show Methods: Inspecting Individual Objects
# ### FABlib API References

# ## Step 1: Import FABlib

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()


# ## Step 2: List Sites

try:
    fablib.list_sites()
except Exception as e:
    print(f"Exception: {e}")

# ## Step 3: Show a Single Site's Full Properties

try:
    fablib.list_sites(filter_function=lambda x: x['RTX6000 Available'] > 3)
except Exception as e:
    print(f"Exception: {e}")

try:
    fablib.list_sites(fields=['Name','ConnectX-6 Available', 'RTX6000 Available'], filter_function=lambda x: x['RTX6000 Available'] > 3)
except Exception as e:
    print(f"Exception: {e}")


# ## Continue Learning

# ## Show a site's properties

try:
    site = fablib.get_random_site()
    
    fablib.show_site(site)
except Exception as e:
    print(f"Exception: {e}")

try:
    fablib.show_site(site, fields=['Name','ConnectX-6 Available', 'RTX6000 Available'])
except Exception as e:
    print(f"Exception: {e}")
