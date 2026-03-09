#!/bin/bash
# Install Ollama + Open WebUI on Debian/Ubuntu
set -euo pipefail

echo "=== Installing Docker ==="
apt-get update
apt-get install -y docker.io
systemctl enable --now docker

echo "=== Checking for NVIDIA GPU ==="
if lspci | grep -i nvidia &>/dev/null; then
    echo "NVIDIA GPU detected, installing drivers..."
    apt-get install -y nvidia-driver-535
    # Install NVIDIA Container Toolkit
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
        sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' > /etc/apt/sources.list.d/nvidia-container-toolkit.list
    apt-get update
    apt-get install -y nvidia-container-toolkit
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
