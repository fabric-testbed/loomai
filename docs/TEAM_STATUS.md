# Team Status

## Current Goal

(None)

## Active Work

(No active work)

## Recently Verified (already working)

- **CH-Topo**: Graph refreshes on node add (line 505 in ChameleonEditor), SSH context menu dispatches `chi-ssh` for ACTIVE instances with IPs (CytoscapeGraph line 510)
- **CH-Deploy**: `auto_network_setup` endpoint creates `loomai-ssh` security group, waits for ACTIVE, allocates floating IPs. `ensure_bastion` creates dual-NIC bastion. Both called in deploy flow (App.tsx lines 1647-1700).
- **CH-Table**: ChameleonSlicesView has expandable rows with instance details, multi-select bulk delete, inline SSH buttons.

## Agent Hierarchy (2026-03-31)

### View Sub-leads (own their view end-to-end)
- `/fabric-view` — FABRIC View: InfrastructureView, slice editor, FABRIC bar, slice lifecycle
- `/chameleon-view` — Chameleon View: ChameleonView, ChameleonEditor, OpenStack, deploy workflow
- `/composite-view` — Composite View: cross-testbed topology, experiment templates, parallel provisioning

### Backend Hierarchy (organized by `/backend-lead`)
- `/backend-lead` — Coordinates backend sub-specialists, owns cross-cutting concerns
- `/backend-fabric` — FABlib, slices, resources, site resolver, monitoring
- `/backend-chameleon` — OpenStack APIs, chameleon_manager, deploy, Chameleon slices
- `/backend-core` — Caching, settings, AI, templates, terminals, file manager, schedule

### Delegation Flow
- View-scoped tasks → view sub-lead → they coordinate design + backend
- Backend-only tasks → `/backend-lead` → delegates to sub-specialist
- Cross-view tasks → `/lead` coordinates between view sub-leads
- Design → `/design` (UI) or `/cli-design` (CLI) first, then implementation

## Completed

- **Topology Refresh E2E Tests (2026-04-01):**
  - `topology-refresh.spec.ts`: 5 real E2E tests verifying "↻ Slices" button in each view
  - Test 1: FABRIC refresh updates state from Configuring→StableOK, verifies management_ip, right-click terminal available
  - Test 2: FABRIC refresh after external delete shows Dead/Closing
  - Test 3: Composite refresh updates member states and graph, verifies Active state + management_ip
  - Test 4: Composite refresh after FABRIC member deleted shows Degraded
  - Test 5: Right-click terminal works on StableOK node after refresh, opens terminal tab, verifies SSH via API

- **Chameleon Per-NIC Floating IP Selection (2026-04-01):**
  - **Data model**: `floating_ips` changed from `string[]` to `Array<string | {node_id, nic}>` with backward compat
  - **Backend**: `PUT /chameleon/drafts/{id}/floating-ips` accepts `{entries: [{node_id, nic}]}` (new) or `{node_ids: [...]}` (old). Validates one FIP per node.
  - **Backend**: `auto_network_setup` selects the OpenStack port at the specified NIC index instead of always using the first port
  - **Frontend**: NIC dropdown appears next to "Floating IP" checkbox when node has multiple NICs. Shows network name per NIC.
  - **Tests**: 9 mock tests in `test_chameleon_floating_ip.py` — port selection, data model parsing, one-FIP-per-node validation

- **Chameleon State Consistency Fix (2026-04-01):**
  - Deploy endpoint now sets state to "Deploying" (not "Active") when instances launched
  - auto_network_setup updates state to "Active" when all instances ACTIVE
  - Graph endpoint updates slice state when live instance statuses change
  - list_chameleon_slices endpoint returns computed real state from resource statuses
  - _compute_chameleon_real_state() in composite.py for member summaries
  - New E2E test: "Chameleon member state is consistent between Chameleon Slices section and Member Status"

- **Composite Topology Continuity E2E Test (2026-04-01):**
  - New test in `composite-provision.spec.ts`: "FABRIC member stays in composite topology throughout all state transitions"
  - Creates FABRIC draft + composite → submits → polls FABRIC state (Draft→Configuring→Nascent→StableOK)
  - At each state change: verifies the FABRIC node exists in the composite graph API AND that the Cytoscape container renders in the GUI
  - Logs all state transitions with timestamps for debugging
  - Success = node present at every checkpoint; failure = node missing at any point

- **CLI Composite Commands + Comprehensive CLI Test Suite (2026-04-01):**
  - **Composite CLI** (`composite.py`): 11 commands — list, show, create, delete, add-fabric, add-chameleon, remove-fabric, remove-chameleon, cross-connections, graph, submit. Registered in `main.py`.
  - **CLI test suite** (5 files, 133 tests): `test_cli_slices.py` (FABRIC), `test_cli_chameleon.py` (Chameleon), `test_cli_composite.py` (Composite), `test_cli_ai.py` (AI/LLM with FABRIC+NRP), `test_cli_config.py` (config, sites, SSH, weaves, artifacts). All 114 mock tests pass in <1s.
  - **Integration tests**: `--integration` flag enables real backend tests for each area.

