# FABlib API Quick Reference — Actual Methods (Ground Truth)
# Source: Extracted from fabrictestbed-extensions installed package
#
# This file documents the REAL methods on each FABlib class.
# If a method is not listed here, it DOES NOT EXIST. Do not invent methods.
#
# Common hallucinated methods that DO NOT EXIST:
#   - node.write_file()          → use node.upload_file(local, remote)
#   - node.get_fabnet_name()     → use get_ip_by_mac() pattern below
#   - iface.get_network_type()   → use iface.get_network().get_type()
#   - import fablib              → use: from fabrictestbed_extensions.fablib.fablib import FablibManager
#   - add_node(..., tags=)       → tags is NOT a parameter
#   - fablib.list_site_names()   → use fablib.get_site_names()

# === CORRECT IMPORT ===
from fabrictestbed_extensions.fablib.fablib import FablibManager

fablib = FablibManager()

# === FablibManager — Key Methods ===
# fablib.new_slice(name) -> Slice
# fablib.get_slice(name=..., slice_id=...) -> Slice
# fablib.get_slices() -> List[Slice]
# fablib.delete_slice(slice_name)
# fablib.get_site_names() -> List[str]           # NOT list_site_names()
# fablib.get_random_site(avoid=[...]) -> str
# fablib.get_random_sites(count=2) -> List[str]
# fablib.get_resources() -> ResourcesV2
# fablib.get_available_resources() -> ResourcesV2
# fablib.list_sites(quiet=False) -> str (table)  # Returns formatted string, NOT dicts
# fablib.show_config()
# fablib.get_image_names() -> dict

# === Slice — Key Methods ===
# slice.add_node(name, site=None, cores=2, ram=8, disk=10, image=None,
#                instance_type=None, host=None, user_data={}, avoid=[]) -> Node
#   NOTE: NO tags parameter. NO random parameter.
#
# slice.add_l2network(name, interfaces=[], type=None, subnet=None) -> NetworkService
# slice.add_l3network(name, interfaces=[], type="IPv4") -> NetworkService
# slice.submit(wait=True, wait_timeout=1800, progress=True, post_boot_config=True,
#              wait_ssh=True) -> str
# slice.wait_ssh(timeout=1800, progress=False)
# slice.post_boot_config()
# slice.delete()
# slice.modify(wait=True)
# slice.renew(end_date=None, days=None)
# slice.save(filename)
# slice.load(filename)
# slice.get_state() -> str
# slice.get_nodes() -> List[Node]
# slice.get_node(name) -> Node
# slice.get_networks() -> List[NetworkService]
# slice.get_network(name) -> NetworkService
# slice.get_interfaces() -> List[Interface]
# slice.get_slice_id() -> str
# slice.get_name() -> str
# slice.get_lease_end() -> str
# slice.get_error_messages() -> List[dict]
# slice.validate() -> (bool, dict)
# slice.isStable() -> bool

# === Node — Key Methods ===
# node.add_component(model, name) -> Component
#   Models: NIC_Basic, NIC_ConnectX_5, NIC_ConnectX_6, GPU_RTX6000,
#           GPU_TeslaT4, GPU_A30, GPU_A40, NVME_P4510, FPGA_Xilinx_U280
#
# node.add_fabnet(name="FABNET", net_type="IPv4", nic_type="NIC_Basic") -> None
#   Returns None! Do NOT capture the return value. After re-fetch, use:
#   node.get_interface(network_name=f"FABNET_IPv4_{node.get_site()}")
#
# node.execute(command, timeout=None, quiet=False) -> (stdout, stderr)
# node.upload_file(local_path, remote_path)       # NOT write_file()
# node.download_file(local_path, remote_path)
# node.upload_directory(local_dir, remote_dir)
# node.download_directory(local_dir, remote_dir)
# node.get_management_ip() -> str
# node.get_ssh_command() -> str
# node.get_name() -> str
# node.get_site() -> str
# node.get_cores() -> int
# node.get_ram() -> int
# node.get_disk() -> int
# node.get_image() -> str
# node.get_interfaces() -> List[Interface]
# node.get_interface(name=None, network_name=None) -> Interface
# node.get_components() -> List[Component]
# node.get_component(name) -> Component
# node.get_host() -> str
# node.get_username() -> str
# node.set_user_data(user_data: dict)            # For cloud-init
# node.add_post_boot_execute(command)
# node.add_post_boot_upload_file(local, remote)
# node.ip_addr_add(addr, subnet, interface)
# node.ip_route_add(subnet, gateway, interface)
# node.ping_test(dst_ip) -> bool
# node.test_ssh() -> bool
# node.delete()

