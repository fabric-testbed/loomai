"""Trovi marketplace routes — browse, search, and get Chameleon shared experiments."""

from __future__ import annotations

import json
import logging
import os
import urllib.request

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["trovi"])

TROVI_API = "https://trovi.chameleoncloud.org"


@router.get("/api/trovi/artifacts")
async def list_trovi_artifacts(q: str = "", tag: str = "", limit: int = 50, offset: int = 0):
    """Search/list Trovi artifacts."""
    try:
        url = f"{TROVI_API}/artifacts"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        artifacts = data.get("artifacts", [])

        # Filter by search query
        if q:
            q_lower = q.lower()
            artifacts = [a for a in artifacts if
                         q_lower in (a.get("title", "") or "").lower() or
                         q_lower in (a.get("short_description", "") or "").lower() or
                         any(q_lower in t.lower() for t in a.get("tags", []))]

        # Filter by tag
        if tag:
            artifacts = [a for a in artifacts if tag in a.get("tags", [])]

        total = len(artifacts)
        artifacts = artifacts[offset:offset + limit]

        return {
            "artifacts": [{
                "uuid": a.get("uuid"),
                "title": a.get("title"),
                "short_description": a.get("short_description"),
                "tags": a.get("tags", []),
                "authors": [auth.get("full_name", "") for auth in a.get("authors", [])],
                "created_at": a.get("created_at"),
                "updated_at": a.get("updated_at"),
                "visibility": a.get("visibility"),
                "versions": len(a.get("versions", [])),
                "source": "trovi",
            } for a in artifacts],
            "total": total,
        }
    except Exception as e:
        logger.warning("Trovi API error: %s", e)
        return JSONResponse({"error": str(e)}, status_code=502)


@router.get("/api/trovi/artifacts/{uuid}")
async def get_trovi_artifact(uuid: str):
    """Get details of a specific Trovi artifact."""
    try:
        url = f"{TROVI_API}/artifacts/{uuid}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        data["source"] = "trovi"
        return data
    except urllib.error.HTTPError as e:
        return JSONResponse({"error": f"Trovi: {e.code}"}, status_code=e.code)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)


@router.get("/api/trovi/tags")
async def list_trovi_tags():
    """Get all unique tags from Trovi artifacts."""
    try:
        url = f"{TROVI_API}/artifacts"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        tags: set[str] = set()
        for a in data.get("artifacts", []):
            for t in a.get("tags", []):
                tags.add(t)
        return {"tags": sorted(tags)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)


@router.post("/api/trovi/artifacts/{uuid}/get")
async def download_trovi_artifact(uuid: str, request: Request):
    """Download a Trovi artifact to my_artifacts/.

    Creates a directory with the artifact metadata and content references.
    """
    try:
        # Fetch artifact details
        url = f"{TROVI_API}/artifacts/{uuid}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            artifact = json.loads(resp.read())

        title = artifact.get("title", "trovi-artifact")
        # Sanitize for directory name
        dir_name = "".join(c if c.isalnum() or c in "-_ " else "" for c in title).strip().replace(" ", "_")[:50]
        if not dir_name:
            dir_name = f"trovi-{uuid[:8]}"

        from app.settings_manager import load_settings
        settings = load_settings()
        artifacts_dir = settings["paths"]["artifacts_dir"]
        dest = os.path.join(artifacts_dir, dir_name)
        os.makedirs(dest, exist_ok=True)

        # Write weave.json with Trovi metadata
        weave_meta = {
            "name": title,
            "description": artifact.get("short_description", ""),
            "description_long": artifact.get("long_description", ""),
            "source": "trovi",
            "source_marketplace": "trovi",
            "trovi_uuid": uuid,
            "tags": artifact.get("tags", []),
            "authors": [a.get("full_name", "") for a in artifact.get("authors", [])],
            "created_at": artifact.get("created_at"),
            "versions": [{
                "slug": v.get("slug"),
                "contents_urn": v.get("contents", {}).get("urn", ""),
            } for v in artifact.get("versions", [])],
        }
        with open(os.path.join(dest, "weave.json"), "w") as f:
            json.dump(weave_meta, f, indent=2)

        # Try to clone git content if available
        latest_version = artifact.get("versions", [{}])[-1] if artifact.get("versions") else {}
        contents_urn = latest_version.get("contents", {}).get("urn", "")
        if contents_urn.startswith("urn:trovi:contents:git:"):
            git_url = contents_urn.replace("urn:trovi:contents:git:", "")
            # Separate URL and commit hash
            if "@" in git_url:
                repo_url, commit = git_url.rsplit("@", 1)
            else:
                repo_url, commit = git_url, "HEAD"

            import subprocess
            try:
                subprocess.run(
                    ["git", "clone", "--depth=1", repo_url, dest],
                    timeout=60, capture_output=True, check=False,
                )
                # Overwrite weave.json (git clone may have created files)
                with open(os.path.join(dest, "weave.json"), "w") as f:
                    json.dump(weave_meta, f, indent=2)
            except Exception as clone_err:
                logger.warning("Git clone failed for %s: %s", repo_url, clone_err)

        return {
            "status": "downloaded",
            "dir_name": dir_name,
            "title": title,
            "source": "trovi",
        }

    except Exception as e:
        logger.warning("Trovi download error: %s", e)
        return JSONResponse({"error": str(e)}, status_code=400)
