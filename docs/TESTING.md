# Testing

> Size as of 2026-10-13: backend 115 files / ~2,070 tests (plus 16 CLI test files, run from `backend/cli/`), frontend 20 files / 118 cases, Playwright mock + contract projects. Prose counts elsewhere in `docs/` are dated phase notes, not current numbers.

Test infrastructure for the fabric-webgui project.

## Help Documentation Validation

User documentation examples and screenshots live in the in-app Help data at
`frontend/src/data/helpData.ts`. Validate REST examples against backend-contract
mode or provider fakes whenever possible. Validate CLI examples with the CLI
test harness for non-mutating commands and with mocked or contract backends for
mutating workflows. Generate GUI screenshots from deterministic Playwright
mocked or contract data, and avoid capturing secrets or live user identifiers.

### Help Screenshot Reference Pattern

The canonical screenshot-backed Help example is
`libraries.marketplace-weave-workflow` ("Find and Open a Marketplace Weave") in
`frontend/src/data/helpData.ts`, backed by
`frontend/e2e/tests/help-screenshots.mock.spec.ts`. Use it as the style and
workflow reference for future Help screenshots.

Good Help screenshots should:

- Explain one workflow, not a random UI state. Interleave each screenshot
  directly after the written step it illustrates.
- Reference every visible marker number in the written instruction text, for
  example "open **FABRIC Marketplace** **(2)**".
- Prefer arrow-only markers for buttons, tabs, inputs, badges, and other small
  controls so the control remains readable.
- Use light region outlines only for large areas, such as a side panel. Avoid
  tight circles around controls; if a circle is needed, make it loose and light.
- Keep markers in the LoomAI theme: blue numbered badges, orange arrows, and
  low-opacity target outlines.
- Left-align screenshot figures in Help. Do not center them in the Help article
  body on wide screens.
- Use deterministic mocked or contract Playwright data. Do not capture live
  users, tokens, emails, API keys, SSH keys, private project names, or live
  resource identifiers.
- Use production-safe examples. For site labels, use production sites and avoid
  EDC, EDUKY, UKY, RENC, LBNL, and development sites.
- Prefer stable, familiar artifacts for examples. The marketplace walkthrough
  uses the `Hello, FABRIC` weave as the reference artifact.

Screenshot image annotations are encoded in the Markdown image alt text after
`||`:

```text
![Caption. || arrow=1:x,y,w,h@labelX,labelY:Target label; rect=2:x,y,w,h@labelX,labelY:Large region](/help-screenshots/example.png)
```

Use `arrow=` for most callouts. Use `rect=` for large highlighted regions.
Reserve `circle=` for rare cases where an arrow alone is not enough. All
coordinates are percentages of the screenshot.

Regenerate and preview the reference screenshots with:

```bash
cd frontend
UPDATE_HELP_SCREENSHOTS=1 \
HELP_TOPIC_PREVIEW_PATH=/tmp/loomai-help-marketplace-weave-topic.png \
E2E_PORT=3100 \
npx playwright test -c e2e/playwright.config.ts --project=mocked-e2e e2e/tests/help-screenshots.mock.spec.ts
```

## Backend Tests

**Framework**: pytest with FastAPI `TestClient`
**Location**: `backend/tests/unit/`, `backend/tests/integration/`, and gated live E2E directories
**Config**: `backend/pytest.ini` — `asyncio_mode = auto`, `testpaths = tests`

### Test Files

