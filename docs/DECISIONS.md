# Architectural Decision Records

Key architectural decisions for the fabric-webgui project.

---

## ADR-001: FastAPI + FABlib Direct Import

**Status**: Accepted

**Context**: FABlib is the official Python library for FABRIC testbed operations. We needed to decide between importing it directly into the backend process or wrapping it via a separate REST API.

**Decision**: Import FABlib directly into the FastAPI process. Offload blocking calls to a dedicated thread pool (`fablib_executor.py`).

**Consequences**:
- (+) No network overhead for FABlib calls — in-process function calls
- (+) Full access to FABlib's object model (slices, nodes, components)
- (-) FABlib's blocking I/O requires a thread pool to avoid starving async operations
- (-) Tight coupling to FABlib's Python API — upgrades may require backend changes

---

## ADR-002: Single Combined Docker Image

**Status**: Accepted

**Context**: The application has a Python backend and a React frontend. We considered running them as separate containers vs. a single combined image.

**Decision**: Production uses a single Docker image with `supervisord` managing both nginx (serving static frontend + reverse proxy) and uvicorn (FastAPI backend). A two-container `docker-compose.dev.yml` is available for development.

**Consequences**:
- (+) Simpler deployment — one image, one `docker compose up`
- (+) No inter-container networking for API calls
- (-) Larger image size (Python + Node.js build artifacts + nginx)
- (-) Single point of failure — both services in one container

---

## ADR-003: OpenAI-Compatible API for AI Provider Abstraction

**Status**: Accepted

**Context**: Multiple AI tools (LoomAI, Aider, OpenCode, Crush, Claude Code, Deep Agents) need LLM access. FABRIC provides a free AI server; NRP/Nautilus is a fallback.

**Decision**: Use the OpenAI-compatible chat completions API format (LiteLLM proxy on FABRIC side). Backend uses `httpx.AsyncClient` (not the `openai` Python library) for direct HTTP calls. A local model proxy (`scripts/model_proxy.py`) rewrites unknown model names to a configured default.

**Consequences**:
- (+) Any OpenAI-compatible tool works without modification
- (+) Model proxy handles hardcoded model names in third-party tools
- (+) No dependency on the `openai` Python package
- (-) Must maintain the model proxy for tools with hardcoded model names
- (-) Tool-calling format tied to OpenAI's function-calling specification

---

## ADR-004: React Hooks-Only State Management

**Status**: Accepted

**Context**: The frontend needs to manage complex state (slices, infrastructure, terminals, validation, UI layout). We considered Redux, Zustand, or React's built-in hooks.

**Decision**: All state lives in `App.tsx` as `useState` hooks. No external state management library. `useCallback` and `useMemo` for performance. `React.memo` on heavy components.

**Consequences**:
- (+) No additional dependencies or boilerplate
- (+) Single source of truth — all state visible in one file
- (-) `App.tsx` is large (many useState declarations and callbacks)
- (-) Prop drilling for deeply nested components

---

## ADR-005: Static Export via Next.js 15

**Status**: Accepted

**Context**: The frontend was originally built with Vite/React. It migrated to Next.js for build tooling but remains entirely client-side rendered.

**Decision**: Use Next.js 15 with `output: 'export'` and `distDir: 'dist'` (static export, no SSR). The entry point (`src/app/page.tsx`) uses `next/dynamic` with `ssr: false` to load `App.tsx`.

**Consequences**:
- (+) Standard Next.js tooling (routing, code splitting, `next/dynamic`)
- (+) Static output served by nginx — no Node.js runtime needed in production
- (+) Dev server proxies `/api/*` to backend via `next.config.mjs` rewrites
- (-) No server-side rendering benefits (all rendering is client-side)

---

## ADR-006: UUID-First Identity Model

**Status**: Accepted

**Context**: FABRIC objects (slices, projects, artifacts) can have duplicate names. We needed a consistent identity strategy.

**Decision**: UUID is the primary key for all FABRIC-managed objects. Names are display labels only. See the full policy in `CLAUDE.md` under "Identity & UUID Policy".

**Consequences**:
- (+) No name collision bugs — UUIDs are globally unique
- (+) Consistent across frontend state, backend storage, and API routes
- (-) UUIDs are less human-readable — UI must show names with disambiguation hints

---

