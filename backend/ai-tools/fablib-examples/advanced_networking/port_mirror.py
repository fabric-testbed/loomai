# PortMirror: Passive Traffic Capture Across Two Slices
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: port_mirror.ipynb
#
# **Port mirroring** (also called SPAN — Switched Port ANalyzer) is a network
# monitoring technique where the dataplane switch copies all traffic flowing
# through a specific physical port and sends a d...

# # PortMirror: Passive Traffic Capture Across Two Slices
# ### FABlib API References
# ### Knowledge Base

# ## Step 0: Import the FABlib Library

from ipaddress import ip_address, IPv4Address, IPv6Address, IPv4Network, IPv6Network
import ipaddress

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()
                     
fablib.show_config();


# ## Step 1: Create the Traffic Generator Slice

# find two available sites

# we will use CX5 to generate traffic and CX6 to mirror traffic into so need sites that have both for this example.
cx5_column_name = 'nic_connectx_5_available'
cx6_column_name = 'nic_connectx_6_available'

# find two sites with available ConnectX-5 and ConnectX-6 cards
(site1, site2) = fablib.get_random_sites(count=2, filter_function=lambda x: x[cx5_column_name] > 0 and x[cx6_column_name] > 0)

slice_name = 'Traffic Generator Slice'

# you can use the below line to override site locations
#site1, site2 = ('INDI', 'CLEM')

print(f'Will create "{slice_name}" on {site1} and {site2}')

node1_name = 'Node1'
node2_name = 'Node2'

network1_name='net1'
network2_name='net2'


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
iface2  = node2.add_component(model='NIC_ConnectX_5', name='nic1').get_interfaces()[0]
iface2.set_mode('auto')
net2.add_interface(iface2)
node2.add_route(subnet=fablib.FABNETV4_SUBNET, next_hop=net2.get_gateway())

#Submit Slice Request
slice.submit();

slice = fablib.get_slice(slice_name)

node1 = slice.get_node(name=node1_name)   
node2 = slice.get_node(name=node2_name)

site1 = node1.get_site()
site2 = node2.get_site()

node1_addr = node1.get_interface(network_name=f'{network1_name}').get_ip_addr()
node2_addr = node2.get_interface(network_name=f'{network2_name}').get_ip_addr()

slice.list_nodes()
slice.list_networks()
print(f'Node1 FABNetV4 IP Address is {node1_addr}')
print(f'Node2 FABNetV4 IP Address is {node2_addr}')


# ### Test the slice

slice = fablib.get_slice(slice_name)

node1 = slice.get_node(name=node1_name)        
node2 = slice.get_node(name=node2_name)           

node2_addr = node2.get_interface(network_name=network2_name).get_ip_addr()

stdout, stderr = node1.execute(f'ping -c 5 {node2_addr}')


# ## Step 2: Create the Listener Slice

listener_slice_name = 'Traffic Listening Slice'
listener_site = site1
listener_node_name = 'listener_node'
listener_pm_service = 'pmservice'
listener_direction = 'both' # can also be 'rx' and 'tx'

# let's see if the traffic generator slice topology provided us with the port name
mirror_port_name = node1.get_interfaces()[0].get_peer_port_name()

if not mirror_port_name:
    print("Can't proceed as the traffic generator topology did not provide the name of the port to mirror")

print(f'Will create slice {listener_slice_name} on {listener_site} listening to port {mirror_port_name}')

# Create listening slice
pmslice = fablib.new_slice(name=listener_slice_name)

listener_node = pmslice.add_node(name=listener_node_name, site=listener_site)
# the first (index 0) interface will be connected into the switch to receive mirror traffic
listener_interface = listener_node.add_component(model='NIC_ConnectX_6', name='pmnic').get_interfaces()[0]

# port mirroring is a network service of a special kind
# it mirrors one or both directions of traffic ('rx', 'tx' or 'both') of a port that we identified in
# Traffic Generator Topology into a port of a card we allocated in this slice (listener_interface)
# NOTE: if you select 'both' directions that results in potentially 200Gbps of traffic, which
# of course is impossible to fit into a single 100Gbps port of a ConnectX_6 card - be mindful of the
# data rates.
pmnet = pmslice.add_port_mirror_service(name=listener_pm_service, 
                                      mirror_interface_name=mirror_port_name,
                                      receive_interface=listener_interface,
                                      mirror_direction = listener_direction)

#Submit Slice Request
pmslice.submit();


# ### Query the Listener slice

pmslice = fablib.get_slice(listener_slice_name)

listener_node = pmslice.get_node(name=listener_node_name)   

pmslice.list_nodes()
pmslice.list_networks()

command = 'sudo dnf install -y tcpdump'

stdout, stderr = listener_node.execute(command)


# ## Step 3: Run the Experiment — Generate and Capture Traffic

slice = fablib.get_slice(slice_name)

node1 = slice.get_node(name=node1_name)        
node2 = slice.get_node(name=node2_name)           
listener_node = pmslice.get_node(name=listener_node_name)

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
# ## Step 4: Delete Both Slices

try:
    fablib.delete_slice(slice_name)
except Exception as e:
    print(e)

try:
    fablib.delete_slice(listener_slice_name)
except Exception as e:
    print(e)
    
print('Done')
