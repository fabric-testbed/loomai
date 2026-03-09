#!/bin/bash
set -euo pipefail

echo "=== Installing Docker Engine on CentOS ==="

# Remove old versions
yum remove -y docker docker-client docker-client-latest docker-common \
  docker-latest docker-latest-logrotate docker-logrotate docker-engine 2>/dev/null || true

# Install prerequisites and add Docker repo
yum install -y yum-utils
yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo

# Install Docker Engine
yum install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Add default user to docker group
DEFAULT_USER=$(logname 2>/dev/null || echo "${SUDO_USER:-centos}")
usermod -aG docker "$DEFAULT_USER" 2>/dev/null || true

# Start and enable Docker
systemctl start docker
systemctl enable docker

echo "=== Docker installed successfully ==="
docker --version