| File | Coverage Area |
|------|--------------|
| `test_health.py` | Health endpoint, basic startup |
| `test_slices_crud.py` | Slice create, list, delete |
| `test_slices_topology.py` | Node, component, network operations |
| `test_slices_validate.py` | Slice validation logic |
| `test_slices_import_export.py` | Import/export `.fabric.json` |
| `test_resources.py` | Sites, images, component models |
| `test_templates.py` | Weave CRUD and loading |
| `test_vm_templates.py` | VM template operations |
| `test_recipes.py` | Recipe listing and execution |
| `test_config.py` | Configuration endpoints |
| `test_projects.py` | Project listing and switching |
| `test_files_local.py` | Container file operations |
| `test_artifacts.py` | Artifact listing, publish, marketplace |
| `test_ai_chat.py` | AI chat completions |
| `test_ai_terminal.py` | AI tool management |
| `test_terminal.py` | Terminal WebSocket basics |
| `test_http_proxy.py` | HTTP proxy endpoints |
| `test_error_handler.py` | Error sanitization middleware |
| `test_fabric_provision_mock.py` | Mock: single/multi node, NIC+FABNetv4, state, delete |
| `test_fabric_hardware_mock.py` | Mock: GPU, NVMe, FPGA, ConnectX-5/6/7, L2STS, L2PTP, multi-site FABNetv4 |
| `unit/test_terminal_sessions.py` · `unit/test_terminal_auth.py` | In-process PTY sessions (buffer/broadcast/detach/cull); single-use attach tickets |
| `integration/test_terminals_routes.py` | Terminal create/list/ticket/delete, WS attach auth, ssh/chameleon argv builders |
| `integration/test_settings_users_routes.py` | Secret masking via `GET/PUT /api/settings`; multi-user list + switch (AI-home swap) |

### Fixtures

- **FABlib mocks**: Mock `FablibManager` to avoid real FABRIC API calls
- **Storage isolation**: Temporary directories for test data
- **Parameterized data**: Site availability, component models

### Running Backend Tests

```bash
cd backend
pip install -r requirements.txt
pytest                          # all tests
pytest -k "test_slices"         # keyword filter
pytest tests/integration/test_health.py  # single file
pytest -v                       # verbose output
```

## Frontend Tests

**Frameworks**: Vitest + Testing Library for component tests, Playwright for mocked/contract/live E2E.
**Locations**: `frontend/src/__tests__/`, `frontend/e2e/tests/`
**Configs**: `frontend/vitest.config.ts`, `frontend/e2e/playwright.config.ts`

### Test Files

| File | Coverage Area |
|------|--------------|
| `src/__tests__/ConfigureView.test.tsx` | Settings load/save and validation controls |
| `src/__tests__/LibrariesView.test.tsx` | Local artifacts, marketplace tab, blank artifact creation |
| `src/__tests__/FileTransferView.test.tsx` | Container/VM file transfer controls and federated endpoint selector |
| `src/__tests__/AIChatPanel.test.tsx` | Model selection persistence and streaming chat |
| `src/__tests__/terminalStore.test.ts` | Persistent-terminal reattach: stored-id reuse on reload, shared-session adoption, stale fallback, destroy kills backend |
| `src/__tests__/consoleLayout.persist.test.ts` | Console split-pane layout validation + restore from localStorage |
| `terminals.mock.spec.ts` | Persistent terminals across reload (mocked `/api/terminals` control plane) |
| `landing.spec.ts` | Landing page rendering |
| `dark-mode.spec.ts` | Theme toggle, dark mode styles |
| `slice-lifecycle.spec.ts` | Create, load, delete slices |
| `topology-editor.spec.ts` | Add nodes, components, networks |
| `infrastructure-view.spec.ts` | Infrastructure panel tabs |
| `template-loading.spec.ts` | Load weave templates |
| `shared-surfaces.mock.spec.ts` | Settings, artifact marketplace, FABRIC storage, and LoomAI chat using mocked APIs |
| `fabric-workflow.mock.spec.ts` | FABRIC editor workflow using mocked APIs |
| `chameleon-workflow.mock.spec.ts` | Chameleon editor workflow using mocked APIs |
| `federated-workflow.mock.spec.ts` | Federated editor workflow using mocked APIs |
| `backend-contract.contract.spec.ts` | Real backend contract harness with deterministic provider fakes |

### Configuration

- **Browser**: Chromium only
- **Parallel**: `fullyParallel: true` (serial in CI: `workers: 1`)
- **Retries**: 1 retry in CI, 0 locally
- **Mocked E2E**: `npm run e2e:mock` starts the frontend and intercepts backend APIs with `frontend/e2e/fixtures/api-mocks.ts`
- **Backend contract**: `npm run e2e:contract` starts the backend with `LOOMAI_CONTRACT_MODE=1` and tests deterministic REST flows without live FABRIC, Chameleon, Artifact Manager, or AI calls
- **Live E2E**: `npm run e2e:live` targets real services and should be treated as provisioning-capable
- **Artifacts**: HTML report (never auto-opens), traces on first retry, screenshots on failure

