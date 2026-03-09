#!/bin/bash
# System Update for Debian 12 (Bookworm)
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

sudo apt-get update
sudo apt-get upgrade -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold"
sudo apt-get autoremove -y

echo "System packages updated successfully."
