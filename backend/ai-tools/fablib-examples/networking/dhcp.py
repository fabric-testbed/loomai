# DHCP Server on a FABRIC L2 Network
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: dhcp.ipynb
#
# This notebook demonstrates how to deploy an **ISC DHCP server** on one node of
# a FABRIC L2 network and have two client nodes obtain IP addresses dynamically
# via the DHCP protocol. This is a realist...

# # DHCP Server on a FABRIC L2 Network
# ### What This Notebook Does
# ### FABlib API References
# ### External References

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

try:
    fablib = fablib_manager()
                     
    fablib.show_config()
except Exception as e:
    print(f"Exception: {e}")


# ## Step 1: Configure the Environment and Import FABlib

# Clean up log directory to avoid large files
import os
for item in os.scandir(os.path.join(os.getcwd(), 'logs')):
    if '.' != item.name[0]:
        os.remove(item.path)


# ## Step 2: Prepare Log Directory

# ## Step 3: Define the Slice Topology
# ### Network Design

slice_name = 'DHCPSlice'

site = fablib.get_random_site()
print(f"Site: {site}")

node1_name = 'Server'
node2_name = 'Client1'
node3_name = 'Client2'
network_name='DHCP-demo-net'
node1_nic_name = 'nic1'
node2_nic_name = 'nic2'
node3_nic_name = 'nic3'
image = 'default_ubuntu_22'

from ipaddress import ip_address, IPv4Address, IPv6Address, IPv4Network, IPv6Network
subnet = IPv4Network("10.0.0.0/24")
available_ips = list(subnet)[1:]

try:
    #Create Slice
    slice = fablib.new_slice(name=slice_name)
    net = slice.add_l2network(name=network_name, subnet=subnet)
    # Node1
    node1 = slice.add_node(name=node1_name, site=site, image=image)
    iface1 = node1.add_component(model='NIC_Basic', name=node1_nic_name).get_interfaces()[0]
    iface1.set_mode('auto')
    net.add_interface(iface1)
    
    # Node2
    node2 = slice.add_node(name=node2_name, site=site, image=image)
    iface2 = node2.add_component(model='NIC_Basic', name=node2_nic_name).get_interfaces()[0]
    iface2.set_mode('auto')
    net.add_interface(iface2)
    
    # Node3
    node3 = slice.add_node(name=node3_name, site=site, image=image)
    iface3 = node3.add_component(model='NIC_Basic', name=node3_nic_name).get_interfaces()[0]
    iface3.set_mode('auto')
    net.add_interface(iface3)

    #Submit Slice Request
    slice.submit()
except Exception as e:
    print(f"Exception: {e}")


# ## Step 4: Submit the Slice

# ## Step 5: Install Packages on All Nodes
# ### Parallel Execution with Threads

def thread_ripper(command):
    nodes = slice.get_nodes()
    threads = {}
    for node in nodes:
        print(f'Create thread for node: {node.get_name()}')
        threads[node] = node.execute_thread(command, output_file=f'logs/{node.get_name()}.log')

    print('Done creating threads!')

    for node, thread in threads.items():
        print(f'node: {node.get_name()}... ', end='')
        stdout, stderr = thread.result()
        print('done!')


# ## Install DHCP Server to the Server Node

# Get nodes
# What we will place the DHCP server on
server = slice.get_node(name=node1_name)
# Our DHCP Clients
client1 = slice.get_node(name=node2_name)
client2 = slice.get_node(name=node3_name)

# Step 1: Update packages:
thread_ripper('sudo apt-get update')
thread_ripper('sudo apt-get install -y net-tools network-manager')

# ## Step 6: Configure the DHCP Server
# ### DHCP Server Architecture
# ### Understanding the dhcpd.conf Configuration
# ### Define the DHCP Subnet

from ipaddress import ip_address, IPv4Address, IPv6Address, IPv4Network, IPv6Network

try:
    subnet = IPv4Network("192.168.1.0/24")
    available_ips = list(subnet)[1:]
except Exception as e:
    print(f"Exception: {e}")

# Step 1: Give the DHCP server an address on the same DHCP subnet we want
try:
    server_iface = server.get_interface(network_name=network_name) 
    server_addr = available_ips.pop(0)
    server_iface.ip_addr_add(addr=server_addr, subnet=subnet)

    stdout, stderr = server.execute(f'sudo ifconfig {server_iface.get_os_interface()} up')
    stdout, stderr = server.execute(f'ip addr show {server_iface.get_os_interface()}')
except Exception as e:
    print(f"Exception: {e}")


# ### Step 6a: Assign a Static IP to the Server

# Step 2: Install DHCP Server
stdout, stderr = server.execute('sudo apt-get install -y isc-dhcp-server', quiet=True, output_file=f'logs/server.log')
# server.execute('sudo rm /etc/dhcp/dhcpd.conf && sudo dpkg --configure -a') # Run this if the above fails


# ### Step 6b: Install isc-dhcp-server

# Step 3: Configure server
stdout, stderr = server.execute('''sudo bash -c 'echo "default-lease-time 600;
max-lease-time 7200;
authoritative;
 
subnet 192.168.1.0 netmask 255.255.255.0 {
 range 192.168.1.100 192.168.1.200;
 option subnet-mask 255.255.255.0;
}
" >> /etc/dhcp/dhcpd.conf'
''')
server.execute(r'''sudo sed -i 's/INTERFACESv4=""/INTERFACESv4="ens7"/' /etc/default/isc-dhcp-server''', quiet=True, output_file='logs/server.log');


# ### Step 6c: Write the DHCP Configuration

# Step 4: Restart the server
server.execute('sudo systemctl restart isc-dhcp-server.service');
server.execute('sudo systemctl status isc-dhcp-server.service');


# ### Step 6d: Start and Verify the DHCP Service

# ## Step 7: Request IP Addresses on the Clients

clients = {}
for client in (client1, client2,):
    # Request DHCP Address
    client.execute('sudo dhclient ens7');
    # Extract IP
    stdout, stderr = client.execute('''ip addr show ens7 | grep "inet " | awk '{print $2}' | cut -d/ -f1''', quiet=True);
    clients[client.get_name() + '_address'] = stdout[:-1].split('\n')[1] # remove newline
    
clients


# ## Step 8: Run the Experiment

try:        
    stdout, stderr = client1.execute(f"ping -c 5 {clients['Client2_address']}")
    
except Exception as e:
    print(f"Exception: {e}")


# ## Continue Learning
# ## Step 9: Delete the Slice

try:
    slice = fablib.get_slice(name=slice_name)
    slice.delete()
except Exception as e:
    print(f"Exception: {e}")
