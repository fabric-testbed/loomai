"""Template management API routes."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.user_context import get_user_storage
from app.routes.slices import build_slice_model, import_slice, SliceModelImport, _get_site_groups, _get_draft, _store_site_groups, _serialize

router = APIRouter(prefix="/api/templates", tags=["templates"])


def _templates_dir() -> str:
    from app.user_context import get_artifacts_dir
    return get_artifacts_dir()


def _sanitize_name(name: str) -> str:
    """Sanitize template name to safe directory name."""
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", name.strip())
    if not safe:
        raise HTTPException(status_code=400, detail="Invalid template name")
    return safe


def _validate_path(base: str, name: str) -> str:
    """Return full path for template dir, with traversal protection."""
    path = os.path.realpath(os.path.join(base, name))
    if not path.startswith(os.path.realpath(base)):
        raise HTTPException(status_code=400, detail="Invalid template name")
    return path


def _ensure_dir() -> None:
    """Ensure the templates storage directory exists."""
    os.makedirs(_templates_dir(), exist_ok=True)


# ---------------------------------------------------------------------------
# TTL-based listing cache
# ---------------------------------------------------------------------------

_templates_cache: tuple[float, list] | None = None
_TEMPLATES_CACHE_TTL = 10  # seconds


def _invalidate_templates_cache():
    global _templates_cache
    _templates_cache = None


# ---------------------------------------------------------------------------
# Boot info helpers (for deploy.sh discovery at boot config time)
# ---------------------------------------------------------------------------

def _boot_info_dir() -> str:
    storage = get_user_storage()
    d = os.path.join(storage, ".boot_info")
    os.makedirs(d, exist_ok=True)
    return d


def _store_boot_info(slice_name: str, tmpl_dir: str) -> None:
    """Store template directory info so boot config executor can find deploy.sh."""
    try:
        path = os.path.join(_boot_info_dir(), f"{slice_name}.json")
        with open(path, "w") as f:
            json.dump({"template_dir": tmpl_dir}, f)
    except Exception:
        pass  # Non-critical


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class SaveTemplateRequest(BaseModel):
    name: str
    description: str = ""
    slice_name: str


class UpdateTemplateRequest(BaseModel):
    description: str


class ToolFileBody(BaseModel):
    content: str


class LoadTemplateRequest(BaseModel):
    slice_name: str = ""


# ---------------------------------------------------------------------------
# Helper: list tool files for a template directory
# ---------------------------------------------------------------------------

def _list_tools(tmpl_dir: str) -> list[dict[str, str]]:
    """Return a sorted list of {filename} dicts for tools in a template dir."""
    tools_dir = os.path.join(tmpl_dir, "tools")
    if not os.path.isdir(tools_dir):
        return []
    return [{"filename": fn} for fn in sorted(os.listdir(tools_dir))
            if os.path.isfile(os.path.join(tools_dir, fn))]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
def list_templates() -> list[dict[str, Any]]:
    """List weaves (dirs containing slice.json, deploy.sh, and/or run.sh)."""
    global _templates_cache
    import time
    if _templates_cache is not None:
        ts, data = _templates_cache
        if time.monotonic() - ts < _TEMPLATES_CACHE_TTL:
            return data
    _ensure_dir()
    tdir = _templates_dir()
    if not os.path.isdir(tdir):
        return []
    results = []
    for entry in sorted(os.listdir(tdir)):
        entry_dir = os.path.join(tdir, entry)
        if not os.path.isdir(entry_dir):
            continue
        tmpl_path = os.path.join(entry_dir, "slice.json")
        deploy_path = os.path.join(entry_dir, "deploy.sh")
        run_path = os.path.join(entry_dir, "run.sh")
        has_template = os.path.isfile(tmpl_path)
        has_deploy = os.path.isfile(deploy_path)
        has_run = os.path.isfile(run_path)
        if not has_template and not has_deploy and not has_run:
            continue  # Not a weave artifact
        meta_path = os.path.join(entry_dir, "metadata.json")

        # Auto-generate metadata if missing
        if not os.path.isfile(meta_path):
            try:
                node_count = 0
                network_count = 0
                name = entry
                if has_template:
                    with open(tmpl_path) as f:
                        model = json.load(f)
                    name = model.get("name", entry)
                    node_count = len(model.get("nodes", []))
                    network_count = len(model.get("networks", []))
                auto_meta = {
                    "name": name,
                    "description": "",
                    "source_slice": "",
                    "created": datetime.now(timezone.utc).isoformat(),
                    "node_count": node_count,
                    "network_count": network_count,
                }
                with open(meta_path, "w") as f:
                    json.dump(auto_meta, f, indent=2)
            except Exception:
                pass

        if os.path.isfile(meta_path):
            try:
                with open(meta_path) as f:
                    meta = json.load(f)
                meta["dir_name"] = entry
                meta["has_template"] = has_template
                meta["has_deploy"] = has_deploy
                meta["has_run"] = has_run
                # Read script argument manifests
                for manifest_name, key in [("deploy.json", "deploy_args"), ("run.json", "run_args")]:
                    manifest_path = os.path.join(entry_dir, manifest_name)
                    if os.path.isfile(manifest_path):
                        try:
                            with open(manifest_path) as f:
                                manifest = json.load(f)
                            meta[key] = manifest.get("args", [])
                        except Exception:
                            pass
                results.append(meta)
            except Exception:
                pass
    results.sort(key=lambda m: m.get("name", "").lower())
    _templates_cache = (time.monotonic(), results)
    return results


@router.post("")
def save_template(req: SaveTemplateRequest) -> dict[str, Any]:
    """Save current slice as a reusable template."""
    _invalidate_templates_cache()
    _ensure_dir()
    safe_name = _sanitize_name(req.name)
    tdir = _templates_dir()
    os.makedirs(tdir, exist_ok=True)
    tmpl_dir = _validate_path(tdir, safe_name)

    if os.path.isdir(tmpl_dir):
        raise HTTPException(status_code=409, detail=f"Template '{req.name}' already exists")

    try:
        model = build_slice_model(req.slice_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to export slice: {e}")

    # Override the name in the model to use the template name
    model["name"] = req.name

    os.makedirs(tmpl_dir, exist_ok=True)
    with open(os.path.join(tmpl_dir, "slice.json"), "w") as f:
        json.dump(model, f, indent=2)

    metadata = {
        "name": req.name,
        "description": req.description,
        "source_slice": req.slice_name,
        "created": datetime.now(timezone.utc).isoformat(),
        "node_count": len(model.get("nodes", [])),
        "network_count": len(model.get("networks", [])),
    }
    with open(os.path.join(tmpl_dir, "metadata.json"), "w") as f:
        json.dump(metadata, f, indent=2)

    return metadata


class CreateArtifactRequest(BaseModel):
    name: str
    description: str = ""
    category: str = "weave"  # weave, vm-template, recipe, notebook


@router.post("/create-blank")
def create_blank_artifact(req: CreateArtifactRequest) -> dict[str, Any]:
    """Create a new blank artifact directory with metadata."""
    _invalidate_templates_cache()
    _ensure_dir()
    safe_name = _sanitize_name(req.name)
    tdir = _templates_dir()
    os.makedirs(tdir, exist_ok=True)
    tmpl_dir = _validate_path(tdir, safe_name)

    if os.path.isdir(tmpl_dir):
        raise HTTPException(status_code=409, detail=f"Artifact '{req.name}' already exists")

    os.makedirs(tmpl_dir, exist_ok=True)

    metadata = {
        "name": req.name,
        "description": req.description,
        "category": req.category,
        "created": datetime.now(timezone.utc).isoformat(),
        "node_count": 0,
        "network_count": 0,
    }
    with open(os.path.join(tmpl_dir, "metadata.json"), "w") as f:
        json.dump(metadata, f, indent=2)

    # Create an empty slice.json for weaves
    if req.category == "weave":
        with open(os.path.join(tmpl_dir, "slice.json"), "w") as f:
            json.dump({"name": req.name, "nodes": [], "networks": []}, f, indent=2)

    return {"dir_name": safe_name, **metadata}


@router.post("/resync")
def resync_templates() -> list[dict[str, Any]]:
    """Clean corrupted entries and return updated list."""
    _invalidate_templates_cache()
    tdir = _templates_dir()
    os.makedirs(tdir, exist_ok=True)

    # Remove corrupted entries (dirs without valid metadata)
    if os.path.isdir(tdir):
        for entry in os.listdir(tdir):
            entry_dir = os.path.join(tdir, entry)
            if not os.path.isdir(entry_dir):
                continue
            meta_path = os.path.join(entry_dir, "metadata.json")
            tmpl_path = os.path.join(entry_dir, "slice.json")
            if not os.path.isfile(meta_path) or not os.path.isfile(tmpl_path):
                shutil.rmtree(entry_dir)

    return list_templates()


@router.get("/runs")
def list_background_runs():
    """List all background runs (active and completed)."""
    from app.run_manager import list_runs
    return list_runs()


@router.get("/runs/{run_id}")
def get_background_run(run_id: str):
    """Get status and metadata for a background run."""
    from app.run_manager import get_run
    meta = get_run(run_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Run not found")
    return meta


@router.get("/runs/{run_id}/output")
def get_background_run_output(run_id: str, offset: int = 0):
    """Get run output from the given byte offset.

    Returns {"output": "...", "offset": N, "status": "..."} where offset
    is the new position for the next poll. Status comes from meta so the
    client knows when to stop polling.
    """
    from app.run_manager import get_run, get_run_output
    meta = get_run(run_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Run not found")
    output, new_offset = get_run_output(run_id, offset)
    return {
        "output": output,
        "offset": new_offset,
        "status": meta.get("status", "unknown"),
    }


@router.post("/runs/{run_id}/stop")
def stop_background_run(run_id: str):
    """Stop a running background run."""
    from app.run_manager import stop_run
    if stop_run(run_id):
        return {"status": "stopped"}
    raise HTTPException(status_code=404, detail="Run not found or already finished")


@router.delete("/runs/{run_id}")
def delete_background_run(run_id: str):
    """Delete a completed run's data."""
    from app.run_manager import delete_run
    if delete_run(run_id):
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Run not found")