### Running Frontend Tests

```bash
cd frontend
npm install
npx playwright install chromium  # first time only
npx tsc --noEmit                 # typecheck
npm test                         # Vitest component tests
npm run e2e:mock                 # mocked Playwright browser suite
npm run e2e:contract             # deterministic backend contract suite
npm run e2e:live                 # live-service Playwright suite
npx playwright test dark-mode    # single file/project default
npx playwright test --headed     # watch in browser
npx playwright show-report       # view HTML report
```

## Real-Provisioning E2E Tests

These tests create real slices on FABRIC and Chameleon, deploy them, and verify they become active. They are slow (5-15 min) and require live credentials.

### Backend Provisioning Tests

| File | Coverage | Marker | Timeout |
|------|----------|--------|---------|
| `tests/fabric/test_fabric_provision_e2e.py` | Single/multi node, FABNetv4, exec on node, 2-node ping, delete, state transitions | `fabric` | 900s |
| `tests/fabric/test_fabric_hardware_e2e.py` | Multi-site FABNetv4/L2STS/L2PTP ping, GPU+Ollama, NVMe r/w, FPGA PCI, ConnectX-5/6/7 | `fabric` | 1800s |
| `tests/chameleon/test_chameleon_provision_e2e.py` | Deploy single/multi node, state transitions | `chameleon` | 900s |
| `tests/composite/test_composite_e2e.py` | Federated FABRIC-only, Chameleon-only, cross-testbed ping (legacy test path) | `composite` | 1200s |
| `tests/fabric/test_fabric_terminal_e2e.py` | Server-held SSH node terminal: attach over WS, run, detach + reattach (PTY persistence) | `fabric` | 1200s |
| `tests/chameleon/test_chameleon_terminal_e2e.py` | Server-held SSH instance terminal: attach, run, detach + reattach | `chameleon` | 1800s |

```bash
# FABRIC provisioning tests
pytest tests/fabric/test_fabric_provision_e2e.py -v -s -m fabric --timeout=900

# FABRIC ping test only (two nodes on FABNetv4)
pytest tests/fabric/test_fabric_provision_e2e.py -v -s -m fabric -k ping --timeout=900

# FABRIC hardware tests (GPU, NVMe, FPGA, SmartNICs, multi-site L2)
pytest tests/fabric/test_fabric_hardware_e2e.py -v -s -m fabric --timeout=1800

# Individual hardware tests
pytest tests/fabric/test_fabric_hardware_e2e.py -v -s -m fabric -k gpu --timeout=1800
pytest tests/fabric/test_fabric_hardware_e2e.py -v -s -m fabric -k nvme --timeout=1200
pytest tests/fabric/test_fabric_hardware_e2e.py -v -s -m fabric -k fpga --timeout=1200
pytest tests/fabric/test_fabric_hardware_e2e.py -v -s -m fabric -k l2sts --timeout=1200
pytest tests/fabric/test_fabric_hardware_e2e.py -v -s -m fabric -k l2ptp --timeout=1200
pytest tests/fabric/test_fabric_hardware_e2e.py -v -s -m fabric -k cx5 --timeout=1200
pytest tests/fabric/test_fabric_hardware_e2e.py -v -s -m fabric -k cx6 --timeout=1200
pytest tests/fabric/test_fabric_hardware_e2e.py -v -s -m fabric -k cx7 --timeout=1200

# Override sites via env vars (defaults: TACC/STAR)
FABRIC_SITE_A=RENC FABRIC_SITE_B=UCSD pytest tests/fabric/test_fabric_hardware_e2e.py -v -s -m fabric -k l2sts
FABRIC_GPU_SITE=DALL pytest tests/fabric/test_fabric_hardware_e2e.py -v -s -m fabric -k gpu

# Chameleon provisioning tests
pytest tests/chameleon/test_chameleon_provision_e2e.py -v -s -m chameleon --timeout=900

# Federated provisioning tests (requires both FABRIC + Chameleon; legacy marker/path)
pytest tests/composite/test_composite_e2e.py -v -s -m composite --timeout=1200

# Terminal persistence over a real node/instance (server-held PTY: attach,
# run, detach, reattach to the SAME shell). Needs the `websockets` dependency.
pytest tests/fabric/test_fabric_terminal_e2e.py -v -s -m fabric --timeout=1200
pytest tests/chameleon/test_chameleon_terminal_e2e.py -v -s -m chameleon --timeout=1800

# Cross-testbed ping test only
pytest tests/composite/test_composite_e2e.py -v -s -m composite -k ping --timeout=1200

# Run all provisioning tests
pytest tests/fabric/ tests/chameleon/ tests/composite/ -v -s -m "fabric or chameleon or composite" --timeout=1200
```

