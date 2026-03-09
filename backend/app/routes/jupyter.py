"""JupyterLab server management — single instance using the base work dir."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import signal
import subprocess

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.user_context import get_user_storage

router = APIRouter(tags=["jupyter"])
logger = logging.getLogger(__name__)

_JUPYTER_PORT = 8889
_jupyter_proc: subprocess.Popen | None = None


def _workdir() -> str:
    d = get_user_storage()
    os.makedirs(d, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Slice working-directory helpers (called from slices.py / templates.py)
# ---------------------------------------------------------------------------

def ensure_slice_workdir(slice_name: str) -> str:
    """Create a per-slice working directory if it doesn't exist.

    Returns the absolute path.
    """
    d = os.path.join(_workdir(), slice_name)
    os.makedirs(d, exist_ok=True)
    return d


def seed_slice_workdir_from_template(slice_name: str, template_dir: str) -> None:
    """Copy template artifacts into the slice working directory.

    Skips files that already exist so user edits are never overwritten.
    """
    import shutil

    dest = ensure_slice_workdir(slice_name)
    if not os.path.isdir(template_dir):
        return

    for item in os.listdir(template_dir):
        src = os.path.join(template_dir, item)
        dst = os.path.join(dest, item)
        if os.path.exists(dst):
            continue
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    logger.info("Seeded workdir %s from template %s", dest, template_dir)


# ---------------------------------------------------------------------------
# JupyterLab lifecycle
# ---------------------------------------------------------------------------

async def _stop_jupyter() -> None:
    global _jupyter_proc
    if _jupyter_proc and _jupyter_proc.poll() is None:
        try:
            os.killpg(os.getpgid(_jupyter_proc.pid), signal.SIGTERM)
            _jupyter_proc.wait(timeout=5)
        except Exception:
            try:
                _jupyter_proc.kill()
            except Exception:
                pass
    _jupyter_proc = None


@router.post("/api/jupyter/start")
async def start_jupyter():
    """Start JupyterLab rooted at the base work directory."""
    global _jupyter_proc

    if _jupyter_proc and _jupyter_proc.poll() is None:
        return {"port": _JUPYTER_PORT, "status": "running"}

    workdir = _workdir()

    cmd = [
        "jupyter", "lab",
        "--no-browser",
        "--ip=0.0.0.0",
        f"--port={_JUPYTER_PORT}",
        "--ServerApp.token=",
        "--ServerApp.password=",
        "--ServerApp.disable_check_xsrf=True",
        "--ServerApp.allow_origin=*",
        "--ServerApp.allow_remote_access=True",
        "--ServerApp.base_url=/jupyter/",
        f"--ServerApp.root_dir={workdir}",
    ]

    env = {**os.environ}

    try:
        _jupyter_proc = subprocess.Popen(
            cmd, cwd=workdir, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid,
        )
        logger.info("JupyterLab started pid=%d on :%d workdir=%s",
                     _jupyter_proc.pid, _JUPYTER_PORT, workdir)
    except Exception:
        logger.exception("Failed to start JupyterLab")
        return {"error": "Failed to start JupyterLab — is jupyterlab installed?",
                "status": "error"}

    await asyncio.sleep(2)
    return {"port": _JUPYTER_PORT, "status": "running"}


@router.post("/api/jupyter/stop")
async def stop_jupyter():
    """Stop the running JupyterLab server."""
    await _stop_jupyter()
    return {"status": "stopped"}


@router.get("/api/jupyter/status")
async def jupyter_status():
    """Check JupyterLab server status."""
    running = _jupyter_proc is not None and _jupyter_proc.poll() is None
    return {
        "port": _JUPYTER_PORT if running else None,
        "status": "running" if running else "stopped",
    }


class ThemeRequest(BaseModel):
    theme: str  # "dark" or "light"


@router.post("/api/jupyter/theme")
async def set_jupyter_theme(req: ThemeRequest):
    """Set JupyterLab theme via its settings API."""
    running = _jupyter_proc is not None and _jupyter_proc.poll() is None
    if not running:
        return {"status": "not_running"}

    jlab_theme = "JupyterLab Dark" if req.theme == "dark" else "JupyterLab Light"
    settings_url = f"http://127.0.0.1:{_JUPYTER_PORT}/jupyter/lab/api/settings/@jupyterlab/apputils-extension:themes"

    import httpx
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.put(
                settings_url,
                json={"raw": json.dumps({"theme": jlab_theme})},
            )
            r.raise_for_status()
    except Exception as e:
        logger.warning("Failed to set JupyterLab theme: %s", e)
        return {"status": "error", "detail": str(e)}

    return {"status": "ok", "theme": jlab_theme}


# ---------------------------------------------------------------------------
# Notebook artifact lifecycle — launch, reset, status, publish-fork
# ---------------------------------------------------------------------------

def _notebooks_workdir() -> str:
    """Return the notebooks workspace root inside the JupyterLab work dir."""
    d = os.path.join(_workdir(), "notebooks")
    os.makedirs(d, exist_ok=True)
    return d


def _originals_dir() -> str:
    storage = get_user_storage()
    d = os.path.join(storage, ".artifact-originals")
    os.makedirs(d, exist_ok=True)
    return d


def _artifacts_dir() -> str:
    from app.user_context import get_artifacts_dir
    return get_artifacts_dir()


def _sanitize_name(name: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", name.strip())
    if not safe:
        raise HTTPException(status_code=400, detail="Invalid name")
    return safe


def _read_artifact_uuid(artifact_dir: str) -> str:
    """Read the artifact_uuid from metadata.json in an artifact directory."""
    meta_path = os.path.join(artifact_dir, "metadata.json")
    if os.path.isfile(meta_path):
        try:
            with open(meta_path) as f:
                return json.load(f).get("artifact_uuid", "")
        except Exception:
            pass
    return ""


@router.post("/api/notebooks/{name}/launch")
async def launch_notebook(name: str):
    """Launch a notebook artifact in JupyterLab.

    - Ensures a working copy exists in work/notebooks/{name}/
    - If no working copy exists, copies from work/my_artifacts/{name}/
    - Starts JupyterLab if not running
    - Returns the URL path to open in the iframe
    """
    safe = _sanitize_name(name)
    artifact_dir = os.path.join(_artifacts_dir(), safe)
    if not os.path.isdir(artifact_dir):
        raise HTTPException(status_code=404, detail=f"Notebook artifact '{name}' not found")

    # Create working copy if it doesn't exist
    work_dir = os.path.join(_notebooks_workdir(), safe)
    if not os.path.isdir(work_dir):
        shutil.copytree(artifact_dir, work_dir)
        logger.info("Created notebook workspace %s from %s", work_dir, artifact_dir)

    # Also ensure we have a clean original copy for reset (keyed by UUID if available)
    artifact_uuid = _read_artifact_uuid(artifact_dir)
    orig_key = artifact_uuid or safe
    orig_dir = os.path.join(_originals_dir(), orig_key)
    if not os.path.isdir(orig_dir):
        shutil.copytree(artifact_dir, orig_dir)

    # Start JupyterLab if not running
    result = await start_jupyter()
    if result.get("status") != "running":
        return {"error": "Failed to start JupyterLab", "status": "error"}

    # Determine which .ipynb file to open (first one found)
    notebook_file = ""
    try:
        for f in sorted(os.listdir(work_dir)):
            if f.endswith(".ipynb"):
                notebook_file = f
                break
    except OSError:
        pass

    # Build the Jupyter URL path
    if notebook_file:
        jupyter_path = f"/jupyter/lab/tree/notebooks/{safe}/{notebook_file}"
    else:
        jupyter_path = f"/jupyter/lab/tree/notebooks/{safe}"

    return {
        "status": "running",
        "port": _JUPYTER_PORT,
        "jupyter_path": jupyter_path,
        "work_dir": f"notebooks/{safe}",
        "has_working_copy": True,
    }


@router.post("/api/notebooks/{name}/reset")
async def reset_notebook(name: str):
    """Reset a notebook workspace to the clean original copy.

    Deletes the working copy and replaces it with the original.
    """
    safe = _sanitize_name(name)
    work_dir = os.path.join(_notebooks_workdir(), safe)
    artifact_dir = os.path.join(_artifacts_dir(), safe)

    # Find the source for reset: prefer .artifact-originals (by UUID, then name), fall back to artifacts dir
    artifact_uuid = _read_artifact_uuid(artifact_dir)
    source = None
    for key in [artifact_uuid, safe] if artifact_uuid else [safe]:
        candidate = os.path.join(_originals_dir(), key)
        if os.path.isdir(candidate):
            source = candidate
            break
    if source is None:
        source = artifact_dir
    if not os.path.isdir(source):
        raise HTTPException(status_code=404, detail=f"No original copy found for '{name}'")

    # Remove existing workspace
    if os.path.isdir(work_dir):
        shutil.rmtree(work_dir)

    # Copy fresh from original
    shutil.copytree(source, work_dir)
    logger.info("Reset notebook workspace %s from %s", work_dir, source)

    return {"status": "reset", "name": safe}


@router.get("/api/notebooks/{name}/status")
async def notebook_status(name: str):
    """Check if a notebook has a working copy and if it's been modified."""
    safe = _sanitize_name(name)
    work_dir = os.path.join(_notebooks_workdir(), safe)
    orig_dir = os.path.join(_originals_dir(), safe)
    artifact_dir = os.path.join(_artifacts_dir(), safe)

    has_workspace = os.path.isdir(work_dir)
    has_original = os.path.isdir(orig_dir) or os.path.isdir(artifact_dir)

    return {
        "name": safe,
        "has_workspace": has_workspace,
        "has_original": has_original,
    }


