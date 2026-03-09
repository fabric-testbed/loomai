#!/bin/bash
# System update for Ubuntu / Debian-based systems
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

echo "=== Updating package lists ==="
sudo apt-get update -y

echo "=== Upgrading all packages ==="
sudo apt-get upgrade -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold"

echo "=== Removing unused packages ==="
sudo apt-get autoremove -y

echo "=== System update complete ==="
echo "The system will reboot shortly to apply kernel updates."