# === Interface — Key Methods ===
# iface.get_ip_addr()          # Returns IPv4Address object, use str() to convert
# iface.get_mac() -> str       # Unique, stable — use for matching after re-fetch
# iface.get_name() -> str
# iface.get_network() -> NetworkService  # NOT get_network_type()
# iface.get_node() -> Node
# iface.get_component() -> Component
# iface.get_os_interface() -> str
# iface.get_bandwidth() -> int
# iface.get_vlan() -> str
# iface.get_site() -> str
# iface.get_device_name() -> str
# iface.get_type() -> str       # This exists on Interface, NOT get_network_type()
# iface.set_ip_addr(addr, mode)
# iface.ip_addr_add(addr, subnet)
# iface.ip_link_up()
# iface.ip_link_down()
# iface.add_sub_interface(name, vlan, bw=10)

# === Component — Key Methods ===
# comp.get_interfaces() -> List[Interface]
# comp.get_interface(name=None, network_name=None) -> Interface
# comp.get_model() -> str
# comp.get_name() -> str
# comp.get_type() -> str
# comp.get_device_name() -> str
# comp.get_pci_addr() -> str
# comp.configure_nvme(mount_point="")
# comp.delete()

# === NetworkService — Key Methods ===
# net.get_interfaces() -> List[Interface]
# net.get_name() -> str
# net.get_type() -> str          # L2Bridge, L2STS, FABNetv4, etc.
# net.get_subnet() -> ip_network
# net.get_gateway() -> ip_address
# net.get_available_ips(count=256) -> List[ip_address]
# net.allocate_ip(addr=None) -> ip_address
# net.add_interface(interface)
# net.delete()


# === PROVEN PATTERN: Get FABNetv4 IP by MAC ===
# This is the ONLY reliable way to find FABNetv4 IPs after provisioning.
# Do NOT use get_fabnet_name() (doesn't exist) or filter by IP prefix.

def get_fabnet_ip(node):
    """Get FABNetv4 IP using network name pattern after re-fetch.
    add_fabnet() returns None — use get_interface(network_name=...) instead."""
    site = node.get_site()
    iface = node.get_interface(network_name=f"FABNET_IPv4_{site}")
    return str(iface.get_ip_addr()) if iface else None


# === PROVEN PATTERN: Full Lifecycle ===
#
# 1. Create slice
# slice_obj = fablib.new_slice(name="my-slice")
#
# 2. Add nodes (NO tags parameter)
# node1 = slice_obj.add_node(name="n1", site=None, cores=2, ram=8, disk=10)
#
# 3. Add networking (add_fabnet returns None — don't capture it)
# node1.add_fabnet()
#
# 4. Submit
# slice_obj.submit()
# slice_obj.wait_ssh(progress=True)
#
# 5. RE-FETCH (required — originals go stale)
# slice_obj = fablib.get_slice(name="my-slice")
# node1 = slice_obj.get_node(name="n1")
#
# 6. Get IPs by network name
# ip1 = get_fabnet_ip(node1)
#
# 7. Execute commands
# stdout, stderr = node1.execute("hostname")
#
# 8. Upload files (NOT write_file)
# node1.upload_file("/local/path", "/remote/path")
#
# 9. Cleanup
# slice_obj.delete()
