"""VM Template management API routes.

VM templates store per-node configurations (image + boot config).
A VM template is detected by having vm-template.json in the artifact dir.

Storage: FABRIC_STORAGE_DIR/my_artifacts/{name}/
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.user_context import get_user_storage

router = APIRouter(prefix="/api/vm-templates", tags=["vm-templates"])


def _vm_templates_dir() -> str:
    from app.user_context import get_artifacts_dir
    return get_artifacts_dir()


def _builtin_templates_dir() -> str:
    """Return the path to the builtin VM templates shipped with the repo."""
    # Check two candidate paths: inside backend (Docker) and repo root (local dev)
    base = os.path.dirname(__file__)
    for levels in [("..", ".."), ("..", "..", "..")]:
        candidate = os.path.realpath(os.path.join(base, *levels, "slice-libraries", "vm_templates"))
        if os.path.isdir(candidate):
            return candidate
    return os.path.join(base, "..", "..", "slice-libraries", "vm_templates")


def _sanitize_name(name: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", name.strip())
    if not safe:
        raise HTTPException(status_code=400, detail="Invalid template name")
    return safe


def _validate_path(base: str, name: str) -> str:
    path = os.path.realpath(os.path.join(base, name))
    if not path.startswith(os.path.realpath(base)):
        raise HTTPException(status_code=400, detail="Invalid template name")
    return path


# ---------------------------------------------------------------------------
# Builtin template helpers
# ---------------------------------------------------------------------------

def _builtin_hash(builtin_dir: str) -> str:
    """Compute a hash of a builtin VM template directory for change detection."""
    hashable: dict[str, Any] = {}
    tmpl_path = os.path.join(builtin_dir, "vm-template.json")
    if os.path.isfile(tmpl_path):
        with open(tmpl_path) as f:
            data = json.load(f)
        hashable["image"] = data.get("image", "")
        hashable["boot_config"] = data.get("boot_config", {})
        hashable["variants"] = data.get("variants", {})
        hashable["setup_script"] = data.get("setup_script", "")
        hashable["remote_dir"] = data.get("remote_dir", "")
        hashable["version"] = data.get("version", "")
    tools_dir = os.path.join(builtin_dir, "tools")
    if os.path.isdir(tools_dir):
        tools = []
        for fn in sorted(os.listdir(tools_dir)):
            fp = os.path.join(tools_dir, fn)
            if os.path.isfile(fp):
                with open(fp) as f:
                    tools.append({"filename": fn, "content": f.read()})
        hashable["_tools"] = tools
    else:
        hashable["_tools"] = []
    # Hash variant subdirectory contents
    variants = data.get("variants", {}) if os.path.isfile(tmpl_path) else {}
    for _img_key, vinfo in sorted(variants.items()):
        vdir = os.path.join(builtin_dir, vinfo.get("dir", ""))
        if os.path.isdir(vdir):
            vfiles = []
            for fn in sorted(os.listdir(vdir)):
                fp = os.path.join(vdir, fn)
                if os.path.isfile(fp):
                    with open(fp) as f:
                        vfiles.append({"filename": fn, "content": f.read()})
            hashable[f"_variant_{vinfo['dir']}"] = vfiles
    return hashlib.sha256(json.dumps(hashable, sort_keys=True).encode()).hexdigest()[:16]


def _list_builtin_templates() -> list[dict[str, Any]]:
    """Scan the builtin VM templates directory and return info for each."""
    bdir = os.path.realpath(_builtin_templates_dir())
    if not os.path.isdir(bdir):
        return []
    results = []
    for entry in sorted(os.listdir(bdir)):
        entry_dir = os.path.join(bdir, entry)
        tmpl_path = os.path.join(entry_dir, "vm-template.json")
        if os.path.isfile(tmpl_path):
            with open(tmpl_path) as f:
                data = json.load(f)
            data["_dir"] = entry_dir
            data["_entry"] = entry
            results.append(data)
    return results


def _seed_if_needed() -> None:
    """Ensure the VM templates storage directory exists.

    Built-in template seeding is disabled — users create or download
    artifacts via the marketplace.
    """
    tdir = _vm_templates_dir()
    os.makedirs(tdir, exist_ok=True)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class CreateVMTemplateRequest(BaseModel):
    name: str
    description: str = ""
    image: str = "default_ubuntu_22"
    boot_config: dict = {}
    cores: Optional[int] = None
    ram: Optional[int] = None
    disk: Optional[int] = None
    site: Optional[str] = None
    host: Optional[str] = None
    image_type: Optional[str] = None
    username: Optional[str] = None
    instance_type: Optional[str] = None
    components: Optional[list] = None


class UpdateVMTemplateRequest(BaseModel):
    description: Optional[str] = None
    image: Optional[str] = None
    boot_config: Optional[dict] = None
    cores: Optional[int] = None
    ram: Optional[int] = None
    disk: Optional[int] = None
    site: Optional[str] = None
    host: Optional[str] = None
    image_type: Optional[str] = None
    username: Optional[str] = None
    instance_type: Optional[str] = None
    components: Optional[list] = None


class ToolFileBody(BaseModel):
    content: str


# ---------------------------------------------------------------------------
# Helper: list tool files
# ---------------------------------------------------------------------------

def _list_tools(tmpl_dir: str) -> list[dict[str, str]]:
    """Return a sorted list of {filename} dicts for tools in a template dir."""
    tools_dir = os.path.join(tmpl_dir, "tools")
    if not os.path.isdir(tools_dir):
        return []
    return [{"filename": fn} for fn in sorted(os.listdir(tools_dir))
            if os.path.isfile(os.path.join(tools_dir, fn))]


def _validate_tool_filename(filename: str) -> str:
    """Sanitize and validate a tool filename."""
    safe = re.sub(r"[^a-zA-Z0-9_\-.]", "_", filename.strip())
    if not safe or safe.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid tool filename")
    return safe


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
def list_vm_templates() -> list[dict[str, Any]]:
    """List VM templates (dirs containing vm-template.json)."""
    _seed_if_needed()
    tdir = _vm_templates_dir()
    if not os.path.isdir(tdir):
        return []
    results = []
    for entry in sorted(os.listdir(tdir)):
        entry_dir = os.path.join(tdir, entry)
        if not os.path.isdir(entry_dir):
            continue
        tmpl_path = os.path.join(entry_dir, "vm-template.json")
        if not os.path.isfile(tmpl_path):
            continue  # Not a VM artifact

        try:
            with open(tmpl_path) as f:
                data = json.load(f)
            # Ensure minimum required fields exist
            changed = False
            if "name" not in data:
                data["name"] = entry
                changed = True
            if "created" not in data:
                data["created"] = datetime.now(timezone.utc).isoformat()
                changed = True
            if changed:
                with open(tmpl_path, "w") as f:
                    json.dump(data, f, indent=2)

            variants = data.get("variants", {})
            summary: dict[str, Any] = {
                "name": data.get("name", entry),
                "description": data.get("description", ""),
                "image": data.get("image", ""),
                "created": data.get("created", ""),
                "dir_name": entry,
                "variant_count": len(variants),
                "version": data.get("version", ""),
            }
            if variants:
                summary["images"] = list(variants.keys())
            else:
                summary["images"] = []
            results.append(summary)
        except Exception:
            pass
    return results


@router.get("/{name}")
def get_vm_template(name: str) -> dict[str, Any]:
    """Get full VM template detail including boot_config."""
    _seed_if_needed()
    safe = _sanitize_name(name)
    tdir = _vm_templates_dir()
    tmpl_dir = _validate_path(tdir, safe)
    tmpl_path = os.path.join(tmpl_dir, "vm-template.json")
    if not os.path.isfile(tmpl_path):
        raise HTTPException(status_code=404, detail=f"VM template '{name}' not found")
    with open(tmpl_path) as f:
        data = json.load(f)
    data["dir_name"] = safe
    data["tools"] = _list_tools(tmpl_dir)
    return data


@router.get("/{name}/variant/{image}")
def get_vm_template_variant(name: str, image: str) -> dict[str, Any]:
    """Synthesize a boot_config for a specific variant of a multi-image template.

    Returns an object with ``image``, ``boot_config``, and variant metadata.
    The boot_config uploads the variant directory to ``remote_dir`` and runs
    the ``setup_script``.
    """
    _seed_if_needed()
    safe = _sanitize_name(name)
    tdir = _vm_templates_dir()
    tmpl_dir = _validate_path(tdir, safe)
    tmpl_path = os.path.join(tmpl_dir, "vm-template.json")
    if not os.path.isfile(tmpl_path):
        raise HTTPException(status_code=404, detail=f"VM template '{name}' not found")

    with open(tmpl_path) as f:
        data = json.load(f)

    variants = data.get("variants", {})
    if not variants:
        raise HTTPException(status_code=400, detail="Template has no variants")
    if image not in variants:
        raise HTTPException(status_code=404, detail=f"No variant for image '{image}'")

    vinfo = variants[image]
    vdir_name = vinfo.get("dir", "")
    vdir_path = os.path.join(tmpl_dir, vdir_name)
    setup_script = data.get("setup_script", "setup.sh")
    remote_dir = data.get("remote_dir", f"~/.fabric/vm-templates/{safe}")

    # Build uploads list from variant directory files
    uploads = []
    if os.path.isdir(vdir_path):
        for fn in sorted(os.listdir(vdir_path)):
            fp = os.path.join(vdir_path, fn)
            if os.path.isfile(fp):
                uploads.append({
                    "id": f"vt_{fn}",
                    "source": f"my_artifacts/{safe}/{vdir_name}/{fn}",
                    "dest": f"{remote_dir}/{fn}",
                })

    # Build commands to make script executable and run it
    commands = [
        {
            "id": "vt_chmod",
            "command": f"chmod +x {remote_dir}/{setup_script}",
            "order": 0,
        },
        {
            "id": "vt_run",
            "command": f"sudo {remote_dir}/{setup_script}",
            "order": 1,
        },
    ]

    return {
        "image": image,
        "label": vinfo.get("label", image),
        "boot_config": {
            "uploads": uploads,
            "commands": commands,
            "network": [],
        },
        "template_name": data.get("name", name),
        "variant_dir": vdir_name,
        "remote_dir": remote_dir,
    }


@router.post("/resync")
def resync_vm_templates() -> list[dict[str, Any]]:
    """Clean corrupted entries and return updated list."""
    tdir = _vm_templates_dir()
    os.makedirs(tdir, exist_ok=True)

    # Remove corrupted entries
    if os.path.isdir(tdir):
        for entry in os.listdir(tdir):
            entry_dir = os.path.join(tdir, entry)
            if not os.path.isdir(entry_dir):
                continue
            tmpl_path = os.path.join(entry_dir, "vm-template.json")
            if not os.path.isfile(tmpl_path):
                shutil.rmtree(entry_dir)

    return list_vm_templates()


@router.post("")
def create_vm_template(req: CreateVMTemplateRequest) -> dict[str, Any]:
    """Create a new VM template."""
    _seed_if_needed()
    safe = _sanitize_name(req.name)
    tdir = _vm_templates_dir()
    os.makedirs(tdir, exist_ok=True)
    tmpl_dir = _validate_path(tdir, safe)

    if os.path.isdir(tmpl_dir):
        raise HTTPException(status_code=409, detail=f"VM template '{req.name}' already exists")

    os.makedirs(tmpl_dir, exist_ok=True)
    data: dict[str, Any] = {
        "name": req.name,
        "description": req.description,
        "image": req.image,
        "builtin": False,
        "created": datetime.now(timezone.utc).isoformat(),
        "boot_config": req.boot_config,
    }
    if req.cores is not None:
        data["cores"] = req.cores
    if req.ram is not None:
        data["ram"] = req.ram
    if req.disk is not None:
        data["disk"] = req.disk
    if req.site:
        data["site"] = req.site
    if req.host:
        data["host"] = req.host
    if req.image_type:
        data["image_type"] = req.image_type
    if req.username:
        data["username"] = req.username
    if req.instance_type:
        data["instance_type"] = req.instance_type
    if req.components:
        data["components"] = req.components
    with open(os.path.join(tmpl_dir, "vm-template.json"), "w") as f:
        json.dump(data, f, indent=2)
    return data


@router.put("/{name}")
def update_vm_template(name: str, req: UpdateVMTemplateRequest) -> dict[str, Any]:
    """Update a VM template."""
    safe = _sanitize_name(name)
    tdir = _vm_templates_dir()
    tmpl_dir = _validate_path(tdir, safe)
    tmpl_path = os.path.join(tmpl_dir, "vm-template.json")
    if not os.path.isfile(tmpl_path):
        raise HTTPException(status_code=404, detail=f"VM template '{name}' not found")

    with open(tmpl_path) as f:
        data = json.load(f)

    if req.description is not None:
        data["description"] = req.description
    if req.image is not None:
        data["image"] = req.image
    if req.boot_config is not None:
        data["boot_config"] = req.boot_config
    if req.cores is not None:
        data["cores"] = req.cores
    if req.ram is not None:
        data["ram"] = req.ram
    if req.disk is not None:
        data["disk"] = req.disk
    if req.site is not None:
        data["site"] = req.site
    if req.host is not None:
        data["host"] = req.host
    if req.image_type is not None:
        data["image_type"] = req.image_type
    if req.username is not None:
        data["username"] = req.username
    if req.instance_type is not None:
        data["instance_type"] = req.instance_type
    if req.components is not None:
        data["components"] = req.components

    with open(tmpl_path, "w") as f:
        json.dump(data, f, indent=2)

    data["dir_name"] = safe
    return data


@router.delete("/{name}")
def delete_vm_template(name: str) -> dict[str, str]:
    """Delete a VM template (builtins cannot be deleted)."""
    safe = _sanitize_name(name)
    tdir = _vm_templates_dir()
    tmpl_dir = _validate_path(tdir, safe)
    tmpl_path = os.path.join(tmpl_dir, "vm-template.json")

    if not os.path.isdir(tmpl_dir):
        raise HTTPException(status_code=404, detail=f"VM template '{name}' not found")

    shutil.rmtree(tmpl_dir)
    return {"status": "deleted", "name": name}


# ---------------------------------------------------------------------------
# Tool file endpoints
# ---------------------------------------------------------------------------

@router.get("/{name}/tools/{filename}")
def read_vm_tool(name: str, filename: str) -> dict[str, str]:
    """Read a VM template tool file's content."""
    safe = _sanitize_name(name)
    safe_file = _validate_tool_filename(filename)
    tdir = _vm_templates_dir()
    tmpl_dir = _validate_path(tdir, safe)
    tool_path = os.path.join(tmpl_dir, "tools", safe_file)

    if not os.path.isfile(tool_path):
        raise HTTPException(status_code=404, detail=f"Tool file '{filename}' not found")

    with open(tool_path) as f:
        content = f.read()
    return {"filename": safe_file, "content": content}


