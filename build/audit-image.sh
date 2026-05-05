#!/usr/bin/env bash
set -euo pipefail

# Security audit for fabric-webui Docker images
# Checks that no secrets, credentials, or user data leaked into the image
#
# Usage: ./audit-image.sh <image-name>
# Exit 0 = all checks pass, Exit 1 = failure

if [[ $# -lt 1 ]]; then
    echo "Usage: $(basename "$0") <image-name>"
    echo "Example: $(basename "$0") fabrictestbed/loomai:latest"
    exit 1
fi

IMAGE="$1"
PASS=0
FAIL=0

check() {
    local description="$1"
    shift
    if "$@"; then
        echo "  PASS: $description"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $description"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== Security audit: $IMAGE ==="
echo ""

# 1. /fabric_config must be empty
check "/fabric_config is empty" \
    docker run --rm --entrypoint sh "$IMAGE" -c \
    '[ -z "$(ls -A /fabric_config 2>/dev/null)" ]'

# 2. /home/fabric/work must be empty
check "/home/fabric/work is empty" \
    docker run --rm --entrypoint sh "$IMAGE" -c \
    '[ -z "$(ls -A /home/fabric/work 2>/dev/null)" ]'

# 3. No secret file patterns (exclude system SSL certs)
check "No secret files (tokens, keys, credentials)" \
    docker run --rm --entrypoint sh "$IMAGE" -c '
    found=$(find / -maxdepth 5 \
        \( -path /proc -o -path /sys -o -path /dev -o -path /etc/ssl -o -path /usr/share/ca-certificates -o -path /usr/lib/ssl \) -prune \
        -o \( \
            -name "id_token*" -o \
            -name "*.pem" -o \
            -name "fabric_rc" -o \
            -name "fabric_bastion_key*" -o \
            -name "slice_key*" -o \
            -name "credentials*.json" -o \
            -name ".env" \
        \) -print 2>/dev/null)
    [ -z "$found" ]'

# 4. No .claude directory
check "No .claude directory" \
    docker run --rm --entrypoint sh "$IMAGE" -c \
    '[ -z "$(find / -maxdepth 4 -type d -name .claude 2>/dev/null | head -1)" ]'

# 5. /root and /tmp are clean (ignoring standard shell dotfiles and pip cache)
check "/root and /tmp are clean" \
    docker run --rm --entrypoint sh "$IMAGE" -c '
    root_files=$(find /root -mindepth 1 -maxdepth 1 \
        ! -name ".bashrc" ! -name ".profile" ! -name ".cache" \
        ! -name ".python_history" ! -name ".wget-hsts" \
        2>/dev/null | head -1)
    tmp_files=$(find /tmp -mindepth 1 -maxdepth 1 2>/dev/null | head -1)
    [ -z "$root_files" ] && [ -z "$tmp_files" ]'

# 6. No secrets in environment variables
check "No secrets in environment variables" \
    docker run --rm --entrypoint sh "$IMAGE" -c '
    suspect=$(env | grep -iE "(TOKEN|SECRET|PASSWORD|API_KEY|PRIVATE_KEY)=" | grep -v "^PATH=" || true)
    [ -z "$suspect" ]'

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [[ $FAIL -gt 0 ]]; then
    echo "AUDIT FAILED"
    exit 1
else
    echo "AUDIT PASSED"
    exit 0
fi
