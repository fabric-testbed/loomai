# Roadmap

Project status and planned work for fabric-webgui.

## Done

Major features completed (see `docs/TEAM_STATUS.md` for details):

- **Core GUI**: Three-panel topology editor, Cytoscape.js graph, Leaflet map, tabular sliver view
- **Slice lifecycle**: Create, submit, modify, refresh, delete, clone, export/import, renew, archive
- **Template system**: Weaves (orchestrated topologies), VM templates, recipes
- **Weave workflow**: Python lifecycle scripts (`start`/`stop`/`monitor`), `weave.sh` orchestrator, background runs with log streaming, failure monitoring, graceful shutdown (SIGTERM trap)
- **Artifact marketplace**: Browse, publish, download artifacts from FABRIC Artifact Manager
- **AI tools**: 6 integrated tools — LoomAI (chat), Aider (web IDE), OpenCode (terminal), Crush (TUI), Claude Code (CLI), Deep Agents (LangChain)
- **AI agents & skills**: 8 agent personas + 31 skills for in-container AI tools, user-customizable via Settings UI with CRUD API
- **Site resolution**: `@group` co-location tags, host-level feasibility checks, auto-assign
- **File management**: Dual-panel browser (container storage + VM SFTP), file editor
- **Terminal**: Local container shell, SSH to VMs via bastion, FABlib log tail
- **Monitoring**: Per-node `node_exporter` install, Prometheus scraping, rolling time-series
- **Guided tours**: 14 interactive walkthroughs with completion checks
- **Help system**: Tooltips, right-click context help, searchable help page
- **Performance optimization**: 3 rounds — lazy loading, React.memo, connection pooling, FABlib thread pool, stale-while-revalidate caching, visibility-aware polling
- **Dark/light mode**: CSS custom properties with `[data-theme="dark"]` overrides
- **Multi-platform builds**: `linux/amd64` + `linux/arm64` Docker images
- **Deployment options**: Docker Compose, Tailscale, LXC/Proxmox template
- **Unified FabricCallManager**: Centralized caching with caller-specified `max_age`, request coalescing, SWR, mutation invalidation, stale-on-error fallback (16 unit tests)
- **Adaptive STEADY/ACTIVE polling**: 300s cache at rest, 30s during transitions, 3-min mutation cooldown, backend-driven cache invalidation for weave runs
- **Sliver state polling**: `GET /slices/{id}/slivers` lightweight endpoint, frontend merges per-node states
- **`loomai` CLI**: 20 command groups, 65+ subcommands (slices, SSH, exec, scp, weaves, artifacts, recipes, monitoring, config, AI assistant), interactive shell with `/ask`, `/model`, tab completion
- **LoomAI assistant**: Intent detection (25+ patterns), ultra-compact 1.5K prompt, pre-fetch pipeline, confidence routing, multi-step templates, conversation persistence, command history, usage tracking, dry run confirmations, failure learning
- **Per-model context management**: compact/standard/large profiles in `chat_context.py`, auto-detection from `/v1/models`, conversation trimming, tool schema filtering, token budgets (30/50/20 split)
- **Model health checks**: Verify each model with 1-token test, mark broken ones unavailable, grouped selector with optgroups
- **Custom LLM providers**: Settings schema (`ai.custom_providers`), model fetching, frontend add/remove UI
- **Shared LLM config**: Auto-discover first healthy FABRIC LLM on startup, persist `ai.default_model` in `settings.json`, bidirectional sync between chat panel and CLI/shell via `PUT /api/ai/models/default`
- **Graceful tool-calling fallback**: Auto-retry without `tools` parameter, "suggest CLI commands" mode for unsupported models
- **`.weaveignore`**: Gitignore-style exclusions for artifact publish, default template seeded
- **Documentation update (2026-03-26)**: ARCHITECTURE.md (AI Chat/Models/Tools endpoints, tour count), CLAUDE.md (6 feature sections, 13 key files), CONVENTIONS.md (AI assistant system section), AGENTS.md (file locations, model discovery, skill guide)
- **Quick wins (2026-03-26)**: Terminal sliver state override (Dead/Closing slices show correct state), getMyArtifacts() 5s dedup cache, listValidTags/listUserProjects session cache, "new conversation" warning (already working), weave run view switching (already fixed)
- **Jupyter AI integration (2026-03-26)**: Added `jupyter-ai` package to requirements.txt and tool installer. JupyterLab startup auto-configures `OPENAI_API_KEY`/`OPENAI_BASE_URL` from FABRIC AI settings. Multi-provider support (FABRIC + NRP + custom). FABRIC system prompt patched into Jupyternaut. Skills and agents copied to `~/.jupyter/fabric_context/`.
- **AI assistant features (2026-03-26)**: Multi-conversation chat (create, switch, rename, delete conversations with localStorage persistence). LLM connection health test button with latency display + `POST /api/ai/models/test` endpoint + `POST /api/ai/models/refresh` force-refresh. Tool execution queue with numbered steps and mutating-tool highlighting. Streaming tool progress summaries (one-line result descriptions in tool card headers).
- **Phase 1 — Polish & Stabilize (2026-03-27)**: Settings view redesigned (two-panel sectioned layout, 9 sections, responsive). Settings validation with live Test buttons (`POST /api/settings/test/{name}`, Test All). UIS query caching (10-min TTL via FabricCallManager). Help docs updated (21 new entries for FABRIC/Chameleon views, AI assistant, CLI). Tour steps updated (FABRIC/Chameleon views, 6 AI tools, multi-conversation). README updated (17 features, 7 AI tools). CONTRIBUTING.md created.
- **Phase 2 — Infrastructure Map + AI Tool Maturity (2026-03-27)**: Live load indicators on map (color-coded markers, link thickness, tooltips, legend, 2-min auto-refresh). Auto AI config propagation on settings save. Uniform FABRIC/NRP access verified + OpenCode bug fix. Crush/Deep Agents in ai-eval. 30 new seeding tests. Custom FABlib branch support (Dockerfile ARG + runtime override).
- **Phase 4a — Chameleon Foundation Layer (2026-03-27)**: Unified `TestbedViewShell` component with `TestbedTheme` prop and CSS custom properties. Both InfrastructureView and ChameleonView refactored to use shared shell. Lease selector dropdown added to ChameleonView toolbar. SSH key management bug fixed (fallback to FABRIC key). ~130 lines of duplicate CSS removed.
- **Phase 4c — Chameleon Scheduling (2026-03-27)**: Chameleon calendar endpoint + ChameleonCalendar component (14-day timeline, lease bars, green theme). Find-available wired into calendar finder with "Reserve at that time" button.
- **Phase 4f — Final Chameleon Items (2026-03-27)**: L2 Stitch with VLAN negotiation (`POST /api/chameleon/negotiate-vlan`). Composite submit (`POST /api/slices/{name}/submit-composite`) with parallel FABRIC+Chameleon provisioning via asyncio.gather. Chameleon networks + floating IPs as editor topology elements. Trovi already implemented (discovered existing backend + frontend).
- **Phase 4e — Cross-Testbed Integration (2026-03-27)**: Chameleon nodes in Composite Slice editor (FABnet v4). Server-side graph merge via `build_chameleon_slice_node_elements()`. EditorPanel gated by `chameleonEnabled` prop (Composite Slice only, not FABRIC view). ChameleonNodeForm with site/type/image/connection dropdowns. SliverComboBox Chameleon group.
- **Phase 4d — Chameleon Topology Editor (2026-03-27)**: 11 new draft management endpoints. ChameleonEditor component with Draft → Lease → Deploy workflow, CytoscapeGraph integration, add node/network forms, deploy controls. `build_chameleon_draft_graph()` in graph_builder.py.
- **Phase 4b — Chameleon Full Editor (2026-03-27)**: 8 new backend endpoints (instance reboot/stop/start, disassociate-ip, network CRUD, node-types/detail). Server management buttons on instance cards. Networks tab. ChameleonTableView (sort, filter, bulk delete, context menu). Map instance markers. Lease extend/delete. Browse hardware specs. Create Lease dropdown with hardware specs.
- **Phase 8 — Production Readiness (2026-03-27)**: Future reservation & auto-execution (reservation_manager.py, background checker, schedule UI in ResourceCalendar). Staging environment (docker-compose.staging.yml). Detailed health monitoring (`GET /api/health/detailed` with subsystem checks).
- **Phase 7 — Testing Foundation (2026-03-27)**: CI/CD pipeline (`.github/workflows/test.yml`). pytest-cov (33% coverage). 20 Vitest frontend unit tests. 12 new WS/SSE backend tests. 4 LLM E2E round-trip tests. Total: 439 backend + 20 frontend unit + 6 Playwright E2E.
- **Phase 5 — FABRIC Resource Scheduling + AI Tool Cleanup (2026-03-27)**: Resource calendar (timeline visualization + `GET /api/schedule/calendar`), next-available finder (`GET /api/schedule/next-available`), alternative suggestions (`GET /api/schedule/alternatives`). Calendar tab in FABRIC view. `lease_end` added to slice summaries. AI preamble OpenCode MCP note. Feature propagation process doc. 30 new tests.