- **Right-Click Terminal + Operational Tests (2026-04-01):**
  - **gui-helpers.ts**: Added `rightClickNodeInGraph()`, `openTerminalFromContextMenu()`, `hasTerminalTab()`, `execOnNode()`, `waitForSSHReady()`.
  - **fabric-provision.spec.ts**: 2 new tests — (1) right-click node → context menu → "Open Terminal" → verify terminal tab in bottom panel + verify node operational via backend SSH, (2) 2-node FABNetv4 slice → right-click terminal + backend ping test.

- **3-Tier FABRIC Test Matrix (2026-04-01):**
  - **Mock integration** (`test_fabric_provision_mock.py`): 11 tests — single/multi node CRUD, NIC+FABNetv4, graph output, state, delete. Runs in 2.5s, no credentials.
  - **Mock hardware** (`test_fabric_hardware_mock.py`): 19 tests — GPU/NVMe/FPGA/CX5/CX6/CX7 components, L2STS/L2PTP/FABNetv4 networks, cross-site topology, graph badge verification. Runs in 2.5s, no credentials.
  - **GUI hardware** (`fabric-hardware.spec.ts`): 18 tests — 9 topology rendering (no auth) + 9 real provisioning (E2E_FULL). Covers all hardware/network types.

- **FABRIC Provisioning E2E Tests (2026-04-01):**
  - **FABRIC backend** (`test_fabric_provision_e2e.py`): 7 tests — single-node submit+StableOK, multi-node with management IPs, NIC+FABNetv4 network, execute command on node (hostname/uname/ip), two-node FABNetv4 ping, delete after active, state transitions (Draft→Configuring→StableOK). `@pytest.mark.fabric`.
  - **FABRIC hardware** (`test_fabric_hardware_e2e.py`): 9 tests — multi-site FABNetv4 ping (explicit sites), L2STS cross-site ping (static IPs), L2PTP cross-site ping, GPU+Ollama LLM query, NVMe format+read/write, FPGA Xilinx PCI detection, ConnectX-5 FABNet ping, ConnectX-6 FABNet ping, ConnectX-7 BlueField FABNet ping. Sites configurable via env vars. `@pytest.mark.fabric`.
  - **FABRIC GUI** (`fabric-provision.spec.ts`): 5 tests — submit via GUI+StableOK, multi-node topology, StableOK badge in Slices tab, execute command on active node, delete active slice. `E2E_FULL=1`.
  - **pytest.ini**: Added `fabric` marker, excluded from default runs.

- **Real-Provisioning E2E Tests (2026-04-01):**
  - **Chameleon backend** (`test_chameleon_provision_e2e.py`): 3 tests — single-node deploy + ACTIVE wait, multi-node deploy, state transition verification. `@pytest.mark.chameleon`.
  - **Chameleon GUI** (`chameleon-provision.spec.ts`): 2 tests — deploy via GUI + verify topology, verify ACTIVE badges in Slices tab. `E2E_FULL=1`.
  - **Composite backend** (`test_composite_e2e.py`): 5 tests — FABRIC-only composite, Chameleon-only composite, state transitions (Draft→Provisioning→Active), cross-testbed ping (FABRIC FABNetv4 ↔ Chameleon FABNetv4), merged graph verification. `@pytest.mark.composite`.
  - **Composite GUI** (`composite-provision.spec.ts`): 3 tests — submit composite with FABRIC member, submit with FABRIC+Chameleon members + verify topology, state badge updates (Draft→Active). `E2E_FULL=1`.
  - **Shared helpers** (`gui-helpers.ts`): Added `isChameleonConfigured()`, `waitForChameleonSliceActive()`, `waitForCompositeActive()`, `deployChameleonDraftViaApi()`.
  - **pytest.ini**: Added `composite` marker, excluded from default runs.



- **Roadmap Completion (2026-03-31):**
  - **Composite LoomAI branding**: Replaced indigo/purple with LoomAI navy/cyan (`#1c2e4a` → `#27aae1`). Updated COMPOSITE_THEME, .composite-bar CSS, CompositeEditorPanel, Slices tab, CytoscapeGraph.
  - **Composite full embedded editors**: FABRIC tab with "Create New FABRIC Slice" button + member slice cards with click-to-navigate. Chameleon tab with "Create New Chameleon Slice" button + member cards. New slices auto-added to composite. `onSwitchToSlice` navigates to testbed view for full editing.
  - **Chameleon bar tabs**: Leases/Resources already removed (verified).
  - **FABNetv4 routes**: `auto_configure_networks` reads L3 config (route_mode/custom_routes). Frontend route editor already exists. Verified wiring.
  - **Graph builder crash fix**: Network emission now uses `_get_node_networks()` for `interfaces` array — previously only read legacy `network` field, causing Cytoscape "nonexistent target" crash.

