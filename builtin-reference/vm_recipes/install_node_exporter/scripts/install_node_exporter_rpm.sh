#!/bin/bash
# Install Prometheus node_exporter on RHEL/Rocky/CentOS systems
set -euo pipefail

NODE_EXPORTER_VERSION="1.8.2"
ARCH=$(uname -m)
case "$ARCH" in
  x86_64)  ARCH="amd64" ;;
  aarch64) ARCH="arm64" ;;
esac

echo "=== Installing node_exporter ${NODE_EXPORTER_VERSION} (${ARCH}) ==="

# Create node_exporter user if it doesn't exist
id -u node_exporter &>/dev/null || useradd --no-create-home --shell /bin/false node_exporter

# Download and install
cd /tmp
curl -fsSL -o node_exporter.tar.gz \
  "https://github.com/prometheus/node_exporter/releases/download/v${NODE_EXPORTER_VERSION}/node_exporter-${NODE_EXPORTER_VERSION}.linux-${ARCH}.tar.gz"
tar xzf node_exporter.tar.gz
cp "node_exporter-${NODE_EXPORTER_VERSION}.linux-${ARCH}/node_exporter" /usr/local/bin/
chown node_exporter:node_exporter /usr/local/bin/node_exporter
rm -rf node_exporter.tar.gz "node_exporter-${NODE_EXPORTER_VERSION}.linux-${ARCH}"

# Create systemd service
cat > /etc/systemd/system/node_exporter.service <<'EOF'
[Unit]
Description=Prometheus Node Exporter
After=network-online.target
Wants=network-online.target

[Service]
User=node_exporter
Group=node_exporter
Type=simple
ExecStart=/usr/local/bin/node_exporter
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Enable and start
systemctl daemon-reload
systemctl enable node_exporter
systemctl start node_exporter

echo "=== node_exporter installed and running on port 9100 ==="
curl -s http://localhost:9100/metrics | head -5
