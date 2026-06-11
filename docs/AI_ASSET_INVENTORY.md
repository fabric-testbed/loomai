# LoomAI AI Asset Inventory

Status: initial inventory for the `ai-tools-update` branch, 2026-06-09.
Follow-up completed: shared skill frontmatter was normalized so built-in skill
names and descriptions parse consistently through `/api/ai/skills`.
Format decision: canonical AI assets use Markdown files with standard
frontmatter; see `AI_ASSET_FORMAT.md`.
Pilot validation completed: required-field validation and first adapter checks
cover the canonical pilot skills for OpenCode, Claude Code, RAG, and CRUD
parsing.
Cross-tool adapter follow-up completed: deterministic workspace seeding now
packages shared and user-custom skills/agents for OpenCode, Claude Code,
Crush, Deep Agents, Antigravity, and Codex, with a read-only `AI_ASSETS.md`
index for Aider and other context-first tools.
Assistant quality-loop follow-up completed: canonical eval assets and static
tests now cover retrieval coverage, tool filtering, intent routing, prompt
terms, and per-model context-budget retention for five core LoomAI tasks.

This document records the current AI assistant, agent, skill, example, RAG, and
tool-seeding assets before designing a canonical cross-tool asset format.

## Scope

There are two related but distinct AI asset surfaces:

- **LoomAI development agents**: repo-development guidance used by humans and
  coding assistants while changing this application. Main files:
  `AGENTS.md`, `CLAUDE.md`, `.claude/commands/`, and repo docs.
- **In-container end-user AI tools**: guidance and assets available to users
  inside the LoomAI runtime container. Main files: `ai-tools/` and mirrored
  `backend/ai-tools/`.

The modernization work should keep these surfaces distinct while making shared
LoomAI/FABlib/Chameleon/Federated knowledge easy to propagate to both when
appropriate.

## Current Counts

| Asset group | Count | Source |
|---|---:|---|
| Shared agents | 22 | `ai-tools/shared/agents/*.md` |
| Shared skills | 41 | `ai-tools/shared/skills/*.md` |
| Assistant eval cases | 5 | `ai-tools/shared/evals/*.md` |
| Developer Claude commands | 34 | `.claude/commands/*.md` |
| Indexed FABlib examples | 84 | `ai-tools/fablib-examples/INDEX.json` |
| Default weave artifacts | 3 | `backend/default_artifacts/*/weave.json` |
| RAG chunks in running backend | 962 | `GET /api/ai/rag/status` |

The public `/api/ai/agents` endpoint currently lists 21 agents because
`ai-tools-evaluator` is intentionally excluded from user-facing agent lists.

## Source Assets

### Shared In-Container Assets

Primary source tree: `ai-tools/`

- `ai-tools/shared/FABRIC_AI.md`: shared master context used to assemble
  runtime `AGENTS.md`.
- `ai-tools/shared/agents/*.md`: selectable agent personas and tool-specific
  agent prompts.
- `ai-tools/shared/skills/*.md`: slash-command-style task workflows.
- `ai-tools/shared/corpus/*.md`: canonical curated RAG maps that tie source
  paths, domains, triggers, and freshness rules to retrieval intent.
- `ai-tools/shared/evals/*.md`: canonical assistant quality checks used by
  the static eval harness.
- `ai-tools/fablib-examples/INDEX.json`: metadata index for example retrieval.
- `ai-tools/fablib-examples/**/*.py`: code examples used by RAG and the
  `search_examples` assistant tool.
- Per-tool defaults:
  - `ai-tools/aider/.aider.conf.yml`
  - `ai-tools/aider/.aiderignore`
  - `ai-tools/claude-code/CLAUDE.md`
  - `ai-tools/claude-code/settings.json`
  - `ai-tools/crush/.crush.json`
  - `ai-tools/deepagents/AGENTS.md`

Docker build contexts:

- `backend/Dockerfile` copies `backend/ai-tools/` into the backend image.
- The root `Dockerfile` copies top-level `ai-tools/` into the combined image.
- The source mirror should stay synchronized for markdown and Python assets.
  Current source drift found by `diff -qr ai-tools backend/ai-tools` is limited
  to generated `__pycache__` files.

### Developer Agent Assets

These are for developing LoomAI itself, not for ordinary user AI sessions:

