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
