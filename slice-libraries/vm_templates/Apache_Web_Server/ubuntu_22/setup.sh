#!/bin/bash
# Apache Web Server setup for Ubuntu 22.04
set -euo pipefail

echo "=== Installing Apache Web Server ==="

sudo apt-get update
sudo apt-get install -y apache2 ssl-cert

echo "=== Enabling modules ==="
sudo a2enmod ssl
sudo a2enmod rewrite
sudo a2ensite default-ssl

echo "=== Configuring firewall ==="
if command -v ufw &>/dev/null; then
    sudo ufw allow 80/tcp 2>/dev/null || true
    sudo ufw allow 443/tcp 2>/dev/null || true
fi

sudo systemctl enable apache2
sudo systemctl restart apache2

echo "=== Apache Web Server installed successfully ==="
curl -s -o /dev/null -w "HTTP status: %{http_code}\n" http://localhost/ || true