- `AGENTS.md`: TeamBrain and repo collaboration contract for all coding agents.
- `CLAUDE.md`: Claude Code project guide, architecture summary, commands, and
  key files.
- `.claude/commands/*.md`: developer slash commands such as `lead`,
  `backend`, `frontend`, `test-guide`, `loomai-assistant`, and
  `update-ai-tools`.

Developer commands overlap conceptually with in-container assets, but they
target a different audience. A canonical asset model should not automatically
merge them.

## Current Tool Packaging

Packaging and propagation are implemented mainly in
`backend/app/routes/ai_terminal.py`.

| Tool | Current packaged assets | Notes |
|---|---|---|
| LoomAI Assistant | In-memory prompt, tool schemas, selected agents, RAG context | Uses `backend/app/routes/ai_chat.py`, `chat_context.py`, `chat_prompt.py`, and `rag.py`. |
| OpenCode | `AGENTS.md`, `.opencode/skills/<name>/SKILL.md`, `.opencode/agent-prompts/*.md`, `opencode.json`, MCP scripts | Full shared skills and agents are adapted. |
| Aider | `AGENTS.md`, `AI_ASSETS.md`, `.aider.conf.yml`, `.aiderignore` | A generated read-only skill/agent index is included in Aider's configured read files. |
| Claude Code | `AGENTS.md`, workspace `CLAUDE.md`, `.claude/commands/*.md` | Shared skills are converted into Claude slash commands. |
| Crush | `AGENTS.md`, `.crush.json`, `.crush/skills/*.md`, `.crush/agents/*.md` | Shared skills and agents are copied directly. |
| Deep Agents | `AGENTS.md`, `.deepagents/AGENTS.md`, `.deepagents/config.json`, `.deepagents/skills/*.md`, `.deepagents/agents/*.md` | Shared and user-custom skills/agents are re-synced on workspace seeding. |
| Antigravity | `AGENTS.md`, `AI_ASSETS.md`, `.antigravity/skills/*.md`, `.antigravity/agents/*.md` | Parallel canonical copies provide discoverable shared context. |
| Codex | `AGENTS.md`, `AI_ASSETS.md`, `.codex/skills/<name>/SKILL.md`, `.codex/agents/*.md`, optional `~/.codex/config.toml` for a flagged custom provider | Parallel canonical copies provide discoverable shared context. Review provider secret handling before expanding provider automation. |
| Jupyter AI | Jupyter AI config, patched system prompt, copied reference skills/agents | Implemented in `backend/app/routes/jupyter.py`. |

Runtime propagation entry points:

- `seed_ai_tool_defaults()` seeds startup defaults.
- `propagate_ai_configs()` regenerates runtime tool configs after settings or
  agent/skill changes.
- `POST /api/ai/propagate-config` exposes manual propagation.
- Agent and skill CRUD writes user overrides under
  `{FABRIC_STORAGE_DIR}/.loomai/agents` and `.loomai/skills`, then triggers
  propagation.

## Current RAG Corpus

RAG is implemented in `backend/app/rag.py` with status/search/rebuild endpoints
in `backend/app/routes/ai_rag.py`.

Current corpus loaders:

- `load_fabric_ai_md()`: section chunks from `ai-tools/shared/FABRIC_AI.md`.
- `load_curated_assets()`: canonical Markdown corpus maps from
  `ai-tools/shared/corpus/*.md`.
- `load_skills()`: built-in skills plus user-custom skill overlays.
- `load_agents()`: shared agents.
- `load_fablib_examples()`: `INDEX.json` entries plus example code, with
  inferred domains, source paths, freshness metadata, and curated flags.
- `load_default_weaves()`: repo-shipped starter weaves from
  `backend/default_artifacts/`.
- `load_weaves()`: user weave artifacts under storage roots.
- `load_site_catalog()`: static FABRIC site coordinate catalog.

Running dev backend status on 2026-06-09:

```json
{
  "status": "ready",
  "chunk_count": 962,
  "embedder": "local:BAAI/bge-small-en-v1.5",
  "dims": 384,
  "sources": {
    "fabric_ai": 263,
    "skill": 273,
    "agent": 329,
    "example": 84,
    "weave": 13
  }
}
```

The index stores under the active user storage root at
`.loomai/rag_index/`. Local embeddings use `fastembed`; remote embeddings are
probed when configured.

## Curated Starter Corpus

