# L2 Networking with a P4 Tofino Hardware Switch
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: fabric_p4_tofino_l2_network.ipynb
#
# Select FABRIC sites include a dedicated **Intel Tofino ASIC** — a high-speed
# programmable switch chip running at up to 6.5 Tbps. Unlike general-purpose
# CPUs or FPGAs, the Tofino is a purpose-built ...

# # L2 Networking with a P4 Tofino Hardware Switch
# ### FABlib API References
# ### Knowledge Base and References

# ## Step 1: Configure the Environment and Understand the Topology
# ### Topology Overview
# ### Pre-requisites

# ## Step 2: Import the FABlib Library

from ipaddress import ip_address, IPv4Address, IPv6Address, IPv4Network, IPv6Network
import ipaddress

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()

fablib.show_config();


# ## Step 3: Create the Experiment Slice

# ### Step 3a: Find Sites with P4 Switch Availability

p4_column_name = 'p4-switch_available'

'''
# Find a site which has a P4 Switch available
[site2] = fablib.get_random_sites(count=1, filter_function=lambda x: x[p4_column_name] > 0)

# Choose another random site other than P4 site to host the VMs
site1 = fablib.get_random_site(avoid=[site2])
'''
site2="MICH"
site1="SALT"

print(f"Sites chosen for hosting VMs: {site1} P4: {site2}")


# ### Step 3b: Define Slice Variables

slice_name = 'P4-Lab-Slice2'
p4_column_name = "p4-switch_available"

node1_name = 'Node1'
node2_name = 'Node2'
p4_name = 'P4'
network1_name = 'net1'
network2_name = 'net2'

print(f"VM Site: {site1}")
print(f"P4 Site: {site2}")

#model='NIC_ConnectX_6'
model='NIC_Basic'

#Create Slice
slice = fablib.new_slice(name=slice_name)

# Create Network
net1 = slice.add_l2network(name=network1_name, subnet=IPv4Network("192.168.0.0/24"))
net2 = slice.add_l2network(name=network2_name, subnet=IPv4Network("192.168.0.0/24"))

# Create Node 1 and its links
node1 = slice.add_node(name=node1_name, site=site1)
iface1 = node1.add_component(model=model, name='nic1').get_interfaces()[0]
iface1.set_mode('config')
net1.add_interface(iface1)
iface1.set_ip_addr(IPv4Address("192.168.0.1"))

# Create P4 switch and its links 
p4 = slice.add_switch(name=p4_name, site=site2)
iface2 = p4.get_interfaces()[0]
iface3 = p4.get_interfaces()[1]

net1.add_interface(iface2)
net2.add_interface(iface3)

# Create Node 2 and its links
node2 = slice.add_node(name=node2_name, site=site1)
iface4 = node2.add_component(model=model, name='nic1').get_interfaces()[0]
iface4.set_mode('config')
net2.add_interface(iface4)
iface4.set_ip_addr(IPv4Address("192.168.0.2"))

# Submit Slice Request
slice.submit()


# ## Step 4: Upload the P4 Source Code to the Switch

slice = fablib.get_slice(slice_name)
switch = slice.get_node(p4_name)
switch.upload_directory("P4_labs", ".")


# ## Compile the basic P4 program
# ### Configure the environment variables
# ### Compile the code

# Execute a series of commands on the switch using execute()
stdout, stderr = switch.execute(command=[

    # Step 1: Enter the Intel Tofino SDE environment
    # This command activates the environment needed to run P4-related tools.
    ("sde-env-9.13.3", r"\[nix\-shell\(SDE\-9.13.3\):.*\$ ", 10),

    # Step 2: Compile the P4 program using p4_build.sh
    # This builds the P4 program specified in the path (basic.p4).
    # The build process may take some time, so a timeout of 20 seconds is used.
    ("p4_build.sh P4_labs/lab1/p4src/basic.p4", r"\[nix\-shell\(SDE-9.13.3\):.*\$ ", 20),

    # Step 3: Exit the SDE environment cleanly
    # Ensures that the environment is properly terminated after execution.
    ("exit", r"\[nix\-shell\(SDE-9.13.3\):.*\$ ", 10)
])