### Frontend Provisioning Tests

| File | Coverage | Gate |
|------|----------|------| 
| `e2e/tests/fabric-hardware.spec.ts` | 9 topology tests (no gate) + 9 real provisioning tests | `E2E_FULL=1` for provisioning |
| `e2e/tests/fabric-provision.spec.ts` | Submit via GUI, multi-node, StableOK badge, exec on node, delete | `E2E_FULL=1` |
| `e2e/tests/chameleon-provision.spec.ts` | Deploy via GUI, verify ACTIVE badges | `E2E_FULL=1` |
| `e2e/tests/composite-provision.spec.ts` | Submit federated slice, state badge updates (legacy test filename) | `E2E_FULL=1` |

```bash
# FABRIC GUI provisioning
E2E_FULL=1 npx playwright test fabric-provision

# Chameleon GUI provisioning
E2E_FULL=1 npx playwright test chameleon-provision

# Federated GUI provisioning (legacy spec name)
E2E_FULL=1 npx playwright test composite-provision

# FABRIC hardware topology (no auth needed — just tests graph rendering)
npx playwright test fabric-hardware --grep "Topology"

# FABRIC hardware provisioning (real hardware)
E2E_FULL=1 npx playwright test fabric-hardware --grep "Provisioning"

# All provisioning GUI tests
E2E_FULL=1 npx playwright test fabric-provision fabric-hardware chameleon-provision composite-provision
```

### Key Test: Cross-Testbed Ping

`test_composite_cross_testbed_with_ping` in `test_composite_e2e.py`:
1. Creates a FABRIC node with NIC + FABNetv4 network
2. Creates a Chameleon node
3. Wraps both in a federated slice with a `fabnetv4` cross-connection
4. Submits the federated slice (parallel deploy)
5. Waits for both Active/StableOK
6. Executes `ping` from FABRIC node to Chameleon node IP
7. Asserts 0% packet loss

## Assistant E2E Tests

Tests the LoomAI assistant end-to-end against real FABRIC-hosted LLMs. Tests go through the full backend stack (`POST /api/ai/chat/stream`): intent detection, system prompt, tool dispatch, SSE streaming.

### Test Files

| File | Coverage | Markers | Timeout |
|------|----------|---------|---------|
| `tests/assistant/test_assistant_knowledge.py` | FABRIC facts, tool triggering, response quality (14 tests) | `llm` | 120s |
| `tests/assistant/test_assistant_slices.py` | Slice creation via chat, software install, SSH commands (5 tests) | `fabric` | 900s |
| `tests/assistant/test_assistant_weaves.py` | Weave creation, file verification, deploy (4 tests) | `llm`, `fabric` | 900s |

### Running Assistant Tests

```bash
# LLM-only knowledge tests (fast, ~8 min)
pytest tests/assistant/test_assistant_knowledge.py -v -s -m llm --timeout=120

# Weave creation only (fast, ~3 min, no FABRIC provisioning)
pytest tests/assistant/test_assistant_weaves.py -v -s -m llm -k "not deploy" --timeout=120

# Slice creation + engagement (slow, ~35 min, real FABRIC provisioning)
pytest tests/assistant/test_assistant_slices.py -v -s -m fabric --timeout=900

# Weave deploy (slow, ~15 min, real FABRIC provisioning)
pytest tests/assistant/test_assistant_weaves.py -v -s -m fabric -k deploy --timeout=900

# All assistant tests
pytest tests/assistant/ -v -s -m "llm or fabric" --timeout=900

# Single test
pytest tests/assistant/test_assistant_knowledge.py -v -s -m llm -k test_fabric_network_types
```

