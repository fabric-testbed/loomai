#!/bin/bash
# mon-setup.sh — Suricata IDS sensor with categorized rules for the attack chain.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
echo 'Acquire::ForceIPv4 "true";' | sudo tee /etc/apt/apt.conf.d/99force-ipv4 >/dev/null
sudo apt-get update -y
sudo apt-get install -y --no-install-recommends suricata jq \
  || sudo apt-get install -y --fix-missing --no-install-recommends suricata jq

MON_IF=$(ip -o -4 addr show | awk '/10\.0\.2\.10\//{print $2; exit}')
echo "sensor_if=$MON_IF"
sudo sed -i "s/^\(\s*-\s*interface:\s*\).*/\1$MON_IF/" /etc/suricata/suricata.yaml || true

# We only mirror the client->server direction, so let Suricata reassemble
# one-sided / mid-stream flows (needed for HTTP app-layer detection on the
# mirror). The stock keys are commented examples, so insert active ones.
grep -qE '^  midstream: true' /etc/suricata/suricata.yaml \
  || sudo sed -i '/^stream:/a\  midstream: true\n  async-oneside: true' /etc/suricata/suricata.yaml

RULES_DIR=$(awk '/^default-rule-path:/{print $2}' /etc/suricata/suricata.yaml)
RULES_DIR=${RULES_DIR:-/etc/suricata/rules}
sudo mkdir -p "$RULES_DIR"
sudo tee "$RULES_DIR/local.rules" >/dev/null <<'EOF'
# Recon
alert tcp any any -> any any (msg:"EDGEIDS Recon SYN scan"; flags:S; threshold:type both, track by_src, count 20, seconds 10; classtype:attempted-recon; priority:2; sid:1000001; rev:1;)
alert tcp any any -> any any (msg:"EDGEIDS Recon FIN/XMAS scan"; flags:F; threshold:type both, track by_src, count 8, seconds 10; classtype:attempted-recon; priority:2; sid:1000002; rev:1;)
# Web application attacks
alert http any any -> any any (msg:"EDGEIDS Web path traversal"; flow:to_server; http.uri.raw; content:"../"; classtype:web-application-attack; priority:1; sid:1000003; rev:1;)
alert http any any -> any any (msg:"EDGEIDS Web SQL injection attempt"; flow:to_server; http.uri; content:"union"; nocase; pcre:"/union\s+select/i"; classtype:web-application-attack; priority:1; sid:1000004; rev:1;)
alert http any any -> any any (msg:"EDGEIDS Suspicious user-agent"; flow:to_server; http.user_agent; content:"EvilEdgeBot"; classtype:trojan-activity; priority:1; sid:1000005; rev:1;)
# Credential attack
alert tcp any any -> any 22 (msg:"EDGEIDS SSH brute force"; flags:S; threshold:type both, track by_src, count 15, seconds 30; classtype:attempted-admin; priority:1; sid:1000006; rev:1;)
# Exfiltration (long DNS labels ~ tunneling)
alert dns any any -> any any (msg:"EDGEIDS Long DNS query (possible exfil)"; dns.query; pcre:"/[a-z0-9]{40,}/i"; classtype:policy-violation; priority:2; sid:1000007; rev:1;)
# Baseline
alert icmp any any -> any any (msg:"EDGEIDS ICMP echo"; itype:8; classtype:misc-activity; priority:3; sid:1000008; rev:1;)
EOF
grep -q 'local.rules' /etc/suricata/suricata.yaml || sudo sed -i '/^rule-files:/a\  - local.rules' /etc/suricata/suricata.yaml

sudo suricata-update || true
sudo systemctl enable suricata
sudo systemctl restart suricata
sleep 3
sudo systemctl --no-pager status suricata | head -5 || true
echo "Suricata on $MON_IF with edgeids rules; alerts -> /var/log/suricata/{fast.log,eve.json}"
