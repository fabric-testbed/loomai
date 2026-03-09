#!/bin/bash
# Network Tools setup for Rocky Linux 8
set -euo pipefail

echo "=== Installing network research tools ==="

sudo dnf install -y epel-release 2>/dev/null || true
sudo dnf install -y \
    iperf3 \
    tcpdump \
    nmap \
    mtr \
    traceroute \
    hping3 \
    wireshark-cli \
    socat \
    bwm-ng \
    iftop \
    nload \
    ethtool \
    iputils \
    iproute \
    bind-utils \
    curl \
    wget \
    nmap-ncat

# netperf may not be available
sudo dnf install -y netperf 2>/dev/null || echo "Note: netperf not available, skipping"

echo "=== Network tools installed successfully ==="
echo "Available tools:"
for tool in iperf3 tcpdump nmap mtr traceroute hping3 tshark socat bwm-ng iftop nload ethtool arping; do
    which "$tool" 2>/dev/null && echo "  $(which $tool)" || echo "  $tool: not found"
done
