# Ping Mesh Connectivity Check
# Source: LoomAI — proven pattern for all-pairs ping verification
#
# Tests connectivity between every pair of nodes in a slice using FABNetv4 IPs.
# Useful as a monitor function or post-deployment verification step.
# Shows MAC-based IP retrieval for multiple nodes.

from fabrictestbed_extensions.fablib.fablib import FablibManager


def get_ip_by_mac(node, mac):
    """Find IP by MAC address."""
    for iface in node.get_interfaces():
        if iface.get_mac() == mac:
            return str(iface.get_ip_addr())
    return None


def ping_mesh(slice_name: str, mac_map: dict = None):
    """Run all-pairs ping between nodes.

    Args:
        slice_name: Name of a StableOK slice
        mac_map: Optional dict of {node_name: mac_address} for FABNetv4 IPs.
                 If None, uses management IPs instead.

    Returns:
        List of (src, dst, success, avg_ms) tuples
    """
    fablib = FablibManager()
    slice_obj = fablib.get_slice(name=slice_name)
    nodes = slice_obj.get_nodes()

    # Build IP map
    ip_map = {}
    for node in nodes:
        name = node.get_name()
        if mac_map and name in mac_map:
            ip_map[name] = get_ip_by_mac(node, mac_map[name])
        else:
            ip_map[name] = node.get_management_ip()

    print(f"### PROGRESS: Testing {len(nodes)}-node mesh ({len(nodes) * (len(nodes)-1)} paths)")
    print(f"  IPs: {ip_map}")

    results = []
    for src_node in nodes:
        src = src_node.get_name()
        for dst_name, dst_ip in ip_map.items():
            if src == dst_name:
                continue
            try:
                stdout, _ = src_node.execute(f"ping -c 3 -W 5 {dst_ip}", timeout=20)
                # Parse average RTT from ping output
                avg_ms = None
                for line in stdout.splitlines():
                    if "avg" in line:
                        # Format: rtt min/avg/max/mdev = 0.5/1.2/2.0/0.3 ms
                        parts = line.split("=")[-1].strip().split("/")
                        if len(parts) >= 2:
                            avg_ms = float(parts[1])
                success = "0% packet loss" in stdout
                results.append((src, dst_name, success, avg_ms))
                status = f"OK ({avg_ms:.1f}ms)" if success and avg_ms else ("OK" if success else "FAIL")
                print(f"  {src} -> {dst_name}: {status}")
            except Exception as e:
                results.append((src, dst_name, False, None))
                print(f"  {src} -> {dst_name}: ERROR ({e})")

    # Summary
    passed = sum(1 for _, _, ok, _ in results if ok)
    total = len(results)
    print(f"\n### PROGRESS: Mesh result: {passed}/{total} paths OK")

    return results


if __name__ == "__main__":
    import sys
    slice_name = sys.argv[1] if len(sys.argv) > 1 else "my-slice"
    results = ping_mesh(slice_name)
    if not all(ok for _, _, ok, _ in results):
        sys.exit(1)
