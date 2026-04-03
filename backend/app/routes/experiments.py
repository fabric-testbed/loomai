"""Runnable weave and cross-testbed experiment management API routes.

Runnable weaves are weave artifacts that have a run script for automatic execution.
A runnable weave is detected by having weave.json (with run_script field) and a
topology file.

Cross-testbed experiment templates use the ``loomai-experiment-v1`` format to
capture both FABRIC and Chameleon resources in a single ``experiment.json`` file,
enabling variable substitution and one-click deployment across testbeds.

Storage: FABRIC_STORAGE_DIR/my_artifacts/{name}/
"""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, HTTPException
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
    """List runnable weaves (weave artifacts that have a run script)."""
    _ensure_dir()
    edir = _experiments_dir()
    if not os.path.isdir(edir):
        return []
    results = []
    for entry in sorted(os.listdir(edir)):
        entry_dir = os.path.join(edir, entry)
        if not os.path.isdir(entry_dir):
            continue
        # A runnable weave needs weave.json and a weave.sh script
        has_weave_json = os.path.isfile(os.path.join(entry_dir, "weave.json"))
        has_weave_sh = os.path.isfile(os.path.join(entry_dir, "weave.sh"))
        if not has_weave_json:
            continue  # No weave marker
        if not has_weave_sh:
            continue  # Not a runnable weave — no run script

        # Read metadata from weave.json
        meta: dict[str, Any] = {}
        for meta_file in ["weave.json", "experiment.json"]:
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


# ---------------------------------------------------------------------------
# Cross-testbed experiment template helpers
# ---------------------------------------------------------------------------

_EXPERIMENT_FORMAT = "loomai-experiment-v1"


def _substitute_variables(data: Any, variables: dict[str, str]) -> Any:
    """Recursively substitute ``${VAR}`` placeholders in strings.

    Walks dicts, lists, and strings. Non-string leaves are returned as-is.
    """
    if isinstance(data, str):
        for key, val in variables.items():
            data = data.replace(f"${{{key}}}", str(val))
        return data
    elif isinstance(data, dict):
        return {k: _substitute_variables(v, variables) for k, v in data.items()}
    elif isinstance(data, list):
        return [_substitute_variables(item, variables) for item in data]
    return data


def _build_cross_testbed_connections(
    fabric_nodes: list[dict],
    chameleon_nodes: list[dict],
) -> list[dict]:
    """Infer cross-testbed connections from Chameleon node connection types.

    A Chameleon node with ``connection_type`` of ``fabnet_v4`` or ``fabnet_v6``
    is assumed to connect to a FABRIC node through the FABRIC overlay network.
    """
    connections: list[dict] = []
    fab_names = [n["name"] for n in fabric_nodes]
    for chi_node in chameleon_nodes:
        conn_type = chi_node.get("connection_type", "")
        if conn_type.startswith("fabnet") and fab_names:
            connections.append({
                "fabric_node": fab_names[0],
                "chameleon_node": chi_node["name"],
                "type": conn_type,
            })
    return connections


# ---------------------------------------------------------------------------
# Cross-testbed experiment template endpoints
# ---------------------------------------------------------------------------


