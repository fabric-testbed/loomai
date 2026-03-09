#!/usr/bin/env bash
#
# Build a native LXC / Proxmox CT template for fabric-webui.
#
# Creates a Debian bookworm rootfs from scratch using debootstrap,
# installs all dependencies, copies in backend/frontend code, builds
# the frontend, writes systemd units and nginx config, then packages
# the whole thing as a gzipped tarball ready for `pct create`.
#
# Requires: sudo, debootstrap, coreutils
#
# Usage:
#   sudo ./build/build-lxc.sh [--tag <version>] [--output <path>]

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TAG=""
OUTPUT=""
SUITE="bookworm"
MIRROR="http://deb.debian.org/debian"
NODE_MAJOR=18

# ── Parse args ────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --tag) TAG="$2"; shift 2 ;;
        --output) OUTPUT="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Build filename from tag (or default to "latest")
if [[ -z "$TAG" ]]; then
    TAG="$(git -C "$REPO_ROOT" describe --tags --always 2>/dev/null || echo "latest")"
fi
if [[ -z "$OUTPUT" ]]; then
    OUTPUT="$REPO_ROOT/build/output/fabric-webui-ct-${TAG}.tar.gz"
fi

# ── Pre-flight checks ────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root (sudo)." >&2
    exit 1
fi

for cmd in debootstrap chroot tar; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "ERROR: Required command '$cmd' not found." >&2
        exit 1
    fi
done

# ── Temp rootfs directory (cleaned up on exit) ────────────────────
ROOTFS="$(mktemp -d /tmp/fabric-webui-rootfs.XXXXXX)"
cleanup() {
    echo "Cleaning up $ROOTFS ..."
    # Unmount any leftover bind mounts
    mountpoint -q "$ROOTFS/proc" 2>/dev/null && umount "$ROOTFS/proc" || true
    mountpoint -q "$ROOTFS/sys"  2>/dev/null && umount "$ROOTFS/sys"  || true
    mountpoint -q "$ROOTFS/dev"  2>/dev/null && umount "$ROOTFS/dev"  || true
    rm -rf "$ROOTFS"
}
trap cleanup EXIT

echo "==> Building rootfs in $ROOTFS"

# ── 1. Debootstrap ───────────────────────────────────────────────
echo "==> Running debootstrap ($SUITE) ..."
debootstrap --variant=minbase "$SUITE" "$ROOTFS" "$MIRROR"

# ── 2. Bind-mount /proc /sys /dev for chroot ─────────────────────
mount --bind /proc "$ROOTFS/proc"
mount --bind /sys  "$ROOTFS/sys"
mount --bind /dev  "$ROOTFS/dev"