- **Final Roadmap Items (2026-03-31):**
  - **Chameleon multi-interface**: Per-node `interfaces` array (2 NICs default). Backend: node creation initializes 2 interfaces, PUT endpoint to update all interfaces. Graph builder: `_get_node_networks()` helper reads interfaces/network/connection_type with backward compat. Frontend: 2 network dropdowns per node in Servers tab. Deploy: passes `network_ids` array for multi-NIC. 1 new test (dual NIC).
  - **FABNetv4 route configuration**: `auto_configure_networks` now reads L3 config `route_mode`/`custom_routes` instead of hardcoding `10.128.0.0/10`. Route editor UI already existed (radio buttons for Default/Custom + editable route list).
  - **Composite bulk delete**: Checkboxes + Select All + floating "Delete Selected" bar in composite Slices tab.
  - **Verified done on roadmap**: Chameleon topology SSH (context menu), live state (auto-refresh), refresh button, live node-add updates, OpenStack CRUD actions, OpenStack bulk ops, ChameleonSlicesView expandable rows, preserveLayout.

- **C6+C7 + CH Verify — Final Phases (2026-03-31):**
  - **C6 — Composite auto-refresh**: Polling effect polls `getCompositeSlice()` every 30s when composite selected + auto-refresh on. Detects member state changes by comparing serialized states. On change, refreshes `compositeGraph`.
  - **C7 — Cross-connection editor + backend**: `PUT /api/composite/slices/{id}/cross-connections` endpoint. CompositeEditorPanel shows cross-connections section with FABRIC↔Chameleon node connections, type badges, delete buttons. FABNetv4 note: all nodes on FABNetv4 are automatically connected via shared internet node.
  - **CH-Topo verified**: Graph refreshes on node add, SSH context menu handles Chameleon instances.
  - **CH-Deploy verified**: `auto_network_setup` + `ensure_bastion` already handle security groups, floating IPs, readiness.
  - **CH-Table verified**: ChameleonSlicesView has expandable rows with instance details.

- **Phases CH1-CH5 — Chameleon Submit, Topology, Network, Polish (2026-03-31):**
  - **CH1 — Submit workflow**: Leases tab in editor panel now shows reservation config (duration picker, server/site summary) before Submit. Submit button deploys directly (one-click, no popup) using `deployChiRef` pattern. Duration read from `chiLeaseDuration` App.tsx state.
  - **CH2 — Topology auto-refresh**: ChameleonEditor accepts `autoRefresh` prop. When enabled, graph refreshes every 30s to pick up live instance status (ACTIVE/BUILD/ERROR). Wired to `chameleonAutoRefresh` toggle in both graphOnly and formsOnly modes.
  - **CH3 — Per-node network in deploy**: Instance creation now reads `node.network.id` for per-node network assignment. Falls back to site-level network if no per-node assignment.
  - **CH4 — OpenStack refresh**: Added Refresh button + Auto toggle to ChameleonOpenStackView action bar. Refresh force-reloads data for active tab. Auto polls every 30s.
  - **CH5 — E2E tests**: Already existed (13 basic + 12 SSH tests in `tests/chameleon/`). Gated behind `@pytest.mark.chameleon`.

- **Chameleon Revised Network Model (2026-03-31):**
  - Per-node `network` field replaces slice-level `networks` array with `connected_nodes`. Each node stores `{"network": {"id": "uuid", "name": "sharednet1"}}` or `null`.
  - Backend: `PUT /api/chameleon/drafts/{id}/nodes/{node_id}/network` endpoint to update a node's network assignment. Node creation includes `network` field.
  - Graph builder: reads per-node `network` field for NIC → network edges. FABNetv4 detection checks `network.name` containing "fabnet" (with `connection_type` backward compat). Legacy `networks` array still supported for backward compat.
  - Frontend: network dropdown per node in ChameleonEditor Servers tab. Lists available Chameleon networks at node's site (from existing `existingNetworks` state). Shows name, shared badge, subnet CIDR. Calls `updateChameleonNodeNetwork()` on change, refreshes graph.
  - Type: `ChameleonDraftNode.network?: { id: string; name: string } | null` added to `chameleon.ts`.

- **Chameleon Node Network Interfaces (2026-03-31):**
  - `build_chameleon_slice_graph()` now emits NIC component badge nodes per server, attached via `parent_vm` field (same pattern as FABRIC VM components)
  - Per-interface edges: NIC → network (replaces old direct server → network edges)
  - FABNetv4 chain: server → [nic] → fabnetv4@site → FABRIC Internet (FABNetv4) cloud node
  - Site-scoped fabnetv4 network nodes (`chi-fabnetv4:{draft_id}:{site}`) with L3 styling
  - Global `fabnet-internet-v4` node (same ID as FABRIC uses — enables dedup in composite graph merge)
  - 4 new tests: NIC badges for connected networks, FABNetv4 chain, multi-interface nodes, no interfaces without networks
  - No frontend changes needed — existing `.component`, `.component-nic` styles and `positionComponentsAtVmEdge()` handle it

