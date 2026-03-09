#!/bin/bash
# Docker Host setup for Rocky Linux 8
set -euo pipefail

# Install prerequisites
sudo dnf -y install dnf-plugins-core

# Add Docker CE repository
sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo

# Install Docker Engine
sudo dnf -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Enable and start Docker
sudo systemctl enable docker
sudo systemctl start docker

# Add the current user to the docker group
CURRENT_USER=$(logname 2>/dev/null || echo "${SUDO_USER:-rocky}")
sudo usermod -aG docker "$CURRENT_USER"

echo "Docker installed successfully. Log out and back in for group changes to take effect."
