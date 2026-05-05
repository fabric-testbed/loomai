# LoomAI

AI-assisted browser-based sandbox for designing, deploying, and managing experiments on the [FABRIC testbed](https://fabric-testbed.net/).

## Features

- **Visual Topology Editor** — Drag-and-drop slice builder with Cytoscape.js graph visualization
- **Geographic Map** — Interactive Leaflet map showing FABRIC sites, backbone links, and resource availability
- **In-Browser Terminals** — SSH into provisioned VMs directly from the web UI
- **File Manager** — Upload, download, and transfer files between local storage and VMs
- **Slice & VM Templates** — Pre-built experiment topologies and node configurations with one-click deployment
- **Boot Configuration** — Per-node startup scripts with real-time progress streaming
- **Monitoring** — Live CPU and network metrics from deployed VMs
- **AI Companion** — AI-powered coding assistants (Aider, OpenCode, Claude Code)

## Quick Install

### One-Line Install

**Prerequisites:** Docker with Compose v2

```bash
curl -fsSL https://raw.githubusercontent.com/fabric-testbed/loomai/main/install.sh | bash
```

This will download the compose file, pull the image, start the container, and verify it's healthy.

Open **http://localhost:3000** in your browser. A password is auto-generated on first start — check the container logs:

```bash
docker compose logs loomai | grep "password"
```

### Manual Install

```bash
# Download the install script
curl -fsSL https://raw.githubusercontent.com/fabric-testbed/loomai/main/install.sh -o install.sh

# Install (or upgrade an existing installation)
bash install.sh

# Check status
bash install.sh --status

# Clean install (remove everything and start fresh)
bash install.sh --clean

# Uninstall
bash install.sh --uninstall
```

### Option 1: Docker (recommended)

**Prerequisites:** Docker with Compose v2

```bash
# Pull and start the container
docker compose pull
docker compose up -d
```

Open **http://localhost:3000** in your browser.

> **Password protection:** LoomAI auto-generates a password on first start. Find it in the container logs with `docker compose logs loomai | grep "password"`. The password persists across restarts. To set your own: `LOOMAI_PASSWORD=mysecret docker compose up -d`

> **Localhost only by default:** Ports are bound to `127.0.0.1` so LoomAI is only accessible from the local machine. **Exposing LoomAI on all interfaces is not recommended** — it makes the UI reachable from any network, which is a security risk even with password protection enabled. If you must allow remote access (e.g., on a cloud VM), use an SSH tunnel instead:
> ```bash
> ssh -L 3000:localhost:3000 user@your-vm    # then open http://localhost:3000 locally
> ```
> As a last resort, you can change the port bindings in `docker-compose.yml`, but only on trusted networks:
> ```yaml
> ports:
>   - "0.0.0.0:3000:3000"   # NOT RECOMMENDED — exposes to all interfaces
> ```

### Option 2: Local Development

**Prerequisites:** Python 3.10+, Node.js 18+

```bash
# Clone the repo
git clone https://github.com/fabric-testbed/loomai.git
cd loomai

# Backend
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend (in a separate terminal)
cd frontend
npm install
npm run dev
```

## Configuration

### Authentication

LoomAI protects the web UI with a password. On first startup, a random password is auto-generated and printed to the container logs.

| Environment Variable | Description |
|---|---|
| `LOOMAI_PASSWORD` | Set a custom password (default: auto-generated, shown in logs) |
| `LOOMAI_NO_AUTH` | Set to `1` to disable password protection (for trusted networks) |

**Find the auto-generated password:**

```bash
docker compose logs loomai | grep "password"
```

**Set a custom password:**

```bash
LOOMAI_PASSWORD=mysecretpassword docker compose up -d
```

Or add to your `docker-compose.yml`:

```yaml
environment:
  - LOOMAI_PASSWORD=mysecretpassword
```

**Change an existing password:**

Set a new `LOOMAI_PASSWORD` value and restart the container. The new password hash replaces the old one.

```bash
LOOMAI_PASSWORD=newpassword docker compose up -d
```

**Reset a forgotten password:**

Delete the stored hash and restart — a new password will be auto-generated and shown in logs:

```bash
docker compose exec loomai rm -f /home/fabric/work/.loomai/password_hash
docker compose restart loomai
docker compose logs loomai | grep "password"
```

**Disable password protection** (trusted networks only):

```bash
LOOMAI_NO_AUTH=1 docker compose up -d
```

### FABRIC Setup

On first launch, the Getting Started tour will guide you through:

1. Uploading your FABRIC identity token (from the [FABRIC portal](https://portal.fabric-testbed.net/))
2. Uploading your bastion SSH key
3. Generating or uploading slice SSH keys
4. Selecting your project

## Updating

```bash
# Using the install script (recommended — handles cleanup)
bash install.sh

# Or manually
docker compose pull
docker compose up -d
```

Running `bash install.sh` on an existing installation will prompt you to choose between an upgrade (keep your data) or a clean install (start fresh). Your credentials, slices, and artifacts are preserved by default.

## Architecture

- **Backend:** FastAPI (Python) wrapping FABlib for all FABRIC operations
- **Frontend:** React 18 + TypeScript with Next.js, Cytoscape.js, and react-leaflet
- **Deployment:** Single Docker image with nginx-served frontend + backend

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for full details.

## Platforms

Multi-architecture image supporting:
- `linux/amd64` (Intel/AMD)
- `linux/arm64` (Apple Silicon, ARM servers)

## Requirements

- Docker with Compose v2 (for Docker install)
- Python 3.10+ and Node.js 18+ (for local development)
- A FABRIC testbed account with an active project
- Works on Linux, macOS (Intel & Apple Silicon), and Windows (via Docker Desktop)

## Links

- [FABRIC Testbed](https://fabric-testbed.net/)
- [FABRIC Portal](https://portal.fabric-testbed.net/)
- [Docker Hub](https://hub.docker.com/r/fabrictestbed/loomai)

## License

MIT
