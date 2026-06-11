#!/bin/bash

SLICE_NAME="${SLICE_NAME:-${1:-chameleon-ssh}}"
SITE="${SITE:-auto}"
NODE_TYPE="${NODE_TYPE:-auto}"
IMAGE="${IMAGE:-CC-Ubuntu22.04}"
LEASE_HOURS="${LEASE_HOURS:-4}"
FLOATING_NETWORK="${FLOATING_NETWORK:-public}"
MANAGEMENT_NETWORK="${MANAGEMENT_NETWORK:-sharednet1}"
SSH_USER="${SSH_USER:-cc}"
MONITOR_INTERVAL="${MONITOR_INTERVAL:-60}"

SLICE_NAME=$(echo "$SLICE_NAME" | sed 's/[^a-zA-Z0-9-]/-/g' | sed 's/--*/-/g' | sed 's/^-//;s/-$//')
if [ -z "$SLICE_NAME" ]; then
  echo "ERROR: SLICE_NAME not set" >&2
  exit 1
fi

SCRIPT="chameleon_ssh_slice.py"

cleanup() {
  echo ""
  echo "### PROGRESS: Stop requested - deleting Chameleon resources..."
  python3 "$SCRIPT" stop "$SLICE_NAME" --site "$SITE" 2>&1 || true
  echo "### PROGRESS: Done."
  exit 0
}

trap cleanup SIGTERM SIGINT

echo "### PROGRESS: Starting Chameleon SSH Slice"
echo "### PROGRESS: Site=$SITE NodeType=$NODE_TYPE Image=$IMAGE LeaseHours=$LEASE_HOURS"

if ! python3 "$SCRIPT" start "$SLICE_NAME" \
  --site "$SITE" \
  --node-type "$NODE_TYPE" \
  --image "$IMAGE" \
  --hours "$LEASE_HOURS" \
  --floating-network "$FLOATING_NETWORK" \
  --management-network "$MANAGEMENT_NETWORK" \
  --ssh-user "$SSH_USER"; then
  echo "ERROR: Failed to deploy Chameleon SSH slice"
  python3 "$SCRIPT" stop "$SLICE_NAME" --site "$SITE" 2>&1 || true
  exit 1
fi

echo "### PROGRESS: Monitoring (click Stop to tear down)..."
while true; do
  if ! python3 "$SCRIPT" monitor "$SLICE_NAME" --site "$SITE" --ssh-user "$SSH_USER"; then
    echo "ERROR: Monitor detected failure - cleaning up..."
    python3 "$SCRIPT" stop "$SLICE_NAME" --site "$SITE" 2>&1 || true
    exit 1
  fi
  sleep "$MONITOR_INTERVAL" &
  wait $! 2>/dev/null || true
done
