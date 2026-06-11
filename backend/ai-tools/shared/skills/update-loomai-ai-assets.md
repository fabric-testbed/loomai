name: update-loomai-ai-assets
description: Update LoomAI built-in RAG docs, examples, skills, agents, and AI terminal seeding assets
---
Use this skill when adding knowledge that LoomAI agents, skills, RAG, or
in-container AI tools should remember in future containers.

## Source Files

- Shared source: `ai-tools/shared/skills`, `ai-tools/shared/agents`,
  `ai-tools/shared/FABRIC_AI.md`
- Backend image context: `backend/ai-tools/shared/...`
- Examples/RAG: `ai-tools/fablib-examples`, `backend/ai-tools/fablib-examples`
- Seeding code: `backend/app/routes/ai_terminal.py`
- RAG loader: `backend/app/rag.py`

## Workflow

1. Update source docs/examples first.
2. Mirror built-in assets into `backend/ai-tools` so new Docker images include them.
3. If examples index or JSON changes, validate with `python -m json.tool`.
4. If Python examples change, syntax-check them.
5. If RAG has a build/reindex command, run it instead of hand-editing generated metadata.
6. Rebuild only when the user asks.

## Prompt Quality

- Keep skills 30-80 lines.
- Keep agents focused with clear ownership.
- Put trigger terms in `description`.
- Reference existing docs instead of copying long sections.
- Include exact API routes and commands only when they prevent mistakes.