@router.get("/{name}")
def get_template(name: str) -> dict[str, Any]:
    """Get full template detail including model JSON and tools listing."""
    _ensure_dir()
    safe_name = _sanitize_name(name)
    tdir = _templates_dir()
    tmpl_dir = _validate_path(tdir, safe_name)

    meta_path = os.path.join(tmpl_dir, "metadata.json")
    tmpl_path = os.path.join(tmpl_dir, "slice.json")
    if not os.path.isfile(meta_path) or not os.path.isfile(tmpl_path):
        raise HTTPException(status_code=404, detail=f"Template '{name}' not found")

    with open(meta_path) as f:
        metadata = json.load(f)
    with open(tmpl_path) as f:
        model = json.load(f)

    metadata["dir_name"] = safe_name
    metadata["model"] = model
    metadata["tools"] = _list_tools(tmpl_dir)
    return metadata


@router.post("/{name}/load")
def load_template(name: str, req: LoadTemplateRequest) -> dict[str, Any]:
    """Load a template as a new draft slice."""
    _ensure_dir()
    safe_name = _sanitize_name(name)
    tdir = _templates_dir()
    tmpl_dir = _validate_path(tdir, safe_name)

    tmpl_path = os.path.join(tmpl_dir, "slice.json")
    if not os.path.isfile(tmpl_path):
        raise HTTPException(status_code=404, detail=f"Template '{name}' not found")

    with open(tmpl_path) as f:
        model_data = json.load(f)

    # Use provided slice name or fall back to template name
    slice_name = req.slice_name.strip() if req.slice_name else model_data.get("name", name)
    model_data["name"] = slice_name

    # If this template has a tools/ directory, inject an upload entry into
    # each node's boot_config so the scripts are available at ~/tools
    tools_dir = os.path.join(tmpl_dir, "tools")
    if os.path.isdir(tools_dir) and os.listdir(tools_dir):
        for node_def in model_data.get("nodes", []):
            bc = node_def.get("boot_config")
            if bc and isinstance(bc, dict):
                uploads = bc.setdefault("uploads", [])
                uploads.insert(0, {
                    "id": "slice-tools",
                    "source": tools_dir,
                    "dest": "~/tools",
                })

    model = SliceModelImport(**model_data)
    result = import_slice(model)

    # Seed the slice working directory with template artifacts
    from app.routes.jupyter import seed_slice_workdir_from_template
    seed_slice_workdir_from_template(slice_name, tmpl_dir)

    # Store template directory info so boot config can find deploy.sh
    _store_boot_info(slice_name, tmpl_dir)

    # Auto-resolve site groups so the user sees candidate sites immediately
    site_groups = _get_site_groups(slice_name)
    if site_groups:
        try:
            from app.site_resolver import resolve_sites
            from app.routes.resources import get_cached_sites
            from app.routes.slices import slice_to_dict

            draft = _get_draft(slice_name)
            if draft is not None:
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
            pass  # Non-critical — user can still manually assign

    return result


