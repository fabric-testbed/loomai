# FABlib Table Styles: Customizing Output Display
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: table_styles.ipynb
#
# FABlib's `list_*()` and `show_*()` methods return data that can be rendered in
# multiple ways. This notebook explores how to control the visual presentation
# of FABlib output tables — useful when you...

# # FABlib Table Styles: Customizing Output Display
# ### FABlib API References

# ## Step 1: Import FABlib

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()


# ## Step 2: Default Site List

try:
    fablib.list_sites()
except Exception as e:
    print(f"Exception: {e}")


# ### Select Specific Columns

# ### Filter Rows by Resource Availability

# ### Combine Columns and Row Filtering

# ## Step 3: Show Properties for a Single Site

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
