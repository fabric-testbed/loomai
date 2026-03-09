#!/bin/bash
# System update for CentOS systems
set -euo pipefail

echo "=== Updating all packages ==="
sudo yum update -y

echo "=== Removing unused packages ==="
sudo yum autoremove -y

echo "=== System update complete ==="
echo "The system will reboot shortly to apply kernel updates."
