# Filter Sites by Available Resources
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: filter_sites_by_available_resources.ipynb
#
# Many FABRIC experiments require hardware that is not universally available —
# GPUs, high-speed NICs, or Precision Time Protocol (PTP) support exist only at
# certain sites, and supply fluctuates as ot...

# # Filter Sites by Available Resources
# ### FABlib API References
# ### Knowledge Base

# ## Step 1: Configure the Environment

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()
                     
fablib.show_config();


# ## Step 2: Filter Sites Using Lambda Functions

fablib.list_sites(filter_function=lambda x: x['nic_connectx_5_available'] > 2);

st_louis_lat_long=(32.773081, -96.797448)

fablib.list_sites(filter_function=lambda x: x['nic_connectx_5_available'] > 2 and x['location'][1] < st_louis_lat_long[1]);


# ## Step 3: Combine Filters with Specific Fields

st_louis_lat_long=(32.773081, -96.797448)

fablib.list_sites(filter_function=lambda x: x['nic_connectx_5_available'] > 2 and x['location'][1] < st_louis_lat_long[1],
                      fields=['name','address', 'nic_connectx_5_available']);


# ## Step 4: Find Sites with PTP Support

fablib.list_sites(filter_function=lambda x: x['ptp_capable'] is True)


# ## Step 5: Select a Random Site Meeting Your Requirements

st_louis_lat_long=(32.773081, -96.797448)

west_site = fablib.get_random_site(filter_function=lambda x: x['nic_connectx_6_available'] > 0 and x['location'][1] < st_louis_lat_long[1] and x['ptp_capable'] is True)                                                                                                                                                                                                                           
east_site = fablib.get_random_site(filter_function=lambda x: x['nic_connectx_6_available'] > 0 and x['location'][1] > st_louis_lat_long[1] and x['ptp_capable'] is True)                                                                                                                                                                                                                           

print(f"west_site: {west_site}")
print(f"east_site: {east_site}")


# ## Step 6: Select Multiple Random Sites

sites = fablib.get_random_sites(count=4, filter_function=lambda x: x['rtx6000_available'] > 2)                                                                                                                                                                                                                           

print(f"sites: {sites}")

# ## Continue Learning
