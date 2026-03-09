#!/bin/bash
# Network Tools setup for Ubuntu 20.04
set -euo pipefail

echo "=== Installing network research tools ==="

sudo apt-get update
sudo apt-get install -y \
    iperf3 \
    tcpdump \
    nmap \
    mtr-tiny \
    traceroute \
    hping3 \
    tshark \
    socat \
    bwm-ng \
    iftop \
    nload \
    ethtool \
    arping \
    netcat-openbsd \
    iproute2 \
    iputils-ping \
    dnsutils \
    curl \
    wget

# netperf may not be in standard repos
sudo apt-get install -y netperf 2>/dev/null || echo "Note: netperf not available, skipping"

echo "=== Network tools installed successfully ==="
echo "Available tools:"
for tool in iperf3 tcpdump nmap mtr traceroute hping3 tshark socat bwm-ng iftop nload ethtool arping; do
    which "$tool" 2>/dev/null && echo "  $(which $tool)" || echo "  $tool: not found"
done
