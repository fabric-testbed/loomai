# List All FABRIC Resources
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: list_all_resources.ipynb
#
# FABRIC is a nationwide, distributed research infrastructure with dozens of
# sites, each offering compute nodes, network hardware, GPUs, FPGAs, and
# SmartNICs. Before you design an experiment, you nee...

# # List All FABRIC Resources
# ### FABlib API References
# ### Knowledge Base

# ## Step 1: Configure the Environment

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()
                     
fablib.show_config();


# ## Step 2: List Available Resources by Site

output_table = fablib.list_sites()

output_table = fablib.list_sites(pretty_names=False)


# ## Step 3: Select Specific Fields

# Optional list of fields to display.
# fields=None desplays all fields.
fields=['name','cores_available','ram_available','disk_available','nic_basic_available']

output_table = fablib.list_sites(fields=fields)


# ## Step 4: Choose an Output Format
# ### Output as Pandas DataFrame

output_table = fablib.list_sites(output='pandas',fields=fields)


# ### Output as Tabular Text

output_table = fablib.list_sites(output='text',fields=fields)


# ### Output as JSON String

output_json = fablib.list_sites(output='json')


# ### Output as Python List of Dicts

output_list = fablib.list_sites(output='list')

output_list = fablib.list_sites(output='list', quiet=True)

for site in output_list:
    print(f"Site: {site['name']}, {site['cores_available']}, {site['ram_available']}, {site['disk_available']}, {site['nic_basic_available']}")


# ## Step 5: Check Resource Availability for a Future Time Window

from datetime import datetime
from datetime import timezone
from datetime import timedelta

start = (datetime.now(timezone.utc) + timedelta(days=1))
end = start + timedelta(days=1)

output_table = fablib.list_sites(start=start, end=end)

fields=['name','cores_available','ram_available','disk_available','nic_connectx_6_available', 'nic_connectx_5_available']
output_table = fablib.list_sites(start=start, end=end, fields=fields)

# Add an example for filtered output


# ## Step 6: List Resources by Host

output_table = fablib.list_hosts()


# ## Step 7: List Facility Ports

output_table = fablib.list_facility_ports()


# ## Step 8: List Available Network Links

fablib.list_links();

# ## Continue Learning
