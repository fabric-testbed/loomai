#!/bin/bash
set -ex

# ── Install Docker ───────────────────────────────────────────────
sudo apt-get update -qq
sudo apt-get install -y -qq docker.io
sudo systemctl enable --now docker

# ── GPU setup (optional — only if NVIDIA GPU is present) ─────────
HAS_GPU=false
if lspci | grep -qi nvidia; then
  HAS_GPU=true
  echo "NVIDIA GPU detected — installing drivers and container toolkit"

  # Install NVIDIA driver
  sudo apt-get install -y -qq nvidia-driver-535

  # Install NVIDIA Container Toolkit
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
    | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
    | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
    | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list > /dev/null
  sudo apt-get update -qq
  sudo apt-get install -y -qq nvidia-container-toolkit
  sudo nvidia-ctk runtime configure --runtime=docker
  sudo systemctl restart docker
else
  echo "No NVIDIA GPU detected — running in CPU-only mode"
fi

# ── Install Ollama ───────────────────────────────────────────────
curl -fsSL https://ollama.com/install.sh | sh

# ── Pull a small default model ───────────────────────────────────
ollama pull llama3.2:3b

# ── Launch Open WebUI (no auth required) ─────────────────────────
DOCKER_ARGS="-d --name open-webui --restart always"
DOCKER_ARGS="$DOCKER_ARGS -p 3000:8080"
DOCKER_ARGS="$DOCKER_ARGS -e OLLAMA_BASE_URL=http://host.docker.internal:11434"
DOCKER_ARGS="$DOCKER_ARGS -e WEBUI_AUTH=false"
DOCKER_ARGS="$DOCKER_ARGS --add-host=host.docker.internal:host-gateway"
DOCKER_ARGS="$DOCKER_ARGS -v open-webui:/app/backend/data"

if [ "$HAS_GPU" = true ]; then
  DOCKER_ARGS="$DOCKER_ARGS --gpus all"
fi

sudo docker run $DOCKER_ARGS ghcr.io/open-webui/open-webui:main

# ── Wait for Open WebUI to be ready ─────────────────────────────
echo "Waiting for Open WebUI to start..."
for i in $(seq 1 30); do
  if curl -sf http://localhost:3000/ > /dev/null 2>&1; then
    echo "Open WebUI is ready"
    break
  fi
  sleep 5
done

echo "=== Ollama LLM Service setup complete ==="
echo "Open WebUI: http://<this-node>:3000 (no login required)"
echo "Ollama API: http://<this-node>:11434"
if [ "$HAS_GPU" = true ]; then
  echo "Mode: GPU-accelerated"
else
  echo "Mode: CPU-only (add a GPU component for acceleration)"
fi