- **Phases C2-C5 — Composite Slice View UI (2026-03-31):**
  - **C2 — Slices tab + selector**: Expandable composite slice table with member details (FAB/CHI badges, state, node count). Composite selector fetches member summaries on selection. New/Delete/Submit wired to meta-slice API.
  - **C3 — Topology styles**: Cytoscape.js stylesheet for `composite-member` compound parent nodes (blue FABRIC bounding boxes, green Chameleon bounding boxes), `composite-shared-network` for shared FABNetv4 (indigo border). Dark mode variants.
  - **C4 — Context menu**: Composite-member bounding boxes excluded from context menu. All FABRIC/Chameleon node actions inherited automatically via `element_type` and `testbed` data fields (SSH, boot config, recipes, reboot, stop/start, FIP assignment).
  - **C5 — Three-tab composite editor**: New `CompositeEditorPanel` component with Composite/FABRIC/Chameleon tabs. Composite tab: member picker with FABRIC/Chameleon slice checklists, instant save via `updateCompositeMembers`, member status summary. FABRIC/Chameleon tabs: member slice listings with navigation guidance. EditorPanel for FABRIC-only view cleaned up (removed stale composite checks).

- **Phase C1 — Meta-Slice Data Model (2026-03-31):**
  - Rewrote `composite.py` from independent-resource model to meta-slice reference model
  - New data model: `{fabric_slices: [id,...], chameleon_slices: [id,...], cross_connections: [...]}`
  - 7 endpoints (down from 13): CRUD + `PUT /members` + merged graph + parallel submit
  - `build_composite_graph()` in graph_builder.py: merges member slice graphs with ID prefixing, compound parent bounding boxes, FABNetv4 dedup
  - `_prefix_graph_ids()` helper rewrites all Cytoscape.js element references
  - Migration: auto-converts old composite_slices.json format on load
  - Frontend: removed 7 old functions, added `updateCompositeMembers`, updated App.tsx handlers
  - 23 tests: CRUD (6), members (7), graph (2), submit (2), migration (2), graph builder (4)

- **Login Button & Auto-Setup (2026-03-30):**
  - **One-click login**: Login button in TitleBar and LandingView opens CM OAuth in a popup window. Main window polls `GET /api/config` every 2s for token arrival (detects new/refreshed tokens via `token_info.exp` comparison).
  - **Auto-setup endpoint**: `POST /api/config/auto-setup` — sets project, resolves bastion_username from UIS API, generates bastion SSH keys via Core API (`POST /sshkeys` with `keytype: bastion`), generates slice keys locally via paramiko, creates FABRIC LLM API key via CM (`POST /credmgr/tokens/create_llm` with Bearer token auth), saves settings + generates `fabric_rc` + `ssh_config`, resets FABlib.
  - **Token expiration**: TitleBar shows "Re-login" button, LandingView shows "Session Expired" card when `token_info.exp * 1000 < Date.now()`.
  - **Multi-project**: Project picker modal (`createPortal`, z-index 99999) after login for users with multiple FABRIC projects.
  - **User pill**: TitleBar shows avatar initial + email when authenticated.

- **Per-View Settings Toggles + Composite Slice Isolation (2026-03-30):**
  - **View toggles**: `views.composite_enabled` setting (default `false`). `GET /api/views/status` endpoint. TitleBar filters views with `requiresComposite`. Settings UI: "Enable Composite Slices View" checkbox in Chameleon section. Only FABRIC visible by default.
  - **Composite slice backend**: New `backend/app/routes/composite.py` with independent CRUD, graph, and submit endpoints.
  - **Composite slice frontend**: Independent state (`compositeSlices`, `selectedCompositeSliceId`, `compositeGraph`).

- **Roadmap Audit + 6 Remaining Items (2026-03-30):**
  - **Roadmap audit**: 8 items marked as done. Side panel collapse fix. Testbed badges. Cross-testbed monitoring. Chameleon E2E tests.

- **Composite Slice View — Full-Width Bar with LoomAI Branding (2026-03-30):**
  - **Full-width composite bar**: `.composite-bar` rendered above the grid (same pattern as FABRIC `.fabric-bar` and Chameleon `.chameleon-bar`). Indigo gradient background (`#312e81` → `#6366F1`) with white text, LoomAI icon, and "Composite Slices" title.
  - **6 tabs**: Slices (renamed from Table), Topology, Storage, Map, Apps, Calendar. Tab styling matches FABRIC/Chameleon bars (`.composite-bar-tab`).
  - **Inline action buttons**: Slice selector (`<select>` with Draft/Active/Past optgroups), + New, Submit, Delete, ↻ Slices, ↻ Resources, Auto ON/OFF — all styled as `.composite-bar-btn` (white-on-gradient, matching `.fabric-bar-action-btn`).
  - **Dark mode**: Darker indigo gradient (`#1e1b4b` → `#3730a3`).
  - **Auto-refresh pulse**: `.composite-bar-btn-active` with green pulse animation matching FABRIC's `.fabric-bar-action-active`.
  - Removed Toolbar component from composite view — replaced by bar-integrated controls.
  - `CompositeView.tsx` + `COMPOSITE_THEME` remain available for reuse.
  - **Provider-agnostic**: View not hardcoded to any testbed — adding providers requires only new editor tabs and submit logic.

