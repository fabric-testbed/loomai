#!/bin/bash
# deploy.sh — P4 BMv2 Lab
# Runs on the webgui container. No services to deploy; slice is ready to use.
SLICE_NAME="${1:-${SLICE_NAME}}"
echo "### PROGRESS: Slice '$SLICE_NAME' provisioned and ready"
echo ""
echo "=== Boot config complete and successful ==="
echo "Slice '$SLICE_NAME' is ready to use."
