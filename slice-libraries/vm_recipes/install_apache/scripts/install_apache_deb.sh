#!/bin/bash
# Install Apache web server on Debian/Ubuntu systems
set -euo pipefail

echo "=== Installing Apache httpd ==="
apt-get update
apt-get install -y apache2 ssl-cert

echo "=== Enabling mod_ssl and mod_rewrite ==="
a2enmod ssl
a2enmod rewrite
a2ensite default-ssl

echo "=== Configuring firewall ==="
if command -v ufw &>/dev/null; then
    ufw allow 80/tcp 2>/dev/null || true
    ufw allow 443/tcp 2>/dev/null || true
fi

systemctl enable apache2
systemctl restart apache2

echo "=== Apache installed and running ==="
curl -s -o /dev/null -w "HTTP status: %{http_code}\n" http://localhost/ || true