- **Phase 9 — Experiment Templates Marketplace (2026-03-27):**
  - `experiment.json` format: FABRIC nodes/networks + Chameleon nodes/networks/floating_ips + cross-testbed connections + variables
  - Backend: `POST /api/experiments/save`, `POST /api/experiments/{name}/load` (with variable substitution), `GET /api/experiments/{name}/template`
  - Variable substitution: `${VAR_NAME}` replaced recursively in all string values
  - Artifact system: `experiment.json` → "experiment" category with `loomai:experiment` tag
  - Frontend: "Save as Experiment" button in Composite Slice toolbar (only when both FABRIC + Chameleon nodes exist)
  - Variable popup: modal for filling in template variables when loading
  - Purple "Experiment" badges on template cards in LibrariesPanel and LibrariesView
  - 28 new integration tests (1,176 total)

- **Test Coverage Improvement (2026-03-27):**
  - Coverage: 35% → 58% (1,148 tests, up from 439). 709 new tests across 20+ files.
  - Chameleon endpoints: 67 integration tests (85% coverage)
  - Reservation manager: 15 tests (96%), monitoring: 27 tests (60%), run manager: 23 tests (76%)
  - Settings manager: 44 unit tests, graph builder: 25 edge case tests
  - Slices advanced: 79 tests, config: 26 tests, AI assistant: 36 tests, Trovi: 16 tests
  - Files: 40 tests, templates: 28 tests, experiments: 30 tests, VM templates: 20 tests
  - Tunnel manager: 17 tests, tool installer: 22 tests, main startup: 26 tests

- **Phase 8 — Production Readiness (2026-03-27):**
  - **Future reservation & auto-execution**: `reservation_manager.py` with JSON persistence. 3 endpoints (create/list/delete). Background checker every 60s auto-submits due reservations. Frontend: "Schedule Submission" section in ResourceCalendar with slice picker, datetime, duration, reservation list.
  - **Staging environment**: `docker-compose.staging.yml` with healthchecks, persistent volume, stable FABlib branch, restart policies.
  - **Detailed health monitoring**: `GET /api/health/detailed` returns subsystem checks (FABlib, storage, AI server, Chameleon, Jupyter), uptime, version, memory, disk, slice counts.

- **Phase 7 — Testing Foundation (2026-03-27):**
  - **CI/CD pipeline**: `.github/workflows/test.yml` — backend pytest + coverage, frontend build + unit tests. Triggers on push/PR to main/chameleon. Coverage uploaded as artifact.
  - **Coverage reporting**: `pytest-cov` added. 33% overall coverage (site_resolver 94%, slice_registry 93%, call_manager 86%).
  - **Frontend unit tests**: Vitest + @testing-library/react. 20 tests across 3 files (AddSliverMenu, SliverComboBox, TestbedViewShell). CSS mocked, next/dynamic mocked.
  - **WebSocket/SSE tests**: 12 new tests — container terminal (connect + cleanup), slice terminal (no-IP error, SSH failure), AI tool WS (unknown tool, no key, claude accepted, status endpoint), AI assistant SSE (content-type, events, tool calls, empty messages).
  - **LLM E2E tests**: 4 new tests (model list, round-trip completion, system message, multi-turn) gated behind `@pytest.mark.llm`.
  - **Total**: 439 backend tests (up from 427), 20 frontend unit tests, 6 Playwright E2E tests.

- **Phase 4f — Final Chameleon Items (2026-03-27):**
  - **L2 Stitch**: Enabled L2 Stitch radio button. VLAN negotiation UI (FABRIC site selector, "Negotiate VLAN" button, result display, VLAN input). Backend `POST /api/chameleon/negotiate-vlan` queries FABRIC facility port VLANs + Chameleon used VLANs, returns common VLANs.
  - **Parallel provisioning**: `POST /api/slices/{name}/submit-composite` uses `asyncio.gather` to run FABRIC submit + Chameleon lease creation in parallel. Frontend calls composite endpoint when chameleon_nodes present.
  - **Chameleon resource types**: New addMode types `chameleon-network` and `chameleon-floating-ip` with forms in Chameleon tab. Network name + CIDR form. Floating IP node selector.
  - **Trovi**: Already fully implemented (discovered existing `trovi.py` backend + LibrariesView "Chameleon Marketplace" tab). Marked as done in roadmap.

- **Composite Slice Editor Tab Restructure (2026-03-27):**
  - Renamed "Slice" tab → "Experiment" (high-level config + cross-testbed services: facility ports, port mirrors)
  - Renamed "Slivers" tab → "FABRIC" (VMs, networks, components only)
  - New "Chameleon" tab (Chameleon bare-metal nodes only, green active styling)
  - AddSliverMenu: new `visibleTypes` prop filters menu per tab
  - SliverComboBox: new `tabFilter` prop filters dropdown per tab
  - Auto-switch tabs on graph click (VM→FABRIC, facility port→Experiment, Chameleon→Chameleon)
  - Guard: chameleon tab auto-switches to FABRIC when chameleon disabled

