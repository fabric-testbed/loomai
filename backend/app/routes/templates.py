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

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.user_context import get_user_storage
from app.routes.slices import build_slice_model, import_slice, SliceModelImport, _get_site_groups, _get_draft, _store_site_groups, _serialize, _get_slice_obj

logger = logging.getLogger(__name__)
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
# Boot info helpers (for weave script discovery at boot config time)
# ---------------------------------------------------------------------------

def _boot_info_dir() -> str:
    storage = get_user_storage()
    d = os.path.join(storage, ".boot_info")
    os.makedirs(d, exist_ok=True)
    return d


def _store_boot_info(slice_name: str, tmpl_dir: str) -> None:
    """Store template directory info so boot config executor can find weave scripts."""
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
# Helper: read weave.json config (with fallback auto-detection)
# ---------------------------------------------------------------------------

_WEAVE_CONFIG_DEFAULTS = {"run_script": "weave.sh", "log_file": "weave.log"}


def _read_weave_config(tmpl_dir: str) -> dict[str, str] | None:
    """Read weave.json from a template directory.

    If weave.json exists, return its contents merged with defaults.
    If not, auto-detect legacy weave scripts for backwards compatibility.
    Returns None if no weave indicator is found.
    """
    weave_json_path = os.path.join(tmpl_dir, "weave.json")
    if os.path.isfile(weave_json_path):
        try:
            with open(weave_json_path) as f:
                config = json.load(f)
            # Merge with defaults
            return {**_WEAVE_CONFIG_DEFAULTS, **config}
        except Exception:
            return dict(_WEAVE_CONFIG_DEFAULTS)

    # Auto-detect weave.sh even without weave.json
    if os.path.isfile(os.path.join(tmpl_dir, "weave.sh")):
        return {"run_script": "weave.sh", "log_file": "weave.log"}

    return None


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
# Helper: generate FABlib-native weave scripts
# ---------------------------------------------------------------------------

_WEAVEIGNORE_DEFAULT = (
    "# .weaveignore — files excluded from publishing\n"
    "# Uses .gitignore-style patterns. One pattern per line.\n"
    "data/\nresults/\noutput/\n*.csv\n*.key\n*.pem\nsecrets/\n"
    ".ipynb_checkpoints/\n"
)


def _generate_experiment_py(weave_name: str) -> str:
    """Generate a FABlib experiment script that loads topology from .graphml."""
    return f'''#!/usr/bin/env python3
"""
{weave_name} — FABlib Experiment Script

Auto-generated by Loomai. Manages the slice lifecycle:
  start:   Load topology from .graphml, submit slice, wait for SSH
  stop:    Delete the slice and free resources
  monitor: Check slice health and node reachability

Usage:
    python3 experiment.py start   SLICE_NAME
    python3 experiment.py stop    SLICE_NAME
    python3 experiment.py monitor SLICE_NAME
"""
import os
import sys

from fabrictestbed_extensions.fablib.fablib import FablibManager

TOPOLOGY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "slice_topology.graphml")


def start(slice_name):
    """Create a slice from the saved topology and wait for it to be ready."""
    fablib = FablibManager()

    print(f"### PROGRESS: Creating slice '{{slice_name}}'...")
    my_slice = fablib.new_slice(name=slice_name)

    print("### PROGRESS: Loading topology from slice_topology.graphml...")
    my_slice.load(TOPOLOGY_FILE)

    print("### PROGRESS: Submitting slice to FABRIC...")
    my_slice.submit()

    print("### PROGRESS: Waiting for SSH access (this may take a few minutes)...")
    my_slice.wait_ssh(progress=True)

    print(f"### PROGRESS: Slice '{{slice_name}}' is ready!")
    for node in my_slice.get_nodes():
        print(f"  {{node.get_name()}}: {{node.get_management_ip()}}")


def stop(slice_name):
    """Delete the slice and free all resources."""
    fablib = FablibManager()

    try:
        my_slice = fablib.get_slice(name=slice_name)
        print(f"### PROGRESS: Deleting slice '{{slice_name}}'...")
        my_slice.delete()
        print(f"### PROGRESS: Slice '{{slice_name}}' deleted.")
    except Exception as e:
        print(f"### PROGRESS: Slice not found or already deleted: {{e}}")


def monitor(slice_name):
    """Check that the slice is healthy and all nodes respond."""
    fablib = FablibManager()

    my_slice = fablib.get_slice(name=slice_name)
    state = str(my_slice.get_state())

    if "StableOK" not in state:
        print(f"ERROR: Slice state is {{state}} (expected StableOK)")
        sys.exit(1)

    for node in my_slice.get_nodes():
        try:
            stdout, stderr = node.execute("echo ok", quiet=True)
            if "ok" not in stdout:
                raise Exception("unexpected output from test command")
        except Exception as e:
            print(f"ERROR: Node {{node.get_name()}} health check failed: {{e}}")
            sys.exit(1)

    print(f"### PROGRESS: All nodes healthy (state: {{state}})")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: experiment.py {{start|stop|monitor}} SLICE_NAME")
        sys.exit(1)

    action = sys.argv[1]
    slice_name = sys.argv[2]

    if action == "start":
        start(slice_name)
    elif action == "stop":
        stop(slice_name)
    elif action == "monitor":
        monitor(slice_name)
    else:
        print(f"Unknown action: {{action}}")
        print("Usage: experiment.py {{start|stop|monitor}} SLICE_NAME")
        sys.exit(1)
'''