@router.post("/save")
def save_experiment_template(body: dict = Body(...)) -> dict[str, Any]:
    """Save the current composite slice as a cross-testbed experiment template.

    Captures both FABRIC topology (via ``build_slice_model``) and Chameleon
    nodes (from in-memory ``_chameleon_slice_nodes``) into a single
    ``experiment.json`` file using the ``loomai-experiment-v1`` format.
    """
    from app.routes.templates import (
        _invalidate_templates_cache,
        _WEAVE_CONFIG_DEFAULTS,
    )

    name: str = body.get("name", "").strip()
    description: str = body.get("description", "")
    slice_name: str = body.get("slice_name", "").strip()
    variables: list[dict] = body.get("variables", [])
    author: str = body.get("author", "")
    tags: list[str] = body.get("tags", ["cross-testbed"])

    if not name:
        raise HTTPException(status_code=400, detail="Experiment name is required")

    _invalidate_templates_cache()
    _ensure_dir()
    safe_name = _sanitize_name(name)
    edir = _experiments_dir()
    os.makedirs(edir, exist_ok=True)
    exp_dir = _validate_path(edir, safe_name)

    if os.path.isdir(exp_dir):
        raise HTTPException(status_code=409, detail=f"Experiment '{name}' already exists")

    # --- Build FABRIC portion ---
    fabric_section: dict[str, Any] = {
        "nodes": [],
        "networks": [],
        "facility_ports": [],
        "port_mirrors": [],
    }
    if slice_name:
        try:
            from app.routes.slices import build_slice_model
            model = build_slice_model(slice_name)
            fabric_section["nodes"] = model.get("nodes", [])
            fabric_section["networks"] = model.get("networks", [])
            fabric_section["facility_ports"] = model.get("facility_ports", [])
            fabric_section["port_mirrors"] = model.get("port_mirrors", [])
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to export FABRIC slice: {e}")

    # --- Build Chameleon portion ---
    from app.routes.chameleon import _chameleon_slice_nodes
    chi_nodes_raw = _chameleon_slice_nodes.get(slice_name, []) if slice_name else []
    chameleon_section: dict[str, Any] = {
        "nodes": [
            {
                "name": n.get("name", ""),
                "site": n.get("site", "CHI@TACC"),
                "node_type": n.get("node_type", "compute_haswell"),
                "image": n.get("image_id", ""),
                "connection_type": n.get("connection_type", "fabnet_v4"),
            }
            for n in chi_nodes_raw
        ],
        "networks": [],
        "floating_ips": [],
    }

    # --- Cross-testbed connections ---
    cross_section: dict[str, Any] = {
        "connections": _build_cross_testbed_connections(
            fabric_section["nodes"], chameleon_section["nodes"]
        ),
    }

    # --- Default variables ---
    if not variables:
        default_slug = _sanitize_name(name).lower().replace("_", "-")
        variables = [
            {
                "name": "SLICE_NAME",
                "label": "Experiment Name",
                "type": "string",
                "default": default_slug,
                "required": True,
            }
        ]

    now = datetime.now(timezone.utc).isoformat()
    experiment_data: dict[str, Any] = {
        "format": _EXPERIMENT_FORMAT,
        "name": name,
        "description": description,
        "author": author,
        "tags": tags,
        "created": now,
        "variables": variables,
        "fabric": fabric_section,
        "chameleon": chameleon_section,
        "cross_testbed": cross_section,
    }

    # --- Write to disk ---
    os.makedirs(exp_dir, exist_ok=True)
    os.makedirs(os.path.join(exp_dir, "scripts"), exist_ok=True)

    with open(os.path.join(exp_dir, "experiment.json"), "w") as f:
        json.dump(experiment_data, f, indent=2)

    # Also write slice.json for backward compat with existing template loader
    if fabric_section["nodes"] or fabric_section["networks"]:
        slice_model = {
            "format": "fabric-webgui-v1",
            "name": name,
            "nodes": fabric_section["nodes"],
            "networks": fabric_section["networks"],
            "facility_ports": fabric_section.get("facility_ports", []),
            "port_mirrors": fabric_section.get("port_mirrors", []),
        }
        with open(os.path.join(exp_dir, "slice.json"), "w") as f:
            json.dump(slice_model, f, indent=2)

    # Write weave.json with is_experiment flag for backward compat
    weave_data = {
        **_WEAVE_CONFIG_DEFAULTS,
        "name": name,
        "description": description,
        "is_experiment": True,
        "created": now,
    }
    with open(os.path.join(exp_dir, "weave.json"), "w") as f:
        json.dump(weave_data, f, indent=2)

    # Seed .weaveignore
    weaveignore_path = os.path.join(exp_dir, ".weaveignore")
    if not os.path.isfile(weaveignore_path):
        with open(weaveignore_path, "w") as f:
            f.write(
                "# .weaveignore — files excluded from publishing\n"
                "data/\nresults/\noutput/\n*.csv\n*.key\n*.pem\nsecrets/\n"
            )

    experiment_data["dir_name"] = safe_name
    return experiment_data


@router.get("/{name}/template")
def get_experiment_template(name: str) -> dict[str, Any]:
    """Get the experiment.json for a cross-testbed experiment template."""
    _ensure_dir()
    safe = _sanitize_name(name)
    edir = _experiments_dir()
    exp_dir = _validate_path(edir, safe)
    exp_path = os.path.join(exp_dir, "experiment.json")
    if not os.path.isfile(exp_path):
        raise HTTPException(status_code=404, detail=f"Experiment template '{name}' not found")

    with open(exp_path) as f:
        data = json.load(f)
    data["dir_name"] = safe
    return data