- **Phase 4e — Cross-Testbed Integration (2026-03-27):**
  - **Backend**: `build_chameleon_slice_node_elements()` in graph_builder.py. `build_graph()` merges Chameleon nodes into FABRIC graph. `_serialize()` injects `chameleon_nodes` from in-memory store (with cache bypass).
  - **Frontend**: EditorPanel accepts `chameleonEnabled`/`chameleonSites` props (gated: only truthy in Composite Slice view, undefined in FABRIC view). ChameleonNodeForm: site/node-type/image dropdowns, FABnet v4 connection type (L2 Stitch disabled "coming soon"). Selected Chameleon node read-only view with delete. SliverComboBox shows "Chameleon Nodes" group with green badges.
  - **Constraint enforced**: `chameleonEnabled={currentView === 'slices' ? chameleonEnabled : undefined}` in App.tsx.

- **Phase 4d — Chameleon Topology Editor (2026-03-27):**
  - **Backend**: 11 new draft management endpoints (create/list/get/delete drafts, add/remove nodes, add/remove networks, set floating IPs, get draft graph, deploy draft). In-memory draft storage. `build_chameleon_draft_graph()` in graph_builder.py.
  - **Frontend**: New `ChameleonEditor` component with 4 workflow states (empty → drafting → deploying → deployed). Split layout: CytoscapeGraph on left, editor panel on right. Add node form (node type + image dropdowns loaded from site APIs), add network form (multi-select connected nodes), floating IP toggles. Deploy controls (lease name, duration hours). Green-themed buttons and status badges. Dark mode support. Local graph building fallback.
  - **Integration**: Editor wired as first tab in ChameleonView. `onDeployed` callback refreshes data and switches to Leases tab.

- **Phase 4c — Chameleon Scheduling (2026-03-27):**
  - **Chameleon calendar**: `GET /api/chameleon/schedule/calendar` endpoint combining lease data with site node-type availability. `ChameleonCalendar` component with 14-day timeline (lease bars, site rows, "now" line, tooltips). Green color scheme. New "Calendar" tab in ChameleonView.
  - **Find available integration**: Wired existing `findChameleonAvailability()` into calendar finder panel. Site/node-type/count/duration inputs. Results: "Available now" or "Available from {date}". "Reserve at that time" button pre-fills Create Lease modal with the suggested start date.

- **Phase 4b — Chameleon Full Editor (2026-03-27):**
  - **Backend**: 8 new endpoints — instance reboot/stop/start, disassociate-ip, network list/create/delete, node-types/detail with hardware specs.
  - **Server management**: Instance cards now have Reboot, Stop, Start, Delete buttons with per-instance loading states and confirmations. Floating IP display with disassociate button.
  - **Network management**: New 'networks' tab. List networks with subnet CIDRs. Create network form (site, name, cidr). Delete with confirmation.
  - **Table view**: New ChameleonTableView component — flat table of all instances. Sortable columns, text filter, multi-select bulk delete, right-click context menu (SSH, reboot, stop/start, delete).
  - **Map enhancement**: GeoView shows Chameleon instance markers (green CircleMarkers offset from site, color-coded by status). Tooltips with name/status.
  - **Lease management**: Extend lease (hours picker + API call), delete lease button, reservations breakdown in detail panel.
  - **Browse enhancement**: Fetches hardware specs per site (CPU model/count, RAM, disk, GPU). Cards show full specs. GPU highlighted in green.
  - **Create Lease enhancement**: Node type dropdown shows hardware specs (e.g., "compute_skylake — 48c, 192GB, 480GB disk").

- **Phase 5 — FABRIC Resource Scheduling + AI Tool Cleanup (2026-03-27):**
  - **Resource availability calendar**: New `GET /api/schedule/calendar` endpoint joins slice lease data with site availability. `ResourceCalendar` component with CSS Grid timeline (14-day, per-site rows, positioned slice bars, "now" line, tooltips, utilization mini-bars). New "Calendar" tab in FABRIC view.
  - **Next-available-time finder**: `GET /api/schedule/next-available` simulates resource freeing by processing lease expirations chronologically. Returns available_now/available_soon/not_available categories. Integrated into Calendar's "Find Available" panel.
  - **Alternative resource suggestions**: `GET /api/schedule/alternatives` suggests different sites, reduced configs, and wait times. Integrated into Calendar finder panel.
  - **Calendar tab integration**: Added to both `InfrastructureView` and `App.tsx` tab bars. Dynamic import for code splitting.
  - **AI tool preambles**: Added OpenCode MCP note (3 lines). Other preambles already per-tool with clear execution methods.
  - **Feature propagation process**: Created `docs/FEATURE_PROPAGATION.md` with architecture, checklist, per-tool table. Updated ai-tools/README.md.
  - **Testing**: 30 new schedule endpoint tests (427 total passing). `lease_end` added to `slice_summary()`.

