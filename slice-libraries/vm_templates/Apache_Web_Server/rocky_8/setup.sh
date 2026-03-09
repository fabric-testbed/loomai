#!/bin/bash
# Apache Web Server setup for Rocky Linux 8
set -euo pipefail

echo "=== Installing Apache Web Server ==="

sudo dnf install -y httpd mod_ssl

echo "=== Configuring firewall ==="
if command -v firewall-cmd &>/dev/null && sudo systemctl is-active firewalld &>/dev/null; then
    sudo firewall-cmd --permanent --add-service=http
    sudo firewall-cmd --permanent --add-service=https
    sudo firewall-cmd --reload
fi

sudo systemctl enable httpd
sudo systemctl start httpd

echo "=== Apache Web Server installed successfully ==="
curl -s -o /dev/null -w "HTTP status: %{http_code}\n" http://localhost/ || true
