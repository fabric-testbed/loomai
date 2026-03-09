#!/bin/bash
# iPerf3 setup for Ubuntu 24.04
set -euo pipefail

echo "=== Installing iPerf3 ==="
sudo apt-get update
sudo apt-get install -y iperf3

echo "=== iPerf3 installed successfully ==="
iperf3 --version
