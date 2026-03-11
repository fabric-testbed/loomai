"""Runnable weave management API routes.

Runnable weaves are weave artifacts that also have run.sh for automatic execution.
A runnable weave is detected by having: slice.json + deploy.sh + run.sh.

Storage: FABRIC_STORAGE_DIR/my_artifacts/{name}/
"""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.user_context import get_user_storage

logger = __import__("logging").getLogger(__name__)
router = APIRouter(prefix="/api/experiments", tags=["experiments"])


# ---------------------------------------------------------------------------
# Directory helpers
# ---------------------------------------------------------------------------

def _experiments_dir() -> str:
    from app.user_context import get_artifacts_dir
    return get_artifacts_dir()


def _sanitize_name(name: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", name.strip())
    if not safe:
        raise HTTPException(status_code=400, detail="Invalid experiment name")
    return safe


def _validate_path(base: str, name: str) -> str:
    path = os.path.realpath(os.path.join(base, name))
    if not path.startswith(os.path.realpath(base)):
        raise HTTPException(status_code=400, detail="Invalid experiment name")
    return path


def _ensure_dir() -> None:
    """Ensure the experiments storage directory exists."""
    os.makedirs(_experiments_dir(), exist_ok=True)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class CreateExperimentRequest(BaseModel):
    name: str
    description: str = ""
    author: str = ""
    tags: list[str] = []
    slice_name: str = ""  # optional: export current slice as the template


class UpdateExperimentRequest(BaseModel):
    description: str | None = None
    author: str | None = None
    tags: list[str] | None = None


class ScriptFileBody(BaseModel):
    content: str


class ReadmeBody(BaseModel):
    content: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
def list_experiments() -> list[dict[str, Any]]:
    """List runnable weaves (weave artifacts that also have run.sh)."""
    _ensure_dir()
    edir = _experiments_dir()
    if not os.path.isdir(edir):
        return []
    results = []
    for entry in sorted(os.listdir(edir)):
        entry_dir = os.path.join(edir, entry)
        if not os.path.isdir(entry_dir):
            continue
        # An experiment is a slice artifact with run.sh
        if not os.path.isfile(os.path.join(entry_dir, "slice.json")):
            continue
        if not os.path.isfile(os.path.join(entry_dir, "deploy.sh")):
            continue
        if not os.path.isfile(os.path.join(entry_dir, "run.sh")):
            continue  # Not a runnable experiment

        # Read metadata from experiment.json or metadata.json
        meta: dict[str, Any] = {}
        for meta_file in ["experiment.json", "metadata.json"]:
            mpath = os.path.join(entry_dir, meta_file)
            if os.path.isfile(mpath):
                try:
                    with open(mpath) as f:
                        meta = json.load(f)
                except Exception:
                    pass
                break

        meta["dir_name"] = entry
        meta.setdefault("name", entry)
        # Count scripts
        scripts_dir = os.path.join(entry_dir, "scripts")
        meta["script_count"] = len(os.listdir(scripts_dir)) if os.path.isdir(scripts_dir) else 0
        meta["has_template"] = True
        meta["has_readme"] = os.path.isfile(os.path.join(entry_dir, "README.md"))
        results.append(meta)
    results.sort(key=lambda m: m.get("name", "").lower())
    return results


@router.post("")
def create_experiment(req: CreateExperimentRequest) -> dict[str, Any]:
    """Create a new experiment."""
    _ensure_dir()
    safe_name = _sanitize_name(req.name)
    edir = _experiments_dir()
    os.makedirs(edir, exist_ok=True)
    exp_dir = _validate_path(edir, safe_name)

    if os.path.isdir(exp_dir):
        raise HTTPException(status_code=409, detail=f"Experiment '{req.name}' already exists")

    os.makedirs(exp_dir, exist_ok=True)
    os.makedirs(os.path.join(exp_dir, "scripts"), exist_ok=True)

    metadata = {
        "name": req.name,
        "description": req.description,
        "author": req.author,
        "tags": req.tags,
        "created": datetime.now(timezone.utc).isoformat(),
    }

    # If a slice_name is provided, export it as the template
    if req.slice_name:
        try:
            from app.routes.slices import build_slice_model
            model = build_slice_model(req.slice_name)
            model["name"] = req.name
            with open(os.path.join(exp_dir, "slice.json"), "w") as f:
                json.dump(model, f, indent=2)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to export slice: {e}")

    with open(os.path.join(exp_dir, "experiment.json"), "w") as f:
        json.dump(metadata, f, indent=2)

    # Create a starter README
    readme = f"# {req.name}\n\n{req.description}\n"
    with open(os.path.join(exp_dir, "README.md"), "w") as f:
        f.write(readme)

    metadata["dir_name"] = safe_name
    return metadata


@router.get("/{name}")
def get_experiment(name: str) -> dict[str, Any]:
    """Get full experiment detail."""
    _ensure_dir()
    safe = _sanitize_name(name)
    edir = _experiments_dir()
    exp_dir = _validate_path(edir, safe)
    meta_path = os.path.join(exp_dir, "experiment.json")
    if not os.path.isfile(meta_path):
        raise HTTPException(status_code=404, detail=f"Experiment '{name}' not found")

    with open(meta_path) as f:
        meta = json.load(f)
    meta["dir_name"] = safe

    # Include README
    readme_path = os.path.join(exp_dir, "README.md")
    meta["readme"] = ""
    if os.path.isfile(readme_path):
        with open(readme_path) as f:
            meta["readme"] = f.read()

    # Include script listing
    scripts_dir = os.path.join(exp_dir, "scripts")
    meta["scripts"] = []
    if os.path.isdir(scripts_dir):
        meta["scripts"] = [{"filename": fn} for fn in sorted(os.listdir(scripts_dir))
                           if os.path.isfile(os.path.join(scripts_dir, fn))]

    # Include template info
    tmpl_path = os.path.join(exp_dir, "slice.json")
    meta["has_template"] = os.path.isfile(tmpl_path)
    if meta["has_template"]:
        with open(tmpl_path) as f:
            tmpl = json.load(f)
        meta["node_count"] = len(tmpl.get("nodes", []))
        meta["network_count"] = len(tmpl.get("networks", []))

    return meta


@router.put("/{name}")
def update_experiment(name: str, req: UpdateExperimentRequest) -> dict[str, Any]:
    """Update experiment metadata."""
    safe = _sanitize_name(name)
    edir = _experiments_dir()
    exp_dir = _validate_path(edir, safe)
    meta_path = os.path.join(exp_dir, "experiment.json")
    if not os.path.isfile(meta_path):
        raise HTTPException(status_code=404, detail=f"Experiment '{name}' not found")

    with open(meta_path) as f:
        meta = json.load(f)

    if req.description is not None:
        meta["description"] = req.description
    if req.author is not None:
        meta["author"] = req.author
    if req.tags is not None:
        meta["tags"] = req.tags

    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    meta["dir_name"] = safe
    return meta


@router.delete("/{name}")
def delete_experiment(name: str) -> dict[str, str]:
    """Delete an experiment."""
    safe = _sanitize_name(name)
    edir = _experiments_dir()
    exp_dir = _validate_path(edir, safe)
    if not os.path.isdir(exp_dir):
        raise HTTPException(status_code=404, detail=f"Experiment '{name}' not found")
    shutil.rmtree(exp_dir)
    return {"status": "deleted", "name": name}


# ---------------------------------------------------------------------------
# README endpoint
# ---------------------------------------------------------------------------

@router.get("/{name}/readme")
def get_readme(name: str) -> dict[str, str]:
    safe = _sanitize_name(name)
    edir = _experiments_dir()
    exp_dir = _validate_path(edir, safe)
    readme_path = os.path.join(exp_dir, "README.md")
    if not os.path.isfile(readme_path):
        return {"content": ""}
    with open(readme_path) as f:
        return {"content": f.read()}


@router.put("/{name}/readme")
def update_readme(name: str, body: ReadmeBody) -> dict[str, str]:
    safe = _sanitize_name(name)
    edir = _experiments_dir()
    exp_dir = _validate_path(edir, safe)
    if not os.path.isdir(exp_dir):
        raise HTTPException(status_code=404, detail=f"Experiment '{name}' not found")
    with open(os.path.join(exp_dir, "README.md"), "w") as f:
        f.write(body.content)
    return {"status": "saved"}


# ---------------------------------------------------------------------------
# Script endpoints
# ---------------------------------------------------------------------------

def _validate_script_filename(filename: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_\-.]", "_", filename.strip())
    if not safe or safe.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid script filename")
    return safe


@router.get("/{name}/scripts/{filename}")
def read_script(name: str, filename: str) -> dict[str, str]:
    safe = _sanitize_name(name)
    safe_file = _validate_script_filename(filename)
    edir = _experiments_dir()
    exp_dir = _validate_path(edir, safe)
    script_path = os.path.join(exp_dir, "scripts", safe_file)
    if not os.path.isfile(script_path):
        raise HTTPException(status_code=404, detail=f"Script '{filename}' not found")
    with open(script_path) as f:
        return {"filename": safe_file, "content": f.read()}


@router.put("/{name}/scripts/{filename}")
def write_script(name: str, filename: str, body: ScriptFileBody) -> dict[str, str]:
    safe = _sanitize_name(name)
    safe_file = _validate_script_filename(filename)
    edir = _experiments_dir()
    exp_dir = _validate_path(edir, safe)
    if not os.path.isdir(exp_dir):
        raise HTTPException(status_code=404, detail=f"Experiment '{name}' not found")
    scripts_dir = os.path.join(exp_dir, "scripts")
    os.makedirs(scripts_dir, exist_ok=True)
    with open(os.path.join(scripts_dir, safe_file), "w") as f:
        f.write(body.content)
    return {"filename": safe_file, "status": "saved"}


@router.delete("/{name}/scripts/{filename}")
def delete_script(name: str, filename: str) -> dict[str, str]:
    safe = _sanitize_name(name)
    safe_file = _validate_script_filename(filename)
    edir = _experiments_dir()
    exp_dir = _validate_path(edir, safe)
    script_path = os.path.join(exp_dir, "scripts", safe_file)
    if not os.path.isfile(script_path):
        raise HTTPException(status_code=404, detail=f"Script '{filename}' not found")
    os.remove(script_path)
    return {"filename": safe_file, "status": "deleted"}


# ---------------------------------------------------------------------------
# Load experiment as a slice
# ---------------------------------------------------------------------------

@router.post("/{name}/load")
def load_experiment(name: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load an experiment's template as a new draft slice."""
    _ensure_dir()
    safe = _sanitize_name(name)
    edir = _experiments_dir()
    exp_dir = _validate_path(edir, safe)
    tmpl_path = os.path.join(exp_dir, "slice.json")
    if not os.path.isfile(tmpl_path):
        raise HTTPException(status_code=404, detail=f"Experiment '{name}' has no template")

    with open(tmpl_path) as f:
        model_data = json.load(f)

    slice_name = (body or {}).get("slice_name", "").strip() if body else ""
    if not slice_name:
        slice_name = model_data.get("name", name)
    model_data["name"] = slice_name

    # Inject scripts as boot config uploads (similar to template tools)
    scripts_dir = os.path.join(exp_dir, "scripts")
    if os.path.isdir(scripts_dir) and os.listdir(scripts_dir):
        for node_def in model_data.get("nodes", []):
            bc = node_def.get("boot_config")
            if bc and isinstance(bc, dict):
                uploads = bc.setdefault("uploads", [])
                uploads.insert(0, {
                    "id": "experiment-scripts",
                    "source": scripts_dir,
                    "dest": "~/scripts",
                })

    from app.routes.slices import import_slice, SliceModelImport, _get_site_groups, _get_draft, _store_site_groups, _serialize
    model = SliceModelImport(**model_data)
    result = import_slice(model)

    # Store boot info
    from app.routes.templates import _store_boot_info
    _store_boot_info(slice_name, exp_dir)

    # Auto-resolve site groups
    site_groups = _get_site_groups(slice_name)
    if site_groups:
        try:
            from app.site_resolver import resolve_sites
            from app.routes.resources import get_cached_sites

            draft = _get_draft(slice_name)
            if draft is not None:
                from app.routes.slices import slice_to_dict
                data = slice_to_dict(draft)
                node_defs = []
                for node in data.get("nodes", []):
                    grp = site_groups.get(node["name"])
                    site = grp if grp else (node.get("site", "") or "auto")
                    node_defs.append({
                        "name": node["name"],
                        "site": site,
                        "cores": node.get("cores", 2),
                        "ram": node.get("ram", 8),
                        "disk": node.get("disk", 10),
                        "components": node.get("components", []),
                    })
                sites = get_cached_sites()
                resolved_defs, new_groups = resolve_sites(node_defs, sites)
                for nd in resolved_defs:
                    try:
                        fab_node = draft.get_node(name=nd["name"])
                        fab_node.set_site(site=nd["site"])
                    except Exception:
                        pass
                merged_groups = dict(site_groups)
                merged_groups.update(new_groups)
                _store_site_groups(slice_name, merged_groups)
                result = _serialize(draft, dirty=True)
        except Exception:
            pass

    return result
