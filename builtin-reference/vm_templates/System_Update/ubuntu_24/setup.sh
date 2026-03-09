#!/bin/bash
# System Update for Ubuntu 24.04
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

sudo apt-get update
sudo apt-get upgrade -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold"
sudo apt-get autoremove -y

echo "System packages updated successfully."
