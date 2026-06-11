name: verify-loomai-change
description: Choose and run efficient validation for LoomAI code, UI, API, Docker, and AI asset changes
---
Use this skill after modifying LoomAI.

## Verification Matrix

- Frontend UI or API client:
  ```bash
  npm --prefix frontend run build
  ```
- Browser regression:
  ```bash
  npx playwright test frontend/e2e/tests/<test>.spec.ts
  ```
- Backend route or storage:
  ```bash
  backend/.venv/bin/python -m pytest backend/tests/<path> -q
  ```
- JSON indexes:
  ```bash
  python -m json.tool <file> >/tmp/validated.json
  ```
- Python examples:
  ```bash
  python -m py_compile <file.py>
  ```
- Live dev smoke after redeploy:
  ```bash
  curl -fsS http://127.0.0.1:8000/api/health
  curl -fsSI http://127.0.0.1:3000/
  ```

## Rules

- Run the narrowest check that can catch the likely regression, then broaden if it fails.
- If a known test hangs, stop it and use a direct route/function check; report the hang.
- For UI state bugs, prefer mocked Playwright tests over real provider calls.
- For AI asset changes, verify files are present in both `ai-tools` and `backend/ai-tools`.