- **Login button & auto-setup (2026-03-30)**: One-click Login button in TitleBar and LandingView. CM OAuth popup with token polling. `POST /api/config/auto-setup` endpoint: project selection, bastion key generation (Core API), slice key generation, FABRIC LLM API key creation (CM Bearer token auth). Token expiration detection with "Re-login" UI. Multi-project picker modal. User avatar pill in TitleBar.

- **Kubernetes multi-user deployment (2026-04-30)**: Full Helm chart for K8s deployment with Hub (CILogon OIDC auth + pod spawning), Configurable HTTP Proxy (CHP), and per-user pods with persistent storage. Key features:
  - Hub: CILogon OIDC with PKCE, FABRIC Core API role verification, CM token provisioning, pod lifecycle management, idle culling, admin dashboard
  - Sub-path routing: `LOOMAI_BASE_PATH` env var, `assetUrl()` utility for static assets, dynamic nginx config generation in entrypoint.sh
  - JupyterLab: Dynamic `base_url` includes CHP sub-path for correct redirects
  - AI tools: Nginx reverse proxy for Aider (9197), OpenCode (9198), web tunnels (9100-9199)
  - Logout: Stops user pod, removes CHP route, clears session (K8s mode only)
  - Stale pod handling: Delete + recreate on 409 conflict during spawn
  - Error pages: User-friendly HTML for CHP 503/500/404 with auto-refresh
  - Tool install locks: Unconditional cleanup on startup (fixes PID reuse across container restarts)
  - Tunnel security: Port-restricted regex `(91[0-9][0-9])` prevents proxying to arbitrary ports
  - PVC: 5Gi recommended for AI tools (~900MB for JupyterLab alone)
  - Image builds: `docker buildx --platform linux/amd64` with versioned tags

## In Progress

(None)

## Gaps & TODOs

### Testing
- ~~No CI/CD test pipeline~~ — Done (Phase 7). `.github/workflows/test.yml` with backend pytest + frontend build/test.
- ~~No test coverage reporting~~ — Done (Phase 7). `pytest-cov` with XML + terminal reports, 33% overall.
- ~~No frontend unit tests~~ — Done (Phase 7). Vitest + @testing-library/react, 20 tests across 3 files.
- ~~Missing WebSocket/SSE/terminal tests~~ — Done (Phase 7). 12 new tests covering container/slice terminals, AI tool WS, chat SSE.
- ~~End-to-end LLM tests~~ — Done (Phase 7). 4 round-trip tests gated behind `@pytest.mark.llm`.
- **Composite slice + base slice test expansion** — The current composite test suite (`tests/integration/test_composite.py`) has 28 tests covering CRUD, members, graph merge, submit, migration, and Chameleon interface rendering. Expand with:
  - **Backend API tests**:
    - Composite member validation with real FABRIC draft slices (create draft → add to composite → verify graph includes it)
    - Cross-connection CRUD (add, list, remove cross-connections, verify graph edges)
    - Replace-fabric-member endpoint (simulate draft → submitted UUID change)
    - Composite submit with mock FABRIC + Chameleon members
    - Per-node interfaces endpoint (update interfaces, verify graph renders correctly)
    - FABNetv4 route configuration (set custom routes via L3 config, verify `auto_configure_networks` reads them)
    - Draft slice fetch by draft ID (the bug we just fixed — ensure `GET /slices/draft-xxx` returns data)
  - **Frontend unit tests** (Vitest):
    - CompositeEditorPanel: render with mock props, test tab switching, member toggle calls API
    - CompositeEditorPanel FABRIC tab: select member → EditorPanel renders with sliceData
    - CompositeEditorPanel Chameleon tab: select member → ChameleonEditor renders in formsOnly mode
    - ChameleonEditor Servers tab: dual-NIC dropdowns render, network selection calls `updateChameleonNodeInterfaces`
    - ChameleonEditor Leases tab: lease checklist renders, toggle calls `addChameleonSliceResource`/`removeChameleonSliceResource`
  - **Playwright E2E tests**:
    - Composite flow: create composite → add FABRIC member → add Chameleon member → verify topology shows both → submit
    - Chameleon flow: create slice → add node → select network for NIC → verify topology shows NIC + network
    - Cross-view sync: edit FABRIC slice in composite editor → switch to FABRIC view → verify changes visible

- **Known bugs — composite slice submit + refresh issues (user-reported 2026-03-31)** — During a composite slice E2E test (create composite → add FABRIC + Chameleon slice → submit), the following issues were observed:
  - **FABRIC slice visibility during Configuring**: After composite submit, the FABRIC slice disappears from the composite topology during the "Configuring" state. User had to manually thrash between FABRIC view and composite view, refreshing multiple times, before the slice became visible again. The root cause is that: (1) the draft is popped from memory on submit, (2) the submitted slice may not be in the call manager cache yet, (3) the composite graph endpoint's live-fetch fallback (`await get_slice(name, max_age=30)`) may fail or be slow during initial provisioning. **Needs investigation**: why does the live-fetch fallback not work consistently? Is there a race condition between the FABRIC submit and the composite graph refresh?
  - **Chameleon slice: lease created but VM never started**: The composite submit calls `deploy_draft()` which creates Blazar leases but does NOT launch Nova instances. The `deploy_draft` endpoint is a "lease-only" operation — instance creation happens in the frontend's `handleDeployChameleonLease` flow (App.tsx lines 1600-1650) which waits for leases to become ACTIVE, gets reservation IDs, and THEN calls `createChameleonInstance` per node. The composite backend submit only calls `deploy_draft`, so instances are never created. **Fix needed**: either (a) make `deploy_draft` also launch instances (auto-deploy mode), or (b) have the composite submit use the full frontend deploy flow, or (c) add a backend endpoint that does the full deploy (lease + wait + instances) in one call.
  - **Auto-refresh not working reliably**: The composite topology should auto-update when member slices change state, but the user had to manually refresh. The composite auto-refresh polls every 30s comparing member state signatures — but this only works when the composite view is active (the polling effect checks `currentView === 'slices'`). If the user is on the FABRIC view, the composite doesn't poll. When they switch back, the tab-switch effect should trigger a refresh, but it may be hitting the same cache/draft issues.

