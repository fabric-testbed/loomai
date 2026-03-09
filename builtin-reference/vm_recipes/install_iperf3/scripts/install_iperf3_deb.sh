#!/bin/bash
# Install iPerf3 on Debian/Ubuntu systems
set -euo pipefail

echo "=== Installing iPerf3 ==="
apt-get update
apt-get install -y iperf3

echo "=== iPerf3 installed ==="
iperf3 --version
