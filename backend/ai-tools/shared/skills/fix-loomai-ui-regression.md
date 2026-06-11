name: fix-loomai-ui-regression
description: Debug and fix LoomAI browser white-screens, topology errors, and UI regressions
---
Use this skill when the LoomAI GUI crashes, white-screens, hides expected data,
or renders topology/slice views incorrectly.

## Steps

1. Identify the view and state: FABRIC, Chameleon, Federated Slices, topology,
   slices table, storage, map, or terminal.
2. Search ownership:
   ```bash
   rg -n "view label|api function|component name" frontend/src
   ```
3. Check API shape in `frontend/src/api/client.ts` and backend route response.
4. Fix null/empty/draft states before changing layout.
5. For topology issues, inspect graph node `data.element_type`, `testbed`,
   `slice_id`, and classes before editing Cytoscape styles.
6. Add a focused Playwright regression with mocked API routes when the bug is
   visible in the browser.
7. Run:
   ```bash
   npm --prefix frontend run build
   ```

## Common LoomAI UI Risks

- Selected ID differs from provider name.
- Draft records have no resources yet but must still display.
- Federated sub-slices may be summaries until expanded.
- Chameleon deploying slices should show planned resources and reservations.
- Do not add ambiguous SSH buttons to rows that represent multiple hosts.
