# PortMirror: Intra-Slice Traffic Capture with Basic NICs
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: port_mirror_basic.ipynb
#
# This notebook demonstrates port mirroring within a **single slice** — no
# separate listener slice is needed. Rather than monitoring traffic from another
# user's slice, this pattern is useful for **de...

# # PortMirror: Intra-Slice Traffic Capture with Basic NICs
# ### FABlib API References
# ### Knowledge Base

# ## Step 0: Import the FABlib Library

from ipaddress import ip_address, IPv4Address, IPv6Address, IPv4Network, IPv6Network
import ipaddress

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()
                     
fablib.show_config();


# ## Step 1: Create the Traffic Generator Nodes

slice_name = 'MySlice-generator-listener-basic'

node1_name = 'Node1'
node2_name = 'Node2'

network1_name='net1'
network2_name='net2'

listener_node_name = 'listener_node'
listener_pm_service = 'pmservice'
listener_direction = 'both' # can also be 'rx' and 'tx'

# we will use CX5 to mirror traffic so need site that have CX5 for this example.
cx5_column_name = 'nic_connectx_5_available'

# find two sites with available ConnectX-5
site1 = fablib.get_random_site(filter_function=lambda x: x[cx5_column_name] == 2)

site2 = fablib.get_random_site(avoid=[site1])

print(f'Will create "{slice_name}" on {site1} and {site2}')


# ### Create the slice

# Create Traffic generator slice

slice = fablib.new_slice(name=slice_name)

# Networks
net1 = slice.add_l3network(name=network1_name, type='IPv4')
net2 = slice.add_l3network(name=network2_name, type='IPv4')

# Node1
node1 = slice.add_node(name=node1_name, site=site1)
iface1 = node1.add_component(model='NIC_ConnectX_5', name='nic1').get_interfaces()[0]
iface1.set_mode('auto')
net1.add_interface(iface1)
node1.add_route(subnet=fablib.FABNETV4_SUBNET, next_hop=net1.get_gateway())

# Node2
node2 = slice.add_node(name=node2_name, site=site2)
iface2  = node2.add_component(model='NIC_Basic', name='nic1').get_interfaces()[0]
iface2.set_mode('auto')
net2.add_interface(iface2)
node2.add_route(subnet=fablib.FABNETV4_SUBNET, next_hop=net2.get_gateway())


#Submit Slice Request
slice.submit();


# ## Step 2: Add the Listener Node to the Same Slice

slice = fablib.get_slice(slice_name)
node1 = slice.get_node(node1_name)

mirror_port_name = node1.get_interfaces()[0].get_peer_port_name()
mirror_port_vlan = node1.get_interfaces()[0].get_peer_port_vlan()

listener_node = slice.add_node(name=listener_node_name, site=site1)
# the first (index 0) interface will be connected into the switch to receive mirror traffic
listener_interface = listener_node.add_component(model='NIC_ConnectX_5', name='pmnic').get_interfaces()[0]

# port mirroring is a network service of a special kind
# it mirrors one or both directions of traffic ('rx', 'tx' or 'both') of a port that we identified in
# Traffic Generator Topology into a port of a card we allocated in this slice (listener_interface)
# NOTE: if you select 'both' directions that results in potentially 200Gbps of traffic, which
# of course is impossible to fit into a single 100Gbps port of a ConnectX_6 card - be mindful of the
# data rates.
pmnet = slice.add_port_mirror_service(name=listener_pm_service, 
                                      mirror_interface_name=mirror_port_name,
                                      mirror_interface_vlan=mirror_port_vlan,
                                      receive_interface=listener_interface,
                                      mirror_direction = listener_direction)


#Submit Slice Request
slice.submit();


# ### Test the slice

slice = fablib.get_slice(slice_name)

node1 = slice.get_node(name=node1_name)        
node2 = slice.get_node(name=node2_name)           

node2_addr = node2.get_interface(network_name=network2_name).get_ip_addr()

stdout, stderr = node1.execute(f'ping -c 5 {node2_addr}')

slice = fablib.get_slice(slice_name)

listener_node = slice.get_node(name=listener_node_name)   

command = 'sudo dnf install -y tcpdump'

stdout, stderr = listener_node.execute(command)


# ## Step 3: Run the Experiment — Generate Traffic and Capture the Mirror

slice = fablib.get_slice(slice_name)

node1 = slice.get_node(name=node1_name)        
node2 = slice.get_node(name=node2_name)           
listener_node = slice.get_node(name=listener_node_name)

node2_addr = node2.get_interface(network_name=network2_name).get_ip_addr()
listener_node_intf_name = listener_node.get_interface(network_name=listener_pm_service).get_device_name()

print(f'Will run tcpdump on {listener_node.get_name()} interface {listener_node_intf_name}, listening to ping in Traffic Generator Slice')

# run everything for 10 seconds
traffic_command = f'timeout 10s ping -c 100 {node2_addr}'
# look at libpcap documentation for more info on how to filter packets
listen_command = f'sudo timeout 10s tcpdump -i {listener_node_intf_name} icmp'

# start traffic generation in the background
node2_thread = node1.execute_thread(traffic_command, output_file='node1_ping.log')
# start tcpdump in the foreground
listener_node_thread = listener_node.execute(listen_command)

# check for errors
stdout, stderr = node2_thread.result()
if stderr and len(stderr):
    print(f'Error output from Traffic Generator Slice: {stderr}')
    
print(f'Done')


# ## Continue Learning
# ## Step 4: Delete the Slice

try:
    fablib.delete_slice(slice_name)
except Exception as e:
    print(e)

print('Done')
