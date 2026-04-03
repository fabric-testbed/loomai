# Create and Submit a Slice
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: create_slice.ipynb
#
# A **slice** is the fundamental unit of an experiment on FABRIC — an isolated,
# named collection of resources (VMs, networks, storage) that belongs to a
# single project. Every experiment starts by cre...

# # Create and Submit a Slice
# ### FABlib API References

# ## Step 1: Import the FABlib Library

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()
                         
fablib.show_config();


# ## Step 2: Submit Options
# ### Option 1: Basic Blocking Submit

# Create a slice
slice = fablib.new_slice(name="MySlice1")

# Design the slice
node = slice.add_node(name="Node1")

#Submit the Request
slice.submit();


# ### Option 2: Silent Blocking Submit

# Create a slice
slice = fablib.new_slice(name="MySlice2")

# Design the slice
node = slice.add_node(name="Node1")

#Submit the Request
slice_id = slice.submit(progress=False)

print(f"slice_id: {slice_id}")


# ### Option 3: Non-Blocking Submit

# Create a slice
slice = fablib.new_slice(name="MySlice3")

# Design the slice
node = slice.add_node(name="Node1")

# Submit the request
slice.submit(wait=False)

# Save the slice ID
slice_id = slice.get_slice_id()

print(f"slice_id: {slice_id}")


# #### Wait for the Non-Blocking Slice to Become Ready

#Get Slice
slice = fablib.get_slice(slice_id=slice_id)

#Wait for ssh to be active
slice_id = slice.wait_ssh(progress=True)

print(f"slice_id: {slice_id}")

#Run post boot config and dataplane network tests
slice.post_boot_config();


# ### Option 4: Future Scheduling — Reserve Resources in Advance

# #### Query Available Sites in the Future Time Window

from datetime import datetime
from datetime import timezone
from datetime import timedelta

start = (datetime.now(timezone.utc) + timedelta(days=1))

fields=['name','nic_connectx_5_available','nic_connectx_6_available']

smart_nic_sites = fablib.list_sites(fields=fields, start=start)

smart_nic_sites = smart_nic_sites.data['Name'].values.tolist()
print(f'All sites with NIC_ConnectX_5/NIC_ConnectX_6 available: {smart_nic_sites}')

import random

if len(smart_nic_sites)==0:
    print('Warning - no sites with available NIC_ConnectX_5/NIC_ConnectX_6 found')
else:    
    print(f'Selecting a site at random among {smart_nic_sites}')
    site = random.choice(smart_nic_sites)

    print(f"Site chosen: {site}")


# #### Submit the Future-Scheduled Slice

# Create a slice
slice = fablib.new_slice(name="MySlice4")

# Design the slice
node = slice.add_node(name="Node1", site=site)
node.add_component(model="NIC_ConnectX_6", name='nic1')
node.add_component(model="NIC_ConnectX_6", name='nic2')

# Submit the request
slice.submit(lease_start_time=start)

# Save the slice ID
slice_id = slice.get_slice_id()

print(f"slice_id: {slice_id}")


# ## Step 3: Validate Before Submitting

# ### Validation Style 1: Validate Nodes as They Are Added

# Create a slice
slice = fablib.new_slice(name="MySlice")

# Add a node and validate it by specifying , do not raise exception in case of errors and remove it from the topology 
# Node1 is requested on a host not belonging to the site and hence is invalid

node1 = slice.add_node(name="Node1", site="MAX", host="gpn-w1.fabric-testbed.net", validate=True, raise_exception=False)

# Add a node and validate it, and raise exception in case of errors

# Node2 is requesting T4 and RTX600 which is an infeasible requests as none of the hosts have both type of the GPUs available.
# Since we requested Exception to be raised in case of errors, the following code raises Exception

node2 = slice.add_node(name="Node2", site="MAX", validate=True, raise_exception=True)
node2.add_component(model='NIC_Basic', name='nic2')
node2.add_component(model='GPU_RTX6000', name='gpu1')
node2.add_component(model='GPU_TeslaT4', name='gpu3')

# Node1 was removed from the topology as requested and Node2 still exists in the topology as requested
slice.list_nodes();


# ### Validation Style 2: Validate the Complete Topology at Once

# Create a slice
slice = fablib.new_slice(name="MySlice")

# Add a node
node1 = slice.add_node(name="Node1", site="MAX", host="gpn-w1.fabric-testbed.net")
# Here node1 is invalid request would be errored and removed from the slice

node2 = slice.add_node(name="Node2", site="MAX")
node2.add_component(model='NIC_Basic', name='nic2')
node2.add_component(model='GPU_RTX6000', name='gpu1')
node2.add_component(model='GPU_TeslaT4', name='gpu3')
# Here node2 is invalid request as you can not have T4 and RTX600 both on a single worker

# This call will report both the errors identified above
slice.validate()


# ## Step 4: Timeout and Retry Configuration

# Create a slice
slice = fablib.new_slice(name="MySlice5")

# Design the slice
node = slice.add_node(name="Node1")

#Submit the Request
slice_id = slice.submit(wait_timeout=600, wait_interval=60)

print(f"slice_id: {slice_id}")

#Delete Slices

try:
    fablib.delete_slice("MySlice1")
except:
    pass

try:
    fablib.delete_slice("MySlice2")
except:
    pass

try:
    fablib.delete_slice("MySlice3")
except:
    pass

try:
    fablib.delete_slice("MySlice4")
except:
    pass

try:
    fablib.delete_slice("MySlice5")
except:
    pass


# ## Continue Learning
# ## Step 5: Delete All Example Slices