def _generate_weave_sh(weave_name: str, default_slice_name: str) -> str:
    """Generate a bash weave orchestrator script."""
    return f'''#!/bin/bash
#
# {weave_name} — Weave Orchestrator
#
# Auto-generated by Loomai. Entry point for the "Run" button.
# Calls experiment.py with start/monitor/stop lifecycle commands.
#

SLICE_NAME="${{SLICE_NAME:-${{1:-{default_slice_name}}}}}"

# Clean the name: only letters, numbers, and hyphens
SLICE_NAME=$(echo "$SLICE_NAME" | sed 's/[^a-zA-Z0-9-]/-/g' | sed 's/--*/-/g' | sed 's/^-//;s/-$//')
if [ -z "$SLICE_NAME" ]; then
  echo "ERROR: SLICE_NAME not set" >&2
  exit 1
fi

SCRIPT="experiment.py"

cleanup() {{
  echo ""
  echo "### PROGRESS: Stop requested — cleaning up..."
  python3 "$SCRIPT" stop "$SLICE_NAME" 2>&1 || true
  echo "### PROGRESS: Done."
  exit 0
}}

trap cleanup SIGTERM SIGINT

if ! python3 "$SCRIPT" start "$SLICE_NAME"; then
  echo "ERROR: Failed to start slice"
  exit 1
fi

echo "### PROGRESS: Monitoring (click Stop to tear down)..."
while true; do
  if ! python3 "$SCRIPT" monitor "$SLICE_NAME"; then
    echo "ERROR: Monitor detected a problem — cleaning up..."
    python3 "$SCRIPT" stop "$SLICE_NAME" 2>&1 || true
    exit 1
  fi
  sleep 30 &
  wait $! 2>/dev/null || true
done
'''


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
def list_templates() -> list[dict[str, Any]]:
    """List weave artifacts (dirs containing weave.json or a topology file)."""
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
        weave_json_path = os.path.join(entry_dir, "weave.json")
        weave_sh_path = os.path.join(entry_dir, "weave.sh")
        has_template = os.path.isfile(tmpl_path)
        has_weave_json = os.path.isfile(weave_json_path)
        has_weave_sh = os.path.isfile(weave_sh_path)
        if not has_template and not has_weave_json and not has_weave_sh:
            continue  # Not a weave artifact
        # Read metadata from weave.json; auto-generate fields if missing
        weave_config = _read_weave_config(entry_dir)
        meta: dict[str, Any] = {}
        if has_weave_json:
            try:
                with open(weave_json_path) as f:
                    meta = json.load(f)
            except Exception:
                pass

        # Auto-populate missing metadata fields into weave.json
        if not meta.get("name"):
            try:
                if has_template:
                    with open(tmpl_path) as f:
                        model = json.load(f)
                    meta.setdefault("name", model.get("name", entry))
                else:
                    meta.setdefault("name", entry)
                meta.setdefault("description", "")
                meta.setdefault("created", datetime.now(timezone.utc).isoformat())
                with open(weave_json_path, "w") as f:
                    json.dump(meta, f, indent=2)
            except Exception:
                pass

        try:
            meta["dir_name"] = entry
            meta["has_template"] = has_template
            meta["has_weave_json"] = has_weave_json
            meta["has_weave_sh"] = has_weave_sh
            # Check if a cleanup script exists on disk
            cleanup_script = (
                meta.get("cleanup_script", "")
                or (weave_config.get("cleanup_script", "") if weave_config else "")
            )
            meta["has_cleanup_script"] = (
                bool(cleanup_script)
                and os.path.isfile(os.path.join(entry_dir, cleanup_script))
            )
            meta.setdefault("name", entry)
            # Ensure description falls back to description_short
            if not meta.get("description") and meta.get("description_short"):
                meta["description"] = meta["description_short"]
            # Include weave config
            if weave_config:
                meta["weave_config"] = weave_config
                # Read argument manifest from weave.json args field
                if weave_config.get("args"):
                    meta["run_args"] = weave_config["args"]
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

    # Export FABlib-native .graphml topology (soft failure — weave still
    # works via slice.json if graphml export fails)
    try:
        slice_obj = _get_slice_obj(req.slice_name)
        graphml_path = os.path.join(tmpl_dir, "slice_topology.graphml")
        slice_obj.save(graphml_path)
    except Exception as e:
        logger.warning("Could not export .graphml for weave '%s': %s", req.name, e)

    # Generate FABlib-native experiment script and orchestrator
    default_slug = _sanitize_name(req.name).lower().replace("_", "-")
    with open(os.path.join(tmpl_dir, "experiment.py"), "w") as f:
        f.write(_generate_experiment_py(req.name))
    weave_sh_path = os.path.join(tmpl_dir, "weave.sh")
    with open(weave_sh_path, "w") as f:
        f.write(_generate_weave_sh(req.name, default_slug))
    os.chmod(weave_sh_path, 0o755)

    # Seed .weaveignore for publishing exclusions
    weaveignore_path = os.path.join(tmpl_dir, ".weaveignore")
    if not os.path.isfile(weaveignore_path):
        with open(weaveignore_path, "w") as f:
            f.write(_WEAVEIGNORE_DEFAULT)

    # Write all metadata into weave.json (single source of truth)
    weave_data = {
        **_WEAVE_CONFIG_DEFAULTS,
        "name": req.name,
        "description": req.description,
        "source_slice": req.slice_name,
        "created": datetime.now(timezone.utc).isoformat(),
        "format": model.get("format", "fabric-webgui-v1"),
        "nodes": model.get("nodes", []),
        "networks": model.get("networks", []),
        "args": [
            {
                "name": "SLICE_NAME",
                "label": "Slice Name",
                "type": "string",
                "required": True,
                "default": default_slug,
                "description": "Name for your FABRIC slice",
            }
        ],
    }
    with open(os.path.join(tmpl_dir, "weave.json"), "w") as f:
        json.dump(weave_data, f, indent=2)

    return weave_data


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

    # Write all metadata into weave.json (single source of truth)
    weave_data = {
        **_WEAVE_CONFIG_DEFAULTS,
        "name": req.name,
        "description": req.description,
        "category": req.category,
        "created": datetime.now(timezone.utc).isoformat(),
    }
    with open(os.path.join(tmpl_dir, "weave.json"), "w") as f:
        json.dump(weave_data, f, indent=2)

    # Create an empty topology file for weaves
    if req.category == "weave":
        with open(os.path.join(tmpl_dir, "slice.json"), "w") as f:
            json.dump({"name": req.name, "nodes": [], "networks": []}, f, indent=2)

    # Seed a default .weaveignore for new artifacts
    weaveignore_path = os.path.join(tmpl_dir, ".weaveignore")
    if not os.path.isfile(weaveignore_path):
        with open(weaveignore_path, "w") as f:
            f.write(_WEAVEIGNORE_DEFAULT)

    return {"dir_name": safe_name, **weave_data}


