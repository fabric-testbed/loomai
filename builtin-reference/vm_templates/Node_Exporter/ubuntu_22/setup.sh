#!/bin/bash
# Node Exporter setup for Ubuntu 22.04
set -euo pipefail

NODE_EXPORTER_VERSION="1.8.2"
ARCH=$(dpkg --print-architecture 2>/dev/null || echo "amd64")

echo "=== Installing node_exporter ${NODE_EXPORTER_VERSION} (${ARCH}) ==="

sudo id -u node_exporter &>/dev/null || sudo useradd --no-create-home --shell /bin/false node_exporter

cd /tmp
curl -fsSL -o node_exporter.tar.gz \
  "https://github.com/prometheus/node_exporter/releases/download/v${NODE_EXPORTER_VERSION}/node_exporter-${NODE_EXPORTER_VERSION}.linux-${ARCH}.tar.gz"
tar xzf node_exporter.tar.gz
sudo cp "node_exporter-${NODE_EXPORTER_VERSION}.linux-${ARCH}/node_exporter" /usr/local/bin/
sudo chown node_exporter:node_exporter /usr/local/bin/node_exporter
rm -rf node_exporter.tar.gz "node_exporter-${NODE_EXPORTER_VERSION}.linux-${ARCH}"

sudo tee /etc/systemd/system/node_exporter.service > /dev/null <<'EOF'
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

sudo systemctl daemon-reload
sudo systemctl enable node_exporter
sudo systemctl start node_exporter

echo "=== node_exporter installed and running on port 9100 ==="