@router.delete("/{name}")
def delete_template(name: str) -> dict[str, str]:
    """Delete a template."""
    _invalidate_templates_cache()
    safe_name = _sanitize_name(name)
    tdir = _templates_dir()
    tmpl_dir = _validate_path(tdir, safe_name)

    if not os.path.isdir(tmpl_dir):
        raise HTTPException(status_code=404, detail=f"Template '{name}' not found")

    shutil.rmtree(tmpl_dir)
    return {"status": "deleted", "name": name}


@router.put("/{name}")
def update_template(name: str, req: UpdateTemplateRequest) -> dict[str, Any]:
    """Update template metadata (description)."""
    _invalidate_templates_cache()
    safe_name = _sanitize_name(name)
    tdir = _templates_dir()
    tmpl_dir = _validate_path(tdir, safe_name)

    meta_path = os.path.join(tmpl_dir, "metadata.json")
    if not os.path.isfile(meta_path):
        raise HTTPException(status_code=404, detail=f"Template '{name}' not found")

    with open(meta_path) as f:
        metadata = json.load(f)

    metadata["description"] = req.description

    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)

    return metadata


# ---------------------------------------------------------------------------
# Tool file endpoints
# ---------------------------------------------------------------------------

def _validate_tool_filename(filename: str) -> str:
    """Sanitize and validate a tool filename."""
    safe = re.sub(r"[^a-zA-Z0-9_\-.]", "_", filename.strip())
    if not safe or safe.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid tool filename")
    return safe


