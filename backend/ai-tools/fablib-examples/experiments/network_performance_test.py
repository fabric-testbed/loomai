# Network Performance Test with iperf3
# Source: LoomAI — proven pattern for bandwidth testing between FABRIC nodes
#
# Creates a 2-node slice with FABNetv4, installs iperf3, runs bandwidth tests,
# and reports results. Shows correct MAC-based IP retrieval and re-fetch pattern.

import sys
import re

from fabrictestbed_extensions.fablib.fablib import FablibManager


def get_fabnet_ip(node):
    """Get FABNetv4 IP using the network name pattern after re-fetch.
    add_fabnet() returns None — use get_interface(network_name=...) instead."""
    site = node.get_site()
    iface = node.get_interface(network_name=f"FABNET_IPv4_{site}")
    return str(iface.get_ip_addr()) if iface else None


def parse_iperf_result(stdout):
    """Extract bandwidth from iperf3 output."""
    for line in stdout.splitlines():
        if "sender" in line.lower():
            m = re.search(r"([\d.]+)\s*(Kbits|Mbits|Gbits)/sec", line)
            if m:
                val, unit = float(m.group(1)), m.group(2)
                if unit == "Kbits":
                    return val / 1_000_000
                elif unit == "Mbits":
                    return val / 1_000
                else:
                    return val
    return None


def start(slice_name: str):
    """Create slice, run iperf3 bandwidth test, report results."""
    fablib = FablibManager()

    print(f"### PROGRESS: Creating slice '{slice_name}'")
    slice_obj = fablib.new_slice(name=slice_name)

    node1 = slice_obj.add_node(name="server", site=None, cores=4, ram=8, disk=10,
                                image="default_ubuntu_22")
    node2 = slice_obj.add_node(name="client", site=None, cores=4, ram=8, disk=10,
                                image="default_ubuntu_22")

    # FABNetv4
    node1.add_fabnet()  # returns None — do NOT capture return value
    node2.add_fabnet()  # returns None

    print("### PROGRESS: Submitting slice...")
    slice_obj.submit()
    slice_obj.wait_ssh(progress=True)

    # Re-fetch slice (REQUIRED)
    slice_obj = fablib.get_slice(name=slice_name)
    server = slice_obj.get_node(name="server")
    client = slice_obj.get_node(name="client")

    # Get IPs by network name pattern
    server_ip = get_fabnet_ip(server)
    client_ip = get_fabnet_ip(client)
    print(f"### PROGRESS: server={server_ip}, client={client_ip}")

    # Install iperf3
    print("### PROGRESS: Installing iperf3...")
    for node in [server, client]:
        node.execute("sudo apt-get update -qq && sudo apt-get install -y -qq iperf3", timeout=300)

    # Start iperf3 server
    server.execute("pkill iperf3 2>/dev/null; nohup iperf3 -s > /dev/null 2>&1 &", timeout=10)

    import time
    time.sleep(2)

    # Run tests: TCP and UDP
    print("### PROGRESS: Running TCP bandwidth test (10 seconds)...")
    tcp_out, _ = client.execute(f"iperf3 -c {server_ip} -t 10", timeout=30)
    tcp_bw = parse_iperf_result(tcp_out)

    print("### PROGRESS: Running UDP bandwidth test (10 seconds)...")
    udp_out, _ = client.execute(f"iperf3 -c {server_ip} -t 10 -u -b 10G", timeout=30)
    udp_bw = parse_iperf_result(udp_out)

    # Report
    print("\n=== Network Performance Results ===")
    print(f"  TCP Bandwidth: {tcp_bw:.2f} Gbps" if tcp_bw else "  TCP: FAILED")
    print(f"  UDP Bandwidth: {udp_bw:.2f} Gbps" if udp_bw else "  UDP: FAILED")
    print("=== End ===\n")
    print(f"### PROGRESS: Test complete. TCP={tcp_bw:.2f} Gbps" if tcp_bw else "### PROGRESS: Test complete.")


def stop(slice_name: str):
    fablib = FablibManager()
    try:
        fablib.get_slice(name=slice_name).delete()
        print("### PROGRESS: Slice deleted.")
    except Exception as e:
        print(f"### PROGRESS: {e}")


def monitor(slice_name: str):
    fablib = FablibManager()
    try:
        s = fablib.get_slice(name=slice_name)
        if "StableOK" not in str(s.get_state()):
            sys.exit(1)
        for n in s.get_nodes():
            n.execute("echo ok", quiet=True)
        print("### PROGRESS: Healthy")
    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: script.py {start|stop|monitor} SLICE_NAME")
        sys.exit(1)
    {"start": start, "stop": stop, "monitor": monitor}[sys.argv[1]](sys.argv[2])
