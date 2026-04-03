# BlueField-3 DPU L3 Network with Automatic Configuration
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: bluefield_dpus_l2_network_basic_auto.ipynb
#
# **DPUs (Data Processing Units)** are a new category of programmable hardware
# that combines a high-performance network interface card with an embedded
# multi-core ARM processor, cryptographic acceler...

# # BlueField-3 DPU L3 Network with Automatic Configuration
# ### FABlib API References
# ### Available BlueField Component Models
# ### Knowledge Base

# ## Step 1: Configure the Environment

from ipaddress import ip_address, IPv4Address, IPv6Address, IPv4Network, IPv6Network
import ipaddress

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()
                     
fablib.show_config();


# ## Step 2: Create the Experiment Slice

slice_name = 'MySlice-bluefields'
#site = fablib.get_random_site()
site="SALT"
print(f"Site: {site}")

node1_name = 'Node1'
node2_name = 'Node2'

network_name='net1'

node1_image = "dpu_ubuntu_24"
node2_image = "default_ubuntu_24"

#Create Slice
slice = fablib.new_slice(name=slice_name)

# Network
#net1 = slice.add_l2network(name=network_name, subnet=IPv4Network("192.168.1.0/24"))
net1 = slice.add_l3network(name=network_name)

# Node1
node1 = slice.add_node(name=node1_name, site=site, image=node1_image)
dpu = node1.add_component(model='NIC_ConnectX_7_400', name='nic1')
iface1 =  dpu.get_interfaces()[0]
iface1.set_mode('auto')
net1.add_interface(iface1)

iface2 =  dpu.get_interfaces()[1]
iface2.set_mode('auto')
net1.add_interface(iface2)

# Node2
node2 = slice.add_node(name=node2_name, site=site, image=node2_image)
iface3 = node2.add_component(model='NIC_Basic', name='nic1').get_interfaces()[0]
iface3.set_mode('auto')
net1.add_interface(iface3)


#Submit Slice Request
slice.submit();


# ## Step 3: Configure the BlueField SmartNIC

slice = fablib.get_slice(slice_name)

node1 = slice.get_node(name=node1_name) 
bluefield = node1.get_component(name='nic1')
output = bluefield.configure()


# ## Step 4: Reboot and Set Up the Host-to-DPU Management Channel

node1.execute("sudo reboot")
slice.wait_ssh()

stdout, stderr = node1.execute("sudo ip addr add 192.168.100.1/24 dev tmfifo_net0")

stdout, stderr = node1.execute("sudo ip link set tmfifo_net0 up")

stdout, stderr = node1.execute("ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ''")


# ## Accessing the DPU (Manual Steps)
# #### SSH Access
# #### Console Access

# ## Step 5: Enable Internet Access on the DPU via NAT

node1.upload_directory("node_tools", ".")

import ipaddress
ip = ipaddress.ip_address(node1.get_management_ip())

if ip.version == 4:
    stdout, stderr = node1.execute("sudo ./node_tools/bf3_rshim.sh --mode ipv4")
else:
    stdout, stderr = node1.execute("sudo ./node_tools/bf3_rshim.sh --mode ipv6")

node1.config()
slice.list_interfaces();

for iface in node1.get_interfaces():
    print(f"Setting IP on {iface.get_name()}")
    stdout, stderr = node1.execute(f"sudo ifconfig {iface.get_physical_os_interface_name()} up")
    stdout, stderr = node1.execute(f"sudo ip addr add {iface.get_ip_addr()}/24 dev {iface.get_physical_os_interface_name()}")

for n in slice.get_nodes():
    print(f"Listing IPs on {n.get_name()}")
    stdout, stderr = n.execute("ip addr")
    print("===============================================================================================================")
    print()


# ## Step 6: Run the Experiment

slice = fablib.get_slice(slice_name)

node1 = slice.get_node(name=node1_name)        
node2 = slice.get_node(name=node2_name)           

node2_addr = node2.get_interface(network_name=network_name).get_ip_addr()

stdout, stderr = node1.execute(f'ping -c 5 {node2_addr}')


# ## Continue Learning
# ## Step 7: Delete the Slice

slice = fablib.get_slice(slice_name)
slice.delete()
