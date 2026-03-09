#!/bin/bash
# Install Open vSwitch with auto-connect on Debian/Ubuntu systems
set -euo pipefail

echo "=== Installing Open vSwitch ==="
apt-get update
apt-get install -y openvswitch-switch

echo "=== Creating OVS bridge br0 ==="
ovs-vsctl --may-exist add-br br0

# Add existing dataplane interfaces
echo "=== Adding existing dataplane interfaces ==="
for iface in $(ip -o link show | awk -F': ' '{print $2}' | grep -v -E '^(lo|eth0|ens3|docker|br|ovs|veth|virbr)'); do
    ovs-vsctl --may-exist add-port br0 "$iface" && echo "  Added $iface to br0" || true
done

# Create auto-connect watcher script
cat > /usr/local/bin/ovs-auto-connect.sh <<'SCRIPT'
#!/bin/bash
# Auto-connect new dataplane interfaces to OVS br0
EXISTING=$(ovs-vsctl list-ports br0 2>/dev/null || true)
for iface in $(ip -o link show | awk -F': ' '{print $2}' | grep -v -E '^(lo|eth0|ens3|docker|br|ovs|veth|virbr)'); do
    if ! echo "$EXISTING" | grep -qx "$iface"; then
        ovs-vsctl --may-exist add-port br0 "$iface" && logger "ovs-auto-connect: added $iface to br0"
    fi
done
SCRIPT
chmod +x /usr/local/bin/ovs-auto-connect.sh

# Create systemd service
cat > /etc/systemd/system/ovs-auto-connect.service <<'EOF'
[Unit]
Description=OVS Auto-Connect Dataplane Interfaces
After=openvswitch-switch.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/ovs-auto-connect.sh
EOF

# Create systemd timer (every 15 seconds)
cat > /etc/systemd/system/ovs-auto-connect.timer <<'EOF'
[Unit]
Description=OVS Auto-Connect Timer

[Timer]
OnBootSec=10
OnUnitActiveSec=15

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now ovs-auto-connect.timer

echo "=== OVS Switch installed with auto-connect timer ==="
ovs-vsctl show
