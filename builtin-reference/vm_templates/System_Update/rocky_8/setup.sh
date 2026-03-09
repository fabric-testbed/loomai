#!/bin/bash
# System Update for Rocky Linux 8
set -euo pipefail

sudo dnf update -y
sudo dnf autoremove -y

echo "System packages updated successfully."
