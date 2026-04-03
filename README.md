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
curl -fsSL https://raw.githubusercontent.com/fabric-testbed/loomai/main/docker-compose.yml -o docker-compose.yml && docker compose up -d
```

Open **http://localhost:3000** in your browser.

### Option 1: Docker (recommended)

**Prerequisites:** Docker with Compose v2

```bash
# Pull and start the container
docker compose pull
docker compose up -d
```

Open **http://localhost:3000** in your browser.

To use a local directory for persistent storage instead of a Docker volume:

```yaml
services:
  loomai:
    image: fabrictestbed/loomai:latest
    ports:
      - "3000:3000"        # Web UI (nginx)
      - "8000:8000"        # Backend API (direct access)
      - "8889:8889"        # JupyterLab
      - "9100-9199:9100-9199"  # SSH tunnels for My Web Apps
    volumes:
      - fabric_work:/home/fabric/work
    environment:
      - FABRIC_CONFIG_DIR=/home/fabric/work/fabric_config
      - FABRIC_STORAGE_DIR=/home/fabric/work
      - DOCKER_REPO=fabrictestbed/loomai
    dns:
      - 8.8.8.8
      - 8.8.4.4
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s

volumes:
  fabric_work:
```

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

On first launch, the Getting Started tour will guide you through:

1. Uploading your FABRIC identity token (from the [FABRIC portal](https://portal.fabric-testbed.net/))
2. Uploading your bastion SSH key
3. Generating or uploading slice SSH keys
4. Selecting your project

## Updating

```bash
docker compose pull
docker compose up -d
```

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