@router.post("/{name}/load-experiment")
def load_experiment_template(name: str, body: dict = Body(default={})) -> dict[str, Any]:
    """Load a cross-testbed experiment template, applying variable substitutions.

    Creates a new FABRIC draft slice and populates Chameleon nodes in-memory.
    """
    _ensure_dir()
    safe = _sanitize_name(name)
    edir = _experiments_dir()
    exp_dir = _validate_path(edir, safe)
    exp_path = os.path.join(exp_dir, "experiment.json")
    if not os.path.isfile(exp_path):
        raise HTTPException(status_code=404, detail=f"Experiment template '{name}' not found")

    with open(exp_path) as f:
        experiment_data = json.load(f)

    # Apply variable substitutions
    user_vars: dict[str, str] = body.get("variables", {})
    # Merge user-provided values with defaults from the template
    merged_vars: dict[str, str] = {}
    for var_def in experiment_data.get("variables", []):
        var_name = var_def["name"]
        if var_name in user_vars:
            merged_vars[var_name] = str(user_vars[var_name])
        elif "default" in var_def:
            merged_vars[var_name] = str(var_def["default"])

    resolved = _substitute_variables(experiment_data, merged_vars)

    # Determine new slice name
    slice_name = merged_vars.get("SLICE_NAME", "").strip()
    if not slice_name:
        slice_name = resolved.get("name", name)

    # --- Import FABRIC portion ---
    fabric = resolved.get("fabric", {})
    fabric_nodes = fabric.get("nodes", [])
    fabric_networks = fabric.get("networks", [])
    fabric_fp = fabric.get("facility_ports", [])
    fabric_pm = fabric.get("port_mirrors", [])

    result: dict[str, Any] = {"name": slice_name}

    if fabric_nodes or fabric_networks:
        from app.routes.slices import import_slice, SliceModelImport

        model_data = {
            "format": "fabric-webgui-v1",
            "name": slice_name,
            "nodes": fabric_nodes,
            "networks": fabric_networks,
            "facility_ports": fabric_fp,
            "port_mirrors": fabric_pm,
        }
        model = SliceModelImport(**model_data)
        result = import_slice(model)

        # Store boot info
        from app.routes.templates import _store_boot_info
        _store_boot_info(slice_name, exp_dir)

        # Auto-resolve site groups
        from app.routes.slices import _get_site_groups, _get_draft, _store_site_groups, _serialize
        site_groups = _get_site_groups(slice_name)
        if site_groups:
            try:
                from app.site_resolver import resolve_sites
                from app.routes.resources import get_cached_sites
                from app.routes.slices import slice_to_dict

                draft = _get_draft(slice_name)
                if draft is not None:
                    data_dict = slice_to_dict(draft)
                    node_defs = []
                    for node in data_dict.get("nodes", []):
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
                    merged_site_groups = dict(site_groups)
                    merged_site_groups.update(new_groups)
                    _store_site_groups(slice_name, merged_site_groups)
                    result = _serialize(draft, dirty=True)
            except Exception:
                pass

    # --- Import Chameleon portion ---
    chameleon = resolved.get("chameleon", {})
    chi_nodes = chameleon.get("nodes", [])
    if chi_nodes:
        from app.routes.chameleon import _chameleon_slice_nodes
        chi_list = _chameleon_slice_nodes.setdefault(slice_name, [])
        for cn in chi_nodes:
            chi_list.append({
                "name": cn.get("name", ""),
                "site": cn.get("site", "CHI@TACC"),
                "node_type": cn.get("node_type", "compute_haswell"),
                "image_id": cn.get("image", ""),
                "connection_type": cn.get("connection_type", "fabnet_v4"),
                "status": "draft",
            })

    # Include metadata about loaded experiment in the result
    result["experiment_loaded"] = True
    result["experiment_name"] = resolved.get("name", name)
    result["chameleon_nodes"] = chi_nodes
    result["cross_testbed"] = resolved.get("cross_testbed", {})

    return result
