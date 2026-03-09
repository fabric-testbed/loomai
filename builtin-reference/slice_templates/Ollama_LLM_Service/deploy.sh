#!/bin/bash
# deploy.sh — Ollama LLM Service
# Runs on the webgui container. Configures FABNetv4 routes.
# The Ollama install (setup-ollama.sh) runs as a VM-side boot command.
SLICE_NAME="${1:-${SLICE_NAME}}"
echo "### PROGRESS: Configuring FABNetv4 for Ollama slice '$SLICE_NAME'"
export SLICE_NAME
python3 <<'PYEOF'
import os, sys, ipaddress
FABNETV4_SUBNET = ipaddress.ip_network("10.128.0.0/10")
slice_name = os.environ["SLICE_NAME"]
errors = []
from fabrictestbed_extensions.fablib.fablib import FablibManager
fablib = FablibManager()
s = fablib.get_slice(name=slice_name)
s.update()
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
print("")
if errors:
    print("=== Boot config complete with errors ===")
    for e in errors:
        print(f"  ERROR: {e}")
    sys.exit(1)
else:
    print("=== Boot config complete and successful ===")
    print("  FABNetv4 routes configured. Ollama install starting on VM (see node logs).")
    for name, ip in node_ips.items():
        print(f"  {name}: FABNet IP = {ip}")
PYEOF
