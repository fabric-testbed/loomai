# Node Networking Patterns — Correct Interface and IP Handling
# Source: LoomAI — ground truth from FABlib API
#
# This example shows the correct ways to work with node interfaces,
# IP addresses, and networking after provisioning. These are the patterns
# the LLM should use instead of hallucinated methods.

from fabrictestbed_extensions.fablib.fablib import FablibManager


def get_fabnet_ip(node):
    """Get FABNetv4 IP using network name pattern after re-fetch.
    add_fabnet() returns None — use get_interface(network_name=...) instead."""
    site = node.get_site()
    iface = node.get_interface(network_name=f"FABNET_IPv4_{site}")
    return str(iface.get_ip_addr()) if iface else None


def demo_interface_methods():
    """Show all the ways to access interface information.

    These are the REAL methods. If a method is not shown here, it probably
    does not exist. Common hallucinated methods:
    - iface.get_network_type()  → WRONG, use iface.get_network().get_type()
    - node.get_fabnet_name()    → WRONG, use MAC matching
    - node.write_file()         → WRONG, use node.upload_file()
    """
    fablib = FablibManager()
    slice_obj = fablib.new_slice(name="net-demo")

    node1 = slice_obj.add_node(name="n1", site=None, cores=2, ram=8, disk=10)
    node2 = slice_obj.add_node(name="n2", site=None, cores=2, ram=8, disk=10)

    # Pattern 1: FABNetv4 with add_fabnet() — simplest
    node1.add_fabnet()  # Returns None — do NOT capture return value
    node2.add_fabnet()  # Returns None

    # Pattern 2: Manual NIC + L2 network
    # nic1 = node1.add_component(model="NIC_Basic", name="nic1")
    # nic2 = node2.add_component(model="NIC_Basic", name="nic2")
    # l2_iface1 = nic1.get_interfaces()[0]
    # l2_iface2 = nic2.get_interfaces()[0]
    # slice_obj.add_l2network(name="lan", interfaces=[l2_iface1, l2_iface2])

    slice_obj.submit()
    slice_obj.wait_ssh(progress=True)

    # Re-fetch (REQUIRED)
    slice_obj = fablib.get_slice(name="net-demo")
    node1 = slice_obj.get_node(name="n1")
    node2 = slice_obj.get_node(name="n2")

    # === Getting IPs ===

    # Method 1: Network name pattern (BEST for FABNetv4)
    n1_ip = get_fabnet_ip(node1)
    n2_ip = get_fabnet_ip(node2)
    print(f"By network name: n1={n1_ip}, n2={n2_ip}")

    # Method 2: Iterate all interfaces
    for node in slice_obj.get_nodes():
        print(f"\n{node.get_name()} interfaces:")
        for iface in node.get_interfaces():
            print(f"  {iface.get_name()}: "
                  f"ip={iface.get_ip_addr()}, "
                  f"mac={iface.get_mac()}, "
                  f"os_iface={iface.get_os_interface()}")
            # Get the network this interface belongs to
            net = iface.get_network()
            if net:
                print(f"    network: {net.get_name()}, type={net.get_type()}")
                # ^^^ THIS is how to get network type — via the network object,
                #     NOT iface.get_network_type() which doesn't exist

    # Method 3: Get interface by network name (works for FABNetv4)
    # The auto-generated network name is FABNET_IPv4_{site_name}
    site = node1.get_site()
    fabnet_iface = node1.get_interface(network_name=f"FABNET_IPv4_{site}")
    if fabnet_iface:
        print(f"\nBy network name: {fabnet_iface.get_ip_addr()}")

    # === Node info ===
    print(f"\nManagement IP: {node1.get_management_ip()}")
    print(f"SSH command: {node1.get_ssh_command()}")
    print(f"Username: {node1.get_username()}")
    print(f"Site: {node1.get_site()}")
    print(f"Host: {node1.get_host()}")

    # === Execute commands ===
    stdout, stderr = node1.execute(f"ping -c 3 {n2_ip}")
    print(f"\nPing result:\n{stdout}")

    # === File transfer ===
    # Upload: node.upload_file(local_path, remote_path)
    # Download: node.download_file(local_path, remote_path)
    # There is NO node.write_file() method!
    import tempfile, os
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("hello from FABRIC!")
        tmp = f.name
    node1.upload_file(tmp, "/tmp/test.txt")
    os.unlink(tmp)
    stdout, _ = node1.execute("cat /tmp/test.txt")
    print(f"Uploaded file content: {stdout.strip()}")

    # Cleanup
    slice_obj.delete()


if __name__ == "__main__":
    demo_interface_methods()