# ── 3. Chroot: install packages ──────────────────────────────────
echo "==> Installing packages inside chroot ..."
chroot "$ROOTFS" bash -c "
    set -euo pipefail
    export DEBIAN_FRONTEND=noninteractive

    # Basic setup
    apt-get update
    apt-get install -y --no-install-recommends \
        systemd systemd-sysv dbus \
        ca-certificates curl gnupg \
        python3 python3-pip python3-venv python3-dev \
        gcc libffi-dev libssl-dev \
        nginx openssh-client git \
        ifupdown isc-dhcp-client iproute2 procps

    # NodeSource repo for Node $NODE_MAJOR
    mkdir -p /etc/apt/keyrings
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
    echo 'deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main' \
        > /etc/apt/sources.list.d/nodesource.list
    apt-get update
    apt-get install -y --no-install-recommends nodejs

    # Clean up
    apt-get clean
    rm -rf /var/lib/apt/lists/*
"

# ── 4. Copy backend and install Python deps ──────────────────────
echo "==> Installing backend ..."
mkdir -p "$ROOTFS/app"
cp -a "$REPO_ROOT/backend/app"          "$ROOTFS/app/app"
cp    "$REPO_ROOT/backend/requirements.txt" "$ROOTFS/app/requirements.txt"

chroot "$ROOTFS" bash -c "
    set -euo pipefail
    pip3 install --no-cache-dir --break-system-packages -r /app/requirements.txt
"

# ── 5. Build frontend ────────────────────────────────────────────
echo "==> Building frontend ..."
FRONTEND_BUILD="$(mktemp -d /tmp/fabric-webui-fe-build.XXXXXX)"
cp -a "$REPO_ROOT/frontend/." "$FRONTEND_BUILD/"

chroot "$ROOTFS" bash -c "
    mkdir -p /tmp/frontend-src
"
cp -a "$FRONTEND_BUILD/." "$ROOTFS/tmp/frontend-src/"

chroot "$ROOTFS" bash -c "
    set -euo pipefail
    cd /tmp/frontend-src
    npm ci
    npm run build
    rm -rf /usr/share/nginx/html/*
    cp -a dist/. /usr/share/nginx/html/
    rm -rf /tmp/frontend-src
    npm cache clean --force 2>/dev/null || true
"
rm -rf "$FRONTEND_BUILD"

# ── 6. Nginx config ──────────────────────────────────────────────
echo "==> Writing nginx config ..."
rm -f "$ROOTFS/etc/nginx/sites-enabled/default"

cat > "$ROOTFS/etc/nginx/conf.d/fabric-webui.conf" <<'NGINX'
server {
    listen 3000;
    root /usr/share/nginx/html;
    index index.html;

    client_max_body_size 500m;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }

    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 3600s;
    }
}
NGINX

# ── 7. Systemd service units ─────────────────────────────────────
echo "==> Writing systemd units ..."

cat > "$ROOTFS/etc/systemd/system/fabric-webui-backend.service" <<'UNIT'
[Unit]
Description=fabric-webui backend
After=network.target
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
WorkingDirectory=/app
ExecStart=/usr/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
Environment=FABRIC_CONFIG_DIR=/home/fabric/work/fabric_config
Environment=FABRIC_STORAGE_DIR=/home/fabric/work
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

cat > "$ROOTFS/etc/systemd/system/fabric-webui-nginx.service" <<'UNIT'
[Unit]
Description=fabric-webui frontend
After=network.target fabric-webui-backend.service

[Service]
Type=forking
ExecStart=/usr/sbin/nginx
ExecReload=/usr/sbin/nginx -s reload
Restart=always

[Install]
WantedBy=multi-user.target
UNIT

# Enable both units
chroot "$ROOTFS" bash -c "
    systemctl enable fabric-webui-backend.service
    systemctl enable fabric-webui-nginx.service
    # Disable the default nginx service to avoid port conflicts
    systemctl disable nginx.service 2>/dev/null || true
"

# ── 8. Directories and environment ───────────────────────────────
echo "==> Setting up directories and environment ..."
mkdir -p "$ROOTFS/home/fabric/work/fabric_config"  && chmod 700 "$ROOTFS/home/fabric/work/fabric_config"
mkdir -p "$ROOTFS/home/fabric/work" && chmod 755 "$ROOTFS/home/fabric/work"

# Environment variables for all sessions
cat > "$ROOTFS/etc/environment" <<'ENV'
FABRIC_CONFIG_DIR=/home/fabric/work/fabric_config
FABRIC_STORAGE_DIR=/home/fabric/work
ENV

# Hostname
echo "fabric-webui" > "$ROOTFS/etc/hostname"

# Network configuration — allow Proxmox-injected config to work
# Proxmox writes /etc/network/interfaces at container create time
# but the guest needs ifupdown + dhcp client installed (done above)
# and networking.service enabled to apply it on boot.
cat > "$ROOTFS/etc/network/interfaces" <<'NET'
auto lo
iface lo inet loopback

auto eth0
iface eth0 inet dhcp
NET

# DNS resolver (Proxmox may override, but provide a sane default)
cat > "$ROOTFS/etc/resolv.conf" <<'DNS'
nameserver 8.8.8.8
nameserver 1.1.1.1
DNS

# Enable networking service
chroot "$ROOTFS" bash -c "
    systemctl enable networking.service
    systemctl enable systemd-resolved.service 2>/dev/null || true
"

# Bake version into the rootfs
echo "$TAG" > "$ROOTFS/etc/fabric-webui-version"
echo "==> Version: $TAG"

# ── 9. Final cleanup ─────────────────────────────────────────────
echo "==> Final cleanup ..."
chroot "$ROOTFS" bash -c "
    apt-get clean 2>/dev/null || true
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*
    rm -rf /root/.npm /root/.cache
"

# Unmount before tarballing
umount "$ROOTFS/proc"
umount "$ROOTFS/sys"
umount "$ROOTFS/dev"

# ── 10. Package as CT template ───────────────────────────────────
echo "==> Creating CT template tarball ..."
mkdir -p "$(dirname "$OUTPUT")"
tar -czf "$OUTPUT" -C "$ROOTFS" .

SIZE=$(du -h "$OUTPUT" | cut -f1)
echo ""
echo "============================================"
echo "  CT template built successfully!"
echo "  Output: $OUTPUT"
echo "  Size:   $SIZE"
echo "============================================"
echo ""
echo "Import into Proxmox with:"
echo ""
echo "  # Copy template to Proxmox storage"
echo "  cp $OUTPUT /var/lib/vz/template/cache/"
echo ""
echo "  # Create container (adjust vmid, storage, resources as needed)"
echo "  pct create 200 /var/lib/vz/template/cache/fabric-webui-ct.tar.gz \\"
echo "      --hostname fabric-webui \\"
echo "      --memory 4096 \\"
echo "      --cores 2 \\"
echo "      --rootfs local-lvm:16 \\"
echo "      --net0 name=eth0,bridge=vmbr0,ip=dhcp \\"
echo "      --unprivileged 0 \\"
echo "      --features nesting=1 \\"
echo "      --mp0 /path/to/fabric_work,mp=/home/fabric/work"
echo ""
echo "  pct start 200"
echo "  # Access at http://<container-ip>:3000"
