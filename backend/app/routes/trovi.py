"""Trovi marketplace routes — browse, search, and get Chameleon shared experiments."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tarfile
import tempfile
import urllib.parse
import urllib.request
import zipfile

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.tracking_headers import add_tracking_headers

logger = logging.getLogger(__name__)
router = APIRouter(tags=["trovi"])

TROVI_API = "https://trovi.chameleoncloud.org"


@router.get("/api/trovi/artifacts")
async def list_trovi_artifacts(q: str = "", tag: str = "", limit: int = 50, offset: int = 0):
    """Search/list Trovi artifacts."""
    try:
        url = f"{TROVI_API}/artifacts"
        req = urllib.request.Request(url, headers=add_tracking_headers({"Accept": "application/json"}))
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
        req = urllib.request.Request(url, headers=add_tracking_headers({"Accept": "application/json"}))
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
        req = urllib.request.Request(url, headers=add_tracking_headers({"Accept": "application/json"}))
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        tags: set[str] = set()
        for a in data.get("artifacts", []):
            for t in a.get("tags", []):
                tags.add(t)
        return {"tags": sorted(tags)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)


def _extract_archive(archive_path: str, dest_dir: str) -> bool:
    """Extract a tar/zip archive into dest_dir. Returns True on success.

    Handles both tar (.tar, .tar.gz, .tgz, .tar.bz2) and zip archives.
    Strips a single top-level directory if present (common in tarballs).
    """
    with tempfile.TemporaryDirectory() as tmp_extract:
        extracted = False

        # Try tar
        try:
            with tarfile.open(archive_path, "r:*") as tf:
                # Safety: reject paths with .. or absolute paths
                for member in tf.getmembers():
                    if member.name.startswith("/") or ".." in member.name:
                        raise ValueError(f"Unsafe path in archive: {member.name}")
                tf.extractall(tmp_extract)
                extracted = True
        except (tarfile.TarError, ValueError):
            pass

        # Try zip if tar failed
        if not extracted:
            try:
                with zipfile.ZipFile(archive_path, "r") as zf:
                    for name in zf.namelist():
                        if name.startswith("/") or ".." in name:
                            raise ValueError(f"Unsafe path in archive: {name}")
                    zf.extractall(tmp_extract)
                    extracted = True
            except (zipfile.BadZipFile, ValueError):
                pass

        if not extracted:
            return False

        # Strip single top-level directory if present
        contents = os.listdir(tmp_extract)
        if len(contents) == 1 and os.path.isdir(os.path.join(tmp_extract, contents[0])):
            src_root = os.path.join(tmp_extract, contents[0])
        else:
            src_root = tmp_extract

        for item in os.listdir(src_root):
            s = os.path.join(src_root, item)
            d = os.path.join(dest_dir, item)
            if os.path.isdir(s):
                if os.path.exists(d):
                    shutil.rmtree(d)
                shutil.copytree(s, d)
            else:
                shutil.copy2(s, d)
        return True


def _has_notebooks(directory: str) -> bool:
    """Check if a directory (recursively) contains any .ipynb files."""
    for root, _, files in os.walk(directory):
        if any(f.endswith(".ipynb") for f in files):
            return True
    return False


@router.post("/api/trovi/artifacts/{uuid}/get")
async def download_trovi_artifact(uuid: str, request: Request):
    """Download a Trovi artifact to my_artifacts/.

    Supports git, archive (tar/zip), and direct HTTP content URNs.
    Untars/unzips archive content into the artifact directory so files
    can be viewed and edited in JupyterLab. If .ipynb files are detected,
    the artifact is tagged as a notebook so it appears in the Notebooks tab.

    Always returns a 200 with a structured payload that includes
    `content_status` and `error_message` so the frontend can render a
    friendly toast and decide whether to auto-launch JupyterLab. The
    statuses are:
      - "extracted"        — tarball/zip downloaded and extracted OK
      - "git-cloned"       — git URN cloned OK
      - "metadata-only"    — artifact has no content version (nothing to fetch)
      - "download-failed"  — contents-meta fetch or tarball download raised
      - "extraction-failed"— downloaded but archive could not be extracted
      - "no-access-method" — version exists but Trovi exposed no HTTP method
      - "git-clone-failed" — git URN, but git clone failed
      - "error"            — unexpected error before/around the download path
    Only true server faults return non-200.
    """
    error_message: str | None = None
    try:
        # Fetch artifact details
        url = f"{TROVI_API}/artifacts/{uuid}"
        req = urllib.request.Request(url, headers=add_tracking_headers({"Accept": "application/json"}))
        with urllib.request.urlopen(req, timeout=15) as resp:
            artifact = json.loads(resp.read())

        title = artifact.get("title", "trovi-artifact")
        # Sanitize for directory name
        dir_name = "".join(c if c.isalnum() or c in "-_ " else "" for c in title).strip().replace(" ", "_")[:50]
        if not dir_name:
            dir_name = f"trovi-{uuid[:8]}"

        from app.settings_manager import get_artifacts_dir
        artifacts_dir = get_artifacts_dir()
        dest = os.path.join(artifacts_dir, dir_name)
        os.makedirs(dest, exist_ok=True)

        # Get latest version's slug and contents URN
        versions = artifact.get("versions", [])
        latest_version = versions[-1] if versions else {}
        contents_urn = latest_version.get("contents", {}).get("urn", "")
        version_slug = latest_version.get("slug", "")

        # Default: no version means there's literally nothing to download
        content_status = "metadata-only"

        if contents_urn.startswith("urn:trovi:contents:git:"):
            # Git URN: clone the repo
            git_url = contents_urn.replace("urn:trovi:contents:git:", "")
            if "@" in git_url:
                repo_url, _commit = git_url.rsplit("@", 1)
            else:
                repo_url = git_url
            try:
                # Clone into a temp dir then move contents (git clone needs empty target)
                with tempfile.TemporaryDirectory() as tmp_clone:
                    clone_target = os.path.join(tmp_clone, "repo")
                    result = subprocess.run(
                        ["git", "clone", "--depth=1", repo_url, clone_target],
                        timeout=120, capture_output=True, check=False,
                    )
                    if result.returncode == 0 and os.path.isdir(clone_target):
                        for item in os.listdir(clone_target):
                            if item == ".git":
                                continue
                            s = os.path.join(clone_target, item)
                            d = os.path.join(dest, item)
                            if os.path.isdir(s):
                                if os.path.exists(d):
                                    shutil.rmtree(d)
                                shutil.copytree(s, d)
                            else:
                                shutil.copy2(s, d)
                        content_status = "git-cloned"
                    else:
                        content_status = "git-clone-failed"
                        error_message = f"git clone failed: {result.stderr.decode(errors='replace')[:300]}"
                        logger.warning("Trovi git clone failed for %s: %s", repo_url, error_message)
            except Exception as clone_err:
                content_status = "git-clone-failed"
                error_message = f"git clone error: {clone_err}"
                logger.warning("Trovi git clone error for %s: %s", repo_url, clone_err)

        elif version_slug:
            # Use the Trovi /artifacts/{uuid}/versions/{slug}/contents endpoint
            # to get a temporary signed download URL for the content tarball.
            # Each step is attributed individually so the user gets a clear
            # error message instead of a silent metadata-only fallback.
            download_url = None
            try:
                contents_meta_url = f"{TROVI_API}/artifacts/{uuid}/versions/{version_slug}/contents"
                req = urllib.request.Request(contents_meta_url, headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    contents_meta = json.loads(resp.read())
                for method in contents_meta.get("access_methods", []):
                    if method.get("protocol") == "http" and method.get("url"):
                        download_url = method["url"]
                        break
            except Exception as meta_err:
                content_status = "download-failed"
                error_message = f"contents metadata fetch failed: {meta_err}"
                logger.warning("Trovi contents-meta fetch failed for %s: %s", uuid, meta_err)

            if download_url and content_status == "metadata-only":
                archive_path: str | None = None
                try:
                    logger.info("Trovi: downloading content for %s", uuid)
                    req = urllib.request.Request(download_url)
                    with urllib.request.urlopen(req, timeout=300) as resp:
                        content_bytes = resp.read()
                    with tempfile.NamedTemporaryFile(suffix=".archive", delete=False) as tmp_f:
                        tmp_f.write(content_bytes)
                        archive_path = tmp_f.name
                except Exception as dl_err:
                    content_status = "download-failed"
                    error_message = f"tarball download failed: {dl_err}"
                    logger.warning("Trovi tarball download failed for %s: %s", uuid, dl_err)

                if archive_path is not None and content_status == "metadata-only":
                    try:
                        if _extract_archive(archive_path, dest):
                            content_status = "extracted"
                            logger.info("Trovi: extracted %d bytes for %s", len(content_bytes), uuid)
                        else:
                            # Save the raw archive so user can extract manually
                            try:
                                shutil.copy2(archive_path, os.path.join(dest, "content.tar.gz"))
                            except Exception:
                                pass
                            content_status = "extraction-failed"
                            error_message = (
                                f"downloaded {len(content_bytes)} bytes but the archive is "
                                "not a recognized tar/zip format; saved as content.tar.gz"
                            )
                            logger.warning(
                                "Trovi content for %s is not a recognized archive (%d bytes)",
                                uuid, len(content_bytes),
                            )
                    except Exception as ex_err:
                        content_status = "extraction-failed"
                        error_message = f"extraction error: {ex_err}"
                        logger.warning("Trovi extraction error for %s: %s", uuid, ex_err)
                    finally:
                        try:
                            os.unlink(archive_path)
                        except OSError:
                            pass
            elif download_url is None and content_status == "metadata-only":
                content_status = "no-access-method"
                error_message = "Trovi did not expose an HTTP download method for this version"
                logger.warning("Trovi: no HTTP access method for %s", uuid)

        # If extraction succeeded, blow away any stale JupyterLab working
        # copy at notebooks/{dir_name}/ so the next launch creates a fresh
        # copy from the freshly-extracted files. (See jupyter.launch_notebook.)
        if content_status in ("extracted", "git-cloned"):
            try:
                from app.routes.jupyter import _notebooks_workdir, _sanitize_name
                stale_workdir = os.path.join(_notebooks_workdir(), _sanitize_name(dir_name))
                if os.path.isdir(stale_workdir):
                    shutil.rmtree(stale_workdir, ignore_errors=True)
            except Exception as cleanup_err:
                logger.warning("Trovi: failed to clean stale notebook workdir: %s", cleanup_err)

        # All Trovi artifacts are categorized as notebooks (Chameleon's
        # primary use case for Trovi is sharing Jupyter notebook experiments)
        is_notebook = True
        has_ipynb = _has_notebooks(dest)
        tags = list(artifact.get("tags", []))
        if "loomai:notebook" not in tags:
            tags.append("loomai:notebook")

        # Write weave.json with Trovi metadata (after extraction so it isn't overwritten)
        weave_meta = {
            "name": title,
            "description": artifact.get("short_description", ""),
            "description_long": artifact.get("long_description", ""),
            "source": "trovi",
            "source_marketplace": "trovi",
            "trovi_uuid": uuid,
            "tags": tags,
            "category": "notebook",
            "has_ipynb": has_ipynb,
            "authors": [a.get("full_name", "") for a in artifact.get("authors", [])],
            "created_at": artifact.get("created_at"),
            "content_status": content_status,
            "error_message": error_message,
            "versions": [{
                "slug": v.get("slug"),
                "contents_urn": v.get("contents", {}).get("urn", ""),
            } for v in artifact.get("versions", [])],
        }
        with open(os.path.join(dest, "weave.json"), "w") as f:
            json.dump(weave_meta, f, indent=2)

        return {
            "status": "downloaded",
            "dir_name": dir_name,
            "title": title,
            "source": "trovi",
            "category": weave_meta["category"],
            "content_status": content_status,
            "error_message": error_message,
            "has_ipynb": has_ipynb,
            "is_notebook": is_notebook,
        }

    except Exception as e:
        logger.warning("Trovi download error: %s", e)
        # Return 200 with structured error so the frontend can show a
        # friendly toast instead of a generic HTTP error popup.
        return {
            "status": "error",
            "dir_name": "",
            "title": "",
            "source": "trovi",
            "category": "notebook",
            "content_status": "error",
            "error_message": str(e),
            "has_ipynb": False,
            "is_notebook": True,
        }