class PublishForkRequest(BaseModel):
    title: str
    description: str = ""
    visibility: str = "author"
    project_uuid: str = ""
    tags: list[str] = []


@router.post("/api/notebooks/{name}/publish-fork")
async def publish_fork(name: str, req: PublishForkRequest):
    """Publish the working copy as a forked artifact.

    Reads the original artifact_uuid from metadata.json and includes
    fork provenance in the new artifact's metadata.
    """
    safe = _sanitize_name(name)
    work_dir = os.path.join(_notebooks_workdir(), safe)
    if not os.path.isdir(work_dir):
        raise HTTPException(status_code=404, detail=f"No workspace for '{name}' — launch it first")

    # Read original metadata for fork provenance
    artifact_dir = os.path.join(_artifacts_dir(), safe)
    original_uuid = ""
    original_title = ""
    meta_path = os.path.join(artifact_dir, "metadata.json")
    if os.path.isfile(meta_path):
        try:
            with open(meta_path) as f:
                meta = json.load(f)
            original_uuid = meta.get("artifact_uuid", "")
            original_title = meta.get("name", safe)
        except Exception:
            pass

    # Update the workspace metadata with fork info before publishing
    work_meta_path = os.path.join(work_dir, "metadata.json")
    work_meta = {}
    if os.path.isfile(work_meta_path):
        try:
            with open(work_meta_path) as f:
                work_meta = json.load(f)
        except Exception:
            pass

    work_meta["name"] = req.title
    work_meta["description"] = req.description
    if original_uuid:
        work_meta["forked_from"] = {
            "artifact_uuid": original_uuid,
            "title": original_title,
            "url": f"https://artifacts.fabric-testbed.net/api/artifacts/{original_uuid}",
        }

    with open(work_meta_path, "w") as f:
        json.dump(work_meta, f, indent=2)

    # Use the artifacts publish flow
    from app.routes.artifacts import _get_auth_headers, ARTIFACT_API, _cache
    import httpx
    import tarfile
    import tempfile

    headers = _get_auth_headers()
    if not headers:
        raise HTTPException(status_code=401, detail="No FABRIC token configured — cannot publish")

    # Step 1: Create artifact record (include title and tags upfront)
    from app.routes.artifacts import _make_descriptions
    desc_short, desc_long = _make_descriptions(req.description, req.title, "notebook")
    create_body = {
        "title": req.title,
        "description_short": desc_short,
        "description_long": desc_long,
        "visibility": req.visibility,
        "tags": list(req.tags) if req.tags else [],
    }
    if req.project_uuid:
        create_body["project_uuid"] = req.project_uuid

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                f"{ARTIFACT_API}/artifacts",
                params={"format": "json"},
                json=create_body,
                headers=headers,
            )
            r.raise_for_status()
            created = r.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code,
                          detail=f"Failed to create artifact: {e.response.text}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to create artifact: {e}")

    artifact_uuid = created["uuid"]

    # Step 2: Update with title and tags
    update_body = {
        "title": req.title,
        "description_short": desc_short,
        "description_long": desc_long,
        "visibility": req.visibility,
        "tags": list(req.tags) if req.tags else [],
    }
    if req.project_uuid:
        update_body["project_uuid"] = req.project_uuid

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.put(
                f"{ARTIFACT_API}/artifacts/{artifact_uuid}",
                params={"format": "json"},
                json=update_body,
                headers=headers,
            )
            r.raise_for_status()
    except Exception as e:
        logger.warning("Failed to update artifact %s title/tags: %s", artifact_uuid, e)

    # Step 3: Package and upload
    with tempfile.TemporaryDirectory() as tmpdir:
        tar_path = os.path.join(tmpdir, f"{safe}.tar.gz")
        with tarfile.open(tar_path, "w:gz") as tf:
            tf.add(work_dir, arcname=safe)

        upload_data = json.dumps({
            "artifact": artifact_uuid,
            "storage_type": "fabric",
            "storage_repo": "renci",
        })

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                with open(tar_path, "rb") as fh:
                    r = await client.post(
                        f"{ARTIFACT_API}/contents",
                        params={"format": "json"},
                        headers=headers,
                        files={"file": (f"{safe}.tar.gz", fh, "application/gzip")},
                        data={"data": upload_data},
                    )
                    r.raise_for_status()
                    version_info = r.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code,
                              detail=f"Content upload failed: {e.response.text}")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Content upload failed: {e}")

    _cache["fetched_at"] = 0
    logger.info("Published fork of %s as %s", name, artifact_uuid)

    return {
        "status": "published",
        "uuid": artifact_uuid,
        "title": req.title,
        "forked_from": original_uuid or None,
    }
