# FABlib Logging: Controlling Diagnostic Output
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: logging.ipynb
#
# FABlib uses Python's standard `logging` module under the hood. By default,
# FABlib suppresses most debug output to keep notebook cells readable.

# # FABlib Logging: Controlling Diagnostic Output
# ### FABlib API References
# ### Knowledge Base

# ## Step 1: Import FABlib

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()


# ## Step 2: Query Sites

try:
    fablib.list_sites()
except Exception as e:
    print(f"Exception: {e}")

# ## Step 3: Show Site Properties

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
