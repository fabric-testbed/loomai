#!/bin/bash
# Install network research tools on Debian/Ubuntu systems
set -euo pipefail

echo "=== Installing network research tools ==="
apt-get update
apt-get install -y \
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

# netperf is not in standard repos, try to install
apt-get install -y netperf 2>/dev/null || echo "Note: netperf not available in repos, skipping"

echo "=== Network tools installed ==="
echo "Available tools:"
for tool in iperf3 tcpdump nmap mtr traceroute hping3 tshark socat bwm-ng iftop nload ethtool arping; do
    which "$tool" 2>/dev/null && echo "  $(which $tool)" || echo "  $tool: not found"
done
