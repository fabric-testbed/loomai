# Create a FABRIC Facility Port
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: facility_port.ipynb
#
# FABRIC does not exist in isolation — it connects to external research
# facilities, campus networks, and other testbeds through **facility ports**. A
# facility port is a pre-provisioned, physical conn...

# # Create a FABRIC Facility Port
# ### FABlib API References
# ### Knowledge Base

# ## Step 1: Configure the Environment and Import FABlib

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()
                     
fablib.show_config();


# ## Step 2: Create the Experiment Slice

slice_name = "MySlice"

facility_port='Chameleon-StarLight'
facility_port_site='STAR'
facility_port_vlan='3309'

#Create a slice
slice = fablib.new_slice(name=slice_name)

node = slice.add_node(name=f"Node1", site='STAR')
#node_iface = node.add_component(model='NIC_ConnectX_6', name="nic1").get_interfaces()[0]
node_iface = node.add_component(model='NIC_Basic', name="nic1").get_interfaces()[0]

facility_port = slice.add_facility_port(name=facility_port, site=facility_port_site, vlan=facility_port_vlan)
facility_port_interface =facility_port.get_interfaces()[0]

print(f"facility_port.get_site(): {facility_port.get_site()}")

#net = slice.add_l2network(name=f'net_facility_port', interfaces=[node_iface,facility_port_interface])
net = slice.add_l2network(name=f'net_facility_port', interfaces=[])
net.add_interface(node_iface)
net.add_interface(facility_port_interface)


#Submit the Request
slice.submit();


# ## Step 3: Observe the Slice's Attributes

slice.show()
slice.list_nodes()
slice.list_networks()
slice.list_interfaces()


# ## Step 4: Configure IP Addressing

from ipaddress import ip_address, IPv4Address, IPv6Address, IPv4Network, IPv6Network

subnet = IPv4Network("192.168.1.0/24")
available_ips = list(subnet)[2:]

node1 = slice.get_node(name=f"Node1")        
node1_iface = node1.get_interface(network_name=f'net_facility_port') 
node1_addr = available_ips.pop(99)
print(f"node1_addr: {node1_addr}")
node1_iface.ip_addr_add(addr=node1_addr, subnet=subnet)

stdout, stderr = node1.execute(f'ip addr show {node1_iface.get_os_interface()}')

stdout, stderr = node1.execute(f'sudo ip link set dev {node1_iface.get_physical_os_interface_name()} up')

stdout, stderr = node1.execute(f'sudo ip link set dev {node1_iface.get_os_interface()} up')


# ## Step 5: Test Connectivity

# ## Step 6: Delete the Slice

# ## Delete the Slice

# ## Continue Learning

slice.delete()
