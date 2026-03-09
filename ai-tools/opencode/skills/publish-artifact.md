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
   curl -s http://localhost:8000/api/artifacts/ | python3 -m json.tool
   ```

2. **Identify the artifact type** by its marker file:
   - `slice.json` → Weave
   - `vm-template.json` → VM Template
   - `recipe.json` → Recipe
   - `*.ipynb` → Notebook

3. **Prepare metadata** — ensure the artifact has:
   - A descriptive name and description
   - All required files (scripts, configs)
   - No hardcoded paths or secrets

4. **Publish via REST API**:
   ```bash
   curl -X POST http://localhost:8000/api/artifacts/<dir_name>/publish \
     -H "Content-Type: application/json" \
     -d '{
       "title": "My Artifact Title",
       "description": "Detailed description of what this does",
       "visibility": "author_project",
       "tags": ["networking", "monitoring"]
     }'
   ```

   **Visibility options:**
   - `"author_project"` — Visible to members of the author's project (default)
   - `"project"` — Visible to a specific project
   - `"public"` — Visible to all FABRIC users

   **Tags:** Optional list of searchable keywords.

5. **Verify publication**:
   ```bash
   # List published artifacts
   curl -s http://localhost:8000/api/artifacts/marketplace | python3 -m json.tool
   ```

## Notes

- The `[LoomAI <Type>]` category marker is auto-prepended to the description
  on publish — you don't need to add it manually.
- Published artifacts appear in the Marketplace tab of the Libraries view.
- Other users can "Get" published artifacts to copy them locally.
- To update a published artifact, make changes locally and re-publish.
- Only the author (or project admins) can update or delete published artifacts.
