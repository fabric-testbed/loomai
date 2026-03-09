# Build Scripts

Scripts for building and publishing `fabric-webui` as Docker images or native LXC containers.

---

## Native LXC / Proxmox CT Template

Build a native Debian rootfs with systemd — not a Docker-export repackage. Uses `debootstrap` to create a proper Debian bookworm container with all dependencies installed natively.

### Prerequisites

- Linux host with `debootstrap` installed (`apt install debootstrap` on Debian/Ubuntu)
- `sudo` access (debootstrap and chroot require root)
- ~5 GB free disk space for the build

### Quick Start

```bash
sudo ./build/build-lxc.sh

# Custom output path
sudo ./build/build-lxc.sh --output /tmp/my-template.tar.gz
```

### Proxmox Import

```bash
# Copy template to Proxmox storage
cp build/output/fabric-webui-ct.tar.gz /var/lib/vz/template/cache/

# Create container
pct create 200 /var/lib/vz/template/cache/fabric-webui-ct.tar.gz \
    --hostname fabric-webui \
    --memory 4096 \
    --cores 2 \
    --rootfs local-lvm:16 \
    --net0 name=eth0,bridge=vmbr0,ip=dhcp \
    --unprivileged 0 \
    --features nesting=1 \
    --mp0 /path/to/fabric_work,mp=/home/fabric/work

pct start 200
```

### Bind Mounts

| Host Path | Container Mount | Purpose |
|-----------|----------------|---------|
| Your `fabric_work/` dir | `/home/fabric/work` | FABlib tokens, SSH keys, `fabric_rc`, templates, uploads |

### Accessing the Container

- **Web UI**: `http://<container-ip>:3000`
- **Console**: `pct enter 200`
- **Services**: `systemctl status fabric-webui-backend fabric-webui-nginx`

### What's Inside

The CT template includes:
- Debian bookworm minimal rootfs with systemd
- Python 3.11, Node 18, nginx
- Backend (uvicorn) as `fabric-webui-backend.service` on port 8000
- Frontend (nginx) as `fabric-webui-nginx.service` on port 3000
- Both services enabled and started automatically on boot

---

## Multi-Platform Docker Build

Scripts for building and publishing `fabric-webui` Docker images for multiple architectures.

## Prerequisites

- Docker with [buildx](https://docs.docker.com/buildx/working-with-buildx/) support (included in Docker Desktop and recent Docker Engine)
- QEMU user-static for cross-architecture builds (auto-installed by buildx on most systems)
- Docker Hub account (for pushing)

## One-Time Setup

```bash
# Log in to Docker Hub
docker login

# Make scripts executable (if needed)
chmod +x build/build-multiplatform.sh build/audit-image.sh
```

## Quick Start

```bash
# Build for both platforms (local only, no push)
./build/build-multiplatform.sh

# Build and push to Docker Hub as latest
./build/build-multiplatform.sh --push

# Build and push with a custom tag
./build/build-multiplatform.sh --push --tag v1.2.0

# Force a clean build (no layer cache)
./build/build-multiplatform.sh --push --no-cache

# Run security audit on an existing image
./build/audit-image.sh fabrictestbed/loomai-dev:latest
```

## Platform Coverage

| Target | Docker Platform | How It Works |
|--------|----------------|--------------|
| Linux x86_64 | `linux/amd64` | Native |
| Windows (Docker Desktop) | `linux/amd64` | Linux containers via WSL2 |
| Mac Intel | `linux/amd64` | Linux containers via Docker VM |
| Mac Apple Silicon (M1-M4) | `linux/arm64` | Native in Docker VM |
| Linux ARM64 | `linux/arm64` | Native |

## Security Audit

When `--push` is used, `audit-image.sh` runs automatically before pushing. It checks:

1. `/home/fabric/work` is empty (no user data or mounted secrets baked in)
3. No secret file patterns — tokens, PEM keys, `fabric_rc`, credentials (excludes system SSL certs)
4. No `.claude` directory
5. `/root` and `/tmp` are clean
6. No secrets in environment variables

The audit can also be run standalone against any image:

```bash
./build/audit-image.sh fabrictestbed/loomai-dev:latest
```

## Verifying a Published Image

```bash
# Confirm both amd64 and arm64 manifests exist
docker buildx imagetools inspect fabrictestbed/loomai-dev:latest
```

## Troubleshooting

**"builder not found" or buildx errors**
```bash
# Remove and recreate the builder
docker buildx rm multiplatform
./build/build-multiplatform.sh
```

**Cross-architecture build fails (exec format error)**
```bash
# Install QEMU support for cross-platform emulation
docker run --rm --privileged multiarch/qemu-user-static --reset -p yes
```

**Push fails with authentication error**
```bash
docker login
# Then retry with --push
```
