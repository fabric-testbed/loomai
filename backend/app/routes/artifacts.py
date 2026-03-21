"""Artifact Marketplace — proxy to FABRIC Artifact Manager + local import/export."""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import shutil
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.http_pool import fabric_client, ai_client
from app.user_context import get_user_storage, get_token_path, register_user_changed_callback

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])
logger = logging.getLogger(__name__)

ARTIFACT_API = "https://artifacts.fabric-testbed.net/api"
_CACHE_TTL = 300  # 5 minutes

# In-memory cache for the full artifact catalog
_cache: dict[str, Any] = {"artifacts": [], "fetched_at": 0}


def _clear_artifact_cache() -> None:
    _cache["artifacts"] = []
    _cache["fetched_at"] = 0

register_user_changed_callback(_clear_artifact_cache)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _storage_dir() -> str:
    return get_user_storage()


def _get_auth_headers() -> dict[str, str]:
    """Read the user's FABRIC id_token and return an Authorization header.

    Authenticated requests see project-visible and author-only artifacts
    in addition to public ones.
    """
    token_path = get_token_path()
    try:
        with open(token_path) as f:
            data = json.load(f)
        token = data.get("id_token", "")
        if token:
            return {"Authorization": f"Bearer {token}"}
    except Exception:
        logger.debug("Could not read auth token", exc_info=True)
    return {}


def _artifacts_dir() -> str:
    """Return the single local storage dir for all artifacts."""
    from app.user_context import get_artifacts_dir
    return get_artifacts_dir()


def _detect_category(entry_dir: str) -> str:
    """Detect artifact category from files present in the directory.

    - weave.json → weave
    - vm-template.json → vm-template
    - recipe.json → recipe
    - *.ipynb files → notebook
    - otherwise → other
    """
    has_weave_json = os.path.isfile(os.path.join(entry_dir, "weave.json"))
    has_vm = os.path.isfile(os.path.join(entry_dir, "vm-template.json"))
    has_recipe = os.path.isfile(os.path.join(entry_dir, "recipe.json"))

    if has_weave_json:
        return "weave"
    if has_vm:
        return "vm-template"
    if has_recipe:
        return "recipe"
    # Check for notebook (.ipynb files)
    try:
        if any(f.endswith('.ipynb') for f in os.listdir(entry_dir)):
            return "notebook"
    except OSError:
        pass
    return "other"


def _normalize_tags(raw_tags: list) -> list[str]:
    """Convert tag objects or strings to a flat string list."""
    return [t if isinstance(t, str) else t.get("tag", "") for t in raw_tags]


_CATEGORY_MARKERS = {
    "weave": "[LoomAI Weave]",
    "vm-template": "[LoomAI VM Template]",
    "recipe": "[LoomAI Recipe]",
    "notebook": "[LoomAI Notebook]",
}

_CATEGORY_TAGS: dict[str, str] = {
    "weave": "loomai:weave",
    "vm-template": "loomai:vm",
    "recipe": "loomai:recipe",
    "notebook": "loomai:notebook",
}


_TAG_TO_CATEGORY: dict[str, str] = {v: k for k, v in _CATEGORY_TAGS.items()}


def _category_from_tags(tags: list[str]) -> str | None:
    """Return category based on loomai: tags, or None if no match."""
    for tag in tags:
        if tag in _TAG_TO_CATEGORY:
            return _TAG_TO_CATEGORY[tag]
    return None


def _ensure_category_tag(tags: list[str], category: str) -> list[str]:
    """Add the category-specific loomai: tag if not already present."""
    cat_tag = _CATEGORY_TAGS.get(category)
    if cat_tag and cat_tag not in tags:
        tags = tags + [cat_tag]
    return tags


def _make_descriptions(description: str, title: str, category: str,
                       description_long: str = "") -> tuple[str, str]:
    """Build (description_short, description_long) for the FABRIC Artifact API.

    - description_short: 5–255 chars, plain user text
    - description_long: full user description (clean, no category markers)

    Category is now identified by loomai: tags, not description markers.
    """
    full = description.strip() if description else ""

    # description_short: plain user text, truncated to 255 chars
    short_text = full or title
    if len(short_text) > 255:
        short_text = short_text[:252].rsplit(" ", 1)[0] + "..."
    desc_short = short_text

    # Ensure minimum 5 chars
    if len(desc_short) < 5:
        desc_short = desc_short.ljust(5)

    # description_long: use explicit long description if provided, else fall back to short
    desc_long = (description_long.strip() if description_long else "") or full or title

    return desc_short, desc_long


def _classify_artifact(tags: list[str], description_short: str = "",
                       description_long: str = "") -> str:
    """Classify artifact by loomai: tags (primary) or description markers (fallback).

    Tags are the authoritative category identifier.  Description markers
    are checked as a fallback for older artifacts published before tags
    were added.  Defaults to "notebook" if neither match.
    """
    # Primary: check tags
    tag_set = set(tags)
    for cat, cat_tag in _CATEGORY_TAGS.items():
        if cat_tag in tag_set:
            return cat
    # Fallback: description markers (backward compat)
    for desc in (description_long, description_short):
        if desc:
            desc_lower = desc.lower()
            for cat, marker in _CATEGORY_MARKERS.items():
                if marker.lower() in desc_lower:
                    return cat
    return "notebook"


def _sanitize_name(name: str) -> str:
    """Sanitize a name for use as a directory name."""
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", name.strip())
    return safe or "artifact"


def _find_local_by_uuid(artifact_uuid: str) -> str | None:
    """Scan my_artifacts/ for an existing directory with a matching artifact_uuid."""
    adir = _artifacts_dir()
    if not os.path.isdir(adir):
        return None
    for entry in os.listdir(adir):
        entry_dir = os.path.join(adir, entry)
        if not os.path.isdir(entry_dir):
            continue
        # Check weave.json, vm-template.json, recipe.json, metadata.json
        for meta_file in ("weave.json", "vm-template.json", "recipe.json", "metadata.json"):
            meta_path = os.path.join(entry_dir, meta_file)
            if os.path.isfile(meta_path):
                try:
                    with open(meta_path) as f:
                        data = json.load(f)
                    if data.get("artifact_uuid") == artifact_uuid:
                        return entry
                except Exception:
                    continue
    return None