@router.get("/{name}/tools/{filename}")
def read_tool(name: str, filename: str) -> dict[str, str]:
    """Read a tool file's content."""
    safe_name = _sanitize_name(name)
    safe_file = _validate_tool_filename(filename)
    tdir = _templates_dir()
    tmpl_dir = _validate_path(tdir, safe_name)
    tool_path = os.path.join(tmpl_dir, "tools", safe_file)

    if not os.path.isfile(tool_path):
        raise HTTPException(status_code=404, detail=f"Tool file '{filename}' not found")

    with open(tool_path) as f:
        content = f.read()
    return {"filename": safe_file, "content": content}


@router.put("/{name}/tools/{filename}")
def write_tool(name: str, filename: str, body: ToolFileBody) -> dict[str, str]:
    """Create or update a tool file."""
    safe_name = _sanitize_name(name)
    safe_file = _validate_tool_filename(filename)
    tdir = _templates_dir()
    tmpl_dir = _validate_path(tdir, safe_name)

    if not os.path.isdir(tmpl_dir):
        raise HTTPException(status_code=404, detail=f"Template '{name}' not found")

    tools_dir = os.path.join(tmpl_dir, "tools")
    os.makedirs(tools_dir, exist_ok=True)
    tool_path = os.path.join(tools_dir, safe_file)

    with open(tool_path, "w") as f:
        f.write(body.content)
    return {"filename": safe_file, "status": "saved"}


@router.delete("/{name}/tools/{filename}")
def delete_tool(name: str, filename: str) -> dict[str, str]:
    """Delete a tool file."""
    safe_name = _sanitize_name(name)
    safe_file = _validate_tool_filename(filename)
    tdir = _templates_dir()
    tmpl_dir = _validate_path(tdir, safe_name)
    tool_path = os.path.join(tmpl_dir, "tools", safe_file)

    if not os.path.isfile(tool_path):
        raise HTTPException(status_code=404, detail=f"Tool file '{filename}' not found")

    os.remove(tool_path)
    return {"filename": safe_file, "status": "deleted"}


