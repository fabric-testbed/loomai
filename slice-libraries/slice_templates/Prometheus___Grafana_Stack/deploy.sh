#!/bin/bash
# deploy.sh — Prometheus + Grafana Stack
# Runs on the webgui container. Configures FABNetv4 routes, collects node IPs,
# and uploads monitoring configuration (prometheus.yml with static targets,
# Grafana dashboard + datasource provisioning) to the monitor node.
# Per-role setup scripts then run as VM-side boot commands.

SLICE_NAME="${1:-${SLICE_NAME}}"
TEMPLATE_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$TEMPLATE_DIR/build"

echo "### PROGRESS: Configuring monitoring stack for slice '$SLICE_NAME'"
export SLICE_NAME BUILD_DIR

python3 "$BUILD_DIR/configure-monitor.py"