### Design Notes

- **Fuzzy keyword matching**: LLM output is non-deterministic. Tests verify presence of factual keywords, not exact strings.
- **Engagement tests use direct-API slices**: The `running_slice` fixture creates slices via REST API (not assistant) to isolate engagement failures from LLM non-determinism.
- **`e2e-assist-*` naming prefix**: All test slices use this prefix for identification and manual cleanup.

## CLI Tests

**Framework**: pytest with Click's `CliRunner`
**Location**: `backend/cli/tests/` (the only CLI tree; run from `backend/cli/`, not from `backend/`, because the two `conftest.py` files clash)
**Pattern**: Mock tests run without backend; integration tests need `--integration` flag

### CLI Test Files

| File | Coverage Area | Mock Tests | Integration Tests |
|------|--------------|------------|-------------------|
| `test_cli_slices.py` | FABRIC slice CRUD, submit, nodes, networks | Help, list, create, delete, submit, validate | Create+delete draft, add node+validate |
| `test_cli_chameleon.py` | Chameleon sites, leases, instances, drafts, slices | Help, list/create/delete for each subgroup | List sites, draft lifecycle |
| `test_cli_federated.py` | Federated CRUD, members, cross-testbed connections, submit | Help, CRUD, add/remove members, submit | Create+show+delete |
| `test_cli_ai.py` | AI models, agents, chat (FABRIC + NRP) | Help, list models/agents, one-shot chat, errors | List real models, query FABRIC/NRP LLMs |
| `test_cli_config.py` | Config, projects, keys, sites, SSH, weaves, artifacts | Help for all commands, mock CRUD | Config show, sites list, weaves/artifacts/recipes list |
| `test_cli_roadmap.py` | CLI modernization roadmap coverage | Natural `--format` placement, JSON cleanliness, new feature command parity | None |

### Running CLI Tests

```bash
cd backend/cli

# All mock tests (no backend needed)
python -m pytest tests -q

# Run tests for a specific CLI area
pytest tests/test_cli_slices.py -v        # FABRIC slices only
pytest tests/test_cli_chameleon.py -v     # Chameleon only
pytest tests/test_cli_federated.py -v     # Federated only
pytest tests/test_cli_ai.py -v            # AI/LLM only
pytest tests/test_cli_config.py -v        # Config, sites, weaves, etc.
pytest tests/test_cli_roadmap.py -v       # Modernized output and new command parity

# Integration tests (requires running backend)
pytest tests/ -v --integration

# Run a specific test class
pytest tests/test_cli_ai.py::TestAIMockModels -v
pytest tests/test_cli_federated.py::TestFederatedMockCRUD -v
```

## Coverage

The backend CI job runs with `--cov=app` and uploads `coverage.xml` as an artifact. No coverage thresholds are enforced for backend or frontend.

## CI/CD

`.github/workflows/test.yml` runs on every push and pull request:

| Job | What it runs | Notes |
|-----|--------------|-------|
| `backend-tests` | `pytest` in `backend/` (unit + integration, with coverage), then the CLI suite from `backend/cli/` | Python 3.11. Live FABRIC/Chameleon e2e dirs are deselected by `pytest.ini`. |
| `frontend-build` | `npm ci`, `npm run build`, `npm test` in `frontend/` | Node 22 (matches `.nvmrc`). |
| Playwright | mock/contract projects | Live and provisioning specs run only locally. |

`hub/tests/` is not run in CI yet. `publish-to-public.yml` mirrors the repo to the public repository on merge to `main`.

## Known Gaps

- **No frontend unit tests** — only Playwright E2E
- **WebSocket tests**: partially covered now — terminal attach auth + a live attach are in `integration/test_terminals_routes.py`, and real-node attach/persistence in the `*_terminal_e2e.py` suites. Still TODO:
  - WebSocket proxy integration tests
  - SSE streaming response tests
  - Tool-calling loop tests
- **No coverage reporting** — no `pytest-cov` or Istanbul/c8 configured
- **No CI test gate** — PRs merge without automated test checks
