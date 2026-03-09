#!/bin/bash
# Install Ollama + Open WebUI on RHEL/Rocky/CentOS
set -euo pipefail

echo "=== Installing Docker ==="
dnf install -y dnf-plugins-core
dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
dnf install -y docker-ce docker-ce-cli containerd.io
systemctl enable --now docker

echo "=== Checking for NVIDIA GPU ==="
if lspci | grep -i nvidia &>/dev/null; then
    echo "NVIDIA GPU detected, installing drivers..."
    dnf install -y epel-release
    dnf install -y nvidia-driver
    # NVIDIA Container Toolkit
    curl -s -L https://nvidia.github.io/libnvidia-container/stable/rpm/nvidia-container-toolkit.repo | \
        tee /etc/yum.repos.d/nvidia-container-toolkit.repo
    dnf install -y nvidia-container-toolkit
    nvidia-ctk runtime configure --runtime=docker
    systemctl restart docker
else
    echo "No NVIDIA GPU detected, running in CPU mode"
fi

echo "=== Installing Ollama ==="
curl -fsSL https://ollama.com/install.sh | sh

echo "=== Pulling llama3.2:3b model ==="
ollama pull llama3.2:3b

echo "=== Starting Open WebUI ==="
docker run -d --name open-webui --restart always \
    -p 3000:8080 \
    -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
    --add-host=host.docker.internal:host-gateway \
    -v open-webui:/app/backend/data \
    ghcr.io/open-webui/open-webui:main

echo "=== Ollama + Open WebUI installed ==="
echo "  Ollama API: http://localhost:11434"
echo "  Open WebUI: http://localhost:3000"
