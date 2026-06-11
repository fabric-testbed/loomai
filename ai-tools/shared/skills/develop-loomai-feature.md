name: develop-loomai-feature
description: Plan, implement, verify, and optionally redeploy a LoomAI application feature
---
Use this skill for LoomAI code changes across frontend, backend, provider
integrations, RAG, Docker, or tests.

## Fast Path

1. Inventory: `git status --short`, then `rg` for the feature/API/component.
2. Choose owner paths:
   - UI: `frontend/src`, `frontend/e2e/tests`
   - API/storage: `backend/app`, `backend/tests`
   - AI assets/RAG: `ai-tools`, `backend/ai-tools`, `backend/app/rag.py`
   - Container: `backend/Dockerfile`, `docker-compose*.yml`
3. Use the LoomAI agent team when useful:
   - `@loomai-team-lead` for task split.
   - `@loomai-frontend-engineer` for UI.
   - `@loomai-backend-engineer` for API/storage.
   - `@loomai-qa-engineer` for tests.
4. Patch the smallest behavior-owning files. Preserve unrelated user changes.
5. Verify with focused tests plus `npm --prefix frontend run build` for UI work.
6. Redeploy only if asked, then smoke test backend and frontend endpoints.

## Done Criteria

- User-visible behavior is implemented.
- API contracts and persistence are consistent.
- Draft/empty/error states are handled.
- Tests or explicit validation cover the risky path.
- Final answer names changed files and validation results.