@router.post("/create-weave")
async def create_weave_endpoint(req: Request) -> dict[str, Any]:
    """Create a complete weave stub with all default files.

    Body: {"name": "my_weave"} — optional: description, num_nodes, site
    """
    _invalidate_templates_cache()
    body = await req.json()
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    from app.routes.ai_chat import _create_weave_tool
    result_json = await _create_weave_tool({
        "name": name,
        "description": body.get("description", ""),
        "num_nodes": body.get("num_nodes", 1),
        "site": body.get("site", "auto"),
        "include_notebooks": True,
    })
    import json as _json
    result = _json.loads(result_json)
    if "error" in result:
        raise HTTPException(409, result["error"])
    return result


@router.post("/resync")
def resync_templates() -> list[dict[str, Any]]:
    """Clean corrupted entries from disk and return updated artifact list."""
    _invalidate_templates_cache()
    tdir = _templates_dir()
    os.makedirs(tdir, exist_ok=True)

    # Remove corrupted entries (dirs without valid weave.json or topology)
    if os.path.isdir(tdir):
        for entry in os.listdir(tdir):
            entry_dir = os.path.join(tdir, entry)
            if not os.path.isdir(entry_dir):
                continue
            weave_path = os.path.join(entry_dir, "weave.json")
            tmpl_path = os.path.join(entry_dir, "slice.json")
            if not os.path.isfile(weave_path) or not os.path.isfile(tmpl_path):
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
    """Stop a running background run.

    Launches graceful shutdown in a background thread since it may take
    up to ~35s (FABRIC slice deletion). Returns immediately with "stopping".
    """
    import threading as _threading
    from app.run_manager import get_run, stop_run

    meta = get_run(run_id)
    if not meta or meta.get("status") != "running":
        raise HTTPException(status_code=404, detail="Run not found or already finished")

    _threading.Thread(target=stop_run, args=(run_id,), daemon=True).start()
    return {"status": "stopping"}


