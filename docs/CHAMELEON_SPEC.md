# Chameleon Cloud Integration — Detailed Implementation Spec

## Context

Extend Loomai to manage Chameleon Cloud experiments alongside FABRIC. Users should be able to browse Chameleon resources, create/manage leases and instances, SSH to nodes, and see everything in a unified map — all from the same GUI and CLI they use for FABRIC.

**Decisions:**
- SDK: `python-chi` primary, `openstacksdk` fallback for gaps
- Scope: Full parity with FABRIC (not phased)
- UI: Chameleon sites integrated into shared map, separate lease management view
- Test credentials: coming soon — build against API docs first

---

## Phase 1: Backend Foundation

### 1.1 Settings Schema
**File**: `backend/app/settings_manager.py`

Add `chameleon` section to `get_default_settings()`:
```python
"chameleon": {
    "enabled": False,
    "auth_url": "https://chi.tacc.chameleoncloud.org:5000/v3",
    "username": "",
    "password": "",           # or application credential
    "project_id": "",
    "project_name": "",
    "region": "CHI@TACC",     # default site
    "sites": {
        "CHI@TACC": {
            "auth_url": "https://chi.tacc.chameleoncloud.org:5000/v3",
            "region": "CHI@TACC",
            "location": {"lat": 30.2672, "lon": -97.7431},  # Austin, TX
        },
        "CHI@UC": {
            "auth_url": "https://chi.uc.chameleoncloud.org:5000/v3",
            "region": "CHI@UC",
            "location": {"lat": 41.7897, "lon": -87.5997},  # Chicago, IL
        },
        "CHI@Edge": {
            "auth_url": "https://chi.edge.chameleoncloud.org:5000/v3",
            "region": "CHI@Edge",
            "location": {"lat": 41.7897, "lon": -87.5997},
        },
        "KVM@TACC": {
            "auth_url": "https://kvm.tacc.chameleoncloud.org:5000/v3",
            "region": "KVM@TACC",
            "location": {"lat": 30.2672, "lon": -97.7431},
        },
    },
},
```

### 1.2 Chameleon Manager (Singleton)
**File**: `backend/app/chameleon_manager.py` (new)

Mirrors `fablib_manager.py` pattern:
- `get_chi(site="CHI@TACC")` — returns authenticated `python-chi` connection for a site
- `reset_chi()` — clears cached connections (on settings change)
- `is_chameleon_configured()` — checks username + password + project_id are set
- Connection pool: one authenticated session per site (Keystone tokens cached)
- Thread-safe singleton with `_lock`

### 1.3 Chameleon Executor
**File**: `backend/app/chameleon_executor.py` (new)

Same pattern as `fablib_executor.py`:
- Dedicated `ThreadPoolExecutor(max_workers=4)` for blocking OpenStack calls
- `run_in_chi_pool(fn, *args)` async bridge

### 1.4 Chameleon Routes
**File**: `backend/app/routes/chameleon.py` (new)

#### Resource Endpoints
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/chameleon/sites` | List Chameleon sites with availability |
| GET | `/api/chameleon/sites/{site}/nodes` | List node types at a site (compute, GPU, storage, FPGA) |
| GET | `/api/chameleon/sites/{site}/availability` | Real-time availability per node type |
| GET | `/api/chameleon/sites/{site}/images` | Available OS images |

#### Lease Endpoints (Blazar API)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/chameleon/leases` | List all leases across all sites |
| POST | `/api/chameleon/leases` | Create a new lease (site, node_type, count, duration) |
| GET | `/api/chameleon/leases/{id}` | Lease details |
| PUT | `/api/chameleon/leases/{id}/extend` | Extend lease duration |
| DELETE | `/api/chameleon/leases/{id}` | Delete/release lease |

