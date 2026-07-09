#!/bin/bash
# gw-setup.sh — gateway: firewall (with IPS hook), victim web service, and a
# traffic mirror to the IDS sensor.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
echo 'Acquire::ForceIPv4 "true";' | sudo tee /etc/apt/apt.conf.d/99force-ipv4 >/dev/null
sudo sysctl -w net.ipv4.ip_forward=1
sudo apt-get update -y
sudo apt-get install -y --no-install-recommends nftables iproute2 python3 \
  || sudo apt-get install -y --fix-missing --no-install-recommends nftables iproute2 python3

EDGE_IF=$(ip -o -4 addr show | awk '/10\.0\.1\.1\//{print $2; exit}')
MON_IF=$(ip -o -4 addr show | awk '/10\.0\.2\.1\//{print $2; exit}')
echo "edge_if=$EDGE_IF mon_if=$MON_IF"

# Firewall with input + forward chains (accept). The IDS->IPS loop appends DROP
# rules here by attacker source IP.
sudo tee /etc/nftables.conf >/dev/null <<EOF
flush ruleset
table inet filter {
  chain input   { type filter hook input   priority 0; policy accept; }
  chain forward { type filter hook forward priority 0; policy accept; }
}
EOF
sudo systemctl enable --now nftables
sudo nft -f /etc/nftables.conf

# Victim web service on :80 (a fake edge admin portal) — the attacker's web
# requests against it are what the IDS inspects.
sudo mkdir -p /srv/victim
sudo tee /srv/victim/index.html >/dev/null <<'EOF'
<html><body><h1>Edge Gateway Admin</h1>
<form action="/login" method="post">user:<input name="user"> pass:<input name="pass">
<button>login</button></form></body></html>
EOF
# Threaded server so a flood of attacker requests can't starve the benign device.
sudo tee /usr/local/bin/victim-web.py >/dev/null <<'EOF'
import functools
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
h = functools.partial(SimpleHTTPRequestHandler, directory="/srv/victim")
ThreadingHTTPServer(("0.0.0.0", 80), h).serve_forever()
EOF
sudo tee /etc/systemd/system/victim-web.service >/dev/null <<'EOF'
[Unit]
Description=Victim web service
[Service]
ExecStart=/usr/bin/python3 /usr/local/bin/victim-web.py
Restart=always
[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable victim-web.service
sudo systemctl restart victim-web.service

# Note: no DNS server is needed. The attacker's DNS-exfil queries to gw:53 are
# captured on the wire by the mirror even with no resolver replying, so Suricata
# still raises the long-DNS-query alert.

# Mirror edge-LAN traffic to the monitor (software SPAN) so the IDS sees it.
sudo tc qdisc replace dev "$EDGE_IF" ingress
sudo tc filter replace dev "$EDGE_IF" parent ffff: protocol all u32 match u8 0 0 \
  action mirred egress mirror dev "$MON_IF"
echo "gateway: firewall + victim web + mirror configured."