## ADR-007: Cytoscape.js + Leaflet (Matching fabvis)

**Status**: Accepted

**Context**: The project replicates fabvis (Jupyter-based FABRIC visualizer). We needed graph and map visualization libraries.

**Decision**: Use Cytoscape.js for topology graphs and Leaflet for geographic map views — the same libraries as fabvis — with matching stylesheets, colors, and layout algorithms.

**Consequences**:
- (+) Visual continuity with fabvis — users see the same graph style
- (+) Mature, well-documented libraries with active communities
- (-) Cytoscape.js bundle is large (~500KB)
- (-) Custom stylesheet must stay in sync with fabvis updates

---

## ADR-008: Thread Pool Isolation for FABlib

**Status**: Accepted

**Context**: FABlib calls are blocking (2–15 seconds each). Running them in the default asyncio thread pool starves WebSocket terminals, SSE streams, and file operations.

**Decision**: A dedicated `ThreadPoolExecutor` with 4 workers and a `"fablib"` thread name prefix (`fablib_executor.py`). All FABlib calls go through `run_in_fablib_pool()`.

**Consequences**:
- (+) WebSocket/SSE/file operations remain responsive during FABlib calls
- (+) Limited concurrency (4 workers) protects FABlib's non-thread-safe internals
- (-) Maximum 4 concurrent FABlib operations — additional calls queue

---

## ADR-009: Module-Level Persistent Stores for Sessions

**Status**: Accepted

**Context**: AI tool terminals and chat sessions need to survive React component remounts (e.g., switching views and returning). We needed a persistence mechanism.

**Decision**: AI tool terminal sessions and chat history are stored at the module level in the backend (Python dicts keyed by session ID). WebSocket handlers reconnect to existing sessions.

**Consequences**:
- (+) Sessions survive frontend component unmount/remount
- (+) No external session store (Redis, database) needed
- (-) Sessions lost on backend restart
- (-) Memory grows with active sessions (mitigated by idle timeouts)

---

## ADR-010: CSS Custom Properties (No CSS-in-JS / Tailwind)

**Status**: Accepted

**Context**: The frontend needs consistent theming (light/dark mode, FABRIC brand colors) across 34+ component CSS files.

**Decision**: Plain CSS files with CSS custom properties defined in `global.css`. `[data-theme="dark"]` overrides for dark mode. BEM-like class naming. No CSS-in-JS, Tailwind, or CSS modules.

**Consequences**:
- (+) Zero runtime CSS overhead — no JS-based style computation
- (+) Theme switching is a single `data-theme` attribute change
- (+) Easy to grep and understand — standard CSS
- (-) No compile-time class name safety (typos fail silently)
- (-) Global namespace requires disciplined naming conventions

---

## ADR-011: Kubernetes Multi-User Deployment via Hub + CHP

**Status**: Accepted

**Context**: LoomAI needed multi-user deployment where each user gets an isolated environment with their own FABRIC credentials, persistent storage, and AI tools. Considered JupyterHub (heavyweight, Jupyter-centric) vs. custom lightweight hub.

**Decision**: Build a custom lightweight Hub (FastAPI) inspired by JupyterHub's architecture: CILogon OIDC authentication, Configurable HTTP Proxy (CHP) for dynamic routing, and per-user Kubernetes pods. Reuses CHP from JupyterHub ecosystem but everything else is custom.

**Consequences**:
- (+) Full control over authentication flow, token management, and pod lifecycle
- (+) Lightweight — no Jupyter kernel management, spawner abstractions, or hub DB migrations
- (+) CHP is battle-tested and handles dynamic routing reliably
- (-) Must maintain pod spawning, idle culling, and session management ourselves
- (-) No ecosystem of JupyterHub plugins

---

## ADR-012: Nginx Reverse Proxy for AI Tools in User Pods

**Status**: Accepted

**Context**: AI tools (JupyterLab, Aider, OpenCode) run on separate ports inside user pods (8889, 9197, 9198). In K8s mode, CHP only routes to one port per pod (3000). Needed a way to expose multiple services.

**Decision**: Use the existing nginx (port 3000) inside each user pod as a reverse proxy. Add location blocks for each tool: `/jupyter/` → port 8889, `/aider/` → port 9197, `/opencode/` → port 9198, `/tunnel/{port}/` → dynamic ports 9100-9199.