@router.put("/{name}/tools/{filename}")
def write_vm_tool(name: str, filename: str, body: ToolFileBody) -> dict[str, str]:
    """Create or update a VM template tool file."""
    safe = _sanitize_name(name)
    safe_file = _validate_tool_filename(filename)
    tdir = _vm_templates_dir()
    tmpl_dir = _validate_path(tdir, safe)

    if not os.path.isdir(tmpl_dir):
        raise HTTPException(status_code=404, detail=f"VM template '{name}' not found")

    tools_dir = os.path.join(tmpl_dir, "tools")
    os.makedirs(tools_dir, exist_ok=True)
    tool_path = os.path.join(tools_dir, safe_file)

    with open(tool_path, "w") as f:
        f.write(body.content)
    return {"filename": safe_file, "status": "saved"}


@router.delete("/{name}/tools/{filename}")
def delete_vm_tool(name: str, filename: str) -> dict[str, str]:
    """Delete a VM template tool file."""
    safe = _sanitize_name(name)
    safe_file = _validate_tool_filename(filename)
    tdir = _vm_templates_dir()
    tmpl_dir = _validate_path(tdir, safe)
    tool_path = os.path.join(tmpl_dir, "tools", safe_file)

    if not os.path.isfile(tool_path):
        raise HTTPException(status_code=404, detail=f"Tool file '{filename}' not found")

    os.remove(tool_path)
    return {"filename": safe_file, "status": "deleted"}
