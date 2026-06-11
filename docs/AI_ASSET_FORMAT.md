# LoomAI AI Asset Format

Status: accepted for `ai-tools-update`, 2026-06-09.

LoomAI AI assets use **Markdown files with standard frontmatter** as the
canonical hand-edited source format. Generated manifests and per-tool files may
be produced from these Markdown sources, but should not become the primary
source of truth.

## Canonical Shape

```markdown
---
id: create-weave
name: create-weave
asset_type: skill
audience: end-user
description: Create a reusable LoomAI weave artifact with topology and run scripts
domains:
  - weave
  - fablib
tools:
  - loomai
  - claude-code
  - opencode
  - crush
  - deepagents
triggers:
  - create weave
  - build experiment template
source_paths:
  - ai-tools/shared/skills/create-weave.md
generated_outputs:
  - .claude/commands/create-weave.md
  - .opencode/skills/create-weave/SKILL.md
freshness: review-on-change
---

# Create Weave

...
```

## Required Fields

| Field | Meaning |
|---|---|
| `id` | Stable machine id. Prefer the filename stem. |
| `name` | User-visible name or slash-command name. |
| `asset_type` | `prompt`, `agent`, `skill`, `example`, `runbook`, or `eval`. |
| `audience` | `developer`, `end-user`, or `both`. |
| `description` | One-sentence summary used by UI lists, adapters, and retrieval. |

## Recommended Fields

| Field | Meaning |
|---|---|
| `domains` | Tags such as `fabric`, `fablib`, `chameleon`, `federated`, `weave`, `testing`, `deployment`. |
| `tools` | Target tools such as `loomai`, `claude-code`, `codex`, `opencode`, `aider`, `crush`, `deepagents`, `antigravity`, `jupyter-ai`. |
| `triggers` | User phrases that should route to or retrieve this asset. |
| `source_paths` | Repo paths the asset depends on. |
| `generated_outputs` | Derived per-tool files this asset should produce. |
| `freshness` | Optional review rule, expiry, or verification policy. |
| `eval_cases` | Optional eval prompt ids that should pass when this asset changes. |

Curated RAG maps live under `ai-tools/shared/corpus/*.md`. They use the same
frontmatter shape as other assets, with `asset_type: runbook` or
`asset_type: example`, and should include `domains`, `triggers`,
`source_paths`, and `freshness`.

Assistant quality evals live under `ai-tools/shared/evals/*.md`. They use
`asset_type: eval`, include a `## Prompt` section in the body, and can declare
static expectations with:

- `expected_tools`: assistant tool schemas that must exist and survive
  declared model-tier filtering.
- `expected_retrieval_domains`: corpus domains that should be covered by
  retrieved context.
- `expected_source_types`: corpus source types such as `curated`, `skill`,
  `example`, or `fabric_ai`.
- `profile_tiers`: model tiers (`standard`, `large`, etc.) that must retain
  expected tools after filtering.
- `prompt_variants` and `required_prompt_terms`: prompt-regression checks.
- `expected_intent_tool` and `expected_intent_confidence`: optional intent
  router checks.

## Compatibility

The backend parser accepts both the canonical format above and the legacy
format used by older assets:

```markdown
name: create-weave
description: Create a reusable LoomAI weave artifact
---

...
```

New or migrated assets should use canonical frontmatter. Legacy files should be
migrated incrementally with tests rather than rewritten in one large churn.

## Generated Outputs

Adapters should derive per-tool files from the Markdown asset body plus
frontmatter:

- Claude Code commands: strip frontmatter and write `.claude/commands/<id>.md`.
- OpenCode skills: write frontmatter plus body to
  `.opencode/skills/<id>/SKILL.md`.
- OpenCode agents: write body to `.opencode/agent-prompts/<id>.md` and use
  `description` in `opencode.json`.
- Crush and Deep Agents: copy canonical Markdown files unless a tool-specific
  adapter is required.
- LoomAI Assistant: use `description`, `domains`, and `triggers` for routing,
  retrieval, and selectable agents.
- Aider, Codex, Antigravity, and Jupyter AI: start with `AGENTS.md`/reference
  context, then add richer adapters only where the tool supports them.

## Pilot Migration

The initial pilot migrated these skills to canonical frontmatter:

- `benchmark`
- `create-chameleon-lease`
- `query-chameleon`
- `create-tutorial`

The parser and adapter code should support this pilot before broader migration.

## Validation

`backend/app/ai_assets.py` provides `validate_markdown_asset()` for canonical
asset checks. The first test coverage verifies:

- required fields are present;
- `id` matches the filename stem;
- `asset_type`, `audience`, and `tools` use known values;
- OpenCode receives canonical frontmatter in `SKILL.md`;
- Claude Code commands receive frontmatter-stripped bodies;
- RAG indexes the body without metadata noise;
- curated corpus assets are indexed with source paths, domains, triggers, and
  freshness metadata;
- assistant eval assets load from `shared/evals/` and verify retrieval,
  tool filtering, intent routing, prompt terms, and context-budget retention;
- the agent/skill CRUD parser reads canonical names and descriptions.
