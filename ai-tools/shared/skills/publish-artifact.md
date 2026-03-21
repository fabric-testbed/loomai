name: publish-artifact
description: Publish a local artifact to the FABRIC Artifact Marketplace
---
Publish a local artifact (weave, VM template, recipe, or notebook) to the
FABRIC Artifact Marketplace so other users can discover and use it.

## Steps

1. **List local artifacts** to find what's available:
   ```bash
   ARTIFACTS_DIR="/home/fabric/work/my_artifacts"
   ls "$ARTIFACTS_DIR"
   ```
   Or via REST API:
   ```bash
   curl -s http://localhost:8000/api/artifacts/local | python3 -m json.tool
   ```

2. **Identify the artifact type** by its marker file:
   - `weave.json` → Weave (category: `weave`)
   - `vm-template.json` → VM Template (category: `vm-template`)
   - `recipe.json` → Recipe (category: `recipe`)
   - `*.ipynb` → Notebook (category: `notebook`)

3. **Prepare metadata** — ensure the artifact has:
   - A descriptive name and description
   - All required files (scripts, configs)
   - No hardcoded paths or secrets

4. **Publish via REST API**:
   ```bash
   curl -X POST http://localhost:8000/api/artifacts/publish \
     -H "Content-Type: application/json" \
     -d '{
       "dir_name": "My_Weave",
       "category": "weave",
       "title": "My Artifact Title",
       "description": "Brief summary for UI cards (5-255 chars)",
       "description_long": "Full detailed description of what this artifact deploys, how it works, prerequisites, expected behavior, and configuration notes.",
       "visibility": "author",
       "tags": ["networking", "monitoring"]
     }'
   ```

   **Descriptions:**
   - `description` → becomes `description_short` (5–255 chars): Brief summary shown on artifact cards
   - `description_long`: Full documentation — use this for comprehensive details

   **Visibility options:**
   - `"author"` — Visible only to the author (default)
   - `"author_project"` — Visible to members of the author's project
   - `"project"` — Visible to a specific project
   - `"public"` — Visible to all FABRIC users

   **Tags:** Optional list of searchable keywords. Category tags
   (`loomai:weave`, `loomai:vm`, `loomai:recipe`) are auto-added.

5. **Verify publication**:
   ```bash
   # List your published artifacts
   curl -s http://localhost:8000/api/artifacts/my | python3 -m json.tool
   # List all marketplace artifacts
   curl -s http://localhost:8000/api/artifacts/remote | python3 -m json.tool
   ```

## Notes

- Category tags (`loomai:weave`, `loomai:vm`, `loomai:recipe`) are auto-added on publish.
- Use `description` for a brief summary (5–255 chars, shown on UI cards).
- Use `description_long` for full documentation of the artifact.
- Published artifacts appear in the Marketplace tab of the Artifacts view.
- Other users can "Get" published artifacts to copy them locally.
- To update a published artifact, upload a new version:
  `curl -X POST http://localhost:8000/api/artifacts/remote/<uuid>/version -d '{"dir_name": "My_Weave"}'`
- Only the author (or project admins) can update or delete published artifacts.