**Consequences**:
- (+) No additional K8s services or CHP configuration per tool
- (+) All traffic goes through the single CHP route to port 3000
- (+) Security: tunnel proxy restricted to ports 9100-9199 via regex `(91[0-9][0-9])`
- (-) Nginx config is generated dynamically in entrypoint.sh (adds complexity)
- (-) JupyterLab requires `base_url` to include the full CHP sub-path for correct redirects

---

## ADR-013: Lazy Tool Installation on Persistent Volume

**Status**: Accepted

**Context**: AI tools (JupyterLab ~900MB, Aider ~900MB, OpenCode ~200MB, etc.) are too large to bake into the Docker image. Users may not need all tools.

**Decision**: Tools are lazy-installed on first use into the persistent volume at `.ai-tools/`. A `ToolInstallOverlay` component shows progress. File-based locks (`fcntl.flock`) prevent concurrent installs. On pod startup, all lock files are unconditionally cleaned (stale locks from previous containers caused "being installed by another process" errors due to PID reuse).

**Consequences**:
- (+) Docker image stays small (~1.5GB vs ~5GB+)
- (+) Users only pay the install time for tools they actually use
- (+) Tools persist across pod restarts via PVC
- (-) First-use latency for each tool (30s–3min depending on tool size)
- (-) PVC must be sized to accommodate installed tools (≥5Gi recommended)

---

## ADR-014: Versioned Image Tags for Kubernetes Deployments

**Status**: Accepted

**Context**: Using `latest` tag for Docker images caused deployment issues — Kubernetes cached old image digests, `helm upgrade` didn't trigger pod restarts, and `kubectl rollout restart` was needed as a workaround.

**Decision**: Always use versioned tags (e.g., `0.2.4`) for production deployments. Reserve `latest` for development only.

**Consequences**:
- (+) Deterministic deployments — every `helm upgrade` with a new tag pulls the correct image
- (+) Easy rollback — just change the tag back to a previous version
- (+) No need for manual `kubectl rollout restart` workarounds
- (-) Must remember to bump the tag on every release

---

## ADR-015: CHP TLS Termination (No Ingress Controller)

**Status**: Accepted

**Context**: LoomAI on Kubernetes needs HTTPS for production (secure cookies, CILogon OIDC). Options: (1) install an ingress controller (nginx-ingress, Traefik) + cert-manager, (2) use cloud-managed HTTPS (GKE Ingress), (3) terminate TLS directly in CHP.

**Decision**: CHP (Configurable HTTP Proxy) terminates TLS directly using `--ssl-key` and `--ssl-cert` flags. The TLS certificate chain and private key are stored in a K8s TLS secret (`loomai-proxy-manual-tls`). When `proxy.https.enabled: true`, the LoadBalancer service exposes only port 443. No ingress controller required.

**Consequences**:
- (+) Zero additional infrastructure — no ingress controller or cert-manager to install/maintain
- (+) Works on any K8s cluster with a LoadBalancer service (GKE, EKS, AKS, bare-metal with MetalLB)
- (+) Simple cert rotation — recreate the K8s secret and restart the proxy pod
- (-) No automatic cert renewal (manual process, or use external automation)
- (-) No HTTP→HTTPS redirect (clients hitting port 80 get connection refused, not a redirect)

---

## ADR-016: Hub-Disabled AI Tools in Kubernetes Mode

**Status**: Accepted

**Context**: In hub (K8s) mode, each user gets a container with limited PVC storage (typically 5Gi). Installable AI tools (Aider ~900MB, Claude Code ~1GB, OpenCode ~200MB, Crush ~150MB, Deep Agents ~500MB) would consume most of this budget, leaving little room for user data.

**Decision**: In hub mode, installable AI tools are greyed out in the UI with a "Local Install Only" badge and disabled launch buttons. LoomAI (the built-in chat assistant, 0MB install) remains fully available. Hub mode is detected via `window.__LOOMAI_BASE_PATH` (set by the hub spawner in K8s, absent in standalone Docker).

**Consequences**:
- (+) User PVC space preserved for data, notebooks, and FABRIC credentials
- (+) No change to standalone Docker — all tools remain available locally
- (+) LoomAI provides full AI assistant capabilities without installation
- (-) Users who want the full tool suite must run LoomAI locally via Docker
