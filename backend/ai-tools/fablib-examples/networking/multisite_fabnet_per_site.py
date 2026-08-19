# Multi-Site FABNetv4: Per-Site Services, Not One Spanning Service
# Source: LoomAI - benchmark-derived network service limit pattern
#
# Hard rule: one FABNetv4/FABNetv6 service can attach VMs at ONE site only.
# A FABNet service can hold up to 255 VMs, but all attached VMs must be at
# the same site. For multi-site L3 connectivity, use node.add_fabnet() once
# per node (recommended) or create one FABNet service per site.

from fabrictestbed_extensions.fablib.fablib import FablibManager

fablib = FablibManager()

slice_name = "multisite-fabnet-per-site-demo"


# ## WRONG: one FABNetv4 service spanning multiple sites

# Do not build one L3 network service and attach interfaces from different
# sites. The draft may be accepted locally, but FABRIC submit rejects it:
# "Service cannot span 2 sites. Limit: 1".
#
# wrong_slice = fablib.new_slice(name="wrong-spanning-fabnet")
# net = wrong_slice.add_l3network(name="one-big-fabnet", type="IPv4")
# vm1 = wrong_slice.add_node(name="vm1", site="DALL")
# vm1_iface = vm1.add_component(model="NIC_Basic", name="nic1").get_interfaces()[0]
# net.add_interface(vm1_iface)
# vm2 = wrong_slice.add_node(name="vm2", site="WASH")
# vm2_iface = vm2.add_component(model="NIC_Basic", name="nic1").get_interfaces()[0]
# net.add_interface(vm2_iface)
# wrong_slice.submit()  # submit-time failure


# ## RIGHT: use add_fabnet once per node

# FABlib creates the correct per-site FABNet services and adds backbone routes
# between them. The resulting IPv4 addresses are in 10.128.0.0/10.
slice_obj = fablib.new_slice(name=slice_name)

vm1 = slice_obj.add_node(name="vm1", site="DALL")
vm1.add_fabnet(net_type="IPv4")

vm2 = slice_obj.add_node(name="vm2", site="WASH")
vm2.add_fabnet(net_type="IPv4")

slice_obj.submit()
slice_obj.wait_ssh(progress=True)


# ## Verify after re-fetch

slice_obj = fablib.get_slice(name=slice_name)
vm1 = slice_obj.get_node(name="vm1")
vm2 = slice_obj.get_node(name="vm2")


def fabnetv4_ip(node):
    site = node.get_site()
    iface = node.get_interface(network_name=f"FABNET_IPv4_{site}")
    if iface is None:
        return None
    return str(iface.get_ip_addr())


vm2_ip = fabnetv4_ip(vm2)
stdout, stderr = vm1.execute(f"ping -c 3 {vm2_ip}")
print(stdout)


# ## Explicit per-site services when you are not using add_fabnet

# If you must manage interfaces manually, create one FABNet service per site
# and attach only interfaces from that same site to each service:
#
# explicit = fablib.new_slice(name="explicit-per-site-fabnet")
# dall_net = explicit.add_l3network(name="fabnet-dall", type="IPv4")
# wash_net = explicit.add_l3network(name="fabnet-wash", type="IPv4")
# dall = explicit.add_node(name="dall-vm", site="DALL")
# dall_iface = dall.add_component(model="NIC_Basic", name="nic1").get_interfaces()[0]
# dall_iface.set_mode("auto")
# dall_net.add_interface(dall_iface)
# dall.add_route(subnet=fablib.FABNETV4_SUBNET, next_hop=dall_net.get_gateway())
# wash = explicit.add_node(name="wash-vm", site="WASH")
# wash_iface = wash.add_component(model="NIC_Basic", name="nic1").get_interfaces()[0]
# wash_iface.set_mode("auto")
# wash_net.add_interface(wash_iface)
# wash.add_route(subnet=fablib.FABNETV4_SUBNET, next_hop=wash_net.get_gateway())


# ## Cleanup

slice_obj = fablib.get_slice(name=slice_name)
slice_obj.delete()