#### Instance Endpoints (Nova API)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/chameleon/instances` | List all instances |
| POST | `/api/chameleon/instances` | Launch instance on a lease (image, key, network) |
| GET | `/api/chameleon/instances/{id}` | Instance details (IP, status) |
| DELETE | `/api/chameleon/instances/{id}` | Terminate instance |
| POST | `/api/chameleon/instances/{id}/associate-ip` | Assign floating IP |

#### SSH/Network
| Method | Path | Description |
|--------|------|-------------|
| WS | `/ws/terminal/chameleon/{instance_id}` | SSH terminal to Chameleon instance |
| POST | `/api/chameleon/instances/{id}/execute` | Run command on instance |

### 1.5 Caching
Use existing `FabricCallManager` with Chameleon-specific cache keys:
- `chi:sites` — site list (TTL: 5 min)
- `chi:leases` — lease list (TTL: 30s, invalidated on create/delete)
- `chi:instances` — instance list (TTL: 30s)
- `chi:{site}:availability` — per-site resources (TTL: 2 min)

### 1.6 Docker
**File**: `backend/requirements.txt`

Add:
```
python-chi
openstacksdk
```

---

## Phase 2: Frontend

### 2.1 Types
**File**: `frontend/src/types/chameleon.ts` (new)

```typescript
export interface ChameleonSite {
  name: string;              // "CHI@TACC"
  auth_url: string;
  region: string;
  location: { lat: number; lon: number };
  node_types: ChameleonNodeType[];
}

export interface ChameleonNodeType {
  name: string;              // "compute_haswell"
  architecture: string;      // "x86_64"
  cpu_count: number;
  ram_mb: number;
  disk_gb: number;
  gpu?: string;              // "P100" etc
  total: number;
  available: number;
}

export interface ChameleonLease {
  id: string;
  name: string;
  site: string;
  status: string;            // "ACTIVE", "PENDING", "TERMINATED"
  start_date: string;
  end_date: string;
  node_type: string;
  node_count: number;
  reservations: ChameleonReservation[];
}

export interface ChameleonReservation {
  id: string;
  resource_type: string;
  status: string;
  min: number;
  max: number;
}

export interface ChameleonInstance {
  id: string;
  name: string;
  site: string;
  lease_id: string;
  status: string;            // "ACTIVE", "BUILD", "SHUTOFF", "ERROR"
  image: string;
  ip_address?: string;
  floating_ip?: string;
  created: string;
}
```

### 2.2 API Client
**File**: `frontend/src/api/client.ts`

Add Chameleon API functions:
```typescript
// Sites & resources
export function getChameleonSites(): Promise<ChameleonSite[]>
export function getChameleonAvailability(site: string): Promise<ChameleonNodeType[]>
export function getChameleonImages(site: string): Promise<string[]>

// Leases
export function listChameleonLeases(): Promise<ChameleonLease[]>
export function createChameleonLease(params: {...}): Promise<ChameleonLease>
export function deleteChameleonLease(id: string): Promise<void>
export function extendChameleonLease(id: string, hours: number): Promise<ChameleonLease>

// Instances
export function listChameleonInstances(): Promise<ChameleonInstance[]>
export function createChameleonInstance(params: {...}): Promise<ChameleonInstance>
export function deleteChameleonInstance(id: string): Promise<void>
```

### 2.3 Map Integration
**File**: `frontend/src/components/GeoView.tsx`

- Add Chameleon sites as markers alongside FABRIC sites
- Different marker color/shape (e.g., orange circle vs blue circle for FABRIC)
- Popup shows Chameleon resource availability
- Legend distinguishes FABRIC vs Chameleon sites

### 2.4 Chameleon View (new top-level view)
**File**: `frontend/src/components/ChameleonView.tsx` (new)

Two-panel layout:
- **Left**: Lease list with status badges, create/delete buttons
- **Right**: Selected lease details — instances, resource info, SSH button

Sub-views:
- **Leases** — list, create, extend, delete
- **Instances** — launch, terminate, associate IP, SSH
- **Resources** — browse node types per site

### 2.5 App.tsx Integration
**File**: `frontend/src/App.tsx`

