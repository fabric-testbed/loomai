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

## Caching — Unified FabricCallManager

All FABlib read calls go through a single `FabricCallManager` singleton (`backend/app/fabric_call_manager.py`).

### Core mechanics
- **Caller-specified `max_age`**: Each endpoint declares acceptable staleness. `max_age=0` → always fresh. `max_age=300` → accept 5-min-old data.
- **Request coalescing**: If a FABlib call is already in-flight for a cache key, concurrent callers `await` the same result via `asyncio.Event`. No duplicate API calls.
- **Stale-while-revalidate (SWR)**: Return stale data immediately, refresh in background. Used for non-urgent reads.
- **Mutation invalidation**: `invalidate(key)` sets `timestamp=0` → next read fetches fresh regardless of `max_age`. `invalidate_prefix(prefix)` expires all matching keys.
- **Stale-on-error fallback**: If a fetch fails but stale data exists, return stale data (prevents blank UI during FABRIC outages).

### Cache keys
| Key | Default `max_age` | Notes |
|-----|-------------------|-------|
| `slices:list` | 30s | Invalidated by submit/delete/create/archive + run_manager |
| `slice:{name}:slivers` | 15s | Lightweight per-node states for polling |
| `sites` | 300s | SWR + 4-min background warmer |
| `links` | 300s | Backbone topology |
| `facility_ports` | 300s | VLAN availability |

### Adding a new cached call
1. Create a sync fetcher function (runs in FABlib thread pool)
2. Choose a cache key (string) and default `max_age`
3. Call `await get_call_manager().get(key, fetcher, max_age=N)`
4. Add `invalidate(key)` calls to relevant mutation endpoints

### Frontend adaptive polling
- **STEADY mode** (all slices stable/terminal): `max_age=300` — near-zero API cost
- **ACTIVE mode** (transitional slices or within 3-min cooldown after mutation): `max_age=30`
- **External change detection**: Polling compares responses with previous state; new slices or state changes auto-trigger ACTIVE mode
- **Run manager integration**: `run_manager.py` invalidates `slices:list` on weave start/stop/finish

### Other caches (not in call manager)
- **Serialization cache** (`_serialize_cache` in `slices.py`): Computation cache keyed on `(name, state)` — caches `slice_to_dict()` + `build_graph()` output
- **Artifacts** (300s), **update-check** (3600s), **template/recipe lists** (10s): Simple TTL caches
- **Frontend GET deduplication**: `fetchJson()` in `client.ts` deduplicates concurrent GET requests
- **Atomic writes**: `.tmp` file + `os.replace()` for persistent JSON

## Thread Safety

- **`FablibManager`**: Singleton with threading lock for initialization
- **`FabricCallManager`**: `asyncio.Lock` protects cache dict + decision logic. Sync wrappers (`get_cached_sites()`, `get_fresh_sites()`) read cache directly under GIL for thread pool callers.
- **`_fablib_lock`** (resources.py): Serializes FABlib resource/topology queries — FABlib internal dicts mutate during iteration. Call manager sits above this; fetcher functions acquire the lock internally.
- **FABlib thread pool**: Dedicated `ThreadPoolExecutor` (4 workers, `"fablib"` prefix) in `fablib_executor.py`
- **Slice registry**: Thread-safe JSON persistence with atomic writes

## Serialization Safety

- **No SSH triggers**: `slice_serializer.py` never calls methods that trigger SSH connections
- **Safe accessors**: `_safe(fn, default)` wrappers around FABlib property access
- **Direct FIM reads**: Reads capacities from the FIM (FABRIC Information Model) directly
- **IP from data**: Reads IP addresses from `fablib_data["addr"]`, never calls `get_ip_addr()`

## Artifact Description Display

Artifacts (weaves, VM templates, recipes, notebooks) have two description fields:
- **`description_short`** (aliased as `description` in template/recipe APIs): One-line summary for card views
- **`description_long`**: Extended description for detail/editor panels

**Convention: Artifact cards always show `description_short`, never `description_long`.** The long description is only shown in detail panels and editor views. This keeps card layouts compact and scannable.

- **Backend** (`templates.py:213`): Falls back `description` → `description_short` when populating template metadata
- **LibrariesPanel.tsx**: Card rendering uses `t.description` (which is the short description from the backend)
- **LibrariesView.tsx**: Card rendering uses `art.description_short || art.description`; detail panels may show both short and long

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

## Artifact Card Descriptions

