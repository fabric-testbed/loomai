#!/bin/bash
#
# Hello FABRIC - Weave Orchestrator
#
# This script is the entry point when you click "Run" in the WebUI.
# It calls hello_fabric.py with three commands:
#   start   - Create and provision the slice
#   monitor - Check slice health every 30 seconds
#   stop    - Delete the slice (called when you click "Stop")
#
# The script runs until you click Stop or a failure is detected.
#

# Get the slice name from the SLICE_NAME env var (set by weave.json args),
# or from the first command-line argument, or use "hello-fabric" as default.
SLICE_NAME="${SLICE_NAME:-${1:-hello-fabric}}"

# Clean the name: only letters, numbers, and hyphens allowed
SLICE_NAME=$(echo "$SLICE_NAME" | sed 's/[^a-zA-Z0-9-]/-/g' | sed 's/--*/-/g' | sed 's/^-//;s/-$//')
if [ -z "$SLICE_NAME" ]; then
  echo "ERROR: SLICE_NAME not set" >&2
  exit 1
fi

# The Python script that manages the slice lifecycle
SCRIPT="hello_fabric.py"

# --- Graceful shutdown handler ---
# When you click "Stop" in the WebUI, this function runs.
# It tells the Python script to delete the slice, then exits cleanly.
cleanup() {
  echo ""
  echo "### PROGRESS: Stop requested — cleaning up..."
  python3 "$SCRIPT" stop "$SLICE_NAME" 2>&1 || true
  echo "### PROGRESS: Done."
  exit 0
}

# Install the shutdown handler (catches the Stop button signal)
trap cleanup SIGTERM SIGINT

# --- Start the slice ---
if ! python3 "$SCRIPT" start "$SLICE_NAME"; then
  echo "ERROR: Failed to start slice"
  exit 1
fi

# --- Monitor loop ---
# Runs every 30 seconds until you click Stop or a failure is detected.
#
# NOTE: We use "sleep 30 & wait $!" instead of plain "sleep 30" so that
# the SIGTERM signal (from the Stop button) is handled immediately.
# Plain sleep blocks signal handling until it finishes, but the WebUI
# only waits 5 seconds before force-killing the script.
echo "### PROGRESS: Monitoring (click Stop to tear down)..."
while true; do
  if ! python3 "$SCRIPT" monitor "$SLICE_NAME"; then
    echo "ERROR: Monitor detected a problem — cleaning up..."
    python3 "$SCRIPT" stop "$SLICE_NAME" 2>&1 || true
    exit 1
  fi
  sleep 30 &
  wait $! 2>/dev/null || true
done
