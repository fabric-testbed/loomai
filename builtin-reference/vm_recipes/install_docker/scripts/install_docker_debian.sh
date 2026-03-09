#!/bin/bash
set -euo pipefail

echo "=== Installing Docker Engine on Debian ==="

# Remove old versions
apt-get remove -y docker docker-engine docker.io containerd runc 2>/dev/null || true

# Install prerequisites
apt-get update
apt-get install -y ca-certificates curl gnupg

# Add Docker GPG key
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

# Add Docker repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker Engine
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Add default user to docker group
DEFAULT_USER=$(logname 2>/dev/null || echo "${SUDO_USER:-debian}")
usermod -aG docker "$DEFAULT_USER" 2>/dev/null || true

# Start and enable Docker
systemctl start docker
systemctl enable docker

echo "=== Docker installed successfully ==="
docker --version
