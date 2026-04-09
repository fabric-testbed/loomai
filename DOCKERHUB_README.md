# LoomAI

FABRIC's AI-powered loom for weaving custom network fabrics. A standalone web interface for the [FABRIC testbed](https://fabric-testbed.net/) and [Chameleon Cloud](https://chameleoncloud.org/) — design, deploy, and manage network experiments from your browser.

## Features

- **Visual Topology Editor** — Drag-and-drop slice builder with Cytoscape.js graph visualization
- **Geographic Map** — Interactive Leaflet map showing FABRIC sites, backbone links, and resource availability
- **In-Browser Terminals** — SSH into provisioned VMs directly from the web UI
- **File Manager** — Upload, download, and transfer files between local storage and VMs
- **Weaves** — Pre-built experiment topologies with one-click deployment
- **Boot Configuration** — Per-node startup scripts with real-time progress streaming
- **Monitoring** — Live CPU and network metrics from deployed VMs
- **AI Companion** — AI-powered coding assistants (Aider, OpenCode, Claude Code)

## Quick Start

### 1. Download the compose file

```bash
curl -O https://raw.githubusercontent.com/fabric-testbed/loomai/main/docker-compose.yml
```

### 2. Start the container

```bash
docker compose pull
docker compose up -d
```

### 3. Open the UI

Navigate to **http://localhost:3000** in your browser.

### 4. Configure credentials

On first launch, the Getting Started tour will guide you through:
1. Uploading your FABRIC identity token (from the [FABRIC portal](https://portal.fabric-testbed.net/))
2. Uploading your bastion SSH key
3. Generating or uploading slice SSH keys
4. Selecting your project

## Persistent Storage

By default, configuration and data are stored in a Docker volume. To use a local directory instead:

```yaml
services:
  loomai:
    image: fabrictestbed/loomai:latest
    ports:
      - "3000:3000"
    volumes:
      - ./fabric_work:/home/fabric/work
```

## Updating

```bash
docker compose pull
docker compose up -d
```

The UI will notify you when a new version is available.

## Requirements

- Docker with Compose v2
- A FABRIC testbed account with an active project
- Works on Linux, macOS (Intel & Apple Silicon), and Windows (via Docker Desktop)

## Platforms

Multi-architecture image supporting:
- `linux/amd64` (Intel/AMD)
- `linux/arm64` (Apple Silicon, ARM servers)

## Links

- [Source Code (GitHub)](https://github.com/fabric-testbed/loomai)
- [FABRIC Testbed](https://fabric-testbed.net/)
- [FABRIC Portal](https://portal.fabric-testbed.net/)
