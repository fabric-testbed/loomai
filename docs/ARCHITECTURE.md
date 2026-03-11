# FABRIC Web GUI — Architecture

## Overview

**fabric-webgui** is a standalone web application that replicates the Jupyter-based **fabvis** GUI (from `fabrictestbed-extensions` fabvis branch) as a browser application. It provides a three-panel topology editor with Cytoscape.js graph visualization, a geographic Leaflet map view, tabular sliver views, file management, AI coding assistants, guided tours, an artifact marketplace, a landing page, and template/recipe libraries for building FABRIC network experiments.

**Target users**: FABRIC testbed researchers who need a visual interface for creating, managing, and monitoring network experiment slices.

**What it replaces**: The fabvis Jupyter widget, providing the same visual language and interaction patterns in a deployable web app.

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Browser (React 18 + TypeScript)                            │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────┐  │
│  │Cytoscape │ │ Leaflet  │ │ xterm.js │ │ CodeMirror 6  │  │
│  │  Graph   │ │   Map    │ │ Terminal │ │  File Editor  │  │
│  └──────────┘ └──────────┘ └──────────┘ └───────────────┘  │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ AI Tools │ (LoomAI, Aider, OpenCode, Crush, Claude Code)│
│  └──────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │          App.tsx (state orchestration)                │   │
│  └──────────────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTP (fetch) + WebSocket (xterm, logs)
                         │ /api/* and /ws/*
┌────────────────────────┴────────────────────────────────────┐
│  nginx (port 3000)                                          │
│  Static files + reverse proxy to backend                    │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────┴────────────────────────────────────┐
│  FastAPI Backend (port 8000)                                │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐    │
│  │ FABlib Mgr   │ │ Slice Serial │ │  Graph Builder   │    │
│  │ (singleton)  │ │  (no SSH)    │ │ (Cytoscape JSON) │    │
│  └──────────────┘ └──────────────┘ └──────────────────┘    │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐    │
│  │Site Resolver │ │Slice Registry│ │Monitoring Manager│    │
│  │(group→site)  │ │(JSON persist)│ │(node_exporter)   │    │
│  └──────────────┘ └──────────────┘ └──────────────────┘    │
│  14 route modules (slices, resources, templates, ...)       │
└────────────────────────┬────────────────────────────────────┘
                         │ FABlib Python API + SSH
┌────────────────────────┴────────────────────────────────────┐
│  FABRIC Testbed (Orchestrator, Sites, VMs)                  │
└─────────────────────────────────────────────────────────────┘
```

## Backend Deep Dive

### Core Modules (`backend/app/`)

| Module | Purpose |
|--------|---------|
| `main.py` | FastAPI app entry point. Mounts all routers, CORS middleware, static files. Defines `GET /api/health` and `GET /metrics`. |
| `fablib_manager.py` | Thread-safe singleton `FablibManager`. Loads `fabric_rc` into `os.environ`, rewrites host paths for Docker, manages multi-key-set SSH system. `get_fablib()` / `reset_fablib()` / `is_configured()`. |
| `slice_serializer.py` | Converts FABlib objects (Slice, Node, Network, Component, Interface, FacilityPort) to JSON-serializable dicts. Reads FIM capacities directly — never triggers SSH calls. |
| `graph_builder.py` | Converts `slice_to_dict()` output to Cytoscape.js graph JSON (`{nodes, edges}`). Maps reservation states to fabvis-matching colors (teal=OK, orange=configuring, red=error, grey=nascent). Creates VM nodes, component badges, network nodes, facility port nodes, and interface edges. |
| `site_resolver.py` | Resolves `@group` co-location tags and `auto` specs to concrete FABRIC sites using live availability with host-level feasibility checks. Groups resolved heaviest-first, then auto nodes. |
| `slice_registry.py` | Thread-safe persistent JSON registry (`registry.json`). Maps slice names to UUIDs, states, project IDs, archived status. Atomic writes via `.tmp` + `os.replace()`. |
| `monitoring_manager.py` | Singleton that installs `node_exporter` via Docker on VMs, scrapes Prometheus metrics over SSH every 15s, stores 60-min rolling time-series. Computes CPU%, memory%, load averages, per-interface network byte rates. |
| `user_context.py` | Manages storage paths and token resolution. Single-user layout under `FABRIC_STORAGE_DIR`. |

### Route Modules — Endpoint Reference

#### Slices (`routes/slices.py` → `/api`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/slices` | List all slices (FABlib + registry merge, includes drafts) |
| POST | `/slices` | Create a new empty draft slice (`?name=`) |
| GET | `/slices/{name}` | Get full slice data with Cytoscape.js graph |
| POST | `/slices/{name}/submit` | Submit slice to FABRIC (create or modify) |
| POST | `/slices/{name}/refresh` | Refresh slice state from FABRIC |
| POST | `/slices/{name}/resolve-sites` | Re-resolve site group assignments |
| DELETE | `/slices/{name}` | Delete a slice (draft or submitted) |
| POST | `/slices/{name}/renew` | Renew slice lease |
| POST | `/slices/{name}/archive` | Archive (hide without deleting) |
| GET | `/slices/{name}/validate` | Validate topology, return errors/warnings |
| POST | `/slices/{name}/clone` | Clone as a new draft |
| GET | `/slices/{name}/export` | Export as `.fabric.json` download |
| POST | `/slices/{name}/save-to-storage` | Export and save to container storage |
| POST | `/slices/archive-terminal` | Archive all Dead/Closing/StableError slices |
| POST | `/slices/reconcile-projects` | Tag registry entries with project IDs |
| GET | `/slices/storage-files` | List `.fabric.json` files in storage |
| POST | `/slices/import` | Import a slice model JSON as draft |
| POST | `/slices/open-from-storage` | Open `.fabric.json` from storage |

**Node operations:**

| Method | Path | Description |
|--------|------|-------------|
| POST | `/slices/{name}/nodes` | Add a node |
| DELETE | `/slices/{name}/nodes/{node}` | Remove a node |
| PUT | `/slices/{name}/nodes/{node}` | Update node (site, host, cores, ram, disk, image) |
| PUT | `/slices/{name}/nodes/{node}/post-boot` | Set post-boot config script |

**Component operations:**

| Method | Path | Description |
|--------|------|-------------|
| POST | `/slices/{name}/nodes/{node}/components` | Add a component |
| DELETE | `/slices/{name}/nodes/{node}/components/{comp}` | Remove a component |

**Facility port operations:**

| Method | Path | Description |
|--------|------|-------------|
| POST | `/slices/{name}/facility-ports` | Add a facility port |
| DELETE | `/slices/{name}/facility-ports/{fp}` | Remove a facility port |

**Network operations:**

| Method | Path | Description |
|--------|------|-------------|
| POST | `/slices/{name}/networks` | Add L2 or L3 network |
| PUT | `/slices/{name}/networks/{net}` | Update subnet/gateway/IP mode |
| DELETE | `/slices/{name}/networks/{net}` | Remove a network |

#### Resources (`routes/resources.py` → `/api`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/sites` | All FABRIC sites with GPS coords and availability (5-min cache) |
| GET | `/sites/{name}` | Detailed site info with per-component allocation |
| GET | `/sites/{name}/hosts` | Per-host resource availability |
| GET | `/links` | Unique backbone links between sites |
| GET | `/resources` | Cores/RAM/disk availability across all sites |
| GET | `/images` | Available VM OS images |
| GET | `/component-models` | Available hardware component models |

#### Templates (`routes/templates.py` → `/api/templates`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | List all weaves (slice.json + deploy.sh artifacts) |
| POST | `/` | Save current slice as template |
| POST | `/resync` | Force re-seed builtins |
| GET | `/{name}` | Get full template with model JSON and tool files |
| POST | `/{name}/load` | Load template as new draft |
| PUT | `/{name}` | Update template metadata |
| DELETE | `/{name}` | Delete template |
| GET | `/{name}/tools/{file}` | Read tool file content |
| PUT | `/{name}/tools/{file}` | Create/update tool file |
| DELETE | `/{name}/tools/{file}` | Delete tool file |

#### VM Templates (`routes/vm_templates.py` → `/api/vm-templates`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | List all VM templates |
| POST | `/` | Create VM template |
| POST | `/resync` | Force re-seed builtins |
| GET | `/{name}` | Get full VM template with boot_config |
| PUT | `/{name}` | Update VM template |
| DELETE | `/{name}` | Delete VM template |
| GET | `/{name}/tools/{file}` | Read tool file |
| PUT | `/{name}/tools/{file}` | Create/update tool file |
| DELETE | `/{name}/tools/{file}` | Delete tool file |

#### Recipes (`routes/recipes.py` → `/api/recipes`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | List all VM recipes |
| GET | `/{name}` | Get recipe detail with steps |
| POST | `/{name}/execute/{slice}/{node}` | Upload scripts and execute on VM |

#### Config (`routes/config.py` → `/api/config`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/config` | FABRIC config status (token, keys, project_id) |
| POST | `/config/token` | Upload token JSON file |
| GET | `/config/login` | CM OAuth login URL |
| POST | `/config/token/paste` | Paste token JSON text |
| GET | `/config/callback` | OAuth callback (saves token, resets FABlib) |
| GET | `/config/projects` | Decode JWT, derive projects and bastion_login |
| POST | `/config/keys/bastion` | Upload bastion private key |
| GET | `/config/keys/slice/list` | List named slice key sets |
| POST | `/config/keys/slice` | Upload slice key pair |
| POST | `/config/keys/slice/generate` | Generate RSA slice key pair |
| PUT | `/config/keys/slice/default` | Set default key set |
| DELETE | `/config/keys/slice/{name}` | Delete key set |
| GET | `/config/slice-key/{slice}` | Get key set for a slice |
| PUT | `/config/slice-key/{slice}` | Assign key set to a slice |
| POST | `/config/save` | Write fabric_rc + ssh_config |
| POST | `/config/rebuild-storage` | Re-initialize storage, re-seed templates |
| GET | `/projects` | List user projects from Core API |
| POST | `/projects/switch` | Switch active project |
| GET | `/projects/{uuid}/details` | Project details from UIS + local counts |

#### Files (`routes/files.py` → `/api/files`)

**Container storage:**

| Method | Path | Description |
|--------|------|-------------|
| GET | `/files` | List files/dirs (`?path=`) |
| POST | `/files/upload` | Upload files |
| POST | `/files/mkdir` | Create directory |
| GET | `/files/content` | Read text file |
| PUT | `/files/content` | Write text file |
| GET | `/files/download` | Download file |
| GET | `/files/download-folder` | Download directory as zip |
| DELETE | `/files` | Delete file or directory |

**VM SFTP:**

| Method | Path | Description |
|--------|------|-------------|
| GET | `/files/vm/{slice}/{node}` | List files via SFTP |
| POST | `/files/vm/{slice}/{node}/download` | Download VM file to container |
| POST | `/files/vm/{slice}/{node}/upload` | Upload container file to VM |
| POST | `/files/vm/{slice}/{node}/upload-direct` | Upload browser file to VM |
| GET | `/files/vm/{slice}/{node}/download-direct` | Download VM file to browser |
| GET | `/files/vm/{slice}/{node}/download-folder` | Download VM folder as zip |
| POST | `/files/vm/{slice}/{node}/read-content` | Read VM text file |
| POST | `/files/vm/{slice}/{node}/write-content` | Write VM text file |
| POST | `/files/vm/{slice}/{node}/mkdir` | Create VM directory |
| POST | `/files/vm/{slice}/{node}/delete` | Delete VM file/directory |
| POST | `/files/vm/{slice}/{node}/execute` | Execute command on VM |

**Provisioning & boot config:**

| Method | Path | Description |
|--------|------|-------------|
| POST | `/files/provisions` | Add file sync rule |
| GET | `/files/provisions/{slice}` | List provisioning rules |
| DELETE | `/files/provisions/{slice}/{rule_id}` | Delete rule |
| POST | `/files/provisions/{slice}/execute` | Execute provisioning |
| GET | `/files/boot-config/{slice}/{node}` | Get boot config |
| PUT | `/files/boot-config/{slice}/{node}` | Save boot config |
| POST | `/files/boot-config/{slice}/{node}/execute` | Execute boot config |
| POST | `/files/boot-config/{slice}/execute-all` | Execute all boot configs |

#### Monitoring (`routes/monitoring.py` → `/api/monitoring`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/{slice}/status` | Monitoring status (enabled/disabled) |
| POST | `/{slice}/enable` | Enable monitoring (install node_exporter) |
| POST | `/{slice}/disable` | Disable monitoring |
| POST | `/{slice}/nodes/{node}/enable` | Enable single node |
| POST | `/{slice}/nodes/{node}/disable` | Disable single node |
| GET | `/{slice}/metrics` | Latest metric values |
| GET | `/{slice}/metrics/history` | Time-series history (`?minutes=`) |
| GET | `/{slice}/infrastructure` | Public FABRIC Prometheus metrics |

#### Artifacts (`routes/artifacts.py` → `/api/artifacts`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/dir` | Get artifacts directory path |
| GET | `/list` | List all local artifacts with categories |
| POST | `/publish` | Publish artifact to FABRIC Artifact Manager |
| GET | `/marketplace` | Browse marketplace artifacts |
| POST | `/get` | Download artifact from marketplace |
| GET | `/authored` | List user's published artifacts |
| DELETE | `/{name}` | Delete local artifact |

#### AI Terminal (`routes/ai_terminal.py` → WebSocket)

| Protocol | Path | Description |
|----------|------|-------------|
| WS | `/ws/ai/{tool}` | AI tool terminal (aider, opencode, crush, claude) |
| GET | `/api/ai/tools` | List available AI tools with status |
| POST | `/api/ai/tools/{tool}/start` | Start an AI tool process |
| POST | `/api/ai/tools/{tool}/stop` | Stop an AI tool process |

#### Metrics (`routes/metrics.py` → `/api/metrics`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/site/{site}` | CPU load + dataplane traffic for a site |
| GET | `/link/{siteA}/{siteB}` | Traffic between two sites |

#### Terminal (`routes/terminal.py` → WebSocket)

| Protocol | Path | Description |
|----------|------|-------------|
| WS | `/ws/terminal/{slice}/{node}` | SSH terminal via bastion |
| WS | `/ws/terminal/container` | Backend container shell |
| WS | `/ws/logs` | FABlib log file tail |

## Frontend Deep Dive

### Framework

Next.js 14 with static export (`NEXT_BUILD_MODE=export`). The app is entirely client-side — `src/app/page.tsx` uses `next/dynamic` with `ssr: false` to load `App.tsx`.

### Component Tree

```
App.tsx (root state orchestration)
├── TitleBar         — View nav, project switch, theme, help, settings
├── Toolbar          — Slice CRUD, submit, refresh, auto-refresh
├── [landing view]:  LandingView       — Welcome page with tour button, quick-start cards
├── [topology view]:
│   ├── Left/Right panels (drag-rearrangeable):
│   │   ├── EditorPanel     — Node/component/network editor, site mapping
│   │   │   ├── SliverComboBox   — Searchable sliver selector
│   │   │   ├── AddSliverMenu    — Add node/network/facility-port
│   │   │   └── ImageComboBox    — Image + VM template picker
│   │   ├── TemplatesPanel  — Artifact browser (weaves, VM, recipes, notebooks)
│   │   ├── AIChatPanel     — LoomAI chat with tool calling
│   │   └── SideConsolePanel — Side console for build logs
│   └── CytoscapeGraph      — Main topology canvas
├── [table view]:    AllSliversView    — Expandable table with bulk ops
├── [map view]:      GeoView           — Leaflet map + DetailPanel
├── [files view]:    FileTransferView  — Dual FileBrowser + FileEditor
├── [libraries view]: LibrariesView    — Full artifact manager (Local, Authored, Marketplace)
├── [ai view]:       AICompanionView   — AI tool launcher cards
│   ├── TerminalCompanionView — Split-pane terminal AI tools
│   ├── AiderWebView          — Aider web interface
│   └── OpenCodeWebView       — OpenCode web interface
├── [client view]:   ClientView        — Web app tunnels to slice VMs
├── [jupyter view]:  JupyterLabView    — Embedded JupyterLab environment
├── BottomPanel      — Console (always rendered)
│   ├── Errors tab
│   ├── Validation tab
│   ├── Log tab (LogView)
│   ├── Local terminal tab
│   ├── Build log tabs (per-slice deploy output)
│   ├── Run script tabs (autonomous experiment output)
│   └── Per-node SSH terminal tabs
├── ConfigureView    — Settings modal (token, keys, project)
├── HelpView         — Full-window searchable help with tour launcher
├── HelpContextMenu  — Global right-click context help
├── GuidedTour       — Interactive step-by-step tour with completion checks
└── LandingView      — Welcome page with getting-started tour button
```

### State Management

All state lives in `App.tsx` as `useState` hooks. No external state library. Key state groups:

- **Slice state**: `selectedSliceId`, `sliceData`, `slices[]`, `loading`
- **Infrastructure**: `infraSites`, `infraLinks`, `images`, `componentModels`, `vmTemplates`
- **UI layout**: `currentView` (landing/topology/sliver/map/files/libraries/client/ai/jupyter), `panelLayout`, `dark`, `consoleExpanded`, `consoleHeight`
- **Terminals**: `terminalTabs[]`, `terminalIdCounter`
- **Validation**: `validationIssues[]`, `validationValid`
- **Errors**: `errors[]`, `bootConfigErrors[]`
- **Project**: `projectName`, `projectId`, `projects[]`
- **Metrics**: `siteMetricsCache`, `linkMetricsCache`, `metricsRefreshRate`
- **AI Tools**: `selectedAiTool`, `enabledAiTools`
- **Tour**: `activeTourId`, `tourStep`, `tourContext` (reactive completion checks)
- **Config**: `configStatus` (polled from backend during interactive tour steps)

### Panel Layout System

Four panels (`editor`, `template`, `chat`, `console`) each have `side` (left/right), `collapsed`, `width`, and `order`. Panels are draggable between sides and reorderable within a side. All panels use a consistent ✕ close button. Layout persisted to `localStorage`.

### Polling / Auto-refresh

A 15-second interval refreshes the slice list while any slice is in a transitional state (`Configuring`, `Ticketed`, `Nascent`, `ModifyOK`, `ModifyError`). Stops when all slices reach stable/terminal states. Auto-executes boot configs once when a slice first reaches `StableOK`.

### Guided Tour System

10 interactive guided tours provide step-by-step walkthroughs of all features:

| Tour | Steps | Interactive Checks |
|------|-------|-------------------|
| Getting Started | 10 | Token, bastion key, slice key, configured, load slices, load slice, select node |
| Topology Editor | 9 | Create slice, add node, select node, add component, create network |
| AI Tools | 6 | Launch a tool |
| Artifacts & Weaves | 8 | Load a weave |
| Map & Resources | 4 | Refresh resources |
| Table View | 6 | Load slices |
| Web Apps | 4 | Load slices |
| JupyterLab | 3 | — |
| Console & Terminals | 6 | Load a slice |
| File Manager | 3 | Load slices |

**Architecture**: `tourSteps.ts` defines `TourDef` and `TourStep` types. `GuidedTour.tsx` renders a spotlight overlay with tooltip card. Steps can have a `completionCheck` key that maps to a `tourContext` object computed in `App.tsx`. The context is reactive — it updates from app state (slice loaded, node selected, etc.) without polling. Config-based checks (`has_token`, `has_bastion_key`, etc.) poll `GET /api/config` every 2 seconds.

The `requiredView` field on each step triggers automatic view transitions, and `targetSelector` highlights the relevant UI element with a spotlight cutout.

### Landing View

The landing page (`LandingView.tsx`) is the default view on launch. It provides:
- Welcome message and "Take the Guided Tour" button
- Quick-start cards for common actions
- AI tool cards with availability badges (Free/Paid)
- Recent slices section

### AI Tools Integration

Five AI coding assistants are integrated:

| Tool | Type | Cost | Features |
|------|------|------|----------|
| LoomAI | Chat panel | Free | FABRIC tool calling, agent personas, model selection |
| Aider | Web IDE | Free | File editing, code generation |
| OpenCode | Web terminal | Free | FABRIC skills, agents, MCP tools |
| Crush | Terminal | Free | Charm TUI, NRP model support |
| Claude Code | Terminal | Paid | Anthropic CLI, advanced coding |

LoomAI (`AIChatPanel.tsx`) supports streaming responses, expandable tool call cards, and multiple agent personas (Network Architect, Troubleshooter, Experiment Designer, etc.).

Terminal-based tools run in split-pane views (`TerminalCompanionView.tsx`) with an embedded file browser. Web-based tools (`AiderWebView.tsx`, `OpenCodeWebView.tsx`) run in iframes.

### Artifact Marketplace

The Libraries view (`LibrariesView.tsx`) provides a full artifact management system:
- **Local tab**: Browse installed artifacts by category (weaves, VM templates, recipes, notebooks)
- **Authored tab**: Manage artifacts you've published
- **Marketplace tab**: Browse community-published artifacts with search, category filter, and tag filter

Artifacts are published to and fetched from the FABRIC Artifact Manager API. Category is determined by `[LoomAI ...]` markers in the description field.

### Help System

Three-tier help system:
1. **Tooltips**: `<Tooltip text="...">` wraps labeled elements for hover help
2. **Context help**: Right-click elements with `data-help-id` for detailed descriptions
3. **Help page**: Full searchable documentation with tour launcher cards

Help entries are defined in `helpData.ts` organized by section.

## Data Flow Diagrams

### Slice Lifecycle

```
Create Draft → Add Nodes/Networks/Components → Validate → Submit
    │                                                        │
    │                                                        ▼
    │                                              FABRIC Orchestrator
    │                                                        │
    │                                              Nascent → Configuring → StableOK
    │                                                                        │
    │                                                              Auto-run boot configs
    │                                                                        │
    ├── Modify (add/remove nodes) → Re-submit → ModifyOK → StableOK         │
    ├── Renew lease                                                          │
    ├── Clone → New draft                                                    │
    ├── Export → .fabric.json                                                │
    ├── Save as template                                                     │
    └── Delete → Closing → Dead (auto-archive)
```

### Graph Rendering Pipeline

```
FABlib Slice Object
    │
    ▼ slice_serializer.py
Plain dict {nodes, networks, facility_ports}
    │
    ▼ graph_builder.py
Cytoscape.js JSON {nodes: [...], edges: [...]}
    │ - VM nodes with state colors
    │ - Component badge nodes
    │ - Network nodes (L2/L3 ellipses)
    │ - Facility port nodes (diamonds)
    │ - Interface edges
    │
    ▼ CytoscapeGraph.tsx
Rendered graph with layout algorithm (dagre/cola/breadthfirst/grid/concentric/cose)
```

### Template Seeding

```
slice-libraries/                  (git-tracked source of truth)
├── slice_templates/
├── vm_templates/
└── vm_recipes/
        │
        │  Docker build: COPY into /app/slice-libraries/
        │  Dev: rsync to backend/slice-libraries/
        │
        ▼
Backend startup / resync endpoint
        │
        │  Hash-based change detection (metadata.json hash)
        │  Only copies if builtin and hash differs
        │
        ▼
FABRIC_STORAGE_DIR/
├── .artifacts/{name}/          # Unified artifact storage
│   ├── slice.json + deploy.sh  # → weave (+ run.sh → runnable weave)
│   ├── vm-template.json        # → VM template
│   ├── recipe.json             # → recipe
│   ├── metadata.json           # Optional metadata
│   └── tools/                  # Optional scripts
```

### SSH Terminal Flow

```
Browser (xterm.js)
    │ WebSocket /ws/terminal/{slice}/{node}
    ▼
FastAPI WebSocket handler (terminal.py)
    │ paramiko SSHClient
    ▼
FABRIC Bastion Host
    │ ProxyCommand
    ▼
VM (management IP)
    │ PTY session
    ▼
Shell (bash)
```

## Slice Libraries

### Structure

```
slice-libraries/
├── slice_templates/           Topologies with site groups and networks
│   ├── Hello_FABRIC/
│   ├── L2_Bridge___Auto_IP/
│   ├── Wide-Area_L2_Network/
│   ├── iPerf3_Bandwidth_Test/
│   ├── Prometheus___Grafana_Stack/  (with tools/ directory)
│   ├── FRR_OSPF_Triangle/
│   ├── P4_BMv2_Lab/
│   ├── Kubernetes_Cluster/
│   ├── GPU_Compute_Pair/
│   └── Ollama_LLM_Service/
├── vm_templates/              Single-node VM blueprints
│   ├── Docker_Host/
│   ├── FRR_Router/
│   ├── OVS_Switch/
│   ├── GPU___CUDA_Host/
│   ├── NVMe_Storage_Node/
│   ├── Ollama_LLM_Server/
│   └── ... (11 total)
└── vm_recipes/                Reusable install actions
    └── install_docker/
        ├── recipe.json
        └── scripts/           OS-specific install scripts
```

### Template Format (`slice.json`)

```json
{
  "format": "fabric-slice-v1",
  "name": "Template Name",
  "nodes": [{
    "name": "node-a",
    "site": "@group-tag",       // co-location group, or "auto", or explicit site
    "cores": 2, "ram": 8, "disk": 10,
    "image": "default_ubuntu_22",
    "vm_template": "Docker Host", // optional, overrides image + merges boot_config
    "boot_config": { "uploads": [], "commands": [], "network": [] },
    "components": [{ "name": "nic1", "model": "NIC_Basic" }]
  }],
  "networks": [{
    "name": "lan",
    "type": "L2Bridge",         // L2Bridge | L2STS | FABNetv4 | FABNetv6
    "interfaces": ["node-a-nic1-p1", "node-b-nic1-p1"],
    "ip_mode": "auto",          // none | auto | config
    "subnet": "192.168.1.0/24"
  }]
}
```

### Recipe Format (`recipe.json`)

```json
{
  "name": "Install Docker",
  "builtin": true,
  "image_patterns": {
    "ubuntu": "install_docker_ubuntu.sh",
    "rocky": "install_docker_rocky.sh"
  },
  "steps": [
    { "type": "upload_scripts" },
    { "type": "execute", "command": "sudo bash ~/.fabric/recipes/install_docker/{script}" }
  ]
}
```

## Storage Layout

```
FABRIC_STORAGE_DIR (/home/fabric/work)
├── fabric_config/               FABRIC credentials (fabric_rc, keys, tokens)
│   ├── fabric_rc
│   ├── ssh_config
│   ├── id_token.json
│   ├── fabric_bastion_key
│   └── slice_keys/
│       ├── keys.json            Key set registry
│       └── {name}/
│           ├── slice_key
│           └── slice_key.pub
├── .drafts/                     Unsaved draft slice state
├── .artifacts/                  Unified artifact storage (weaves, VM templates, recipes, notebooks)
├── .all_slices/
│   └── registry.json            Slice name→UUID→state registry
├── .slice-keys/                 Per-slice key assignments
├── .monitoring/                 Monitoring state persistence
│   └── {slice_name}.json
└── (user files)                 Container storage (visible in file browser)
```

## Build & Deploy

### Local Development

```bash
./run-dev.sh
# Backend: http://localhost:8000 (uvicorn --reload)
# Frontend: http://localhost:3000 (next dev, proxies /api/* to backend)
```

### Docker Compose (two-container, dev)

```bash
docker compose -f docker-compose.dev.yml up --build
# frontend container (nginx:3000) → backend container (uvicorn:8000)
```

### Combined Single Image (from Docker Hub)

```bash
docker compose up -d
# fabrictestbed/loomai-dev:latest — nginx + uvicorn under supervisord
```

### Multi-Platform Build

```bash
./build/build-multiplatform.sh --push --tag v0.1.4
# Builds linux/amd64 + linux/arm64
# Runs build/audit-image.sh security check before push
```

### Tailscale Deployment

```bash
docker-compose -f docker-compose.tailscale.yml up
# Tailscale sidecar + app container with TS_SERVE_CONFIG
```

### LXC/Container Template

```bash
sudo ./build/build-lxc.sh --tag v0.1.4
# Builds a Proxmox-ready .tar.gz with systemd services
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `FABRIC_CONFIG_DIR` | `/home/fabric/work/fabric_config` | Path to fabric_rc, keys, tokens |
| `FABRIC_STORAGE_DIR` | `/home/fabric/work` | Persistent storage root |
| `FABRIC_PROJECT_ID` | (from fabric_rc) | Active FABRIC project UUID |
| `WEBGUI_BASE_URL` | `http://localhost:3000` | OAuth callback redirect base |

### fabric_rc

Standard FABRIC configuration file with `export KEY=VALUE` lines. Parsed by `fablib_manager.py` and loaded into `os.environ`. Contains orchestrator hosts, bastion config, SSH command template, log settings, and credential paths.

## Brand & Styling

### FABRIC Colors (from fabvis)

| Name | Hex | Usage |
|------|-----|-------|
| Primary | `#5798bc` | Headers, borders, links |
| Dark | `#1f6a8c` | Dark mode accents |
| Teal | `#008e7a` | StableOK state, success |
| Orange | `#ff8542` | Configuring state, warnings |
| Coral | `#e25241` | Error state, destructive actions |

### CSS Architecture

25+ CSS files in `frontend/src/styles/`, one per component/view (including `guided-tour.css`, `landing-view.css`, `ai-companion.css`). Uses CSS custom properties defined in `global.css` with `[data-theme="dark"]` overrides. No CSS-in-JS or Tailwind — plain CSS with BEM-like naming.

### Dark/Light Mode

Toggle in TitleBar. Persisted to `localStorage`. Sets `data-theme` attribute on `<html>`. All components read from CSS custom properties. Graph colors defined as parallel light/dark palettes in `graph_builder.py`.

## Type System

### Key TypeScript Interfaces (`types/fabric.ts`)

| Interface | Backend Counterpart | Description |
|-----------|-------------------|-------------|
| `SliceData` | `slice_to_dict()` + `graph_builder()` | Full slice with graph |
| `SliceSummary` | `slice_summary()` | Lightweight list entry |
| `SliceNode` | `serialize_node()` | Node with components/interfaces |
| `SliceNetwork` | `serialize_network()` | Network with type/layer/subnet |
| `SliceComponent` | `serialize_component()` | Hardware component |
| `SliceInterface` | `serialize_interface()` | Network interface |
| `CyGraph` | `build_cytoscape_graph()` | Cytoscape.js node/edge arrays |
| `SiteInfo` | `GET /api/sites` response | Site with GPS + availability |
| `BootConfig` | `boot-config` endpoints | Uploads + commands + network |
| `MonitoringHistory` | `GET /monitoring/{}/metrics/history` | Time-series per node |
| `VMTemplateDetail` | `GET /api/vm-templates/{}` | VM template with boot_config |
| `RecipeSummary` | `GET /api/recipes` response | Recipe metadata |
| `ProjectDetails` | `GET /projects/{}/details` | Full project info |
| `ConfigStatus` | `GET /api/config` response | Token, key, project config status |
| `TourStep` | `tourSteps.ts` | Tour step with completion check |
| `TourDef` | `tourSteps.ts` | Tour definition with steps |

### Additional Interfaces in `api/client.ts`

| Interface | Description |
|-----------|-------------|
| `SliceModel` | Import/export format for `.fabric.json` files |
| `TemplateSummary` | Template list entry with metadata |