def _get_current_user_identity() -> tuple[str, str]:
    """Extract the user's email and name from the JWT id_token."""
    token_path = get_token_path()
    try:
        with open(token_path) as f:
            data = json.load(f)
        token = data.get("id_token", "")
        if not token:
            return "", ""
        parts = token.split(".")
        if len(parts) != 3:
            return "", ""
        payload = parts[1] + "=" * (4 - len(parts[1]) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload))
        return decoded.get("email", ""), decoded.get("name", "")
    except Exception:
        return "", ""


def _get_current_user_email() -> str:
    """Extract the user's email from the JWT id_token."""
    email, _ = _get_current_user_identity()
    return email


async def _fetch_all_artifacts() -> list[dict[str, Any]]:
    """Fetch all artifact pages and return a combined, normalized list.

    Results are cached in memory for _CACHE_TTL seconds.
    """
    now = time.time()
    if _cache["artifacts"] and (now - _cache["fetched_at"]) < _CACHE_TTL:
        return _cache["artifacts"]

    all_artifacts: list[dict[str, Any]] = []
    page = 1
    headers = _get_auth_headers()
    while True:
        r = await fabric_client.get(
            f"{ARTIFACT_API}/artifacts",
            params={"format": "json", "page": page},
            headers=headers,
        )
        r.raise_for_status()
        data = r.json()
        results = data.get("results", [])
        for art in results:
            art["tags"] = _normalize_tags(art.get("tags", []))
            art["category"] = _classify_artifact(art["tags"], art.get("description_short", ""), art.get("description_long", ""))
        all_artifacts.extend(results)
        if data.get("next") is None:
            break
        page += 1
        if page > 20:  # safety limit
            break

    _cache["artifacts"] = all_artifacts
    _cache["fetched_at"] = now
    logger.info("Fetched %d artifacts from Artifact Manager (%d pages)", len(all_artifacts), page)
    return all_artifacts


async def _fetch_artifact(uuid: str) -> dict[str, Any]:
    """Fetch a single artifact by UUID."""
    headers = _get_auth_headers()
    r = await fabric_client.get(f"{ARTIFACT_API}/artifacts/{uuid}", params={"format": "json"}, headers=headers)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class DownloadRequest(BaseModel):
    uuid: str
    version_uuid: str = ""
    local_name: str = ""
    overwrite: bool = False


class PublishRequest(BaseModel):
    dir_name: str
    category: str
    title: str
    description: str = ""
    description_long: str = ""
    tags: list[str] = []
    visibility: str = "author"
    project_uuid: str = ""
    action: str = ""  # "update", "fork", or "" for auto/new


class UpdateArtifactRequest(BaseModel):
    title: str = ""
    description: str = ""
    description_long: str = ""
    visibility: str = ""
    tags: list[str] = []
    project_uuid: str = ""
    authors: list[dict] = []
    category: str = ""


class UploadVersionRequest(BaseModel):
    artifact_uuid: str
    dir_name: str
    category: str


class RevertRequest(BaseModel):
    version_uuid: str | None = None  # specific version, or latest if None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/remote")
async def list_remote_artifacts():
    """Return all artifacts from the FABRIC Artifact Manager (cached).

    All filtering, searching, and sorting is done client-side for
    instant responsiveness.
    """
    try:
        artifacts = await _fetch_all_artifacts()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to reach Artifact Manager: {e}")

    # Collect all unique tags for the filter UI
    all_tags: dict[str, int] = {}
    for art in artifacts:
        for t in art.get("tags", []):
            all_tags[t] = all_tags.get(t, 0) + 1

    # Sort tags by frequency descending
    sorted_tags = sorted(all_tags.items(), key=lambda x: -x[1])

    return {
        "artifacts": artifacts,
        "total_count": len(artifacts),
        "tags": [{"name": t, "count": c} for t, c in sorted_tags],
    }


@router.post("/remote/refresh")
async def refresh_remote_artifacts():
    """Force-refresh the artifact cache."""
    _cache["fetched_at"] = 0
    try:
        artifacts = await _fetch_all_artifacts()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to reach Artifact Manager: {e}")

    all_tags: dict[str, int] = {}
    for art in artifacts:
        for t in art.get("tags", []):
            all_tags[t] = all_tags.get(t, 0) + 1
    sorted_tags = sorted(all_tags.items(), key=lambda x: -x[1])

    return {
        "artifacts": artifacts,
        "total_count": len(artifacts),
        "tags": [{"name": t, "count": c} for t, c in sorted_tags],
    }


@router.get("/remote/{uuid}")
async def get_remote_artifact(uuid: str):
    """Get full detail for a single remote artifact."""
    try:
        art = await _fetch_artifact(uuid)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch artifact: {e}")

    art["tags"] = _normalize_tags(art.get("tags", []))
    art["category"] = _classify_artifact(art["tags"], art.get("description_short", ""), art.get("description_long", ""))
    return art