- **Phase 4a — Chameleon Foundation Layer (2026-03-27):**
  - **Unified TestbedViewShell component**: Shared layout shell with `TestbedTheme` prop (`{name, primary, dark, light, logo}`). CSS custom properties (`--testbed-primary/dark/light`) for theme-aware styling. Pre-built `FABRIC_THEME` and `CHAMELEON_THEME` constants. Handles header (logo with light/dark mode), tab bar with active indicator, toolbar slot, and content area.
  - **InfrastructureView refactored**: Replaced custom `.infra-header`/`.infra-subtabs` with `<TestbedViewShell theme={FABRIC_THEME}>`. All functionality preserved.
  - **ChameleonView refactored**: Replaced custom `.chi-header`/`.chi-tabs` with `<TestbedViewShell theme={CHAMELEON_THEME}>`. All functionality preserved.
  - **Lease selector dropdown**: Added to ChameleonView toolbar — leases grouped by status (Active/Pending/Past), "None" to deselect, "Create Lease" button alongside.
  - **SSH key management fix**: Fixed `get_chameleon_ssh_key()` bug — was calling `get_default_slice_key_path()` without required `config_dir` arg and not unpacking the tuple return. Now correctly falls back to FABRIC slice private key.
  - **Chameleon branding**: Green theme via TestbedViewShell, consistent across header, tabs, badges.
  - Removed ~130 lines of duplicate header/tab CSS from both view stylesheets.

- **Phase 2 — Infrastructure Map + AI Tool Maturity (2026-03-27):**
  - **Infrastructure map — live load indicators**: Site markers color-coded by CPU utilization (green <50%, orange 50-80%, red >80%, gray no data). Link thickness/color by bandwidth (low/medium/high). Tooltip with site name, utilization %, CPU load, traffic. Legend overlay in bottom-left. 2-minute auto-refresh for metrics, pauses when tab hidden.
  - **Auto AI tool config propagation**: `propagate_ai_configs()` function re-seeds all 6 tools on settings save. Hooked into `PUT /api/settings` via BackgroundTasks. `POST /api/ai/propagate-config` endpoint for manual trigger. Each tool isolated in try/except.
  - **Uniform FABRIC/NRP model access**: Verified all tools configure both providers. Fixed bug in `_build_opencode_config()` where model dicts were used as keys instead of ID strings.
  - **Crush + Deep Agents in ai-eval**: Updated eval skill, ai-tools-evaluator agent, and Claude Code ai-eval command with evaluation criteria for Crush (.crush.json, skills, agents) and Deep Agents (config.json, AGENTS.md, skills, agents).
  - **AI seeding verification tests**: 30 new tests in `test_ai_seeding.py` covering all 5 tools (OpenCode, Aider, Claude, Crush, Deep Agents) + propagation tests.
  - **Custom FABlib branch support**: `ARG FABLIB_BRANCH=claude-ify` in Dockerfile with sed rewrite. Runtime override via `entrypoint.sh` (reinstalls if env var differs from build). docker-compose.dev.yml updated with build arg.



- **Phase 1 — Polish & Stabilize (2026-03-27):**
  - **Settings view redesign**: Two-panel sectioned layout (sidebar + content). 9 sections: User Profile, SSH Keys, FABlib, Projects, LLMs, AI Tools, Chameleon, Appearance, Storage. Responsive (dropdown at < 768px). Removed "Advanced Settings" toggle — all settings directly accessible.
  - **Settings validation — live Test buttons**: `POST /api/settings/test/{setting_name}` endpoint (token, bastion_ssh, fablib, ai_server, nrp_server, project). `POST /api/settings/test-all` runs all tests concurrently. Frontend: per-section Test buttons with spinner/green-check/red-X results, "Test All" in sidebar.
  - **Cache UIS project/user queries**: `FabricCallManager` with 10-min TTL for `uis:people:{uuid}` and `uis:projects:{uuid}` lookups via sync httpx fetchers.
  - **Help documentation update**: Added 21 entries for FABRIC view (8 sub-tabs), Chameleon view, AI assistant (conversations, health), Deep Agents, Jupyter AI, CLI. Updated overview (7 AI tools), titlebar, settings entries.
  - **Guided tours update**: Updated discoverLoomai (FABRIC/Chameleon views, CLI, 6 AI tools), gettingStarted (6 tools), aiTools (6 tools, multi-conversation). Added `TourRequiredView` types for 'fabric' and 'chameleon'.
  - **README update**: Features section expanded from 12 to 17 items (7 AI tools, CLI, caching, polling, monitoring, tours, performance, dark mode).
  - **CONTRIBUTING.md**: New 153-line guide covering setup, structure, workflow, style, testing, PRs, architecture refs, Claude Code agents.
  - **Roadmap updated**: Marked help docs, guided tours, README, CONTRIBUTING as done.



- **Bidirectional model sync (2026-03-26):**
  - `PUT /api/ai/models/default` — new endpoint to set the default model in `settings.json`
  - Chat panel: calls backend on model change, polls every 30s for external changes (CLI)
  - CLI shell: `/model` command syncs selection to backend via PUT endpoint
  - Flow: chat panel ↔ `settings.json` ↔ CLI/shell — any change propagates within 30s