# stdout: Captures the standard output of the executed commands.
# stderr: Captures any error messages encountered during execution.


# ### Step 5b: Verify Compilation Artifacts

stdout, stderr = switch.execute("ls ~/.bf-sde/9.13.3/build/basic/")

stdout, stderr = switch.execute("ls ~/.bf-sde/9.13.3/build/basic/tofino/pipe/")


# ## Start the switch daemon and configure the switch ports

thread = switch.execute_thread(command=[
    # Enter SDE environment
    ("sde-env-9.13.3", r"\[nix\-shell\(SDE\-9.13.3\):.*\$ ", 10),

    # Load Kernel Modules
    ("sudo $SDE_INSTALL/bin/./bf_kdrv_mod_load $SDE_INSTALL", r"\[nix\-shell\(SDE-9.13.3\):.*\$ ", 20),

    # Start run_switchd.sh interactively (DO NOT run in background)
    ("run_switchd.sh -p basic", r"bfshell>", 30),  # Wait for switchd prompt to appear

    # Enter UCLI after switchd starts
    ("ucli", r"bf-sde>", 10),

    # Port configuration inside UCLI
    ("pm port-add 1/- 100G NONE", r"bf-sde>", 10),
    ("pm port-add 2/- 100G NONE", r"bf-sde>", 10),
    ("pm port-enb 1/-", r"bf-sde>", 10),
    ("pm port-enb 2/-", r"bf-sde>", 10),
    ("pm show", r"bf-sde>", 10),
    ("pm show", r"bf-sde>", 10),
    ("pm show", r"bf-sde>", 10),
    # Keep the session open to prevent exit
    ("sleep infinity", r"bf-sde>", 300)
], output_file="run_switchd.log")

import time
time.sleep(120)


# ### Step 6b: Update the Forwarding Table Port Numbers

file_path = "~/P4_labs/lab1/bfrt_python/setup.py"
INGRESS = switch.get_interfaces()[0].get_device_name()
EGRESS = switch.get_interfaces()[1].get_device_name()

switch.execute(
    f"sed -i 's/ingress_logical *= *[0-9]\\+/ingress_logical = {INGRESS}/' {file_path}"
)
switch.execute(
    f"sed -i 's/egress_logical *= *[0-9]\\+/egress_logical = {EGRESS}/' {file_path}"
)

# Execute a series of commands on the switch using execute()
stdout, stderr = switch.execute(command=[
    
    # Step 1: Enter the Intel Tofino SDE environment
    # This command activates the environment needed to run P4-related tools.
    ("sde-env-9.13.3", r"\[nix\-shell\(SDE\-9.13.3\):.*\$ ", 10),

    # Step 2: Run the BFShell script to set up the P4 runtime environment
    # This script initializes the environment and configures the necessary settings.
    # --no-status-srv: Disables the status server.
    # -b <script>: Runs the Python setup script inside bfshell.
    ("run_bfshell.sh --no-status-srv -b ~/P4_labs/lab1/bfrt_python/setup.py", 
     r"\[nix\-shell\(SDE\-9.13.3\):.*\$ ", 10),

    # Step 3: Exit the SDE environment cleanly
    # Ensures that the environment is properly terminated after execution.
    #("exit", r"\[nix\-shell\(SDE\-9.13.3\):.*\$ ", 10)
])

# stdout will contain the standard output from the executed commands.
# stderr will contain any error messages encountered during execution.


# ## Step 5: Test Connectivity Between the VMs

slice=fablib.get_slice(slice_name)
node1=slice.get_node(node1_name)
node2=slice.get_node(node2_name)

node1_addr = node1.get_interface(network_name=network1_name).get_ip_addr()
node2_addr = node2.get_interface(network_name=network2_name).get_ip_addr()

stdout, stderr = node1.execute(f'ping -c 5 {node2_addr}')
stdout, stderr = node2.execute(f'ping -c 5 {node1_addr}')


# ## Continue Learning
# ## Step 6: Delete the Slice

slice=fablib.get_slice(slice_name)
slice.delete()