- Add `'chameleon'` to `TopView` type
- Add navigation tab in TitleBar
- Add Chameleon state: `[chameleonLeases, setChameleonLeases]`, etc.
- Add polling (STEADY/ACTIVE pattern, same as FABRIC slices)

### 2.6 Settings UI — Chameleon Section
**File**: `frontend/src/components/ConfigureView.tsx`

Dedicated Chameleon section in Settings with:

**Enable/Disable Toggle** (top of section)
- Switch: "Enable Chameleon Cloud Integration"
- When off: the rest of the section is collapsed/grayed out, and all Chameleon UI across the app is hidden
- When toggled on: expands to show credential forms; when toggled off: hides all Chameleon views immediately

**Per-Site Credentials** (expandable accordion per site)
- **CHI@TACC**:
  - Application Credential ID (text input)
  - Application Credential Secret (password input, masked)
  - Project ID (text input, auto-filled if detected from auth)
  - "Test Connection" button — authenticates to Keystone + lists leases
  - Status indicator: green check / red X / gray dash
- **CHI@UC**: same fields
- **CHI@Edge**: same fields (optional)
- **KVM@TACC**: same fields (optional)

**Default Site** dropdown — which site to use when none specified

**"Test All" button** — tests all configured sites at once, shows summary

---

## Phase 3: CLI

### 3.1 Chameleon Commands
**File**: `cli/loomai_cli/commands/chameleon.py` (new)

```
loomai chameleon sites                    # List Chameleon sites
loomai chameleon sites CHI@TACC           # Show site details + availability
loomai chameleon leases                   # List leases
loomai chameleon leases create --site CHI@TACC --type compute_haswell --count 2 --hours 4
loomai chameleon leases delete <id>
loomai chameleon leases extend <id> --hours 2
loomai chameleon instances                # List instances
loomai chameleon instances create --lease <id> --image CC-Ubuntu22.04
loomai chameleon instances delete <id>
loomai chameleon ssh <instance_id>        # SSH to instance
loomai chameleon exec <instance_id> "cmd" # Run command
```

### 3.2 AI Chat Integration
- Add Chameleon tools to `execute_tool()` in `ai_chat.py`
- Update `FABRIC_AI.md` with Chameleon operations
- Add skills: `create-chameleon-lease.md`, `query-chameleon.md`
- `loomai ? "reserve 2 GPU nodes on CHI@TACC"` should work

---

## Phase 4: Cross-Testbed

### 4.1 Cross-Testbed Networking
Two approaches for FABRIC ↔ Chameleon connectivity:

**Option A: Dedicated L2 via Facility Port**
- FABRIC facility ports can provide dedicated Layer 2 connections to Chameleon sites
- Chameleon bare-metal nodes with dedicated NICs can be stitched to FABRIC VLANs
- Requires coordinating VLAN IDs between FABRIC facility port allocation and Chameleon network configuration
- Best for: high-bandwidth, low-latency experiments; network research; custom protocol testing
- Configuration: user specifies a FABRIC facility port + VLAN and a Chameleon isolated network; Loomai wires them together

