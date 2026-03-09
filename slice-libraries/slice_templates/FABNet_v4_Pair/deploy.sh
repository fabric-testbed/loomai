#!/bin/bash
# deploy.sh — L3 Network (FABNetv4)
# Runs on the webgui container. Adds FABNetv4 routes and verifies connectivity.
set -e
SLICE_NAME="${1:-${SLICE_NAME}}"
if [ -z "$SLICE_NAME" ]; then echo "ERROR: SLICE_NAME not set" >&2; exit 1; fi
echo "### PROGRESS: Configuring FABNetv4 for slice '$SLICE_NAME'"
export SLICE_NAME
python3 <<'PYEOF'
import os, sys, ipaddress, re
FABNETV4_SUBNET = ipaddress.ip_network("10.128.0.0/10")
slice_name = os.environ["SLICE_NAME"]
errors = []

from fabrictestbed_extensions.fablib.fablib import FablibManager
fablib = FablibManager()
print(f"### PROGRESS: Loading slice '{slice_name}'")
s = fablib.get_slice(name=slice_name)
s.update()

print("### PROGRESS: Adding FABNetv4 routes (10.128.0.0/10)")
node_ips = {}
for node in s.get_nodes():
    for iface in node.get_interfaces():
        net = iface.get_network()
        if net and str(net.get_type()) in ("FABNetv4", "FABNetv4Ext"):
            gw = net.get_gateway()
            if gw:
                try:
                    node.ip_route_add(subnet=FABNETV4_SUBNET, gateway=gw)
                    print(f"  {node.get_name()}: ip route add 10.128.0.0/10 via {gw}")
                except Exception as e:
                    if "File exists" not in str(e):
                        errors.append(f"{node.get_name()} route: {e}")
                    else:
                        print(f"  {node.get_name()}: route already exists")
            fd = iface.get_fablib_data()
            ip = fd.get("addr")
            if ip:
                node_ips[node.get_name()] = ip

print("### PROGRESS: Verifying FABNetv4 connectivity")
names = list(node_ips.keys())
if len(names) >= 2:
    src = s.get_node(names[0])
    dst_ip = node_ips[names[1]]
    try:
        out, _ = src.execute(f"ping -c 3 -W 3 {dst_ip}", quiet=True)
        m = re.search(r'(\d+) received', out)
        recv = int(m.group(1)) if m else 0
        if recv > 0:
            print(f"  Connectivity OK: {names[0]} → {names[1]} ({dst_ip})  [{recv}/3 packets]")
        else:
            print(f"  WARNING: ping {names[0]} → {dst_ip} got 0/3 (routes may need a moment)")
    except Exception as e:
        print(f"  Connectivity check warning: {e}")

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
PYEOF
