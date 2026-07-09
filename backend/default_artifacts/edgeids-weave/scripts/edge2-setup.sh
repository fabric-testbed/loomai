#!/bin/bash
# edge2-setup.sh — BENIGN edge device. Generates only normal traffic so you can
# contrast a healthy device against the compromised one.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
echo 'Acquire::ForceIPv4 "true";' | sudo tee /etc/apt/apt.conf.d/99force-ipv4 >/dev/null
sudo ip route del default via 10.0.1.1 2>/dev/null || true
sudo apt-get update -y
sudo apt-get install -y --no-install-recommends curl iputils-ping \
  || sudo apt-get install -y --fix-missing --no-install-recommends curl iputils-ping

sudo tee /usr/local/bin/edge2-benign.sh >/dev/null <<'EOF'
#!/bin/bash
GW=10.0.1.1
while true; do
  curl -s -m 5 -A "Mozilla/5.0 EdgeSensor" "http://$GW/" >/dev/null 2>&1 || true
  ping -c 3 -W 2 "$GW" >/dev/null 2>&1 || true
  sleep 30
done
EOF
sudo chmod +x /usr/local/bin/edge2-benign.sh
sudo tee /etc/systemd/system/edge2-traffic.service >/dev/null <<'EOF'
[Unit]
Description=Benign edge device
After=network-online.target
[Service]
ExecStart=/usr/local/bin/edge2-benign.sh
Restart=always
[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable edge2-traffic.service
sudo systemctl restart edge2-traffic.service
echo "edge2 (benign) configured: periodic web + ping."
