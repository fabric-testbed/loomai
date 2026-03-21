# Team Status

## Current Goal

(None)

## Active Work

(No active work)

## Completed

- **JupyterLab button on weave cards:**
  - Added "Jup" button to the bottom-right of each weave card in LibrariesPanel side panel
  - Button opens JupyterLab to the weave's folder (`/jupyter/lab/tree/my_artifacts/{dirName}`)
  - Styled in orange (FABRIC brand), shows "..." while launching
  - CSS in template-panel.css (`.tp-jupyter-btn`)

- **Artifact tags & short/long descriptions in AI tools:**
  - Removed all `[LoomAI ...]` description marker references — artifacts now use real tags (`loomai:weave`, `loomai:vm`, `loomai:recipe`)
  - Added `description` (short, 5-255 chars for UI cards) + `description_long` (full detailed docs) guidance to: FABRIC_AI.md, create-weave skill, template-builder agent, publish-artifact skill, claude-code CLAUDE.md
  - Updated weave.json examples in all docs to include `description_long` field
  - Synced to backend/ai-tools/shared/ and pushed to running container

- **Weave default argument values in popup:**
  - Frontend: SLICE_NAME now uses `arg.default` from weave.json as base for uniquification (not `t.name`)
  - AI tools: create-weave skill, template-builder agent, FABRIC_AI.md all updated with meaningful defaults and docs explaining that defaults prepopulate the Run popup
  - Synced to backend/ai-tools/shared/

- **Refactor weave pattern: Python lifecycle scripts with start/stop/monitor:**
  - New pattern: `weave.sh` is a thin orchestrator that calls `<name>.py start|stop|monitor`
  - Python script uses FABlib directly (not curl/REST API) for slice create/delete/health-check
  - `weave.sh` handles SIGTERM trap (Stop button) → calls `stop`, monitors in a loop → calls `monitor`
  - Created `backend/default_artifacts/Hello_FABRIC/` reference weave (hello_fabric.py + weave.sh + weave.json) with beginner-friendly comments
  - Added `_seed_default_artifacts()` in `backend/app/main.py` to copy Hello_FABRIC into `my_artifacts/` on first startup
  - Updated: `ai-tools/shared/skills/create-weave.md`, `ai-tools/shared/agents/template-builder.md`, `ai-tools/shared/FABRIC_AI.md`
  - Synced to `backend/ai-tools/shared/`; all syntax validated

- **Add weave failure monitoring and graceful shutdown to AI skills/agents:**
  - All weave.sh examples now include: `CREATED_SLICES` array to track slices, `report_failure()` for per-node diagnostics, `cleanup()` + `trap SIGTERM SIGINT` for Stop button handling, post-StableOK management IP verification, and monitoring loop
  - When user clicks Stop: trap fires → data collected → all tracked slices deleted → clean exit
  - Updated: `ai-tools/shared/skills/create-weave.md`, `ai-tools/shared/agents/template-builder.md`, `ai-tools/shared/FABRIC_AI.md` (new "Weave Failure Handling & Graceful Shutdown" section)
  - Synced to `backend/ai-tools/shared/`; all bash syntax validated

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
  - React.memo expansion: 10 additional components wrapped (AllSliversView, LibrariesPanel, BottomPanel, SideConsolePanel, Toolbar, TitleBar, DetailPanel, AIChatPanel, StatusBar, SlicesView) — total now 13 of 40+ components (LibrariesPanel is the Artifacts panel component)
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
  - Phase 1 (Quick Wins): Remove duplicate refreshSlice in boot-config path; tune polling intervals (per-run 2s→5s, active runs 10s→30s); visibility-aware polling (pause when tab hidden); Artifacts panel only polls when visible
  - Phase 2 (Request Management): AbortController on polling requests; backend list_slices dedup cache (5s TTL + asyncio.Lock)
  - Phase 3 (Backend Bottlenecks): Eliminate per-slice UUID confirmations in GET /slices (O(N)→O(1)); serialization cache for stable slices
  - Phase 4 (Idle Optimization): Conditional active runs polling; monitoring manager exponential backoff for unreachable nodes
  - Phase 5 (Infrastructure): Stale-while-revalidate site cache with background refresh; dedicated FABlib thread pool (4 workers)
  - Phase 6 (Frontend Rendering): React.memo on CytoscapeGraph, GeoView, EditorPanel

- Update E2E tests for new features: fix infrastructure view tab count (2→3 for Facility Ports), update template loading test selectors (transport controls), add missing API mocks (ai/tools/status, templates/runs, links, facility-ports, projects), update test data with has_deploy/has_run fields

- Persist Claude Code config across container rebuilds: backup/restore entire ~/.claude/ dir + ~/.claude.json to .loomai/tools/claude-code/; add Settings panel in Claude Code sidebar to view, edit, save, and reset config files; force IPv4 for Node.js connectivity
- Fix slice delete race condition: slices no longer pop back to StableOK after deletion — polling preserves Closing/Dead state until FABRIC confirms (2-min timeout)
- Propagate weave workflow knowledge (weave.json, weave.sh, run_manager, background runs, console log tabs) across all skills, agents, and prompts — updated: create-weave skill, template-builder, devops-engineer, experiment-designer, fabric-manager, troubleshooter agents; libraries, create-template, artifacts, backend commands; ARCHITECTURE.md, CLAUDE.md
- Remove all "builtin" artifact references from frontend, backend AI docs, ai-tools/ copies, and markdown docs

- Orchestrated run: weave.sh handles the full experiment lifecycle in one click
- Unified play button color: all ▶ buttons use primary blue (#5798bc) regardless of mode (Load/Deploy/Run)
- Transport controls on weave cards: ▶ Play, ■ Stop, ↺ Reset always visible with enable/disable states
- Artifacts view: weave cards show "Open in Slices" instead of Load/Deploy/Run
- Running weave indicator + reattach: Artifacts panel now shows "running" badge on weaves with active background runs, plus "View Output" / "Last Output" button to open the log tab in BottomPanel
- Backend/Frontend: Add tool install progress popup with SSE streaming

## Blockers

(No blockers)
