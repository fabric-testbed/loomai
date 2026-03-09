#!/bin/bash
# Install FRRouting with auto-connect on Debian/Ubuntu systems
set -euo pipefail

echo "=== Installing FRRouting ==="
apt-get update
apt-get install -y frr

echo "=== Enabling FRR daemons (zebra, ospfd, bgpd) ==="
sed -i 's/^zebra=no/zebra=yes/' /etc/frr/daemons
sed -i 's/^ospfd=no/ospfd=yes/' /etc/frr/daemons
sed -i 's/^bgpd=no/bgpd=yes/' /etc/frr/daemons

echo "=== Enabling IP forwarding ==="
sysctl -w net.ipv4.ip_forward=1
echo 'net.ipv4.ip_forward = 1' > /etc/sysctl.d/99-ip-forward.conf

systemctl restart frr

# Create auto-connect watcher script
cat > /usr/local/bin/frr-auto-connect.sh <<'SCRIPT'
#!/bin/bash
# Auto-detect new dataplane interfaces and add them to FRR
KNOWN_FILE="/var/run/frr-known-interfaces"
touch "$KNOWN_FILE"
for iface in $(ip -o link show | awk -F': ' '{print $2}' | grep -v -E '^(lo|eth0|ens3|docker|br|ovs|veth|virbr)'); do
    if ! grep -qx "$iface" "$KNOWN_FILE"; then
        ip link set "$iface" up 2>/dev/null || true
        echo "$iface" >> "$KNOWN_FILE"
        logger "frr-auto-connect: detected new interface $iface"
    fi
done
SCRIPT
chmod +x /usr/local/bin/frr-auto-connect.sh

# Create systemd service and timer
cat > /etc/systemd/system/frr-auto-connect.service <<'EOF'
[Unit]
Description=FRR Auto-Connect Dataplane Interfaces
After=frr.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/frr-auto-connect.sh
EOF

cat > /etc/systemd/system/frr-auto-connect.timer <<'EOF'
[Unit]
Description=FRR Auto-Connect Timer

[Timer]
OnBootSec=10
OnUnitActiveSec=15

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now frr-auto-connect.timer

echo "=== FRR Router installed with auto-connect timer ==="
vtysh -c "show version" 2>/dev/null || echo "(vtysh not available yet — FRR is starting)"