@router.delete("/runs/{run_id}")
def delete_background_run(run_id: str):
    """Delete a completed run's data."""
    from app.run_manager import delete_run
    if delete_run(run_id):
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Run not found")


@router.get("/{name}/weave-log")
def get_weave_log(name: str, offset: int = 0) -> dict[str, Any]:
    """Read the weave log file from the given byte offset.

    Returns {"output": "...", "offset": N} where offset is the new position
    for the next poll.
    """
    safe_name = _sanitize_name(name)
    tdir = _templates_dir()
    tmpl_dir = _validate_path(tdir, safe_name)

    # Determine log file name from weave.json
    weave_config = _read_weave_config(tmpl_dir)
    log_file = weave_config.get("log_file", "weave.log") if weave_config else "weave.log"
    log_path = os.path.join(tmpl_dir, log_file)

    if not os.path.isfile(log_path):
        return {"output": "", "offset": 0}

    size = os.path.getsize(log_path)
    if offset >= size:
        return {"output": "", "offset": offset}

    with open(log_path, "r", errors="replace") as f:
        f.seek(offset)
        data = f.read()
    return {"output": data, "offset": size}


@router.get("/{name}")
def get_template(name: str) -> dict[str, Any]:
    """Get full template detail including model JSON and tools listing."""
    _ensure_dir()
    safe_name = _sanitize_name(name)
    tdir = _templates_dir()
    tmpl_dir = _validate_path(tdir, safe_name)

    weave_path = os.path.join(tmpl_dir, "weave.json")
    tmpl_path = os.path.join(tmpl_dir, "slice.json")
    if not os.path.isfile(weave_path) or not os.path.isfile(tmpl_path):
        raise HTTPException(status_code=404, detail=f"Template '{name}' not found")

    with open(weave_path) as f:
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

    # Store template directory info so boot config can find weave scripts
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

    weave_path = os.path.join(tmpl_dir, "weave.json")
    if not os.path.isfile(weave_path):
        raise HTTPException(status_code=404, detail=f"Template '{name}' not found")

    with open(weave_path) as f:
        metadata = json.load(f)

    metadata["description"] = req.description

    with open(weave_path, "w") as f:
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
# Run weave scripts against a slice
# ---------------------------------------------------------------------------