- **Documentation update (2026-03-26):**
  - ARCHITECTURE.md: Added AI Chat/Models/Tools endpoint tables, fixed tour count (10→14), added `ai.default_model` to settings schema, fixed AI terminal endpoint paths
  - CLAUDE.md: Added 6 new key feature sections (AI tools, artifacts, CLI, tours, monitoring, AllSliversView), expanded key files with 7 new backend + 6 new frontend entries, added default model discovery docs
  - CONVENTIONS.md: Added AI Chat System section (intent detection patterns, context management tiers, custom LLM providers, model proxy)
  - AGENTS.md: Added `common-tasks` skill (29 total), added file locations table, workspace seeding docs, background model discovery, how to add skills/agents

- **Shared LLM config for GUI + CLI + shell (2026-03-26):**
  - Fixed `_find_first_healthy_model()` bug — was calling `.lower()` on dicts instead of strings
  - Added `ai.default_model` and `ai.default_model_source` to settings schema with accessors
  - Background model discovery on startup: discovers first healthy FABRIC LLM, persists to `settings.json`
  - Chat endpoint (`ai_chat.py`): 3-tier fallback (request > settings > hardcoded)
  - `/api/ai/models/default`: fast path reads persisted setting, slow path discovers
  - CLI one-shot (`loomai ? joke`): resolves model from `~/.loomai/config` or backend before sending
  - Frontend: persists selected model in localStorage across page reloads
  - Full health check (`_fetch_all_models`) syncs settings default when it changes
  - Deployed and verified: `gpt-oss-20b` auto-discovered, `loomai ? "tell me a joke"` works out of the box


- **Weave Lifecycle — FABlib-native export + cleanup script:**
  - "Save as Weave" now exports 6 files: `weave.json` (enriched with topology + args), `slice.json`, `slice_topology.graphml` (FABlib native), `experiment.py` (start/stop/monitor lifecycle), `weave.sh` (orchestrator with SIGTERM trap), `.weaveignore`
  - Generated weaves are standalone-runnable with FABlib alone (no WebGUI dependency)
  - Optional cleanup script: `cleanup_script` field in `weave.json`, "Clean" button on weave cards (reuses existing `start-run` infrastructure)
  - `has_cleanup_script` exposed in template listing (checks file exists on disk)
  - 6 new integration tests (graphml, experiment.py, weave.sh, weave.json topology, cleanup true/false)
  - MockSlice.save() enhanced to write minimal graphml for test verification

- **Unified FabricCallManager (Phases 1-9):**
  - Phase 1: `FabricCallManager` singleton with caller-specified `max_age`, request coalescing, SWR, mutation invalidation, stale-on-error fallback + 16 unit tests
  - Phase 2: Migrated slice list cache from ad-hoc `_list_slices_cache` to call manager; `GET /slices?max_age=N`
  - Phase 3: Adaptive STEADY/ACTIVE frontend polling — `max_age=300` at rest, `max_age=30` during transitions, 3-min mutation cooldown
  - Phase 4: Sliver state polling — `GET /slices/{id}/slivers?max_age=N` lightweight endpoint; frontend merges per-node states during provisioning
  - Phase 5: Per-slice detail `max_age` param + `invalidate_prefix("slice:{name}")` on submit/delete/refresh
  - Phase 6: Resource cache migration — sites, links, facility ports through call manager; sync wrappers for thread pool callers; cache warmer via call manager
  - Phase 7: Run manager invalidates `slices:list` on weave start/stop/finish; frontend detects external slice changes → auto-triggers ACTIVE mode
  - Phase 8: Resource availability polling — `max_age` on `GET /sites`, `/links`, `/facility-ports`; 5-min background refresh in `useInfrastructure` with tab visibility handling
  - Phase 9: Updated CONVENTIONS.md and ARCHITECTURE.md with call manager docs

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
  - useMemo for JSON.stringify(sliceData) in AI assistant

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
- Propagate weave workflow knowledge (weave.json, weave.sh, run_manager, background runs, console log tabs) across all skills, agents, and prompts — updated: create-weave skill, template-builder agent, devops-engineer, experiment-designer, fabric-manager, troubleshooter agents; libraries, create-template, artifacts, backend commands; ARCHITECTURE.md, CLAUDE.md
- Remove all "builtin" artifact references from frontend, backend AI docs, ai-tools/ copies, and markdown docs

- Orchestrated run: weave.sh handles the full experiment lifecycle in one click
- Unified play button color: all ▶ buttons use primary blue (#5798bc) regardless of mode (Load/Deploy/Run)
- Transport controls on weave cards: ▶ Play, ■ Stop, ↺ Reset always visible with enable/disable states
- Artifacts view: weave cards show "Open in Slices" instead of Load/Deploy/Run
- Running weave indicator + reattach: Artifacts panel now shows "running" badge on weaves with active background runs, plus "View Output" / "Last Output" button to open the log tab in BottomPanel
- Backend/Frontend: Add tool install progress popup with SSE streaming

## Blockers

(No blockers)
