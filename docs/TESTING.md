# Testing

Test infrastructure for the fabric-webgui project.

## Backend Tests

**Framework**: pytest with FastAPI `TestClient`
**Location**: `backend/tests/integration/` (18 test files)
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

**Framework**: Playwright (E2E only, no unit tests)
**Location**: `frontend/e2e/tests/` (6 spec files)
**Config**: `frontend/e2e/playwright.config.ts`

### Test Files

| File | Coverage Area |
|------|--------------|
| `landing.spec.ts` | Landing page rendering |
| `dark-mode.spec.ts` | Theme toggle, dark mode styles |
| `slice-lifecycle.spec.ts` | Create, load, delete slices |
| `topology-editor.spec.ts` | Add nodes, components, networks |
| `infrastructure-view.spec.ts` | Infrastructure panel tabs |
| `template-loading.spec.ts` | Load weave templates |

### Configuration

- **Browser**: Chromium only
- **Parallel**: `fullyParallel: true` (serial in CI: `workers: 1`)
- **Retries**: 1 retry in CI, 0 locally
- **Base URL**: `http://localhost:3000`
- **Startup**: Auto-starts `npm run dev` with 60-second timeout
- **Artifacts**: HTML report (never auto-opens), traces on first retry, screenshots on failure

### Running Frontend Tests

```bash
cd frontend
npm install
npx playwright install chromium  # first time only
npx playwright test              # all tests
npx playwright test dark-mode    # single file
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
| `tests/composite/test_composite_e2e.py` | FABRIC-only, Chameleon-only, cross-testbed ping | `composite` | 1200s |

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

# Composite provisioning tests (requires both FABRIC + Chameleon)
pytest tests/composite/test_composite_e2e.py -v -s -m composite --timeout=1200

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
| `e2e/tests/composite-provision.spec.ts` | Submit composite, state badge updates | `E2E_FULL=1` |

```bash
# FABRIC GUI provisioning
E2E_FULL=1 npx playwright test fabric-provision

# Chameleon GUI provisioning
E2E_FULL=1 npx playwright test chameleon-provision

# Composite GUI provisioning
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
3. Wraps both in a composite with a `fabnetv4` cross-connection
4. Submits composite (parallel deploy)
5. Waits for both Active/StableOK
6. Executes `ping` from FABRIC node to Chameleon node IP
7. Asserts 0% packet loss

## CLI Tests

**Framework**: pytest with Click's `CliRunner`
**Location**: `backend/cli/tests/`
**Pattern**: Mock tests run without backend; integration tests need `--integration` flag

### CLI Test Files

| File | Coverage Area | Mock Tests | Integration Tests |
|------|--------------|------------|-------------------|
| `test_cli_slices.py` | FABRIC slice CRUD, submit, nodes, networks | Help, list, create, delete, submit, validate | Create+delete draft, add node+validate |
| `test_cli_chameleon.py` | Chameleon sites, leases, instances, drafts, slices | Help, list/create/delete for each subgroup | List sites, draft lifecycle |
| `test_cli_composite.py` | Composite CRUD, members, cross-connections, submit | Help, CRUD, add/remove members, submit | Create+show+delete, full lifecycle |
| `test_cli_ai.py` | AI models, agents, chat (FABRIC + NRP) | Help, list models/agents, one-shot chat, errors | List real models, query FABRIC/NRP LLMs |
| `test_cli_config.py` | Config, projects, keys, sites, SSH, weaves, artifacts | Help for all commands, mock CRUD | Config show, sites list, weaves/artifacts/recipes list |

### Running CLI Tests

```bash
cd backend/cli

# All mock tests (no backend needed)
pytest tests/test_cli_slices.py tests/test_cli_chameleon.py tests/test_cli_composite.py tests/test_cli_ai.py tests/test_cli_config.py -v

# Run tests for a specific CLI area
pytest tests/test_cli_slices.py -v        # FABRIC slices only
pytest tests/test_cli_chameleon.py -v     # Chameleon only
pytest tests/test_cli_composite.py -v     # Composite only
pytest tests/test_cli_ai.py -v            # AI/LLM only
pytest tests/test_cli_config.py -v        # Config, sites, weaves, etc.

# Integration tests (requires running backend)
pytest tests/ -v --integration

# Run a specific test class
pytest tests/test_cli_ai.py::TestAIMockModels -v
pytest tests/test_cli_composite.py::TestCompositeMockCRUD -v
```

## Coverage

Not configured for either backend or frontend. No coverage thresholds or reporting.

## CI/CD

No automated test pipeline. The only GitHub Actions workflow is `publish-to-public.yml` for mirroring to a public repository. Tests are run locally.

## Known Gaps

- **No frontend unit tests** — only Playwright E2E
- **WebSocket tests**: TODO comments in test files for:
  - WebSocket proxy integration tests
  - SSE streaming response tests
  - Tool-calling loop tests
  - Terminal WebSocket session tests
- **No coverage reporting** — no `pytest-cov` or Istanbul/c8 configured
- **No CI test gate** — PRs merge without automated test checks
