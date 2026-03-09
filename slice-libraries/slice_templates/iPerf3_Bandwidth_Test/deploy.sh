#!/bin/bash
# deploy.sh — iPerf3 Bandwidth Test
# Runs on the webgui container. Configures FABNetv4 routes and deploys iPerf3.
set -e
SLICE_NAME="${1:-${SLICE_NAME}}"
if [ -z "$SLICE_NAME" ]; then echo "ERROR: SLICE_NAME not set" >&2; exit 1; fi
echo "### PROGRESS: Deploying iPerf3 slice '$SLICE_NAME'"
export SLICE_NAME
python3 <<'PYEOF'
import os, sys, ipaddress
from concurrent.futures import ThreadPoolExecutor
FABNETV4_SUBNET = ipaddress.ip_network("10.128.0.0/10")
slice_name = os.environ["SLICE_NAME"]
errors = []

from fabrictestbed_extensions.fablib.fablib import FablibManager
fablib = FablibManager()
print(f"### PROGRESS: Loading slice '{slice_name}'")
s = fablib.get_slice(name=slice_name)
s.update()

print("### PROGRESS: Adding FABNetv4 routes")
node_ips = {}
for node in s.get_nodes():
    for iface in node.get_interfaces():
        net = iface.get_network()
        if net and str(net.get_type()) in ("FABNetv4", "FABNetv4Ext"):
            gw = net.get_gateway()
            if gw:
                try:
                    node.ip_route_add(subnet=FABNETV4_SUBNET, gateway=gw)
                    print(f"  {node.get_name()}: route 10.128.0.0/10 via {gw}")
                except Exception as e:
                    if "File exists" not in str(e):
                        errors.append(f"{node.get_name()} route: {e}")
            fd = iface.get_fablib_data()
            ip = fd.get("addr")
            if ip:
                node_ips[node.get_name()] = ip

print("### PROGRESS: Installing iPerf3 on all nodes")
def setup_node(node):
    name = node.get_name()
    node.execute("sudo apt-get update -qq && sudo apt-get install -y -qq iperf3", quiet=True)
    print(f"  {name}: iperf3 installed")
    if "server" in name.lower():
        node.execute("pkill iperf3 2>/dev/null || true; sleep 1; nohup iperf3 -s -D", quiet=True)
        print(f"  {name}: iperf3 server started on port 5201")
    else:
        print(f"  {name}: iperf3 client ready")

with ThreadPoolExecutor(max_workers=len(s.get_nodes())) as pool:
    list(pool.map(setup_node, s.get_nodes()))

print("")
if errors:
    print("=== Boot config complete with errors ===")
    for e in errors:
        print(f"  ERROR: {e}")
    sys.exit(1)
else:
    print("=== Boot config complete and successful ===")
    for name, ip in node_ips.items():
        print(f"  {name}: FABNet IP = {ip}")
    print("  iPerf3 server listening on port 5201")
    print("  Run a test: iperf3 -c <server-fabnet-ip> -t 30")
PYEOF
