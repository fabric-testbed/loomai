#!/bin/bash
# System update for Rocky Linux / RHEL-based systems
set -euo pipefail

echo "=== Updating all packages ==="
sudo dnf update -y

echo "=== Removing unused packages ==="
sudo dnf autoremove -y

echo "=== System update complete ==="
echo "The system will reboot shortly to apply kernel updates."