@router.post("/download")
async def download_artifact(req: DownloadRequest):
    """Download a remote artifact and import it into local storage."""
    try:
        art = await _fetch_artifact(req.uuid)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch artifact detail: {e}")

    tag_strs = _normalize_tags(art.get("tags", []))
    category = _classify_artifact(tag_strs, art.get("description_short", ""), art.get("description_long", ""))

    # Find the version to download
    versions = art.get("versions", [])
    if not versions:
        raise HTTPException(status_code=404, detail="Artifact has no downloadable versions")

    if req.version_uuid:
        version = next((v for v in versions if v["uuid"] == req.version_uuid), None)
        if not version:
            raise HTTPException(status_code=404, detail="Specified version not found")
    else:
        active = [v for v in versions if v.get("active", True)]
        version = active[0] if active else versions[0]

    urn = version.get("urn", "")
    if not urn:
        raise HTTPException(status_code=400, detail="Version has no downloadable URN")

    download_url = f"{ARTIFACT_API}/contents/download/{urn}"
    try:
        r = await ai_client.get(download_url, headers=_get_auth_headers())
        r.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Download failed: {e}")

    local_name = _sanitize_name(req.local_name or art.get("title", "artifact"))

    # Deduplicate: check if we already have this artifact locally by UUID
    existing_local = _find_local_by_uuid(req.uuid)
    if existing_local:
        local_name = existing_local  # update existing copy instead of creating new

    dest_dir = os.path.join(_artifacts_dir(), local_name)

    if os.path.exists(dest_dir):
        if existing_local:
            # Always update the existing copy (dedup by UUID)
            shutil.rmtree(dest_dir)
        elif not req.overwrite:
            raise HTTPException(
                status_code=409,
                detail=f"Local artifact '{local_name}' already exists. Set overwrite=true to replace it."
            )
        else:
            shutil.rmtree(dest_dir)

    os.makedirs(dest_dir, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        raw_path = os.path.join(tmpdir, "artifact_download")
        with open(raw_path, "wb") as f:
            f.write(r.content)

        extracted = False
        try:
            with tarfile.open(raw_path, "r:*") as tf:
                for member in tf.getmembers():
                    if member.name.startswith("/") or ".." in member.name:
                        raise HTTPException(status_code=400, detail="Artifact contains unsafe paths")
                extract_dir = os.path.join(tmpdir, "extracted")
                os.makedirs(extract_dir, exist_ok=True)
                tf.extractall(extract_dir)
                extracted = True
        except tarfile.TarError:
            pass

        if extracted:
            contents = os.listdir(extract_dir)
            if len(contents) == 1 and os.path.isdir(os.path.join(extract_dir, contents[0])):
                src_dir = os.path.join(extract_dir, contents[0])
            else:
                src_dir = extract_dir

            for item in os.listdir(src_dir):
                s = os.path.join(src_dir, item)
                d = os.path.join(dest_dir, item)
                if os.path.isdir(s):
                    shutil.copytree(s, d)
                else:
                    shutil.copy2(s, d)
        else:
            # Not a recognized archive — drop the raw file for manual extraction
            content_type = r.headers.get("content-type", "")
            filename = local_name
            if "zip" in content_type:
                filename += ".zip"
            elif "gzip" in content_type or "x-gzip" in content_type:
                filename += ".tar.gz"
            else:
                filename += ".bin"
            shutil.copy2(raw_path, os.path.join(dest_dir, filename))

    # Write metadata into weave.json (single source of truth)
    weave_path = os.path.join(dest_dir, "weave.json")
    weave_data: dict[str, Any] = {}
    if os.path.isfile(weave_path):
        try:
            with open(weave_path) as f:
                weave_data = json.load(f)
        except Exception:
            pass
    if not weave_data.get("name"):
        weave_data["name"] = art.get("title", local_name)
        weave_data.setdefault("description", art.get("description_long", "") or art.get("description_short", ""))
        weave_data["source"] = "artifact-manager"
        weave_data["artifact_uuid"] = req.uuid
        weave_data.setdefault("created", datetime.now(timezone.utc).isoformat())
        weave_data["tags"] = tag_strs
        with open(weave_path, "w") as f:
            json.dump(weave_data, f, indent=2)

    # Save a clean reference copy for reset functionality, keyed by UUID
    originals_dir = os.path.join(_storage_dir(), ".artifact-originals")
    os.makedirs(originals_dir, exist_ok=True)
    orig_dest = os.path.join(originals_dir, req.uuid)
    if os.path.exists(orig_dest):
        shutil.rmtree(orig_dest)
    shutil.copytree(dest_dir, orig_dest)

    # Detect category from the files actually present
    detected_category = _detect_category(dest_dir)
    logger.info("Downloaded artifact %s (%s) to %s", art.get("title"), detected_category, dest_dir)

    return {
        "status": "downloaded",
        "title": art.get("title"),
        "category": detected_category,
        "local_name": local_name,
        "local_path": dest_dir,
    }


@router.get("/local")
def list_local_artifacts():
    """List all local artifacts with file-based category detection."""
    adir = _artifacts_dir()
    results = []

    for entry in sorted(os.listdir(adir)):
        entry_dir = os.path.join(adir, entry)
        if not os.path.isdir(entry_dir):
            continue
        category = _detect_category(entry_dir)
        if category == "other":
            continue  # Skip unrecognized directories

        # Read metadata — check category-specific files first, then
        # metadata.json (legacy).  Merge artifact_uuid from legacy file
        # if the primary file doesn't have it.
        meta: dict[str, Any] = {}
        meta_candidates = list(_META_FILES_MAP.get(category, ["weave.json"])) + ["metadata.json"]
        uuid_from_legacy = ""
        for meta_file in meta_candidates:
            mpath = os.path.join(entry_dir, meta_file)
            if os.path.isfile(mpath):
                try:
                    with open(mpath) as f:
                        data = json.load(f)
                except Exception:
                    logger.debug("Metadata parsing failed for %s", mpath, exc_info=True)
                    continue
                if not meta:
                    meta = data
                elif data.get("artifact_uuid") and not meta.get("artifact_uuid"):
                    # Primary file lacked artifact_uuid but legacy file has it
                    uuid_from_legacy = data["artifact_uuid"]
                    if data.get("source"):
                        meta.setdefault("source", data["source"])
        if uuid_from_legacy:
            meta["artifact_uuid"] = uuid_from_legacy

        meta["dir_name"] = entry
        meta["category"] = category
        meta["is_from_marketplace"] = meta.get("source") == "artifact-manager"
        meta.setdefault("name", entry)
        # Ensure description falls back to description_short
        if not meta.get("description") and meta.get("description_short"):
            meta["description"] = meta["description_short"]

        # Override file-based category using loomai: tags.
        # Marketplace downloads all get weave.json, so tags are the
        # authoritative category signal for those artifacts.
        tags = _normalize_tags(meta.get("tags", []))
        tag_cat = _category_from_tags(tags)
        if tag_cat:
            meta["category"] = tag_cat
        elif meta["is_from_marketplace"] and category == "weave":
            # Marketplace artifact with no loomai: tag → notebook
            meta["category"] = "notebook"

        results.append(meta)

    return {"artifacts": results}


class LocalMetadataUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    description_short: str | None = None
    description_long: str | None = None
    tags: list[str] | None = None
    authors: list[str] | None = None
    project_uuid: str | None = None
    visibility: str | None = None


@router.put("/local/{dir_name}/metadata")
def update_local_metadata(dir_name: str, req: LocalMetadataUpdate):
    """Update name/description in the local artifact's metadata file."""
    adir = _artifacts_dir()
    entry_dir = os.path.join(adir, dir_name)
    if not os.path.isdir(entry_dir):
        raise HTTPException(status_code=404, detail="Artifact not found")

    category = _detect_category(entry_dir)
    meta_file = "weave.json"
    for mf in _META_FILES_MAP.get(category, ["weave.json"]):
        if os.path.isfile(os.path.join(entry_dir, mf)):
            meta_file = mf
            break

    meta_path = os.path.join(entry_dir, meta_file)
    meta: dict[str, Any] = {}
    if os.path.isfile(meta_path):
        try:
            with open(meta_path) as f:
                meta = json.load(f)
        except Exception:
            logger.debug("Metadata parsing failed", exc_info=True)

    for field in ("name", "description", "description_short", "description_long",
                    "project_uuid", "visibility"):
        val = getattr(req, field, None)
        if val is not None:
            meta[field] = val
    if req.tags is not None:
        meta["tags"] = req.tags
    if req.authors is not None:
        meta["authors"] = req.authors

    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    return {"status": "ok", "metadata": meta}


def _read_local_metadata(src_dir: str, category: str) -> tuple[dict[str, Any], str]:
    """Read the local metadata JSON for an artifact directory.

    Checks category-specific files first, then metadata.json as legacy
    fallback.  If multiple files exist, prefers one that contains
    ``artifact_uuid`` so the smart-publish update path works correctly.

    Returns (metadata_dict, metadata_file_path).
    """
    meta_files = _META_FILES_MAP.get(category, ["weave.json"])
    # Also check metadata.json (legacy format from older downloads)
    all_candidates = list(meta_files) + (["metadata.json"] if "metadata.json" not in meta_files else [])

    first_found: tuple[dict[str, Any], str] | None = None
    for mf in all_candidates:
        mpath = os.path.join(src_dir, mf)
        if os.path.isfile(mpath):
            try:
                with open(mpath) as f:
                    data = json.load(f)
            except Exception:
                data = {}
            # Prefer the file that already has artifact_uuid
            if data.get("artifact_uuid"):
                return data, mpath
            if first_found is None:
                first_found = (data, mpath)

    if first_found is not None:
        return first_found
    # Fall back to primary metadata file (may not exist yet)
    return {}, os.path.join(src_dir, meta_files[0])


def _write_local_metadata(meta_path: str, meta: dict[str, Any],
                          artifact_uuid: str,
                          tags: list[str] | None = None) -> None:
    """Write artifact_uuid, source, and tags back to the local metadata file."""
    meta["artifact_uuid"] = artifact_uuid
    meta["source"] = "artifact-manager"
    if tags is not None:
        meta["tags"] = tags
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)


