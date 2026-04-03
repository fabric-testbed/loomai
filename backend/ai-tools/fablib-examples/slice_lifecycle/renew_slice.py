# Renew a Slice Reservation
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: renew_slice.ipynb
#
# Every FABRIC slice has a **lease** — a time period during which your resources
# are reserved. When the lease expires, your slice is automatically terminated
# and all data on the VMs is permanently lost.

# # Renew a Slice Reservation
# ### FABlib API References
# ### Knowledge Base

# ## Step 1: Import the FABlib Library

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()
                     
fablib.show_config();


# ## Step 2: Set the Slice Name

slice_name='MySlice'


# ## Step 3: Renew the Slice

from datetime import datetime
from datetime import timezone
from datetime import timedelta

#Set end host to now plus 1 day
end_date = (datetime.now(timezone.utc) + timedelta(days=6)).strftime("%Y-%m-%d %H:%M:%S %z")

try:
    slice = fablib.get_slice(name=slice_name)

    slice.renew(end_date)
except Exception as e:
    print(f"Exception: {e}")


# ## Step 4: Verify the New Lease End Date
# ## Continue Learning

try:
    slice = fablib.get_slice(name=slice_name)
    print(f"Lease End (UTC)        : {slice.get_lease_end()}")
       
except Exception as e:
    print(f"Exception: {e}")
