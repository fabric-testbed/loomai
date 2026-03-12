"""VM Template management API routes.

VM templates store per-node configurations (image + boot config).
A VM template is detected by having vm-template.json in the artifact dir.

Storage: FABRIC_STORAGE_DIR/my_artifacts/{name}/
"""

from __future__ import annotations

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


def _ensure_dir() -> None:
    """Ensure the VM templates storage directory exists."""
    os.makedirs(_vm_templates_dir(), exist_ok=True)


# ---------------------------------------------------------------------------
# TTL-based listing cache
# ---------------------------------------------------------------------------

_vm_templates_cache: tuple[float, list] | None = None
_VM_TEMPLATES_CACHE_TTL = 10  # seconds


def _invalidate_vm_templates_cache():
    global _vm_templates_cache
    _vm_templates_cache = None


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
    global _vm_templates_cache
    import time
    if _vm_templates_cache is not None:
        ts, data = _vm_templates_cache
        if time.monotonic() - ts < _VM_TEMPLATES_CACHE_TTL:
            return data
    _ensure_dir()
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
    _vm_templates_cache = (time.monotonic(), results)
    return results


@router.get("/{name}")
def get_vm_template(name: str) -> dict[str, Any]:
    """Get full VM template detail including boot_config."""
    _ensure_dir()
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
    _ensure_dir()
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
    _invalidate_vm_templates_cache()
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
    _invalidate_vm_templates_cache()
    _ensure_dir()
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
    _invalidate_vm_templates_cache()
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
    """Delete a VM template."""
    _invalidate_vm_templates_cache()
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