# ---------------------------------------------------------------------------
# Run deploy.sh / run.sh from a weave against a slice
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)


class RunScriptRequest(BaseModel):
    slice_name: str = ""
    args: dict[str, str] = {}


@router.post("/{name}/run-script/{script}")
def run_weave_script(name: str, script: str, req: RunScriptRequest):
    """Run deploy.sh or run.sh from a weave artifact, streaming output as SSE.

    The script is executed on the backend container with args set as env vars.
    """
    if script not in ("deploy.sh", "run.sh"):
        raise HTTPException(status_code=400, detail="Only deploy.sh and run.sh are supported")

    safe_name = _sanitize_name(name)
    tdir = _templates_dir()
    tmpl_dir = _validate_path(tdir, safe_name)
    script_path = os.path.join(tmpl_dir, script)
    if not os.path.isfile(script_path):
        raise HTTPException(status_code=404, detail=f"Script '{script}' not found in weave '{name}'")

    def _stream():
        import json as _json

        def _sse(payload: dict) -> str:
            return "data: " + _json.dumps(payload) + "\n\n"

        # Build env vars from args dict (with legacy slice_name fallback)
        script_args = dict(req.args)
        if req.slice_name and "SLICE_NAME" not in script_args:
            script_args["SLICE_NAME"] = req.slice_name
        env = {**os.environ, **script_args}
        slice_name = script_args.get("SLICE_NAME", "")
        label = f" for slice {slice_name!r}" if slice_name else ""
        step_msg = f"Running {script}{label}..."
        yield _sse({"type": "step", "message": step_msg})
        cmd = ["bash", script_path]
        if slice_name:
            cmd.append(slice_name)
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, env=env, cwd=tmpl_dir,
            )
            for raw in iter(proc.stdout.readline, ""):
                line_str = raw.rstrip()
                if not line_str:
                    continue
                if line_str.startswith("### PROGRESS:"):
                    msg = line_str[len("### PROGRESS:"):].strip()
                    yield _sse({"type": "progress", "message": msg})
                else:
                    yield _sse({"type": "output", "message": line_str})
            proc.wait()
            if proc.returncode != 0:
                yield _sse({"type": "error", "message": f"{script} exited with code {proc.returncode}"})
            else:
                yield _sse({"type": "done", "message": f"{script} complete"})
        except Exception as e:
            yield _sse({"type": "error", "message": str(e)})

    return StreamingResponse(_stream(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Background runs — detached from HTTP connections
# ---------------------------------------------------------------------------

class StartRunRequest(BaseModel):
    slice_name: str = ""
    args: dict[str, str] = {}


@router.post("/{name}/start-run/{script}")
def start_background_run(name: str, script: str, req: StartRunRequest):
    """Start a weave script as a background run, detached from the HTTP connection.

    Returns a run_id that can be used to poll status and output.
    """
    if script not in ("deploy.sh", "run.sh"):
        raise HTTPException(status_code=400, detail="Only deploy.sh and run.sh are supported")

    safe_name = _sanitize_name(name)
    tdir = _templates_dir()
    tmpl_dir = _validate_path(tdir, safe_name)
    script_path = os.path.join(tmpl_dir, script)
    if not os.path.isfile(script_path):
        raise HTTPException(status_code=404, detail=f"Script '{script}' not found in weave '{name}'")

    # Read weave display name from metadata
    meta_path = os.path.join(tmpl_dir, "metadata.json")
    weave_name = name
    if os.path.isfile(meta_path):
        try:
            with open(meta_path) as f:
                weave_name = json.load(f).get("name", name)
        except Exception:
            pass

    # Build script args — merge legacy slice_name with new args dict
    script_args = dict(req.args)
    if req.slice_name and "SLICE_NAME" not in script_args:
        script_args["SLICE_NAME"] = req.slice_name

    from app.run_manager import start_run
    run_id = start_run(
        weave_dir_name=safe_name,
        weave_name=weave_name,
        script=script,
        script_path=script_path,
        cwd=tmpl_dir,
        script_args=script_args,
    )
    return {"run_id": run_id, "status": "running"}