# Module-level constant for metadata file lookup (used by list_local_artifacts,
# update_local_metadata, and _read_local_metadata)
_META_FILES_MAP: dict[str, list[str]] = {
    "weave": ["weave.json"],
    "vm-template": ["vm-template.json", "weave.json"],
    "recipe": ["recipe.json", "weave.json"],
    "notebook": ["weave.json"],
}


async def _upload_content(headers: dict[str, str], artifact_uuid: str,
                          src_dir: str, dir_name: str) -> dict[str, Any]:
    """Tar a local directory and upload it as artifact content."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tar_path = os.path.join(tmpdir, f"{dir_name}.tar.gz")
        with tarfile.open(tar_path, "w:gz") as tf:
            tf.add(src_dir, arcname=dir_name)

        upload_data = json.dumps({
            "artifact": artifact_uuid,
            "storage_type": "fabric",
            "storage_repo": "renci",
        })

        try:
            with open(tar_path, "rb") as fh:
                r = await ai_client.post(
                    f"{ARTIFACT_API}/contents",
                    params={"format": "json"},
                    headers=headers,
                    files={"file": (f"{dir_name}.tar.gz", fh, "application/gzip")},
                    data={"data": upload_data},
                )
                r.raise_for_status()
                return r.json()
        except httpx.HTTPStatusError as e:
            detail = e.response.text
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Content upload failed for artifact {artifact_uuid}: {detail}",
            )
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail=f"Content upload failed for artifact {artifact_uuid}: {e}",
            )


async def _create_new_artifact(headers: dict[str, str], req: PublishRequest,
                               src_dir: str, desc_short: str, desc_long: str,
                               publish_tags: list[str]) -> dict[str, Any]:
    """Create a new remote artifact, upload content, return response dict."""
    create_body: dict[str, Any] = {
        "title": req.title,
        "description_short": desc_short,
        "description_long": desc_long,
        "visibility": req.visibility,
    }
    if publish_tags:
        create_body["tags"] = publish_tags
    if req.project_uuid:
        create_body["project_uuid"] = req.project_uuid
    try:
        r = await fabric_client.post(
            f"{ARTIFACT_API}/artifacts",
            params={"format": "json"},
            json=create_body,
            headers=headers,
        )
        r.raise_for_status()
        created = r.json()
    except httpx.HTTPStatusError as e:
        detail = e.response.text
        raise HTTPException(status_code=e.response.status_code,
                            detail=f"Failed to create artifact: {detail}")
    except Exception as e:
        raise HTTPException(status_code=502,
                            detail=f"Failed to create artifact: {e}")

    artifact_uuid = created["uuid"]

    # Update with full metadata (title, tags, project)
    update_body: dict[str, Any] = {
        "title": req.title,
        "description_short": desc_short,
        "description_long": desc_long,
        "visibility": req.visibility,
    }
    if publish_tags:
        update_body["tags"] = publish_tags
    if req.project_uuid:
        update_body["project_uuid"] = req.project_uuid
    try:
        r = await fabric_client.put(
            f"{ARTIFACT_API}/artifacts/{artifact_uuid}",
            params={"format": "json"},
            json=update_body,
            headers=headers,
        )
        r.raise_for_status()
    except Exception as e:
        logger.warning("Failed to update new artifact %s: %s", artifact_uuid, e)

    # Upload content
    version_info = await _upload_content(headers, artifact_uuid, src_dir,
                                         req.dir_name)

    return {
        "status": "published",
        "uuid": artifact_uuid,
        "title": req.title,
        "visibility": req.visibility,
        "version": version_info.get("version", ""),
    }


@router.get("/local/{dir_name}/publish-info")
async def get_publish_info(dir_name: str):
    """Return publish options for a local artifact.

    Frontend uses this to determine what options to show in the publish dialog.
    """
    adir = _artifacts_dir()
    entry_dir = os.path.join(adir, dir_name)
    if not os.path.isdir(entry_dir):
        raise HTTPException(status_code=404, detail="Artifact not found")

    category = _detect_category(entry_dir)
    local_meta, _ = _read_local_metadata(entry_dir, category)
    existing_uuid = local_meta.get("artifact_uuid", "")

    if not existing_uuid:
        return {
            "can_update": False,
            "can_fork": False,
            "is_author": False,
            "artifact_uuid": None,
            "remote_title": None,
        }

    # Check remote artifact
    remote = None
    is_author = False
    remote_title = None
    try:
        remote = await _fetch_artifact(existing_uuid)
        user_email, user_name = _get_current_user_identity()
        is_author = _is_user_author(remote, user_email, user_name)
        remote_title = remote.get("title", "")
    except Exception:
        # Remote artifact doesn't exist anymore or unreachable
        pass

    return {
        "can_update": is_author and remote is not None,
        "can_fork": existing_uuid != "" and remote is not None,
        "is_author": is_author,
        "artifact_uuid": existing_uuid,
        "remote_title": remote_title,
    }


@router.post("/publish")
async def publish_artifact(req: PublishRequest):
    """Publish a local artifact to the FABRIC Artifact Manager.

    The `action` field controls behavior:
    - "update": Push a new version to the existing artifact (requires authorship)
    - "fork": Create a new artifact with forked_from provenance
    - "" (empty/default): Create a brand new artifact (no existing uuid, or legacy auto behavior)
    """
    headers = _get_auth_headers()
    if not headers:
        raise HTTPException(status_code=401, detail="No FABRIC token configured — cannot publish")

    src_dir = os.path.join(_artifacts_dir(), req.dir_name)
    if not os.path.isdir(src_dir):
        raise HTTPException(status_code=404, detail=f"Local artifact '{req.dir_name}' not found in {req.category}")

    desc_short, desc_long = _make_descriptions(req.description, req.title, req.category, req.description_long)
    publish_tags = _ensure_category_tag(list(req.tags), req.category)
    local_meta, meta_path = _read_local_metadata(src_dir, req.category)
    existing_uuid = local_meta.get("artifact_uuid", "")

    if req.action == "update":
        # --- UPDATE existing artifact (user is the author) ---
        if not existing_uuid:
            raise HTTPException(status_code=400, detail="Cannot update: no artifact_uuid in local metadata")

        # Verify authorship
        try:
            remote = await _fetch_artifact(existing_uuid)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to fetch remote artifact: {e}")

        user_email, user_name = _get_current_user_identity()
        if not _is_user_author(remote, user_email, user_name):
            raise HTTPException(status_code=403, detail="You are not the author of this artifact")

        update_body: dict[str, Any] = {
            "title": req.title,
            "description_short": desc_short,
            "description_long": desc_long,
            "visibility": req.visibility,
        }
        if publish_tags:
            update_body["tags"] = publish_tags
        if req.project_uuid:
            update_body["project_uuid"] = req.project_uuid

        try:
            r = await fabric_client.put(
                f"{ARTIFACT_API}/artifacts/{existing_uuid}",
                params={"format": "json"},
                json=update_body,
                headers=headers,
            )
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            detail = e.response.text
            raise HTTPException(status_code=e.response.status_code,
                                detail=f"Failed to update artifact: {detail}")
        except Exception as e:
            raise HTTPException(status_code=502,
                                detail=f"Failed to update artifact: {e}")

        version_info = await _upload_content(headers, existing_uuid, src_dir, req.dir_name)

        # Update .artifact-originals
        originals_dir = os.path.join(_storage_dir(), ".artifact-originals")
        os.makedirs(originals_dir, exist_ok=True)
        orig_dest = os.path.join(originals_dir, existing_uuid)
        if os.path.exists(orig_dest):
            shutil.rmtree(orig_dest)
        shutil.copytree(src_dir, orig_dest)

        _write_local_metadata(meta_path, local_meta, existing_uuid, publish_tags)
        _cache["fetched_at"] = 0
        logger.info("Updated artifact %s (%s) with new version (visibility=%s)",
                    req.title, existing_uuid, req.visibility)

        return {
            "status": "updated",
            "uuid": existing_uuid,
            "title": req.title,
            "visibility": req.visibility,
            "version": version_info.get("version", ""),
        }

    elif req.action == "fork":
        # --- FORK: create new artifact with provenance ---
        if not existing_uuid:
            raise HTTPException(status_code=400, detail="Cannot fork: no artifact_uuid in local metadata")

        # Fetch remote info for provenance
        remote_title = ""
        remote_version = ""
        try:
            remote = await _fetch_artifact(existing_uuid)
            remote_title = remote.get("title", "")
            versions = remote.get("versions", [])
            if versions:
                active = [v for v in versions if v.get("active", True)]
                remote_version = (active[0] if active else versions[0]).get("version", "")
        except Exception:
            logger.warning("Could not fetch remote artifact %s for fork provenance", existing_uuid)

        # Write forked_from to local metadata before creating the new artifact
        local_meta["forked_from"] = {
            "artifact_uuid": existing_uuid,
            "version": remote_version,
            "title": remote_title,
        }
        # Clear the old artifact_uuid so _create_new_artifact starts fresh
        local_meta.pop("artifact_uuid", None)
        local_meta["source"] = "artifact-manager"
        with open(meta_path, "w") as f:
            json.dump(local_meta, f, indent=2)

        # Create new artifact
        result = await _create_new_artifact(headers, req, src_dir, desc_short,
                                            desc_long, publish_tags)
        new_uuid = result["uuid"]

        # Write the new uuid back
        _write_local_metadata(meta_path, local_meta, new_uuid, publish_tags)

        # Save .artifact-originals
        originals_dir = os.path.join(_storage_dir(), ".artifact-originals")
        os.makedirs(originals_dir, exist_ok=True)
        orig_dest = os.path.join(originals_dir, new_uuid)
        if os.path.exists(orig_dest):
            shutil.rmtree(orig_dest)
        shutil.copytree(src_dir, orig_dest)

        _cache["fetched_at"] = 0
        logger.info("Forked artifact %s from %s as %s", req.title, existing_uuid, new_uuid)

        result["forked_from"] = existing_uuid
        return result

    else:
        # --- CREATE NEW (no existing uuid, or legacy auto behavior) ---
        # If there's an existing_uuid but action is empty, this is the legacy
        # "auto" path. We still support it for backwards compat but the frontend
        # should now explicitly choose "update" or "fork".
        if existing_uuid:
            # Legacy auto path: check authorship to decide
            remote = None
            is_author = False
            try:
                remote = await _fetch_artifact(existing_uuid)
                user_email, user_name = _get_current_user_identity()
                is_author = _is_user_author(remote, user_email, user_name)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    logger.info("Remote artifact %s no longer exists — will create new", existing_uuid)
                else:
                    logger.warning("Failed to fetch remote artifact %s: %s", existing_uuid, e)
            except Exception as e:
                logger.warning("Failed to fetch remote artifact %s: %s", existing_uuid, e)

            if remote and is_author:
                # Auto-update
                update_body = {
                    "title": req.title,
                    "description_short": desc_short,
                    "description_long": desc_long,
                    "visibility": req.visibility,
                }
                if publish_tags:
                    update_body["tags"] = publish_tags
                if req.project_uuid:
                    update_body["project_uuid"] = req.project_uuid
                try:
                    r = await fabric_client.put(
                        f"{ARTIFACT_API}/artifacts/{existing_uuid}",
                        params={"format": "json"},
                        json=update_body,
                        headers=headers,
                    )
                    r.raise_for_status()
                except httpx.HTTPStatusError as e:
                    detail = e.response.text
                    raise HTTPException(status_code=e.response.status_code,
                                        detail=f"Failed to update artifact: {detail}")
                except Exception as e:
                    raise HTTPException(status_code=502,
                                        detail=f"Failed to update artifact: {e}")
                version_info = await _upload_content(headers, existing_uuid, src_dir, req.dir_name)
                originals_dir = os.path.join(_storage_dir(), ".artifact-originals")
                os.makedirs(originals_dir, exist_ok=True)
                orig_dest = os.path.join(originals_dir, existing_uuid)
                if os.path.exists(orig_dest):
                    shutil.rmtree(orig_dest)
                shutil.copytree(src_dir, orig_dest)
                _cache["fetched_at"] = 0
                return {
                    "status": "updated",
                    "uuid": existing_uuid,
                    "title": req.title,
                    "visibility": req.visibility,
                    "version": version_info.get("version", ""),
                }

            # Fall through to create new (fork without explicit provenance)
            logger.info("Creating new artifact (auto fork/re-create) — local had uuid %s", existing_uuid)

        result = await _create_new_artifact(headers, req, src_dir, desc_short,
                                            desc_long, publish_tags)
        new_uuid = result["uuid"]
        _write_local_metadata(meta_path, local_meta, new_uuid, publish_tags)

        originals_dir = os.path.join(_storage_dir(), ".artifact-originals")
        os.makedirs(originals_dir, exist_ok=True)
        orig_dest = os.path.join(originals_dir, new_uuid)
        if os.path.exists(orig_dest):
            shutil.rmtree(orig_dest)
        shutil.copytree(src_dir, orig_dest)

        _cache["fetched_at"] = 0
        logger.info("Published artifact %s as %s (visibility=%s)", req.title, new_uuid, req.visibility)

        return result


@router.get("/valid-tags")
async def list_valid_tags():
    """Return the set of tags accepted by the Artifact Manager for publishing."""
    headers = _get_auth_headers()
    try:
        r = await fabric_client.get(
            f"{ARTIFACT_API}/meta/tags",
            params={"format": "json"},
            headers=headers,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch tags: {e}")

    results = data.get("results", data if isinstance(data, list) else [])
    return {
        "tags": [
            {"tag": t["tag"] if isinstance(t, dict) else t, "restricted": t.get("restricted", False) if isinstance(t, dict) else False}
            for t in results
        ]
    }


# ---------------------------------------------------------------------------
# My Artifacts — annotated local artifacts + authorship info
# ---------------------------------------------------------------------------

@router.get("/my")
async def get_my_artifacts():
    """Return local artifacts annotated with remote authorship info.

    Cross-references local artifacts (which may have artifact_uuid from
    marketplace downloads) with the remote catalog, and identifies
    artifacts the current user authored.
    """
    user_email, user_name = _get_current_user_identity()

    # Gather local artifacts
    local_list = list_local_artifacts()["artifacts"]

    # Fetch remote catalog (cached)
    try:
        remote_list = await _fetch_all_artifacts()
    except Exception:
        remote_list = []

    remote_by_uuid: dict[str, dict] = {a["uuid"]: a for a in remote_list}

    # Build a set of remote UUIDs we have locally
    local_remote_uuids: set[str] = set()

    for art in local_list:
        art_uuid = art.get("artifact_uuid", "")
        if art_uuid and art_uuid in remote_by_uuid:
            remote = remote_by_uuid[art_uuid]
            art["remote_status"] = "linked"
            art["remote_artifact"] = remote
            art["is_author"] = _is_user_author(remote, user_email, user_name)
            local_remote_uuids.add(art_uuid)
        elif art_uuid:
            art["remote_status"] = "remote_deleted"
            art["is_author"] = False
            art["remote_artifact"] = None
        else:
            art["remote_status"] = "not_linked"
            art["is_author"] = False
            art["remote_artifact"] = None

    # Find remote artifacts the user authors but hasn't downloaded
    authored_remote_only = []
    for remote in remote_list:
        if remote["uuid"] in local_remote_uuids:
            continue
        if _is_user_author(remote, user_email, user_name):
            authored_remote_only.append(remote)

    return {
        "local_artifacts": local_list,
        "authored_remote_only": authored_remote_only,
        "user_email": user_email,
    }


def _is_user_author(remote_artifact: dict, user_email: str, user_name: str = "") -> bool:
    """Check if the current account authored a remote artifact.

    Matches by email only — different accounts (even for the same person)
    are treated as separate identities so each account sees only its own
    artifacts.
    """
    if not user_email:
        return False
    email_lower = user_email.lower()
    # Author-only visibility means the current user must be the author
    if remote_artifact.get("visibility") == "author":
        return True
    # Check created_by email
    created_by = remote_artifact.get("created_by") or {}
    created_email = (created_by.get("email") or "").lower()
    if created_email and created_email == email_lower:
        return True
    # Check author entry emails
    for author in remote_artifact.get("authors", []):
        author_email = (author.get("email") or "").lower()
        if author_email and author_email == email_lower:
            return True
    return False


# ---------------------------------------------------------------------------
# Update remote artifact settings
# ---------------------------------------------------------------------------

@router.put("/remote/{uuid}")
async def update_remote_artifact(uuid: str, req: UpdateArtifactRequest):
    """Update settings for a remote artifact the user authors."""
    headers = _get_auth_headers()
    if not headers:
        raise HTTPException(status_code=401, detail="No FABRIC token configured")

    update_body: dict[str, Any] = {}
    if req.title:
        update_body["title"] = req.title
    if req.description or req.description_long:
        desc_short, desc_long = _make_descriptions(req.description, req.title or "", req.category, req.description_long)
        update_body["description_short"] = desc_short
        update_body["description_long"] = desc_long
    if req.visibility:
        update_body["visibility"] = req.visibility
    if req.tags is not None:
        update_body["tags"] = _ensure_category_tag(list(req.tags), req.category)
    if req.project_uuid:
        update_body["project_uuid"] = req.project_uuid
    if req.authors:
        update_body["authors"] = req.authors

    if not update_body:
        raise HTTPException(status_code=400, detail="No fields to update")

    try:
        r = await fabric_client.put(
            f"{ARTIFACT_API}/artifacts/{uuid}",
            params={"format": "json"},
            json=update_body,
            headers=headers,
        )
        r.raise_for_status()
        updated = r.json()
    except httpx.HTTPStatusError as e:
        detail = e.response.text
        raise HTTPException(status_code=e.response.status_code, detail=f"Failed to update artifact: {detail}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to update artifact: {e}")

    _cache["fetched_at"] = 0
    logger.info("Updated artifact %s", uuid)

    updated["tags"] = _normalize_tags(updated.get("tags", []))
    updated["category"] = _classify_artifact(updated["tags"], updated.get("description_short", ""), updated.get("description_long", ""))
    return updated


# ---------------------------------------------------------------------------
# Upload new version of an existing remote artifact
# ---------------------------------------------------------------------------

@router.post("/remote/{uuid}/version")
async def upload_artifact_version(uuid: str, req: UploadVersionRequest):
    """Upload a new version for an existing remote artifact from a local directory."""
    headers = _get_auth_headers()
    if not headers:
        raise HTTPException(status_code=401, detail="No FABRIC token configured")

    src_dir = os.path.join(_artifacts_dir(), req.dir_name)
    if not os.path.isdir(src_dir):
        raise HTTPException(status_code=404, detail=f"Local artifact '{req.dir_name}' not found")

    with tempfile.TemporaryDirectory() as tmpdir:
        tar_path = os.path.join(tmpdir, f"{req.dir_name}.tar.gz")
        with tarfile.open(tar_path, "w:gz") as tf:
            tf.add(src_dir, arcname=req.dir_name)

        upload_data = json.dumps({
            "artifact": uuid,
            "storage_type": "fabric",
            "storage_repo": "renci",
        })

        try:
            with open(tar_path, "rb") as fh:
                r = await ai_client.post(
                    f"{ARTIFACT_API}/contents",
                    params={"format": "json"},
                    headers=headers,
                    files={"file": (f"{req.dir_name}.tar.gz", fh, "application/gzip")},
                    data={"data": upload_data},
                )
                r.raise_for_status()
                version_info = r.json()
        except httpx.HTTPStatusError as e:
            detail = e.response.text
            raise HTTPException(status_code=e.response.status_code, detail=f"Version upload failed: {detail}")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Version upload failed: {e}")

    _cache["fetched_at"] = 0
    logger.info("Uploaded new version for artifact %s from %s", uuid, req.dir_name)

    return {
        "status": "uploaded",
        "artifact_uuid": uuid,
        "version": version_info.get("version", ""),
    }


@router.delete("/remote/{uuid}/version/{version_uuid}")
async def delete_artifact_version(uuid: str, version_uuid: str):
    """Delete a specific version from a remote artifact."""
    headers = _get_auth_headers()
    if not headers:
        raise HTTPException(status_code=401, detail="No FABRIC token configured")
    try:
        r = await fabric_client.delete(
            f"{ARTIFACT_API}/contents/{version_uuid}",
            params={"format": "json"},
            headers=headers,
        )
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        detail = e.response.text
        raise HTTPException(status_code=e.response.status_code, detail=f"Failed to delete version: {detail}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to delete version: {e}")

    _cache["fetched_at"] = 0
    logger.info("Deleted version %s from artifact %s", version_uuid, uuid)
    return {"status": "deleted", "uuid": uuid, "version_uuid": version_uuid}


# ---------------------------------------------------------------------------
# Revert local artifact to a published version
# ---------------------------------------------------------------------------

@router.post("/local/{dir_name}/revert")
async def revert_local_artifact(dir_name: str, req: RevertRequest):
    """Revert a local artifact to a specific (or latest) published version.

    Downloads the version from the Artifact Manager and replaces all local
    files, preserving the artifact_uuid link in metadata.
    """
    # 1. Resolve local artifact directory
    local_dir = os.path.join(_artifacts_dir(), dir_name)
    if not os.path.isdir(local_dir):
        raise HTTPException(status_code=404, detail=f"Local artifact '{dir_name}' not found")

    # 2. Read metadata to get artifact_uuid from weave.json
    weave_path = os.path.join(local_dir, "weave.json")
    if not os.path.isfile(weave_path):
        raise HTTPException(status_code=400, detail="Local artifact has no weave.json — cannot determine remote link")

    try:
        with open(weave_path) as f:
            local_meta = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read weave.json: {e}")

    artifact_uuid = local_meta.get("artifact_uuid", "")
    if not artifact_uuid:
        raise HTTPException(
            status_code=400,
            detail="Local artifact is not linked to a remote artifact (no artifact_uuid in weave.json)",
        )

    # 3. Fetch remote artifact info
    try:
        art = await _fetch_artifact(artifact_uuid)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch remote artifact {artifact_uuid}: {e}")

    # 4. Find the version to download
    versions = art.get("versions", [])
    if not versions:
        raise HTTPException(status_code=404, detail="Remote artifact has no downloadable versions")

    if req.version_uuid:
        version = next((v for v in versions if v["uuid"] == req.version_uuid), None)
        if not version:
            raise HTTPException(status_code=404, detail=f"Version {req.version_uuid} not found on remote artifact")
    else:
        active = [v for v in versions if v.get("active", True)]
        version = active[0] if active else versions[0]

    urn = version.get("urn", "")
    if not urn:
        raise HTTPException(status_code=400, detail="Version has no downloadable URN")

    # 5. Download the tar.gz
    download_url = f"{ARTIFACT_API}/contents/download/{urn}"
    try:
        r = await ai_client.get(download_url, headers=_get_auth_headers())
        r.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Download failed: {e}")

    # 6. Extract to a temp directory
    with tempfile.TemporaryDirectory() as tmpdir:
        raw_path = os.path.join(tmpdir, "artifact_download")
        with open(raw_path, "wb") as f:
            f.write(r.content)

        extracted = False
        try:
            with tarfile.open(raw_path, "r:*") as tf:
                for member in tf.getmembers():
                    if member.name.startswith("/") or ".." in member.name:
                        raise HTTPException(status_code=400, detail="Artifact contains unsafe paths")
                extract_dir = os.path.join(tmpdir, "extracted")
                os.makedirs(extract_dir, exist_ok=True)
                tf.extractall(extract_dir)
                extracted = True
        except tarfile.TarError:
            pass

        # 7. Clear the local artifact directory completely
        for item in os.listdir(local_dir):
            item_path = os.path.join(local_dir, item)
            if os.path.isdir(item_path):
                shutil.rmtree(item_path)
            else:
                os.remove(item_path)

        if extracted:
            # Determine actual content root (handle single-directory tarballs)
            contents = os.listdir(extract_dir)
            if len(contents) == 1 and os.path.isdir(os.path.join(extract_dir, contents[0])):
                src_dir = os.path.join(extract_dir, contents[0])
            else:
                src_dir = extract_dir

            # 8. Copy extracted contents into the local artifact directory
            for item in os.listdir(src_dir):
                s = os.path.join(src_dir, item)
                d = os.path.join(local_dir, item)
                if os.path.isdir(s):
                    shutil.copytree(s, d)
                else:
                    shutil.copy2(s, d)
        else:
            # Not a recognized archive — drop the raw file for manual extraction
            content_type = r.headers.get("content-type", "")
            filename = dir_name
            if "zip" in content_type:
                filename += ".zip"
            elif "gzip" in content_type or "x-gzip" in content_type:
                filename += ".tar.gz"
            else:
                filename += ".bin"
            shutil.copy2(raw_path, os.path.join(local_dir, filename))

    # 9. Re-write weave.json preserving the artifact_uuid link
    tag_strs = _normalize_tags(art.get("tags", []))
    category = _detect_category(local_dir)
    weave_data: dict[str, Any] = {}
    revert_weave_path = os.path.join(local_dir, "weave.json")
    if os.path.isfile(revert_weave_path):
        try:
            with open(revert_weave_path) as f:
                weave_data = json.load(f)
        except Exception:
            pass
    weave_data.update({
        "name": art.get("title", dir_name),
        "description": art.get("description_long", "") or art.get("description_short", ""),
        "source": "artifact-manager",
        "artifact_uuid": artifact_uuid,
        "created": datetime.now(timezone.utc).isoformat(),
        "tags": tag_strs,
    })
    with open(revert_weave_path, "w") as f:
        json.dump(weave_data, f, indent=2)

    # 10. Update .artifact-originals with fresh copy (keyed by UUID)
    originals_dir = os.path.join(_storage_dir(), ".artifact-originals")
    os.makedirs(originals_dir, exist_ok=True)
    orig_dest = os.path.join(originals_dir, artifact_uuid)
    if os.path.exists(orig_dest):
        shutil.rmtree(orig_dest)
    shutil.copytree(local_dir, orig_dest)

    logger.info("Reverted local artifact '%s' to version %s", dir_name, version.get("uuid", "latest"))

    return {
        "status": "reverted",
        "dir_name": dir_name,
        "version": version.get("uuid", ""),
        "category": category,
    }


# ---------------------------------------------------------------------------
# Delete remote artifact
# ---------------------------------------------------------------------------

@router.delete("/remote/{uuid}")
async def delete_remote_artifact(uuid: str):
    """Delete a remote artifact from the FABRIC Artifact Manager."""
    headers = _get_auth_headers()
    if not headers:
        raise HTTPException(status_code=401, detail="No FABRIC token configured")

    try:
        r = await fabric_client.delete(
            f"{ARTIFACT_API}/artifacts/{uuid}",
            params={"format": "json"},
            headers=headers,
        )
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        detail = e.response.text
        raise HTTPException(status_code=e.response.status_code, detail=f"Failed to delete artifact: {detail}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to delete artifact: {e}")

    _cache["fetched_at"] = 0
    logger.info("Deleted remote artifact %s", uuid)

    return {"status": "deleted", "uuid": uuid}
