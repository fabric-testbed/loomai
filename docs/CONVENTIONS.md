# Code Conventions

Coding conventions for the fabric-webgui project, inferred from the existing codebase.

## Naming

- **Backend (Python)**: `snake_case` for functions, variables, and modules
- **Frontend (TypeScript)**: `camelCase` for variables and functions, `PascalCase` for components and interfaces
- **CSS**: BEM-like naming with semantic prefixes (`.toolbar-*`, `.editor-panel`, `.slice-combo-*`, `.tp-*` for template panel)
- **Route modules**: One file per domain — 18 modules in `backend/app/routes/`
- **CSS files**: One per component/view — 34 files in `frontend/src/styles/`
- **Type definitions**: Centralized in `frontend/src/types/fabric.ts`

## State Management

- React hooks only — no Redux, Zustand, or Recoil
- All application state lifted to `App.tsx` as `useState` hooks
- `useCallback` for event handlers passed as props (14+ extracted callbacks)
- `useMemo` for expensive computations (e.g., `JSON.stringify(sliceData)` in AI chat)
- `React.memo` on heavy components (13 of 40+ components wrapped)
- Panel layout state persisted to `localStorage`

## API Pattern

- **Client layer**: Typed fetch wrappers in `frontend/src/api/client.ts` via `fetchJson<T>()`
- **SSE streaming**: For long-running operations (script execution, tool install)
- **WebSocket**: For terminals (`xterm.js` → `/ws/terminal/*`), AI tool sessions (`/ws/ai/*`), log tailing (`/ws/logs`)
- **Polling**: 15-second auto-refresh for transitional slice states; visibility-aware (pauses when tab hidden)

## Error Handling

### Backend
- **Centralized middleware**: `error_handler.py` installs exception handlers on the FastAPI app
- **Sanitization**: Regex checks for sensitive patterns (`/home/`, `ssh`, `password`, `token`, `secret`, `paramiko`, `Traceback`) — replaces with generic "internal error" message
- **500 cap**: Messages longer than 200 chars are also replaced with the generic message
- **Unhandled exceptions**: Caught at the top level, logged with traceback, generic 500 returned

### Frontend
- `try/catch` around API calls → errors pushed to `setErrors` state array
- Errors displayed in the BottomPanel "Errors" tab with clear-all

## Caching

- **TTL-based in-memory caches**: Artifacts (300s), update-check (3600s), slice list dedup (5s), template/recipe lists (10s), site availability (5 min with stale-while-revalidate)
- **Atomic writes**: `.tmp` file + `os.replace()` pattern for all persistent JSON (settings, registry, configs)
- **Background refresh**: Site cache refreshes in the background when stale

## Thread Safety

- **`FablibManager`**: Singleton with threading lock for initialization
- **Async caches**: `asyncio.Lock` protects shared cache dicts
- **FABlib thread pool**: Dedicated `ThreadPoolExecutor` (4 workers, `"fablib"` prefix) in `fablib_executor.py` — prevents blocking calls from starving async operations
- **Slice registry**: Thread-safe JSON persistence with atomic writes

## Serialization Safety

- **No SSH triggers**: `slice_serializer.py` never calls methods that trigger SSH connections
- **Safe accessors**: `_safe(fn, default)` wrappers around FABlib property access
- **Direct FIM reads**: Reads capacities from the FIM (FABRIC Information Model) directly
- **IP from data**: Reads IP addresses from `fablib_data["addr"]`, never calls `get_ip_addr()`

## Identity & UUID Policy

See the "Identity & UUID Policy" section in [`../CLAUDE.md`](../CLAUDE.md) for the full policy. Key rule: **UUID is the primary key** for all FABRIC-managed objects; names are display-only.

## Dark / Light Mode

- **CSS custom properties**: Global vars in `global.css` (`:root` definitions)
- **Theme toggle**: `[data-theme="dark"]` attribute on `<html>` with CSS variable overrides
- **Graph colors**: Parallel `STATE_COLORS` / `STATE_COLORS_DARK` dicts in `graph_builder.py`
- **Persistence**: Theme preference stored in `localStorage`

## CSS Variables

Global CSS variables use the `--fabric-*` prefix for brand colors and `--state-*` for reservation state colors:

```css
--fabric-primary    /* #5798bc — headers, borders, links */
--fabric-success    /* #008e7a — StableOK state */
--fabric-warning    /* #ff8542 — Configuring state */
--fabric-danger     /* #e25241 — Error state */
--state-active, --state-configuring, --state-nascent, etc.
```

## File Organization

```
backend/
├── app/
│   ├── routes/          # 18 route modules, one per domain
│   ├── *.py             # Core modules (fablib_manager, slice_serializer, graph_builder, etc.)
│   └── ...
├── scripts/             # Utilities (model_proxy.py, etc.)
├── tests/integration/   # pytest tests (18 test files)
└── ai-tools/shared/     # AI agent/skill definitions

frontend/
├── src/
│   ├── app/             # Next.js app directory (page.tsx entry)
│   ├── components/      # React components
│   ├── api/client.ts    # Typed API client
│   ├── types/fabric.ts  # TypeScript interfaces
│   ├── data/            # Static data (helpData.ts, tourSteps.ts)
│   └── styles/          # 34 CSS files, one per component
└── e2e/tests/           # Playwright E2E specs (6 test files)
```