class RunScriptRequest(BaseModel):
    slice_name: str = ""
    args: dict[str, str] = {}


@router.post("/{name}/run-script/{script}")
def run_weave_script(name: str, script: str, req: RunScriptRequest):
    """Run a weave script, streaming output as SSE.

    The script is executed on the backend container with args set as env vars.
    When script is "auto", resolves the run script from weave.json.
    """
    safe_name = _sanitize_name(name)
    tdir = _templates_dir()
    tmpl_dir = _validate_path(tdir, safe_name)

    # Resolve "auto" script from weave.json
    if script == "auto":
        weave_config = _read_weave_config(tmpl_dir)
        if weave_config:
            script = weave_config["run_script"]
        else:
            script = "weave.sh"

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
    When script is "auto", resolves the run script from weave.json.
    """
    safe_name = _sanitize_name(name)
    tdir = _templates_dir()
    tmpl_dir = _validate_path(tdir, safe_name)

    # Resolve script name — "auto" reads from weave.json
    if script == "auto":
        weave_config = _read_weave_config(tmpl_dir)
        if weave_config:
            script = weave_config["run_script"]
        else:
            script = "weave.sh"  # ultimate fallback

    if script not in ("weave.sh",):
        # Allow any script name that exists in the weave directory
        script_path = os.path.join(tmpl_dir, script)
        if not os.path.isfile(script_path):
            raise HTTPException(status_code=400, detail=f"Script '{script}' not found")
    else:
        script_path = os.path.join(tmpl_dir, script)
        if not os.path.isfile(script_path):
            raise HTTPException(status_code=404, detail=f"Script '{script}' not found in weave '{name}'")

    # Read weave display name from weave.json
    weave_json_path = os.path.join(tmpl_dir, "weave.json")
    weave_name = name
    if os.path.isfile(weave_json_path):
        try:
            with open(weave_json_path) as f:
                weave_name = json.load(f).get("name", name)
        except Exception:
            pass

    # Build script args — merge legacy slice_name with new args dict
    script_args = dict(req.args)
    if req.slice_name and "SLICE_NAME" not in script_args:
        script_args["SLICE_NAME"] = req.slice_name

    # Resolve log path from weave.json
    weave_config = _read_weave_config(tmpl_dir)
    log_file = weave_config.get("log_file", "weave.log") if weave_config else "weave.log"
    weave_log_path = os.path.join(tmpl_dir, log_file)

    from app.run_manager import start_run, get_run
    run_id = start_run(
        weave_dir_name=safe_name,
        weave_name=weave_name,
        script=script,
        script_path=script_path,
        cwd=tmpl_dir,
        script_args=script_args,
        log_path=weave_log_path,
    )

    # Store active run info in weave.json so the weave knows its running process
    run_meta = get_run(run_id) or {}
    try:
        weave_data = {}
        if os.path.isfile(weave_json_path):
            with open(weave_json_path) as f:
                weave_data = json.load(f)
        weave_data["active_run"] = {
            "run_id": run_id,
            "pid": run_meta.get("pid"),
            "pgid": run_meta.get("pgid"),
            "started_at": run_meta.get("started_at"),
            "script": script,
            "args": script_args,
        }
        with open(weave_json_path, "w") as f:
            json.dump(weave_data, f, indent=2)
    except Exception as e:
        logger.warning("Failed to write run info to weave.json: %s", e)

    return {"run_id": run_id, "status": "running"}


