#!/bin/bash
# Install iPerf3 on RHEL/Rocky/CentOS systems
set -euo pipefail

echo "=== Installing iPerf3 ==="
dnf install -y iperf3

echo "=== iPerf3 installed ==="
iperf3 --version
