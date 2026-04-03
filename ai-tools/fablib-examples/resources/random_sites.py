# Random Site Selection: Writing Portable Experiments
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: random_sites.ipynb
#
# Hardcoding a specific FABRIC site name in your notebook creates a fragile
# experiment — if that site is down, at capacity, or undergoing maintenance,
# your notebook will fail with no clear explanatio...

# # Random Site Selection: Writing Portable Experiments
# ### FABlib API References

# ## Step 1: Import FABlib

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()


# ## Step 2: Inspect All Available Sites

try:
    fablib.list_sites()
except Exception as e:
    print(f"Exception: {e}")

# ## Step 3: Select a Random Site

try:
    fablib.list_sites(filter_function=lambda x: x['RTX6000 Available'] > 3)
except Exception as e:
    print(f"Exception: {e}")

# ## Continue Learning

try:
    fablib.list_sites(fields=['Name','ConnectX-6 Available', 'RTX6000 Available'], filter_function=lambda x: x['RTX6000 Available'] > 3)
except Exception as e:
    print(f"Exception: {e}")


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