Artifact cards (weaves, VM templates, recipes, notebooks) MUST use `description_short` for display text. Fall back to `description` only if `description_short` is missing. The `description` field may contain multi-paragraph long descriptions unsuitable for cards. CSS classes (`.template-card-desc`, `.vmt-card-desc`) enforce 2-line clamp as a safety net.

Pattern: `{item.description_short || item.description}`

This applies to both `LibrariesPanel.tsx` (side panel cards) and `LibrariesView.tsx` (full-screen cards).

## AI Chat System

### Intent Detection (`chat_intent.py`)

A pre-processing layer that pattern-matches user messages before the LLM call. This allows immediate tool execution without relying on the LLM's function-calling support.

- **`detect_intent(message)`** — Scans the message against compiled regex patterns and returns `(tool_name, arguments, confidence)`.
- **`detect_multi_step(message)`** — Delegates to `chat_templates.match_template()` for multi-step operation workflows. Returns a template dict or `None`.
- **`is_destructive(tool_name)`** — Returns `True` for tools in `DESTRUCTIVE_TOOLS` (`delete_slice`, `submit_slice`) that require user confirmation.

**Confidence levels:**
| Level | Behavior | Example |
|-------|----------|---------|
| `high` | Execute tool immediately, pass results to LLM for formatting | `"list slices"` → `list_slices` |
| `medium` | Execute likely tool, let LLM decide if more is needed | `"create slice mytest"` → `create_slice` |
| `low` | Pass to LLM with tool-calling if the model supports it | `"help"`, ambiguous file creation |

**Pattern structure:** `_RAW_PATTERNS` is a list of `(regex_str, tool_name, arg_extractor, confidence)` tuples. `arg_extractor` is an optional callable that pulls arguments from the regex match groups. Patterns are compiled once at module load into `INTENT_PATTERNS`.

**Learning from failures:** `record_intent_result()` tracks per-model per-intent success/fail counts. `should_disable_tools()` returns `True` if a model's tool-calling failure rate exceeds 50% (after at least 5 attempts).

### Context Management (`chat_context.py`)

Per-model context window management: model profiles, token estimation, conversation trimming, system prompt variants, and tool schema filtering.

**Model profiles** — `get_model_profile(model_name, context_length=None)` returns a dict with `tier`, `context_window`, `max_output`, `temperature`, `supports_tools`, and other limits.

Profile resolution order:
1. Check `MODEL_OVERRIDES` for a substring match on the model name
2. Auto-detect tier from `context_length` (typically from `/v1/models` response)
3. Fall back to `"standard"` tier

**Three tiers:**
| Tier | Context | System prompt | Tool result max | Summarize at | Max tools |
|------|---------|---------------|-----------------|--------------|-----------|
| `compact` (≤12K) | 8,192 | compact (~3K tokens) | 200 chars | 40% | 10 |
| `standard` (12-65K) | 32,768 | standard (~8K tokens) | 800 chars | 70% | 37 |
| `large` (>65K) | 131,072 | full | 2,000 chars | 85% | 37 |

**Token budget:** 30% system prompt, 50% conversation, 20% tool results. Enforced by `trim_conversation()` before every LLM call:
1. Calculate budget from `context_window * summarize_at - system_tokens - max_output`
2. If conversation fits, return as-is (with `near_full` flag if >90% used)
3. Otherwise, keep system message + last 4 messages and summarize older messages

**Tool schema filtering:** `filter_tool_schemas(schemas, max_tools)` prioritizes `CORE_TOOLS` (15 essential tools like `list_slices`, `query_sites`, `ssh_execute`) and drops non-core tools when the schema count exceeds the tier's `max_tools` limit.

### Custom LLM Providers

**Settings schema** (`settings_manager.py`): `ai.custom_providers` is a list of `{"name": str, "base_url": str, "api_key": str}` entries. Configured alongside `ai.ai_server_url` (FABRIC primary) and `ai.nrp_server_url` (NRP/Nautilus fallback).

**Model routing** (in `ai_chat.py`):
- `nrp:<model_name>` prefix → routes to the NRP server URL with NRP API key
- No prefix → routes to the primary FABRIC AI server
- On 5xx from the primary server, auto-fallback to NRP if an NRP key is configured
- `default_model_source` tracks where the active model comes from: `"fabric"`, `"nrp"`, or `"custom:<name>"`

**Model proxy** (`scripts/model_proxy.py`): A lightweight HTTP reverse proxy for AI tools (e.g., OpenCode) that use hardcoded model names. Intercepts `/v1/chat/completions` requests and rewrites any model name not in the allowed list to the configured default. Usage: `model_proxy.py <port> <target_url> <default_model> <allowed_models>`.
