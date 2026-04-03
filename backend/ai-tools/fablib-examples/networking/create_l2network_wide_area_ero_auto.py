# Wide-Area L2 Network with Explicit Route Options (ERO) and Bandwidth Reservation
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: create_l2network_wide_area_ero_auto.ipynb
#
# This notebook demonstrates how to provision two **wide-area Layer 2 Ethernet
# circuits** between the same pair of FABRIC sites, each following a **different
# explicitly specified path** through the F...

# # Wide-Area L2 Network with Explicit Route Options (ERO) and Bandwidth Reservation
# ### Key Concepts: ERO and Bandwidth Reservation
# ### FABlib API References

# ## Step 1: Configure the Environment

from ipaddress import ip_address, IPv4Address, IPv6Address, IPv4Network, IPv6Network
import ipaddress

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()
                     
fablib.show_config();


# ## Step 2: Define the Slice Topology
# ### Topology Overview
# ### Why Dedicated NICs for ERO?
# ### Post-Boot Automation

slice_name = 'MySlice-ero'
[site1, site2, site3, site4] = ["ATLA", "WASH", "STAR", "NEWY"]
print(f"Sites: {site1}, {site2}, {site3}, {site4}")

node1_name = 'Node1'
node2_name = 'Node2'
# Path1 : LOSA -> SALT -> NEWY
# Path2 : LOSA -> DALL -> NEWY
net1_name = 'net-with-ero-path1' 
net2_name = 'net-with-ero-path2'

image="default_rocky_9"


# ## Step 4: Submit the Slice

slice.submit();


# ## Step 3: Run the Experiment

# Get Slice and Nodes
slice = fablib.get_slice(slice_name)

node1 = slice.get_node(name=node1_name)        
node2 = slice.get_node(name=node2_name)


# ### Ping on Path1 (via WASH)

node2_net1_addr = node2.get_interface(network_name=net1_name).get_ip_addr()

stdout, stderr = node1.execute(f'ping -c 5 {node2_net1_addr}')


# ### iPerf3 Bandwidth Test on Path1 (via WASH, 8 Gbps reserved)

print("xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
stdout1, stderr1 = node2.execute("docker run -d --rm "
                                 "--network host "
                                 "fabrictestbed/slice-vm-rocky9-multitool:0.1.0 "
                                 "iperf3 -s -1",
                                 quiet=True, output_file=f"{node2.get_name()}.log");

print(f"Source:  {node2.get_name()} to Dest: {node1.get_name()}")

stdout2, stderr2 = node1.execute("docker run --rm "
                                 "--network host "
                                 "fabrictestbed/slice-vm-rocky9-multitool:0.1.0 "
                                 f"iperf3 -c {node2_net1_addr} -P 10 -t 30 -i 10 -O 10",
                                 quiet=False, output_file=f"{node1.get_name()}.log");
print("xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")


# ### Ping on Path2 (via STAR)

node2_net2_addr = node2.get_interface(network_name=net2_name).get_ip_addr()

stdout, stderr = node1.execute(f'ping -c 5 {node2_net2_addr}')


# ### iPerf3 Bandwidth Test on Path2 (via STAR, 2 Gbps reserved)

print("xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
stdout1, stderr1 = node2.execute("docker run -d --rm "
                                 "--network host "
                                 "fabrictestbed/slice-vm-rocky9-multitool:0.1.0 "
                                 "iperf3 -s -1",
                                 quiet=True, output_file=f"{node2.get_name()}.log");

print(f"Source:  {node2.get_name()} to Dest: {node1.get_name()}")

stdout2, stderr2 = node1.execute("docker run --rm "
                                 "--network host "
                                 "fabrictestbed/slice-vm-rocky9-multitool:0.1.0 "
                                 f"iperf3 -c {node2_net2_addr} -P 10 -t 30 -i 10 -O 10",
                                 quiet=False, output_file=f"{node1.get_name()}.log");
print("xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")


# ## Continue Learning
# ## Step 4: Delete the Slice

slice.delete()
