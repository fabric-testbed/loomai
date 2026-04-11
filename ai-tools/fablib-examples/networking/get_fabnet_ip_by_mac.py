# Get FABNetv4 IP Address After Provisioning
# Source: LoomAI — proven pattern for retrieving FABNetv4 IPs
#
# IMPORTANT: add_fabnet() returns None. MACs are empty before submit.
# After submit + re-fetch, use get_interface(network_name=...) to find
# the FABNetv4 interface by its auto-generated network name pattern:
#   FABNET_IPv4_{site_name}
#
# Do NOT:
#   - Capture add_fabnet() return value (it's None)
#   - Use get_fabnet_name() (doesn't exist)
#   - Filter by IP prefix like startswith("10.128") (FABNetv4 is /10, spans 10.128-10.191)
#   - Use iface.get_network_type() (doesn't exist)

from fabrictestbed_extensions.fablib.fablib import FablibManager

fablib = FablibManager()

slice_name = "fabnet-ip-demo"


def get_fabnet_ip(node):
    """Get the FABNetv4 IP for a node after re-fetching the slice.

    The network name follows the pattern: FABNET_IPv4_{site_name}
    """
    site = node.get_site()
    iface = node.get_interface(network_name=f"FABNET_IPv4_{site}")
    if iface:
        return str(iface.get_ip_addr())
    return None


# ## Step 1: Build topology

slice_obj = fablib.new_slice(name=slice_name)

node1 = slice_obj.add_node(name="node1", site=None)
node1.add_fabnet()  # Returns None — do NOT capture

node2 = slice_obj.add_node(name="node2", site=None)
node2.add_fabnet()  # Returns None — do NOT capture

# ## Step 2: Submit and wait

slice_obj.submit()
slice_obj.wait_ssh(progress=True)

# ## Step 3: Re-fetch slice (REQUIRED — original objects are stale)

slice_obj = fablib.get_slice(name=slice_name)
node1 = slice_obj.get_node(name="node1")
node2 = slice_obj.get_node(name="node2")

# ## Step 4: Get FABNetv4 IPs by network name pattern

node1_ip = get_fabnet_ip(node1)
node2_ip = get_fabnet_ip(node2)
print(f"FABNetv4 IPs: node1={node1_ip}, node2={node2_ip}")

# ## Step 5: Use the IPs

stdout, stderr = node1.execute(f"ping -c 3 {node2_ip}")
print(stdout)

# ## Step 6: Cleanup

slice_obj = fablib.get_slice(name=slice_name)
slice_obj.delete()
