#!/bin/bash
# Install network research tools on RHEL/Rocky/CentOS systems
set -euo pipefail

echo "=== Installing network research tools ==="
dnf install -y epel-release 2>/dev/null || true
dnf install -y \
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

# netperf not always available
dnf install -y netperf 2>/dev/null || echo "Note: netperf not available in repos, skipping"

echo "=== Network tools installed ==="
echo "Available tools:"
for tool in iperf3 tcpdump nmap mtr traceroute hping3 tshark socat bwm-ng iftop nload ethtool arping; do
    which "$tool" 2>/dev/null && echo "  $(which $tool)" || echo "  $tool: not found"
done
