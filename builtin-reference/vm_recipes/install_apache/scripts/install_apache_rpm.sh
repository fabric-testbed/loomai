#!/bin/bash
# Install Apache web server on RHEL/Rocky/CentOS systems
set -euo pipefail

echo "=== Installing Apache httpd ==="
dnf install -y httpd mod_ssl

echo "=== Configuring firewall ==="
if command -v firewall-cmd &>/dev/null && systemctl is-active firewalld &>/dev/null; then
    firewall-cmd --permanent --add-service=http
    firewall-cmd --permanent --add-service=https
    firewall-cmd --reload
fi

systemctl enable httpd
systemctl start httpd

echo "=== Apache installed and running ==="
curl -s -o /dev/null -w "HTTP status: %{http_code}\n" http://localhost/ || true
