# Team Status

## Current Goal

(None)

## Active Work

(No active work)

## Completed

- **Add Deep Agents AI tool:**
  - Added `deepagents` to TOOL_REGISTRY (pip: deepagents-cli[anthropic], ~500 MB)
  - Added TOOL_CONFIGS entry with OPENAI_API_KEY/BASE_URL env vars pointing to FABRIC AI server
  - Created `ai-tools/deepagents/AGENTS.md` project instructions
  - Added `_setup_deepagents_workspace()` for .deepagents/AGENTS.md seeding
  - Added to WebSocket handler dispatch and `seed_ai_tool_defaults()`
  - Added `"deepagents": True` to default settings
  - Added frontend tool card (DA icon, green gradient, Free tier)
  - Updated ARCHITECTURE.md and ai-tools README

- **Performance optimization Round 3:**
  - Code splitting: 8 heavy views lazy-loaded with next/dynamic (HelpView, ConfigureView, JupyterLabView, AICompanionView, ArtifactEditorView, LandingView, FileTransferView, InfrastructureView)
  - React.memo expansion: 10 additional components wrapped (AllSliversView, LibrariesPanel, BottomPanel, SideConsolePanel, Toolbar, TitleBar, DetailPanel, AIChatPanel, StatusBar, SlicesView) — total now 13 of 40+ components
  - Startup parallelization: 5 initial API calls (images, models, templates, AI tools, recipes) batched into single Promise.all for one render cycle

- **Performance optimization Round 2:**
  - gzip compression + static asset cache headers in nginx
  - Lightweight state-only polling endpoint (GET /slices/{name}/state)
  - HTTP connection pooling (shared httpx clients for FABRIC/AI APIs)
  - Template/recipe/VM-template listing caches (10s TTL)
  - Async file I/O wrapping (asyncio.to_thread)
  - useCallback extraction for 14 inline callbacks in App.tsx
  - useMemo for JSON.stringify(sliceData) in AI chat

- **Performance optimization Round 1 (all 6 phases):**
  - Phase 1 (Quick Wins): Remove duplicate refreshSlice in boot-config path; tune polling intervals (per-run 2s→5s, active runs 10s→30s); visibility-aware polling (pause when tab hidden); LibrariesPanel only polls when visible
  - Phase 2 (Request Management): AbortController on polling requests; backend list_slices dedup cache (5s TTL + asyncio.Lock)
  - Phase 3 (Backend Bottlenecks): Eliminate per-slice UUID confirmations in GET /slices (O(N)→O(1)); serialization cache for stable slices
  - Phase 4 (Idle Optimization): Conditional active runs polling; monitoring manager exponential backoff for unreachable nodes
  - Phase 5 (Infrastructure): Stale-while-revalidate site cache with background refresh; dedicated FABlib thread pool (4 workers)
  - Phase 6 (Frontend Rendering): React.memo on CytoscapeGraph, GeoView, EditorPanel

- Update E2E tests for new features: fix infrastructure view tab count (2→3 for Facility Ports), update template loading test selectors (transport controls), add missing API mocks (ai/tools/status, templates/runs, links, facility-ports, projects), update test data with has_deploy/has_run fields

- Persist Claude Code config across container rebuilds: backup/restore entire ~/.claude/ dir + ~/.claude.json to .loomai/tools/claude-code/; add Settings panel in Claude Code sidebar to view, edit, save, and reset config files; force IPv4 for Node.js connectivity
- Fix slice delete race condition: slices no longer pop back to StableOK after deletion — polling preserves Closing/Dead state until FABRIC confirms (2-min timeout)
- Remove all "builtin" artifact references from frontend, backend AI docs, and both ai-tools/ copies

- Orchestrated run: ▶ Run on deploy+run weaves now deploys first, waits for completion, then auto-starts run.sh — full experiment lifecycle in one click
- Unified play button color: all ▶ buttons use primary blue (#5798bc) regardless of mode (Load/Deploy/Run)
- Transport controls on weave cards: ▶ Play, ■ Stop, ↺ Reset always visible with enable/disable states
- Artifacts view: weave cards show "Open in Slices" instead of Load/Deploy/Run
- Running weave indicator + reattach: LibrariesPanel now shows "running" badge on weaves with active background runs, plus "View Output" / "Last Output" button to open the log tab in BottomPanel
- Backend/Frontend: Add tool install progress popup with SSE streaming

## Blockers

(No blockers)