- **Deep E2E test suite for composite + base slice workflows** — The WebUI needs comprehensive end-to-end tests that simulate real user clicks through the full workflow. Current Playwright tests are minimal (6 tests). A deep E2E suite should cover:
  - **FABRIC view E2E**:
    - Create new slice → add node → add component → add network → verify topology shows all elements
    - Submit slice → verify state transitions (Configuring → StableOK) → verify polling updates
    - Open SSH terminal on provisioned node → verify connection
    - Run boot config → verify Console shows progress
    - Delete slice → verify cleanup
  - **Chameleon view E2E**:
    - Create Chameleon slice → add node → select network for each NIC → verify topology
    - Check lease in Leases tab → verify it appears with checkbox
    - Submit → verify lease creation → wait for ACTIVE → verify instances launched
    - Verify SSH terminal on ACTIVE instance
    - Delete slice → verify cleanup
  - **Composite view E2E**:
    - Create composite slice → create new FABRIC slice from composite editor → create new Chameleon slice from composite editor
    - Add both as members → verify composite topology shows both with bounding boxes
    - Edit FABRIC member inline in composite editor → verify topology updates
    - Edit Chameleon member inline → verify topology updates
    - Submit composite → verify BOTH FABRIC and Chameleon slices deploy (leases + instances)
    - Wait for both to become active → verify composite topology shows live state
    - Open SSH terminal from composite topology context menu → verify connection
    - Switch to FABRIC view → verify submitted slice visible and editable
    - Switch to Chameleon view → verify slice visible with deployed instances
    - Delete composite → verify member slices not deleted
  - **Cross-view sync E2E**:
    - Create FABRIC slice in FABRIC view → switch to composite → add it → verify appears
    - Edit FABRIC slice in FABRIC view (add node) → switch to composite → verify topology updated
    - Submit from composite → switch to FABRIC view → verify state change visible
    - Auto-refresh: enable auto on composite → submit from FABRIC view → wait → verify composite updates without manual refresh
  - **Error handling E2E**:
    - Submit with invalid configuration → verify error shown (not white screen)
    - Network assignment to non-existent network → verify error handling
    - Delete a member slice from testbed view while composite references it → verify graceful handling

### AI Chat Features
- (all items completed)

### AI Tool Configuration
- ~~**Automatic AI tool config propagation**~~ — Done (2026-03-27)
- ~~**Uniform FABRIC/NRP model access across all 6 tools**~~ — Done (2026-03-27)
- ~~**Include Crush and Deep Agents in `/ai-eval`**~~ — Done (2026-03-27)
- ~~**Clarify FABlib execution methods per tool**~~ — Done (preambles already per-tool; added OpenCode MCP note)
- ~~**Propagate new features to all 6 tool prompts**~~ — Done (process documented in `docs/FEATURE_PROPAGATION.md`)
- ~~**User-customizable AI agents & skills**~~ — Done (2026-04-02). CRUD API (`/api/ai/agents`, `/api/ai/skills`) with built-in + user-custom merge. Settings UI "Agents & Skills" section with inline editor, source badges, create/edit/delete/reset. Changes auto-propagate to all AI tools and invalidate chat cache.
- ~~**Crush/Deep Agents workspace seeding**~~ — Done (2026-03-27, 30 verification tests)
- ~~**Runtime validation**~~ — Done (2026-03-27, seeding tests cover file creation + config correctness)

### UI/UX
- ~~**FABRIC view — full slice editor and manager**~~ — Done. All sub-items complete: slice selector, topology editor, table, map, storage, apps, browse, facility ports, slices list, calendar, create slice, blue branding.
- ~~**FABRIC view — Map & Details enhancements**~~ — Done. Map shows selected slice nodes only when a slice is selected. Details promoted to full side panel with searchable resource dropdown (Sites + Links optgroups). Map clicks sync to Details panel.
- ~~**FABRIC view — Rename "Table" to "Slices" and move to first tab**~~ — Done. "Slices" is the default/leftmost tab.
- ~~**FABRIC view — Action buttons and auto-refresh**~~ — Done. New/Submit/Delete buttons + auto-refresh toggle in FABRIC bar. Stable topology refresh with `preserveLayout` — diffs elements by ID, updates data in-place, skips re-layout.
- ~~**FABRIC view — Editor panel tab renaming**~~ — Done. FABRIC view shows "Slice"/"Slivers" tabs; Composite Slice view shows "Experiment"/"FABRIC"/"Chameleon" via `viewContext` prop.
- ~~**Composite Slice view — cross-testbed editor**~~ — Done. Cross-testbed topology (FABnet v4 + L2 Stitch), parallel provisioning, editor tab restructure (Experiment/FABRIC/Chameleon), unified graph.
- ~~**Settings view redesign — sectioned navigation**~~ — Done (2026-03-27)
- ~~**Settings validation — live "Test" buttons**~~ — Done (2026-03-27)
- ~~**Infrastructure map — live load indicators**~~ — Done (2026-03-27)

- ~~**Settings — per-view enable/disable toggles**~~ — Done (2026-03-30). `views.composite_enabled` in settings.json (default `false`). `GET /api/views/status` endpoint. TitleBar filters with `requiresComposite`. ConfigureView: "Enable Composite Slices View" checkbox in Chameleon section. Chameleon already gated by `chameleon.enabled`. FABRIC always visible. Only FABRIC shown on first launch.

- ~~**FABRIC view — Run/rerun post-boot config**~~ — Done. Right-click VM → "Run Boot Config" context menu (CytoscapeGraph), right-click slice → "Run Boot Config (All)", "Run Boot Config" button in EditorPanel, per-node `run-boot-config-node` action. Progress streams to Console. Full pipeline: `post_boot_config` → `auto_configure_networks` → execute user boot commands.

- ~~**FABRIC view — Post-boot config not executing on submit (bug)**~~ — Done. Frontend auto-triggers boot config pipeline when slice reaches StableOK: polling detects transition (App.tsx:890), submit handler checks immediate StableOK (App.tsx:1183), and newly-stable slices trigger via `bootConfigRanRef` guard.

- ~~**FABRIC view — FABNetv4 networks not auto-configured (bug)**~~ — Done. `POST /slices/{name}/auto-configure-networks` endpoint (slices.py:2155) reads FABlib-assigned IPs and runs `ip addr add`/`ip route add` on each VM. Called automatically in boot pipeline after `post_boot_config()`.

- ~~**FABRIC view — Rename "Per-Interface Octets" to "Interface Config"**~~ — Done. Section labeled "Interface Config" (EditorPanel:3182) with per-interface IP/prefix/gateway form fields.

- ~~**FABRIC view — FABNetv4 route configuration**~~ — Done (2026-04-02). "Route Configuration" section in EditorPanel Interface Config: radio buttons for "Default FABNet Subnet" vs "Custom Subnets", editable route list with add/remove, default `10.128.0.0/10`. Backend `L3ConfigRequest` stores `route_mode` + `custom_routes`; `auto_configure_networks` reads configured routes and runs `ip route add` per subnet.

- ~~**FABRIC view — Facility ports and cross-testbed services in Slivers tab**~~ — Done. Facility ports in SliverComboBox, FacilityPortForm for add, FacilityPortReadOnlyView for detail, add/remove from both Experiment and Slivers tabs (EditorPanel:405-451).

