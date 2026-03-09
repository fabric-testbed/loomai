#!/bin/bash
# Install Prometheus + Grafana monitoring stack on Debian/Ubuntu
set -euo pipefail

PROM_VERSION="2.51.2"
ARCH=$(dpkg --print-architecture 2>/dev/null || echo "amd64")

echo "=== Installing Prometheus ${PROM_VERSION} (${ARCH}) ==="

# Create prometheus user
id -u prometheus &>/dev/null || useradd --no-create-home --shell /bin/false prometheus
mkdir -p /etc/prometheus /var/lib/prometheus

# Download and install Prometheus
cd /tmp
curl -fsSL -o prometheus.tar.gz \
  "https://github.com/prometheus/prometheus/releases/download/v${PROM_VERSION}/prometheus-${PROM_VERSION}.linux-${ARCH}.tar.gz"
tar xzf prometheus.tar.gz
cd "prometheus-${PROM_VERSION}.linux-${ARCH}"
cp prometheus promtool /usr/local/bin/
cp -r consoles console_libraries /etc/prometheus/
chown -R prometheus:prometheus /etc/prometheus /var/lib/prometheus
rm -rf /tmp/prometheus*

# Prometheus configuration with file-based service discovery
cat > /etc/prometheus/prometheus.yml <<'EOF'
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

  - job_name: 'node_exporter'
    file_sd_configs:
      - files:
          - '/etc/prometheus/targets/*.json'
        refresh_interval: 30s
EOF

mkdir -p /etc/prometheus/targets
chown -R prometheus:prometheus /etc/prometheus

# Install nmap for network scanning
apt-get update
apt-get install -y nmap

# Auto-discovery script for node_exporter targets
cat > /usr/local/bin/prometheus-discover-targets.sh <<'SCRIPT'
#!/bin/bash
# Discover node_exporter targets on local networks
TARGETS_DIR="/etc/prometheus/targets"
TARGETS_FILE="${TARGETS_DIR}/auto_discovered.json"
mkdir -p "$TARGETS_DIR"

TARGETS="["
FIRST=true
for addr in $(ip -o -4 addr show | awk '{print $4}' | grep -v '127.0.0'); do
    NETWORK="$addr"
    for ip in $(nmap -sn "$NETWORK" 2>/dev/null | grep "Nmap scan report" | awk '{print $NF}' | tr -d '()'); do
        if curl -s --connect-timeout 1 "http://${ip}:9100/metrics" &>/dev/null; then
            if [ "$FIRST" = true ]; then FIRST=false; else TARGETS="${TARGETS},"; fi
            TARGETS="${TARGETS}{\"targets\":[\"${ip}:9100\"],\"labels\":{\"instance\":\"${ip}\"}}"
        fi
    done
done
TARGETS="${TARGETS}]"
echo "$TARGETS" > "$TARGETS_FILE"
chown prometheus:prometheus "$TARGETS_FILE"
SCRIPT
chmod +x /usr/local/bin/prometheus-discover-targets.sh

# Prometheus systemd service
cat > /etc/systemd/system/prometheus.service <<'EOF'
[Unit]
Description=Prometheus Monitoring
After=network-online.target
Wants=network-online.target

[Service]
User=prometheus
Group=prometheus
Type=simple
ExecStart=/usr/local/bin/prometheus \
  --config.file=/etc/prometheus/prometheus.yml \
  --storage.tsdb.path=/var/lib/prometheus/ \
  --web.console.templates=/etc/prometheus/consoles \
  --web.console.libraries=/etc/prometheus/console_libraries \
  --web.listen-address=:9090
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Discovery timer (runs every 60s)
cat > /etc/systemd/system/prometheus-discover.service <<'EOF'
[Unit]
Description=Prometheus Target Discovery

[Service]
Type=oneshot
ExecStart=/usr/local/bin/prometheus-discover-targets.sh
EOF

cat > /etc/systemd/system/prometheus-discover.timer <<'EOF'
[Unit]
Description=Prometheus Target Discovery Timer

[Timer]
OnBootSec=30
OnUnitActiveSec=60

[Install]
WantedBy=timers.target
EOF

echo "=== Installing Grafana ==="
apt-get install -y apt-transport-https software-properties-common
curl -fsSL https://apt.grafana.com/gpg.key | gpg --dearmor -o /usr/share/keyrings/grafana-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/grafana-archive-keyring.gpg] https://apt.grafana.com stable main" > /etc/apt/sources.list.d/grafana.list
apt-get update
apt-get install -y grafana

# Configure Prometheus as default Grafana datasource
mkdir -p /etc/grafana/provisioning/datasources
cat > /etc/grafana/provisioning/datasources/prometheus.yaml <<'EOF'
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://localhost:9090
    isDefault: true
    editable: true
EOF

systemctl daemon-reload
systemctl enable --now prometheus
systemctl enable --now grafana-server
systemctl enable --now prometheus-discover.timer

# Run initial discovery
/usr/local/bin/prometheus-discover-targets.sh || true

echo "=== Prometheus + Grafana installed ==="
echo "  Prometheus: http://localhost:9090"
echo "  Grafana:    http://localhost:3000 (admin/admin)"