The first curated pass uses all requested categories. The canonical starter map
is `ai-tools/shared/corpus/curated-rag-starter.md` and its backend mirror. It
declares domains, triggers, source paths, tool targets, and
`freshness: review-on-change` for:

- FABlib create/submit/modify/delete, L2/L3 networking, SSH execution,
  MAC-based IP lookup, and safe submit/polling patterns.
- Repo default weaves: Hello FABRIC, Prometheus/Grafana monitoring, and
  Chameleon SSH slice.
- Chameleon/OpenStack Blazar, Nova, Neutron, floating-IP, security-group, and
  FABNetv4 route-metric patterns.
- Federated Slice and Composite/Federated member workflows.
- Troubleshooting runbooks for SSH, transitional slice states, post-boot
  failures, Chameleon failures, topology refresh/cache issues, and UI/backend
  regression triage.
- LoomAI development guidance for agents changing this repo.

## Observed Gaps

- **Docs drift cleanup**: Current roadmap, architecture, help, tour, and
  AI-tool docs now describe the eight launchable tools plus Jupyter AI, and
  distinguish full skill/agent adapters from `AGENTS.md`-only context.
- **Canonical migration is partial**: The schema is documented and pilot
  skills are normalized, while legacy-format assets remain accepted during
  migration.
- **Live LLM eval runner is missing**: The static quality loop exists, but
  there is not yet an optional live model runner that scores actual responses
  against the same canonical eval assets.
- **RAG source metadata is still uneven**: Example and skill metadata are
  richer now, but agent, weave, troubleshooting, and provider-pattern metadata
  can still improve for curated retrieval, freshness checks, or eval targeting.
- **Secret handling review needed**: Codex custom-provider setup can write a
  bearer token into `~/.codex/config.toml`. Prefer env-var or runtime injection
  where supported before expanding provider automation.

## Canonical Asset Format

Accepted format: Markdown files with standard `---` frontmatter. The detailed
schema, compatibility notes, and pilot migration are documented in
`AI_ASSET_FORMAT.md`.

Canonical frontmatter fields:

- `id`
- `name`
- `description`
- `audience`: `developer`, `end-user`, or `both`
- `asset_type`: `prompt`, `agent`, `skill`, `example`, `runbook`, `eval`
- `domains`: for example `fabric`, `fablib`, `chameleon`, `federated`,
  `weave`, `testing`, `deployment`
- `tools`: supported target tools, such as `loomai`, `claude-code`, `codex`,
  `opencode`, `aider`, `crush`, `deepagents`, `antigravity`, `jupyter-ai`
- `triggers`: short phrases used for retrieval, routing, or auto-selection
- `source_paths`: repo paths the asset depends on
- `generated_outputs`: expected derived files per tool
- `freshness`: optional expiry or verification rule
- `eval_cases`: optional prompts/tests that should pass when the asset changes

Assistant eval assets additionally use `expected_tools`,
`expected_retrieval_domains`, `expected_source_types`, `profile_tiers`,
`prompt_variants`, `required_prompt_terms`, and optional intent expectations.

## User Questions Before Corpus Expansion

Before adding new assets or expanding the RAG corpus, ask the user which
materials should be included in each category:

- Extra skills to add or split from existing skills.
- Example weaves to promote into curated RAG examples.
- FABlib snippets and gotchas that should be treated as known-good patterns.
- Chameleon/OpenStack API patterns that should be documented and indexed.
- Federated Slice workflows that should become skills, examples, or evals.
- Troubleshooting cases that should be represented as runbooks or eval prompts.

Initial answer for the starter pass: include all categories.

## Immediate Follow-Ups

1. Done: update docs/help text so the advertised AI tool set matches current
   code.
2. Done for the starter pass: curated corpus now covers FABlib examples,
   example weaves, Chameleon/OpenStack, Federated workflows, troubleshooting,
   and LoomAI development guidance.
3. Done: deterministic cross-tool packaging adapters now seed canonical
   skills/agents or `AI_ASSETS.md` indexes into supported tool workspaces.
4. Done: assistant quality eval assets and static checks now cover the first
   five common LoomAI assistant tasks.
5. Next expansion should add RAG operations UI/API diagnostics, then any
   user-specific weaves, lab examples, or
   preferred FABlib/Chameleon/Federated snippets that are not already in the
   starter source paths.