- ~~**Side panel collapse controls interfere with center panel**~~ — Done (2026-03-30). Converted `position: absolute` tabs to flex rail layout (`.collapsed-tab-rail`). Collapsed panel buttons now render as proper flex items in left/right grid columns instead of overlapping center content. Removed compensating padding from center column.

- ~~**Chameleon view — mirror FABRIC view look, feel, and patterns with Chameleon branding**~~ — Done. Same layout/patterns as FABRIC view with green #39B54A Chameleon branding:
  - **Leases tab as default entry point** — Rename/reposition the Leases tab as the leftmost default tab (like FABRIC's Slices tab). This is where users pick or create a lease before editing.
  - **Lease selector dropdown** — Add a lease selector to the Chameleon bar (like FABRIC's slice selector). Show active/pending leases grouped by status.
  - **Action buttons** — Add "New Lease", "Deploy", and "Delete" buttons to the Chameleon bar (like FABRIC's New/Submit/Delete).
  - **Auto-refresh toggle** — Add auto-refresh for lease and instance state polling (like FABRIC's auto-refresh). Update instance statuses in-place without re-layout.
  - **Editor panel for Chameleon** — The editor side panel should show lease metadata on a "Lease" tab and instance/network editing on a "Resources" tab (like FABRIC's Slice/Slivers tabs).
  - **Resources tab** — Combine the Browse and any resource browsing into a unified Resources tab with sub-category selector (like FABRIC's Sites & Hosts / Facility Ports pattern): Node Types, Images, Networks.
  - **Map with lease overlay** — Show selected lease's instances on the map (already partially done). Add layer toggles for Chameleon sites vs instances.
  - **Details side panel** — Promote details to a full side panel with searchable resource dropdown (sites, node types, instances).
  - **Stable topology on refresh** — When auto-refresh updates instance data, preserve graph element positions (like FABRIC's preserveLayout).
  - **Archive/clear terminal leases** — Individual and bulk archive for terminated/expired leases.
- **Chameleon view — Topology, editor, table, and OpenStack improvements**:
  - ~~**Topology: right-click SSH terminal**~~ — Done. CytoscapeGraph context menu dispatches `chi-ssh` for ACTIVE Chameleon instances with IPs.
  - ~~**Topology: live instance state after deploy**~~ — Done. Backend `get_draft_graph` overlays live Nova instance status. Auto-refresh (30s) picks up state changes.
  - ~~**Topology: refresh button and auto-refresh**~~ — Done. ChameleonEditor `autoRefresh` prop wired to Chameleon bar toggle. Refreshes graph every 30s.
  - ~~**Live topology updates on node add**~~ — Done. `handleAddNode` calls `refreshGraph(draft.id)` immediately after API call.
  - ~~**Chameleon network model (revised)**~~ — Done (2026-04-02). Multi-NIC per-interface network selection implemented. Data model: `interfaces: [{nic: 0, network: {id, name}}, ...]` in chameleon.ts. ChameleonEditor renders one network dropdown per NIC. Backend `update_draft_node_interfaces` endpoint stores per-NIC assignments. Deploy passes all network UUIDs to Nova create. Default: NIC 0 on sharednet1, NIC 1 unconnected.
  - ~~**Table view like FABRIC**~~ — Done. ChameleonSlicesView with expandable parent/child rows (drafts + leases as parents, nodes/networks/instances as children). Columns: Name, Site, Status, Nodes, Networks. Multi-select bulk delete, inline SSH buttons.
  - ~~**OpenStack tab**~~ — Done. ChameleonOpenStackView with 7 sub-tabs (Instances, Networks, Key Pairs, Leases, Images, Floating IPs, Security Groups). Search/filter per tab, independently scrollable.
  - ~~**OpenStack tab — full CRUD actions**~~ — Done. All 7 tabs have full CRUD: Instances (delete, reboot, stop/start, +FIP), Networks (create, delete), Leases (create, extend, import, delete), Key Pairs (create, import, delete), Floating IPs (allocate, associate, disassociate, release), Security Groups (create, delete, add/remove rules). Confirmation dialogs for destructive ops.
  - ~~**OpenStack tab — multi-select bulk operations**~~ — Done. Row checkboxes, select-all header checkbox, "N selected" indicator, bulk delete/release per tab with confirmation.
  - **Chameleon Slices (first-class LoomAI abstraction)** — A "slice" is a LoomAI concept (not a native Chameleon concept) that groups a set of Chameleon servers into a logical unit the user operates on together. This is the primary organizational concept for the Chameleon view, analogous to FABRIC slices.
    - **Core concept** — A slice is a named collection of Chameleon servers (instances), their networks, and associated reservations. A slice may span multiple Chameleon sites (multi-site) and may be backed by multiple Blazar reservations. Slices are persisted to `{STORAGE_DIR}/.loomai/chameleon_slices.json`.
    - **Rename "Table" tab → "Slices"** — The current "Table" tab becomes the "Slices" tab. Each slice is an expandable row in the table. Expanding a slice row reveals its member servers with status, site, image, IPs. Columns: Name, Sites, Status, Servers, Reservations.
    - **Topology tab** — Selecting a slice in the selector loads its member servers and networks into the Topology tab as a Cytoscape.js graph, clustered by site.
    - **Drafts become slices** — All new drafts are immediately a slice (in "draft" state). Creating a draft creates a slice. The Slices tab shows both draft slices and deployed slices. Draft slices have a "Draft" badge; deployed slices show "Active"/"Deployed".
    - **Editor panel: add/remove servers** — The editor panel allows:
      - **Add new servers** to a slice (specify site, node type, image, count). New servers put the slice into "draft mode" (has undeployed nodes).
      - **Add existing servers** to a slice — select from running Chameleon instances not currently in any slice.
      - **Remove servers from a slice** — removing a server from a slice only unassociates it (does NOT delete the server from Chameleon). The server becomes "unaffiliated" and can be added to another slice.
    - **Submit (deploy)** — When a slice has new/undeployed servers, clicking Submit deploys them. The user chooses:
      - **Existing reservation** — deploy onto an ACTIVE reservation already associated with the slice.
      - **New reservation** — create a new Blazar lease/reservation as part of the submit, then deploy instances once the reservation is ACTIVE.
      The slice tracks which reservation each server belongs to.
    - **Deploy log** — When a slice is submitted, a per-slice deploy log should appear in the Bottom Panel (Console) showing each step of the deployment process in real time:
      - Step-by-step progress: "Ensuring SSH keypair...", "Creating lease at CHI@TACC...", "Waiting for lease ACTIVE...", "Launching node1...", "Launching node2...", "Setting slice to Active..."
      - Each step shows success (green checkmark) or failure (red X with error message)
      - Timestamped entries so the user can see how long each step takes
      - Errors are preserved in the log even if the deploy continues (partial success)
      - The log tab persists after deploy completes so the user can review what happened
      - Pattern: similar to FABRIC weave build logs that stream to the Console panel via `### PROGRESS:` lines
    - **Delete slice** — Two options:
      - **Release servers** (default) — unassociate all servers from the slice. Servers continue running on Chameleon but are no longer grouped. Reservations are not affected.
      - **Delete servers** (optional, with confirmation) — delete all servers in the slice from Chameleon AND release the associated reservations if they have no other servers.
    - **Multiple reservations per slice** — A slice may accumulate multiple reservations over time (e.g., initial deploy + later additions). The editor panel should show a "Reservations" section listing all reservations associated with the slice, with actions:
      - **Extend** a reservation
      - **Delete** a reservation (with option to delete its servers or release them)
      - **Reuse** a reservation — when adding new servers, offer to deploy onto an existing ACTIVE reservation if it has capacity.
    - **Import from reservation** — Add all servers from a given Blazar reservation to an existing slice. Useful for adopting servers created outside LoomAI (e.g., via Chameleon GUI or CLI) into the slice management system.
    - **Slice selector** — The selector dropdown in the Chameleon bar lists all slices (both draft and deployed). Selecting a slice loads it into Topology, Slices (table), and Editor views.
    - **SSH terminals to Chameleon servers** — Any ACTIVE server in a slice should have an SSH terminal button (like FABRIC VM terminals in the Bottom Panel). Clicking it opens a WebSocket-backed terminal session to the server. Requirements:
      - **SSH key management** — LoomAI manages the SSH key pair used for Chameleon servers. On deploy, LoomAI registers a Nova key pair (or reuses an existing one) so the launched instances are accessible. The private key is stored in `{STORAGE_DIR}/fabric_config/` alongside FABRIC keys.
      - **Key injection on deploy** — When creating instances, LoomAI passes the managed key pair name to Nova so the public key is injected into the server's `authorized_keys`.
      - **Direct SSH via floating IP** — If the server has a floating IP, SSH connects directly to the floating IP using the managed private key.
      - **SSH via Chameleon bastion** — If no floating IP, SSH tunnels through the Chameleon site's bastion/gateway host (similar to FABRIC's bastion pattern). LoomAI must know each site's bastion address and configure ProxyJump accordingly.
      - **Terminal UI** — SSH terminals appear as tabs in the Bottom Panel (Console), labeled with the server name and site. Multiple terminals can be open simultaneously. Uses the same `TerminalPanel` / xterm.js infrastructure as FABRIC VM terminals.
      - **Context menu SSH** — Right-clicking a server in the Topology graph or Slices table offers "SSH" as a context menu action.
      - **CLI support** — `loomai chameleon ssh <slice> <server>` opens an SSH session from the CLI, using the managed key.
    - **Chameleon network access & remote configuration** — Chameleon bare-metal servers can be accessed directly from the internet but require floating IPs and properly configured security groups. LoomAI needs to investigate and automate the full chain so users can easily SSH and run remote configuration on their servers. Key areas:
      - **Floating IP auto-allocation** — On deploy, LoomAI should automatically allocate and associate a floating IP to each server that needs external access. The user should be able to opt-in/out per server (e.g., a checkbox in the editor "Assign floating IP"). The allocation uses Neutron's floating IP pool for the site.
      - **Security group configuration** — Chameleon networks have security groups that block traffic by default. LoomAI must ensure that SSH (port 22) is allowed inbound for servers the user wants to access. Investigate: what default security groups exist at each site? Do we need to create a custom "loomai-ssh" security group with port 22/TCP ingress? Should LoomAI also open ICMP (ping) and user-specified ports?
      - **Auto-configure on deploy** — When a slice is submitted, LoomAI should: (1) ensure a security group allowing SSH exists, (2) apply it to each server, (3) allocate + associate floating IPs for servers that need them, (4) wait for the server to become reachable (ping or SSH probe), (5) then mark the server as "ready" in the slice.
      - **Remote configuration (boot scripts)** — After SSH access is established, LoomAI should support running boot configuration scripts on Chameleon servers (similar to FABRIC boot config). This includes: uploading files, running shell commands, installing packages, configuring network interfaces. The boot config tab in the editor should work for Chameleon servers just as it does for FABRIC VMs.
      - **Readiness detection** — After deploy + floating IP + security group, poll each server to detect when SSH is actually reachable (not just Nova ACTIVE). Show a "Connecting..." → "Ready" status in the topology and editor. Only enable the SSH terminal button when the server is actually reachable.
      - **Investigation needed** — Document the exact Chameleon requirements per site: default security groups, floating IP pools, bastion hosts (if any), SSH usernames per image (cc for CentOS/Ubuntu, but may differ for other images), network topology (provider vs. tenant networks). This should be a reference document in `docs/` that the implementation can reference.
  - ~~**OpenStack tab — refresh button**~~ — Done. Manual refresh button + auto-refresh toggle (30s polling) for Instances and Leases tabs. Each tab re-fetches on activation.
  - ~~**Chameleon submit workflow (revised)**~~ — Done. All configuration in editor before submit: Leases tab for reservation config (new vs existing, duration), Servers tab for node/network config. One-click submit reads pre-configured settings. No popups.
  - ~~**Lease membership in editor Leases tab**~~ — Done. Leases tab shows all available leases with checkbox per lease. Toggling adds/removes from slice `resources` array. Immediate persist on toggle. Graph + Slices tab update on change. Multiple leases per slice supported.
  - ~~**Remove Leases tab from Chameleon bar**~~ — Done. Standalone Leases tab already removed; lease management in editor Leases tab.
  - ~~**Remove Resources tab**~~ — Done. Standalone Resources tab already removed; resource browsing via OpenStack sub-tabs and editor.
- ~~**Fix Chameleon instance creation — reservation hints**~~ — Done. `scheduler_hints: {"reservation": reservation_id}` passed in Nova create body (chameleon.py:754-757, 2973). Deploy workflow extracts reservation ID from lease and passes to each instance creation call.
- **Chameleon end-to-end integration tests** — Create a real Chameleon test suite that runs against the live Chameleon API (gated behind a flag like `--chameleon-tests`). Tests should verify the complete workflow:
  - **Lease lifecycle**: Create lease → wait for ACTIVE → extend → delete
  - **Instance lifecycle**: Create instance on a lease → wait for ACTIVE → verify SSH access → reboot → delete
  - **Network operations**: List networks, list shared networks, verify sharednet1 exists
  - **Node types**: Query available node types per site, verify counts
  - **Draft workflow**: Create draft → add nodes → add network → deploy as lease → create instances → SSH verify → cleanup
  - **Availability finder**: Query availability for a node type, verify response format
  - **Slice deploy + SSH readiness test**: Create a Chameleon slice → add a server → submit/deploy → wait for lease ACTIVE → wait for instance ACTIVE → SSH into the server via the WebSocket terminal endpoint → run a command (e.g., `hostname`) and verify output → cleanup. This is the critical end-to-end test that validates the full user workflow from slice creation to SSH access. Should test both floating IP and non-floating-IP scenarios. Should also verify that the `loomai-key` SSH keypair is injected and that the terminal connects successfully without manual key configuration.
  - Tests must clean up all resources after completion (delete instances, delete leases)
  - Tests require Chameleon credentials configured in settings (skip if not configured)
  - Add to CI as an optional job (like LLM tests with `@pytest.mark.chameleon`)
- ~~**Chameleon CLI commands**~~ — Done. 1,225 lines in `cli/loomai_cli/commands/chameleon.py`: sites, images, leases (list/create/extend/delete), instances (list/create/delete/reboot/stop/start), networks (list/create/delete), keypairs (list/create/delete), ips (list/allocate/associate/disassociate/release), security-groups (list/create/delete/add-rule/remove-rule), slices (list/create/delete/add-resource/remove-resource), drafts (list/create/delete/add-node/remove-node/add-network/remove-network/deploy). All support `--site` and JSON output.

### Caching/Performance
- ~~**Cache UIS project/user queries**~~ — Done (2026-03-27)

### Resource Scheduling & Future Reservations
- ~~**Resource availability calendar**~~ — Done (2026-03-27)
- ~~**Future reservation & auto-execution**~~ — Done (Phase 8). `reservation_manager.py` with JSON persistence, background checker (60s), auto-submit. Frontend: schedule section in ResourceCalendar.
- ~~**Next-available-time finder**~~ — Done (2026-03-27)
- ~~**Alternative resource suggestions**~~ — Done (2026-03-27)

### Infrastructure
- ~~**Custom FABlib branch support**~~ — Done (2026-03-27)
- ~~No staging environment~~ — Done (Phase 8). `docker-compose.staging.yml` with healthchecks, persistent volume, stable branch.
- ~~No health check monitoring~~ — Done (Phase 8). `GET /api/health/detailed` with subsystem checks (FABlib, storage, AI server, Chameleon, Jupyter, memory, disk).

### Chameleon Cloud — Next Steps
Core Chameleon integration is done (9 phases: backend, CLI, frontend types, settings UI, map, ChameleonView, AI tools, SSH, cross-testbed topology). Remaining work:

- ~~**Multi-site Chameleon drafts**~~ — Done (Phase M, 2026-03-29). Per-node site field required, draft-level site removed, deploy creates one lease per site concurrently, graph clusters by site, multi-site topology view.

- ~~**Chameleon SSH terminal verification & fixes**~~ — Done (Phase T, 2026-03-29). E2E tested at CHI@UC. Per-site SSH keys (`chameleon_key_{site}`). Floating IP via Neutron. SSH button in OpenStack Instances, Slices tab, and topology context menu. SSH shows for any ACTIVE instance with an IP. "+ FIP" button for manual floating IP assignment. `ensure_keypair` endpoint syncs keypair + private key. Auto-routable network selection (prefers sharednet1). Double-click deployed node → SSH terminal. Username `cc` for all Chameleon images. Two-hop SSH via bastion supported in terminal handler.
- ~~**Chameleon context menu parity**~~ — Done (Phase V, 2026-03-29). Right-click deployed Chameleon nodes: Recipes (matched by image), Run Boot Config, Open in Web Apps, Assign Floating IP. Same power as FABRIC context menu.
- ~~**Chameleon boot config**~~ — Done (Phase W, 2026-03-29). Storage at `.boot-config/chameleon/{slice_id}/{node_name}.json`. GET/PUT/POST execute endpoints. Paramiko SSH execution with SFTP uploads. Boot config panel in ChameleonEditor for deployed nodes.
- ~~**Auto-bastion**~~ — Done (Phase X, 2026-03-29). `ensure-bastion` endpoint creates dual-NIC bastion (sharednet1 + experiment net) with floating IP. Terminal handler supports two-hop SSH (bastion → worker). Deploy flow auto-creates bastion for nodes without FIP. Bastion lifecycle stored in slice data.
- ~~**Chameleon OpenStack cleanup**~~ — Done (Phase T, 2026-03-29). Removed redundant Leases/Resources tabs. Auto-refresh toggle (30s). Bulk operations (checkboxes, select-all, bulk delete). Dark mode fixes.
- ~~**Deploy flow hardening**~~ — Done (Phase Z, 2026-03-29). Auto-bastion in deploy, auto-boot-config after SSH ready, IP refresh to topology graph.
- ~~**Import from reservation**~~ — Done (Phase AB, 2026-03-29). Endpoint + "Import" button in OpenStack Leases tab.
- ~~**Slices table sync**~~ — Done (Phase AA, 2026-03-29). Click instance row → highlight in topology. `selectedInstanceId` prop.

- ~~**Chameleon topology feature parity**~~ — Done (Phase AF, 2026-03-29). Recipes in context menu (prop wired through ChameleonEditor → CytoscapeGraph). Save as VM Template. Archive terminated slices from selector. `chi-save-template` action type.
- ~~**Chameleon editor polish**~~ — Done (Phase AG, 2026-03-29). Clean detail labels for deployed instances (Name, Status, Site, Node Type, Image, IPs, Instance ID, SSH Ready). File uploads in boot config panel (source/dest with SFTP). Documentation updated (ARCHITECTURE.md Chameleon section, CLAUDE.md key files).

- ~~**Chameleon topology + Slices tab: feature parity with FABRIC**~~ — Done (Phases T/V/W/X/AA/AF/AG, 2026-03-29). Auto-refresh topology + Slices (30s polling via `chameleonAutoRefresh`). Right-click context menu: recipes (`chi-apply-recipe`), Run Boot Config (`chi-run-boot-config`), Open in Web Apps (`chi-open-web`), Save as VM Template (`chi-save-template`), Assign FIP (`chi-assign-fip`). Click-to-select syncs topology ↔ Slices table (`selectedInstanceId`). SSH inline in Slices table rows. Double-click deployed node → SSH terminal. Node labels show name, status, site, IPs.

- ~~**Chameleon Slices as first-class concept**~~ — Largely done. Backend: `chameleon_slices.json` persistent storage, CRUD endpoints (create/list/delete slices, add/remove resources), deploy endpoint with per-site lease creation. Frontend: ChameleonSlicesView with expandable table, slice selector in Chameleon bar, deploy dialog with lease creation/availability/network selection, multi-site support. Remaining: multi-reservation per-slice UI for managing multiple leases on one slice.

- ~~**LoomAI auto-bastion for Chameleon SSH**~~ — Done (Phase X, 2026-03-29). See auto-bastion entry above.

- ~~**Filterable server type and image selectors in Chameleon editor**~~ — Done. Custom `ChameleonNodeTypeComboBox` and `ChameleonImageComboBox` components with searchable text input, availability badges ("X avail / Y total"), "Available only" checkbox filter, architecture-filtered image list, and image size display. Components in `frontend/src/components/editor/`.

- ~~**Chameleon view — full-featured Chameleon interface**~~ — Done (Phases 4a/4b/4d). All sub-items complete including graphical topology editor with Draft → Lease → Deploy workflow.
  - ~~**Lease selector dropdown**~~ — Done (Phase 4a)
  - ~~**Server management**~~ — Done (reboot, stop, start, delete, floating IP associate/disassociate)
  - ~~**Network management**~~ — Done (list, create, delete networks with subnets)
  - ~~**Map viewer**~~ — Done (instance markers overlaid on sites, color-coded by status)
  - ~~**Lease management**~~ — Done (create, extend, delete with UI)
  - ~~**SSH terminal**~~ — Done (already implemented)
  - ~~**Table view**~~ — Done (ChameleonTableView with sort, filter, bulk delete, context menu)
  - ~~**Browse tab**~~ — Done (hardware specs: CPU, RAM, disk, GPU per node type)
  - ~~**Chameleon branding**~~ — Done (TestbedViewShell green theme)

- ~~**Unified testbed view architecture with per-testbed branding**~~ — Done (2026-03-27). `TestbedViewShell` component with `TestbedTheme` prop, CSS custom properties, light/dark logo support. Both views refactored.

- ~~**Create Lease UI**~~ — Done (Phase 4b, 2026-03-27). Enhanced with hardware specs in node type dropdown.

- ~~**Future reservations via calendar**~~ — Done (Phase 4c, 2026-03-27). `GET /api/chameleon/schedule/calendar` + ChameleonCalendar component with 14-day timeline.

- ~~**Next-available-time finder**~~ — Done (Phase 4c, 2026-03-27). Wired existing `findChameleonAvailability()` into calendar finder with "Reserve at that time" button.

- ~~**Slice editor: Chameleon nodes**~~ — Done (Phase 4e+4f). FABnet v4 + L2 Stitch with VLAN negotiation. Composite submit with parallel provisioning (FABRIC + Chameleon in parallel via asyncio.gather).

- ~~**All Chameleon resource types in editor**~~ — Done (Phase 4f). Chameleon networks, floating IPs as topology elements in the Chameleon tab.

- ~~**SSH key management**~~ — Done (2026-03-27). Fixed `get_chameleon_ssh_key()` fallback bug; verified terminal handler uses correct key.

### Trovi Marketplace Integration
- ~~**Trovi as a second artifact marketplace**~~ — Done (already implemented). Backend: `trovi.py` (175 lines). Frontend: "Chameleon Marketplace" tab in LibrariesView with search, browse, get. Source badges (green "Trovi"). API client functions: `listTroviArtifacts`, `downloadTroviArtifact`, `getTroviTags`.

### Documentation
- ~~**README update**~~ — Done: Features section updated with all 7 AI tools, CLI, caching, adaptive polling, performance, guided tours, monitoring, smart LLM management, dark/light mode
- ~~**CONTRIBUTING guide**~~ — Done: Created `CONTRIBUTING.md` with setup, project structure, code style, testing, PR guidelines, agent tools

---

## Future Work

### Test Coverage Improvement
- ~~**Increase backend coverage from 33% to 60%+**~~ — Done. Coverage: 35% → 58% (1,148 tests, up from 439). Added 709 new tests across 20+ test files. Key modules covered: Chameleon (85%), reservations (96%), monitoring (60%), run manager (76%), settings (full), graph builder (edge cases), slices (advanced), files, templates, experiments, tunnels, tool installer.

### Composite Cross-Testbed Slices (FABRIC + Chameleon)

**Core concept**: A composite slice is a **meta-slice** — a named collection of references to existing slices from other views (FABRIC slices, Chameleon slices, future NRP slices, etc.). The composite view does NOT have its own topology editor for adding nodes. Users create and manage individual slices in their respective testbed views (FABRIC view, Chameleon view), then compose them together in the Composite view for a unified cross-testbed experience.

- **Composite Slice View — unified multi-testbed UI** — The Composite Slice view aggregates slices from other views into a single cross-testbed view. It shows merged topology, map, and status but does not duplicate editing functionality.
  - **View-specific top bar** — Same pattern as FABRIC/Chameleon bars. Layout:
    - **Left: label** — "Composite Slices" text label with LoomAI icon.
    - **Center: tabs** — Six content tabs: **Slices** (table of composite slices, expandable to show member slices per testbed), **Topology** (unified Cytoscape.js graph merging all member slice topologies), **Storage** (shared/per-node storage across all member slices), **Map** (Leaflet map showing all member slice resources across all testbed sites), **Apps** (web apps running on any member slice node), **Calendar** (resource scheduling across testbeds).
    - **Right: action widgets** — Composite slice selector dropdown, **New** button (create new composite slice — opens a picker to select member slices from FABRIC/Chameleon), **Submit** button (deploy all un-deployed member slices in parallel), **Delete** button (remove composite slice — does NOT delete member slices, just the grouping), **Refresh** buttons, **Auto on/off** toggle.
  - **Consistent with FABRIC view** — Same visual patterns, tab behavior, action widget placement.
  - **Bulk delete in Slices tab** — The composite Slices tab should support selecting multiple composite slices and deleting them in bulk:
    - **Row checkboxes**: Each composite slice row has a checkbox. A "Select All" checkbox in the header selects/deselects all visible rows.
    - **Bulk action bar**: When 1+ rows are selected, show a floating action bar with "Delete N selected" button.
    - **Delete options**: Same as single delete — "Remove grouping only" (default, member slices untouched) or "Delete all member slices too" (with confirmation listing all affected FABRIC + Chameleon slices).
    - **Confirmation dialog**: Lists all selected composite slices and their member counts before proceeding.
    - **Progress**: Show per-composite progress during bulk delete (success/failure for each).
  - **Provider-agnostic** — Not hardcoded to FABRIC + Chameleon. Adding a new provider means its slices become selectable as composite members.
  - ~~**LoomAI branding for composite bar**~~ — Done. Replaced indigo (`#312e81` → `#6366F1`) with LoomAI brand colors (`#1c2e4a` → `#27aae1`). Updated COMPOSITE_THEME, .composite-bar CSS, CompositeEditorPanel, Slices tab badges, CytoscapeGraph composite-shared-network style.

- **Composite slice as meta-slice** — A composite slice is defined entirely by its references to member slices from other views. It has no resources of its own.
  - **Data model**: `{ id, name, created, fabric_slices: [slice_id, ...], chameleon_slices: [slice_id, ...], cross_connections: [...] }`
  - **Creating a composite slice**: User clicks "New" → names the composite → picks one or more FABRIC slices and/or Chameleon slices from dropdown/checklist pickers (showing name, state, site, node count). The picker shows all available slices from each testbed view.
  - **Cross-testbed connections**: The composite view can define cross-testbed connections between member slices (FABnet v4, L2 Stitch). These are overlay connections that link nodes from different testbed slices.
  - **Storage**: `{STORAGE_DIR}/.loomai/composite_slices.json` — references only, not resource data.
  - **Lifecycle**:
    1. **New** — name the composite, select member slices
    2. **Edit** — manage membership, edit member slices inline, define cross-connections
    3. **Submit** — The Submit button in the composite view submits ALL member slices that are in the composite. For each member: FABRIC slices are submitted via FABlib, Chameleon slices are deployed via the Chameleon deploy flow. All submissions run in parallel via `asyncio.gather`. Already-deployed/active members are skipped. The user clicks one button and all testbed resources across all member slices are provisioned.
    4. **Operational** — unified topology, SSH to any node, monitoring across all members
    5. **Delete composite** — removes the composite grouping only. Member slices remain in their testbed views untouched. Optional: "Delete All" to also delete all member slices from their testbeds (with confirmation).

- ~~**Composite editor panel — three tabs for editing**~~ — Done. CompositeEditorPanel with Composite/FABRIC/Chameleon tabs. Tab 1 (Composite): member slice pickers with checkboxes for FABRIC + Chameleon slices, status summary. Tab 2 (FABRIC): embeds EditorPanel with selected FABRIC member's sliceData for inline editing. Tab 3 (Chameleon): embeds ChameleonEditor in `formsOnly` mode for inline Chameleon member editing. Bidirectional sync — edits in composite reflect in native views and vice versa.

- **Per-provider slice isolation** — Each view has fully independent slice state:
  - **FABRIC view**: `fabricSlices`, `selectedFabricSliceId`, `fabricSliceData`
  - **Chameleon view**: `chameleonSlices`, `selectedChameleonSliceId`, `chameleonSliceData` — already separate
  - **Composite view**: `compositeSlices`, `selectedCompositeSliceId` — references to member slices, merged graph built on demand
  - The composite view does NOT own any slice data. It reads member slice data from FABRIC and Chameleon state and merges it for display.

- **Merged topology and graph — full feature parity with base views** — The composite topology must show all the same graph elements and support all the same interactions as the FABRIC and Chameleon views. Currently missing: components, networks, slice grouping boxes. The composite topology is NOT a simplified summary — it is the union of all member slice topologies rendered with full fidelity.
  - **Graph merge**: Backend endpoint `GET /api/composite/slices/{id}/graph` fetches each member slice's graph and merges them into one Cytoscape.js graph. All element types are preserved: nodes, components (NICs, GPUs, storage), network services, interfaces, edges.
  - **Slice grouping boxes**: Each member slice is rendered as a compound/parent node (bounding box) in the graph. FABRIC member slices get a blue bounding box labeled with the slice name. Chameleon member slices get a green bounding box. All nodes from a member slice are children of their slice's bounding box. This visually groups nodes by their base slice.
  - **Components visible**: FABRIC node components (NICs, GPUs, SmartNICs, storage) must appear in the composite topology exactly as they do in the FABRIC view — as child nodes of their parent VM with the same icons and labels.
  - **Network links visible**: All network services (L2Bridge, L2STS, L2PTP, FABNetv4, FABNetv6) and their edges to node interfaces must appear in the composite topology. Networks render as diamond-shaped nodes with edges to connected interfaces, matching the FABRIC view stylesheet.
  - **Shared FABNetv4 network**: When both FABRIC and Chameleon nodes are connected to FABNetv4, there is ONE FABNetv4 network node in the composite topology. Both FABRIC node interfaces and Chameleon node interfaces connect to this single shared network node. This visually shows the cross-testbed L3 connectivity — FABRIC VMs and Chameleon servers all connected to the same internet. The graph merge must deduplicate FABNetv4 (match by network type, not by ID) and attach edges from both testbeds to the single node.
  - **Chameleon networks visible**: Chameleon networks (sharednet1, experiment nets, fabnetv4) appear as network nodes with edges to connected Chameleon server interfaces. Same green styling as in the Chameleon view.
  - **Testbed badges**: Nodes retain `[FAB]` (blue) or `[CHI]` (green) badges. Networks shared across testbeds (FABNetv4) get a special `[SHARED]` (indigo) badge.
  - **Map merge**: Leaflet map shows all member slice nodes at their respective testbed sites. Nodes from different member slices at the same site are visually grouped.
  - **Status aggregation**: Composite slice status derived from member statuses (all StableOK/Active → "Active", any transitioning → "Provisioning", any error → "Degraded").
  - **Auto-refresh**: Composite topology updates automatically when any member slice state changes in FABRIC or Chameleon views. No manual refresh needed.

- **Inherited context menu and interactions — full parity** — Every node, component, and network in the composite topology inherits ALL the capabilities it has in its base view. The composite view does not strip functionality — it composes it.
  - **Right-click context menu**: Right-clicking any element shows the same context menu actions as in its base view:
    - **FABRIC nodes**: SSH terminal, Run Boot Config, Run Boot Config (All), Recipes (matched by image), Open in Web Apps, Save as VM Template
    - **Chameleon nodes**: SSH terminal, Run Boot Config, Recipes, Open in Web Apps, Assign Floating IP, Save as VM Template
    - **Networks**: Show connected nodes, network details
    - **Components**: Component details, interface configuration
  - **Double-click**: Double-clicking a deployed node opens an SSH terminal (same behavior as base views).
  - **Click-to-select**: Clicking a node selects it and shows its details in the DetailPanel. The DetailPanel shows full node info including testbed badge, IPs, state, components.
  - **Drag and layout**: Nodes are draggable. Layout algorithms apply across the full composite graph. `preserveLayout` works for stable updates during auto-refresh.

- **Cross-testbed connectivity — shared FABNetv4 visualization** — Defined at the composite level. The composite topology must visually show that FABRIC and Chameleon nodes on FABNetv4 are connected to the same global network.
  - **Single global FABNetv4 Internet node**: One "FABRIC Internet (FABNetv4)" cloud node in the composite graph. This is the shared L3 network that both testbeds connect to.
  - **FABRIC side**: FABRIC nodes with FABNetv4 interfaces connect to their FABRIC FABNetv4 network node, which connects to the global internet node (existing pattern from `build_graph()`).
  - **Chameleon side**: Chameleon nodes with fabnetv4 interfaces connect to their local site-scoped fabnetv4 network node (e.g., "fabnetv4 @ CHI@TACC"), which connects to the same global internet node. This shows the path: Chameleon node → local fabnetv4 → global FABRIC Internet.
  - **Visible cross-testbed link**: The result is that FABRIC VMs and Chameleon servers are visually connected through the shared global FABNetv4 Internet node — making the cross-testbed L3 connectivity obvious at a glance.
  - **Graph merge deduplication**: `build_composite_graph()` already deduplicates FABNetv4 internet nodes from multiple FABRIC members. It must also recognize Chameleon fabnetv4 network nodes and connect them to the shared internet node.
  - **L2 Stitch**: Dedicated L2 links via Chameleon facility ports with VLAN negotiation between specific FABRIC and Chameleon nodes. Rendered as dashed cross-testbed edges.

- **Unified operations across member slices** — The composite view provides a unified interface for operating on nodes from all member slices. Every operation available in a base view is available in the composite view for that node type.
  - **SSH terminals**: SSH to any node (FABRIC VM via bastion, Chameleon server via floating IP or auto-bastion). Terminal tabs labeled with node name + testbed badge.
  - **Boot config**: Run boot config on any node. Backend routes to FABlib SSH (FABRIC) or Paramiko SSH (Chameleon) based on node type.
  - **Recipes**: Execute recipes on any node. Backend detects testbed and uses appropriate SSH path. Recipe matching uses the node's image regardless of testbed.
  - **Context menu**: Full context menu for all node types — same actions as in the base view (see "Inherited context menu" above).
  - **Monitoring**: Merged metrics from all member slice nodes (node_exporter on both FABRIC VMs and Chameleon servers).

- **Experiment templates** — Save/load composite slice definitions as experiment templates (already implemented in Phase 9). Templates capture member slice references + cross-connections + variables.

### NRP/Nautilus Testbed Integration
- **NRP as a third testbed** — Integrate the National Research Platform (Nautilus/NRP) alongside FABRIC and Chameleon. NRP provides Kubernetes-based compute with GPU access. Key requirements:
  - NRP view with Kubernetes namespace/pod management
  - Pod topology editor (similar to Chameleon's Draft → Deploy)
  - GPU resource browsing per NRP cluster
  - Cross-testbed: NRP pods in the Composite Slice editor alongside FABRIC VMs and Chameleon bare-metal
  - NRP branding (purple/blue theme)
  - Backend: Kubernetes API client via `kubectl` or Python `kubernetes` library

### Experiment Templates Marketplace
- ~~**Cross-testbed experiment templates**~~ — Done (Phase 9). `experiment.json` format capturing FABRIC + Chameleon resources. Save/load experiment endpoints with variable substitution. "Save as Experiment" button in Composite Slice toolbar. Variable popup for parameterized loading. "Experiment" category in artifact system (purple badge). 28 new tests.

### Real-Time Collaboration
- **Multi-user editing** — Allow multiple users to view and edit the same slice simultaneously. Key requirements:
  - WebSocket-based presence (show who's viewing/editing)
  - Operational transform or CRDT for concurrent topology edits
  - Cursor/selection sharing in the graph editor
  - Chat sidebar for in-context discussion
  - Conflict resolution for simultaneous submit attempts
  - Per-user undo/redo stacks
  - Requires multi-user backend (currently single-user with optional user switching)

### Monitoring Dashboards
- **In-app Grafana-like metrics visualization** — Replace the current per-node metrics display with a full dashboard system. Key requirements:
  - Dashboard builder: users create custom dashboards with draggable metric panels
  - Panel types: time-series line chart, gauge, stat card, table, heatmap
  - Data sources: node_exporter (VM metrics), FABRIC public Prometheus (site metrics), Chameleon instance metrics
  - Pre-built dashboards: "Slice Overview" (all nodes CPU/RAM/network), "Site Comparison" (cross-site utilization), "Experiment Timeline" (resource usage over experiment duration)
  - Dashboard persistence (save/load from storage)
  - Dashboard sharing via artifact marketplace
  - Alert rules: notify when CPU > 90%, disk full, node unreachable
