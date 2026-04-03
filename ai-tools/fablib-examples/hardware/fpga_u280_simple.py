# Provisioning a Xilinx U280 FPGA on FABRIC
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: fpga_u280_simple.ipynb
#
# FPGAs (Field-Programmable Gate Arrays) are reconfigurable hardware devices
# that can implement custom digital logic at very high speed and low latency.
# Unlike CPUs or GPUs, FPGAs execute computation...

# # Provisioning a Xilinx U280 FPGA on FABRIC
# ### FABlib API References
# ### Pre-requisites
# ### Knowledge Base

# ## Step 1: Configure the Environment

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()
                     
fablib.show_config();


# ## Step 2: Select an FPGA Type and Find an Available Site

FPGA_CHOICE='FPGA_Xilinx_U280'

# don't edit - convert from FPGA type to a resource column name
# to use in filter lambda function below
choice_to_column = {
    "FPGA_Xilinx_U280": "fpga_u280_available",
}

column_name = choice_to_column.get(FPGA_CHOICE, "Unknown")
print(f'{column_name=}')

# name the slice and the node 
slice_name=f'My Simple FPGA Slice with {FPGA_CHOICE}'
node_name='fpga-node'

print(f'Will create slice "{slice_name}" with node "{node_name}"')

import random

# you can limit to one of the sites on this list (or use None)
#allowed_sites = ['MAX', 'INDI']
allowed_sites = None

fpga_sites_df = fablib.list_sites(output='pandas', quiet=True, filter_function=lambda x: x[column_name] > 0)
# note that list_sites with 'pandas' doesn't actually return a dataframe like doc sez, it returns a Styler 
# based on the dataframe
fpga_sites = fpga_sites_df.data['Name'].values.tolist()
print(f'All sites with FPGA available: {fpga_sites}')

if len(fpga_sites)==0:
    print('Warning - no sites with available FPGAs found')
else:
    if allowed_sites and len(allowed_sites) > 0:
        fpga_sites = list(set(fpga_sites) & set(allowed_sites))
    
    print('Selecting a site at random' + f'among {allowed_sites}' if allowed_sites else '')
    site = random.choice(fpga_sites)
    print(f'Preparing to create slice "{slice_name}" with node {node_name} in site {site}')


# ## Step 3: Create the Slice with an FPGA Component

# Create Slice. Note that by default submit() call will poll for 360 seconds every 10-20 seconds
# waiting for slice to come up. Normal expected time is around 2 minutes. 
slice = fablib.new_slice(name=slice_name)

# Add node with a 100G drive and a couple of CPU cores (default)
node = slice.add_node(name=node_name, site=site, disk=100)
node.add_component(model=FPGA_CHOICE, name='fpga1')

#Submit Slice Request
slice.submit();


# ## Step 4: Inspect the Slice and Node

slice = fablib.get_slice(name=slice_name)
slice.show();


# ## Get the Node

node = slice.get_node(node_name) 
node.show()

fpga = node.get_component('fpga1')
fpga.show();


# ## Step 5: Verify the FPGA PCI and JTAG Devices

command = "sudo dnf install -q -y pciutils usbutils"
stdout, stderr = node.execute(command)

print('Checking to see if Xilinx PCI device(s) are present')
command = "lspci | grep 'Xilinx'"
stdout, stderr = node.execute(command)

print('Checking to see if JTAG-over-USB is available')
command = "lsusb -d 0403:6011"
stdout, stderr = node.execute(command)


# ## Important: FPGA Reprogramming Constraints in a Shared Environment

# ## Continue Learning
# ## Step 6: Delete the Slice

fablib.delete_slice(slice_name)
