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
