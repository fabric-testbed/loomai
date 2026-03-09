#!/bin/bash
# iPerf3 setup for Rocky Linux 8
set -euo pipefail

echo "=== Installing iPerf3 ==="
sudo dnf install -y iperf3

echo "=== iPerf3 installed successfully ==="
iperf3 --version
