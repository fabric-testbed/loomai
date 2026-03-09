#!/bin/bash
# System Update for CentOS Stream 9
set -euo pipefail

sudo dnf update -y
sudo dnf autoremove -y

echo "System packages updated successfully."
