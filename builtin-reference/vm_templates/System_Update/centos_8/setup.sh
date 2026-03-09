#!/bin/bash
# System Update for CentOS 8
set -euo pipefail

sudo dnf update -y
sudo dnf autoremove -y

echo "System packages updated successfully."