**Option B: FABnet v4 with Routing**
- Both FABRIC nodes and Chameleon instances connect to FABnet v4 (FABRIC's IPv4 routed network)
- Chameleon instances use a floating IP reachable from FABRIC's FABnet
- Requires: correct route setup on both sides — FABRIC nodes need routes to Chameleon IPs and vice versa
- Best for: simple connectivity, multi-site experiments where bandwidth isn't critical
- Configuration: Loomai auto-configures routes on FABRIC nodes to reach Chameleon floating IPs, and provides setup scripts for Chameleon instances

Both approaches should be selectable when creating cross-testbed topologies in the GUI.

### 4.2 Unified Topology View
- Cytoscape graph can show both FABRIC nodes and Chameleon instances
- Different node shapes/colors per testbed (FABRIC: blue, Chameleon: orange)
- Cross-testbed edges for stitched connections (L2 facility port or FABnet route)
- Edge labels indicate connection type ("L2 Stitch" vs "FABnet v4")

### 4.3 Unified Monitoring
- Chameleon instances get same monitoring treatment as FABRIC nodes
- SSH-based `node_exporter` install + metrics collection

## Enable/Disable Toggle

### Global Chameleon Toggle
The Chameleon integration is controlled by a single `chameleon.enabled` boolean in settings. When **disabled**:

**Hidden from UI:**
- "Chameleon" tab in TitleBar navigation — not rendered
- Chameleon sites on GeoView map — not shown
- Chameleon section in ConfigureView — collapsed to just the enable toggle
- ChameleonView component — not loaded
- Chameleon options in topology editor (cross-testbed nodes) — hidden
- Chameleon commands in AI assistant tool list — excluded

**Hidden from CLI:**
- `loomai chameleon` command group — prints "Chameleon integration is disabled. Enable it in Settings."
- AI assistant does not suggest or execute Chameleon tools

**Backend behavior when disabled:**
- Chameleon routes return 404 or `{"error": "Chameleon integration is disabled"}`
- No Keystone auth sessions created
- No background polling for Chameleon resources
- Zero overhead — as if Chameleon code doesn't exist

**Implementation:**
- Frontend: check `settings.chameleon.enabled` (fetched with config on mount) before rendering any Chameleon UI
- Backend: middleware or per-route check of `settings_manager.is_chameleon_enabled()`
- CLI: check at command group level, short-circuit with message

---

## Implementation Order

1. **Settings + Manager + Executor** (backend foundation) — no UI needed yet, testable via curl
2. **Routes** (lease + instance CRUD) — API endpoints
3. **CLI commands** — `loomai chameleon` group
4. **Frontend types + API client** — no UI yet, just the data layer
5. **Map integration** — Chameleon sites on the shared map
6. **ChameleonView** — lease/instance management UI
7. **Settings UI** — Chameleon credentials in ConfigureView
8. **AI assistant tools** — Chameleon skills for LoomAI
9. **SSH/terminal** — WebSocket terminal to Chameleon instances
10. **Cross-testbed topology** — mixed graphs, stitching

## Files Created/Modified

| File | Status | Description |
|------|--------|-------------|
| `backend/app/chameleon_manager.py` | New | Singleton wrapping python-chi |
| `backend/app/chameleon_executor.py` | New | Thread pool for blocking calls |
| `backend/app/routes/chameleon.py` | New | All Chameleon REST endpoints |
| `backend/app/settings_manager.py` | Modified | Add chameleon settings section |
| `backend/requirements.txt` | Modified | Add python-chi, openstacksdk |
| `frontend/src/types/chameleon.ts` | New | TypeScript interfaces |
| `frontend/src/api/client.ts` | Modified | Chameleon API functions |
| `frontend/src/components/ChameleonView.tsx` | New | Lease/instance management |
| `frontend/src/components/GeoView.tsx` | Modified | Chameleon sites on map |
| `frontend/src/components/ConfigureView.tsx` | Modified | Chameleon credentials UI |
| `frontend/src/App.tsx` | Modified | Chameleon view + state |
| `cli/loomai_cli/commands/chameleon.py` | New | CLI command group |
| `cli/loomai_cli/main.py` | Modified | Register chameleon commands |
| `backend/ai-tools/shared/FABRIC_AI.md` | Modified | Chameleon context |
| `backend/ai-tools/shared/skills/` | New files | Chameleon skills |

## Verification

1. Backend tests: `python -m pytest tests/ -x`
2. Frontend: `npx tsc --noEmit`
3. Manual: Configure Chameleon credentials → browse sites on map → create lease → launch instance → SSH
4. CLI: `loomai chameleon sites` → `loomai chameleon leases create ...`
5. AI: `loomai ? "show me Chameleon resources at TACC"`
