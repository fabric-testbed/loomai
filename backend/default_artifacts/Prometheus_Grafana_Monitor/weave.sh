#!/bin/bash
#
# Prometheus + Grafana Monitor - Weave Orchestrator
#
# This script is the entry point when you click "Run" in the WebUI.
# It calls prom_grafana_monitor.py with three commands:
#
#   start   - Create a 3-node slice, install Prometheus + Grafana,
#             configure monitoring targets, and create a Grafana tunnel
#   monitor - Check slice health, SSH access, and Prometheus targets
#   stop    - Delete the slice and free resources
#
# The script runs until you click Stop or a failure is detected.
# When stopped, the slice is automatically deleted.
#

# Get slice name from env var (set by weave.json args) or command line
SLICE_NAME="${SLICE_NAME:-${1:-prom-grafana}}"
MONITOR_INTERVAL="${MONITOR_INTERVAL:-30}"

# Clean the name: only letters, numbers, and hyphens
SLICE_NAME=$(echo "$SLICE_NAME" | sed 's/[^a-zA-Z0-9-]/-/g' | sed 's/--*/-/g' | sed 's/^-//;s/-$//')
if [ -z "$SLICE_NAME" ]; then
  echo "ERROR: SLICE_NAME not set" >&2
  exit 1
fi

# The Python script that manages the slice lifecycle
SCRIPT="prom_grafana_monitor.py"

# --- Graceful shutdown handler ---
# When you click "Stop" in the WebUI, this function runs.
# It deletes the monitoring slice, then exits cleanly.
cleanup() {
  echo ""
  echo "### PROGRESS: Stop requested — deleting slice and cleaning up..."
  python3 "$SCRIPT" stop "$SLICE_NAME" 2>&1 || true
  echo "### PROGRESS: Done."
  exit 0
}

# Install the shutdown handler (catches the Stop button signal)
trap cleanup SIGTERM SIGINT

# --- Start: create slice and deploy monitoring stack ---
if ! python3 "$SCRIPT" start "$SLICE_NAME"; then
  echo "ERROR: Failed to start monitoring stack"
  exit 1
fi

# --- Monitor loop ---
# Checks slice health every MONITOR_INTERVAL seconds.
# Runs until you click Stop or a failure is detected.
#
# NOTE: We use "sleep N & wait $!" instead of plain "sleep N" so that
# the SIGTERM signal (from the Stop button) is handled immediately.
# Plain sleep blocks signal handling until it finishes, but the WebUI
# only waits 5 seconds before force-killing the script.
echo "### PROGRESS: Monitoring every ${MONITOR_INTERVAL}s (click Stop to tear down)..."
while true; do
  if ! python3 "$SCRIPT" monitor "$SLICE_NAME"; then
    echo "ERROR: Monitor detected a problem — cleaning up..."
    python3 "$SCRIPT" stop "$SLICE_NAME" 2>&1 || true
    exit 1
  fi
  sleep "$MONITOR_INTERVAL" &
  wait $! 2>/dev/null || true
done
