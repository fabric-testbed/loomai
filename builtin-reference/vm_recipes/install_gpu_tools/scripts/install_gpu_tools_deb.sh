#!/bin/bash
# Install NVIDIA GPU tools (drivers, CUDA, cuDNN, NCCL, PyTorch) on Debian/Ubuntu
set -euo pipefail

echo "=== Checking for NVIDIA GPU ==="
if ! lspci | grep -i nvidia &>/dev/null; then
    echo "ERROR: No NVIDIA GPU detected. Attach a GPU component (e.g. GPU_RTX6000) to this node."
    exit 1
fi

echo "=== Installing NVIDIA drivers ==="
apt-get update
apt-get install -y nvidia-driver-535

echo "=== Installing CUDA 12.6 toolkit ==="
ARCH=$(dpkg --print-architecture 2>/dev/null || echo "amd64")
if [ "$ARCH" = "amd64" ]; then
    CUDA_REPO="ubuntu2204/x86_64"
else
    CUDA_REPO="ubuntu2204/sbsa"
fi
cd /tmp
wget -q "https://developer.download.nvidia.com/compute/cuda/repos/${CUDA_REPO}/cuda-keyring_1.1-1_all.deb"
dpkg -i cuda-keyring_1.1-1_all.deb
apt-get update
apt-get install -y cuda-toolkit-12-6

echo "=== Configuring CUDA environment ==="
cat > /etc/profile.d/cuda.sh <<'EOF'
export PATH=/usr/local/cuda-12.6/bin:$PATH
export LD_LIBRARY_PATH=/usr/local/cuda-12.6/lib64:${LD_LIBRARY_PATH:-}
EOF
# Apply for current session
export PATH=/usr/local/cuda-12.6/bin:$PATH
export LD_LIBRARY_PATH=/usr/local/cuda-12.6/lib64:${LD_LIBRARY_PATH:-}

echo "=== Installing cuDNN ==="
apt-get install -y libcudnn8 libcudnn8-dev 2>/dev/null || \
    apt-get install -y libcudnn9-cuda-12 libcudnn9-dev-cuda-12 2>/dev/null || \
    echo "Note: cuDNN package not found in repos, skipping"

echo "=== Installing NCCL ==="
apt-get install -y libnccl2 libnccl-dev 2>/dev/null || \
    echo "Note: NCCL package not found in repos, skipping"

echo "=== Installing NVIDIA Container Toolkit ==="
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' > /etc/apt/sources.list.d/nvidia-container-toolkit.list
apt-get update
apt-get install -y nvidia-container-toolkit

echo "=== Installing Python ML tools ==="
apt-get install -y python3-pip python3-venv
pip3 install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

echo "=== Installing nvidia-smi monitoring tools ==="
apt-get install -y nvtop 2>/dev/null || echo "Note: nvtop not available, skipping"

rm -f /tmp/cuda-keyring_1.1-1_all.deb

echo "=== GPU Tools installed ==="
echo "  NVIDIA driver: $(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null || echo 'reboot required')"
echo "  CUDA: $(nvcc --version 2>/dev/null | grep 'release' || echo '/usr/local/cuda-12.6')"
echo "  PyTorch: $(python3 -c 'import torch; print(f"torch {torch.__version__}, CUDA available: {torch.cuda.is_available()}")' 2>/dev/null || echo 'installed, reboot may be needed')"
