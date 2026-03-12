"""File browser endpoints: container storage CRUD, VM SFTP, provisioning."""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import shutil
import tempfile
import threading
import uuid
import zipfile
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from app.fablib_manager import get_fablib
from app.slice_registry import resolve_slice_name
from app.user_context import get_user_storage
from app.routes.terminal import (
    _load_private_key,
    _get_ssh_config,
    _connect_bastion,
    _open_tunnel,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# Per-slice boot config log storage
# ---------------------------------------------------------------------------

_boot_logs: dict[str, list] = {}
_boot_running: set[str] = set()
_boot_lock = threading.Lock()


def _load_template_dir(slice_name: str) -> str | None:
    """Return the template directory stored when a template was loaded, or None."""
    storage = get_user_storage()
    info_path = os.path.join(storage, ".boot_info", f"{slice_name}.json")
    if not os.path.isfile(info_path):
        return None
    try:
        with open(info_path) as f:
            return json.load(f).get("template_dir")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _storage_dir() -> str:
    return get_user_storage()


def _safe_path(base: str, user_path: str) -> str:
    """Resolve *user_path* under *base*, rejecting traversals.

    If *user_path* is already an absolute path that lives under *base*,
    it is accepted as-is (this happens for template/recipe tool directories
    injected at load time).
    """
    # If user_path is absolute and already under base, accept it directly
    if os.path.isabs(user_path):
        resolved = os.path.realpath(user_path)
        base_resolved = os.path.realpath(base)
        if resolved.startswith(base_resolved + os.sep) or resolved == base_resolved:
            return resolved
        # Also allow paths under the templates/recipes source directories
        # (e.g. slice-libraries paths baked into the Docker image)
        if os.path.exists(resolved):
            return resolved
        raise HTTPException(status_code=400, detail="Path traversal not allowed")
    joined = os.path.join(base, user_path.lstrip("/"))
    resolved = os.path.realpath(joined)
    base_resolved = os.path.realpath(base)
    if not resolved.startswith(base_resolved + os.sep) and resolved != base_resolved:
        raise HTTPException(status_code=400, detail="Path traversal not allowed")
    return resolved


def _entry(full_path: str) -> dict:
    """Build a FileEntry dict for a single path."""
    st = os.stat(full_path)
    return {
        "name": os.path.basename(full_path),
        "type": "dir" if os.path.isdir(full_path) else "file",
        "size": st.st_size,
        "modified": datetime.fromtimestamp(st.st_mtime).isoformat(),
    }


def _provisions_dir() -> str:
    d = os.path.join(_storage_dir(), ".provisions")
    os.makedirs(d, exist_ok=True)
    return d


def _load_provisions(slice_name: str) -> list:
    path = os.path.join(_provisions_dir(), f"{slice_name}.json")
    if not os.path.isfile(path):
        return []
    with open(path) as f:
        return json.load(f)


def _save_provisions(slice_name: str, rules: list):
    path = os.path.join(_provisions_dir(), f"{slice_name}.json")
    with open(path, "w") as f:
        json.dump(rules, f, indent=2)


# ---------------------------------------------------------------------------
# FABlib node helper
# ---------------------------------------------------------------------------

def _get_node(slice_name: str, node_name: str):
    """Return FABlib node object for a slice/node pair."""
    fablib = get_fablib()
    from app.slice_registry import get_slice_uuid
    uuid = get_slice_uuid(slice_name)
    if uuid:
        try:
            slice_obj = fablib.get_slice(slice_id=uuid)
            return slice_obj.get_node(node_name)
        except Exception:
            pass
    slice_obj = fablib.get_slice(slice_name)
    return slice_obj.get_node(node_name)


# ---------------------------------------------------------------------------
# SFTP helper (used only for VM file listing)
# ---------------------------------------------------------------------------

def _get_sftp(slice_name: str, node_name: str):
    """Return (bastion, target_client, sftp_client) for a VM node."""
    import paramiko

    fablib = get_fablib()
    from app.slice_registry import get_slice_uuid
    uuid = get_slice_uuid(slice_name)
    if uuid:
        try:
            slice_obj = fablib.get_slice(slice_id=uuid)
        except Exception:
            slice_obj = fablib.get_slice(slice_name)
    else:
        slice_obj = fablib.get_slice(slice_name)
    node_obj = slice_obj.get_node(node_name)
    management_ip = str(node_obj.get_management_ip())
    username = node_obj.get_username()

    if not management_ip:
        raise HTTPException(status_code=400, detail="Node has no management IP")

    ssh_config = _get_ssh_config(slice_name=slice_name)
    bastion = _connect_bastion(ssh_config)
    channel = _open_tunnel(bastion, management_ip)

    pkey = _load_private_key(ssh_config["slice_key"])
    target = paramiko.SSHClient()
    target.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    target.connect(
        hostname=management_ip,
        username=username,
        pkey=pkey,
        sock=channel,
        timeout=15,
    )
    sftp = target.open_sftp()
    return bastion, target, sftp


# ---------------------------------------------------------------------------
# Container file endpoints
# ---------------------------------------------------------------------------

@router.get("/api/files")
async def list_files(path: str = ""):
    base = _storage_dir()
    target = _safe_path(base, path)
    if not os.path.isdir(target):
        raise HTTPException(status_code=404, detail="Directory not found")
    def _do():
        entries = []
        for name in sorted(os.listdir(target)):
            if name in (".provisions", ".boot-config", ".slice-keys", ".all_slices"):
                continue
            full = os.path.join(target, name)
            try:
                entries.append(_entry(full))
            except OSError:
                continue
        return entries
    return await asyncio.to_thread(_do)


@router.post("/api/files/upload")
async def upload_files(path: str = "", files: List[UploadFile] = File(...)):
    base = _storage_dir()
    target = _safe_path(base, path)
    os.makedirs(target, exist_ok=True)
    saved = []
    for f in files:
        # filename may contain subdirectory paths (e.g. "folder/sub/file.txt")
        dest = os.path.join(target, f.filename)
        resolved = os.path.realpath(dest)
        # Prevent writing outside target
        if not resolved.startswith(os.path.realpath(target) + os.sep) and resolved != os.path.realpath(target):
            continue
        # Create intermediate directories for nested paths
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        content = await f.read()
        with open(dest, "wb") as out:
            out.write(content)
        saved.append(f.filename)
    return {"uploaded": saved}


class MkdirRequest(BaseModel):
    name: str


@router.post("/api/files/mkdir")
async def create_folder(body: MkdirRequest, path: str = ""):
    base = _storage_dir()
    target = _safe_path(base, path)
    new_dir = os.path.join(target, body.name)
    _safe_path(base, os.path.join(path, body.name))
    os.makedirs(new_dir, exist_ok=True)
    return {"created": body.name}


MAX_TEXT_SIZE = 5 * 1024 * 1024  # 5 MB


@router.get("/api/files/content")
async def read_file_content(path: str = ""):
    """Read text file content for in-browser editing."""
    base = _storage_dir()
    target = _safe_path(base, path)
    if not os.path.isfile(target):
        raise HTTPException(status_code=404, detail="File not found")
    size = os.path.getsize(target)
    if size > MAX_TEXT_SIZE:
        raise HTTPException(status_code=400, detail="File too large to edit (>5 MB)")
    def _do():
        try:
            with open(target, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Cannot read file: {e}")
        return {"path": path, "content": content}
    return await asyncio.to_thread(_do)


class FileContentBody(BaseModel):
    path: str
    content: str


@router.put("/api/files/content")
async def write_file_content(body: FileContentBody):
    """Write text file content from in-browser editor."""
    base = _storage_dir()
    target = _safe_path(base, body.path)
    def _do():
        try:
            with open(target, "w", encoding="utf-8") as f:
                f.write(body.content)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Cannot write file: {e}")
        return {"path": body.path, "status": "ok"}
    return await asyncio.to_thread(_do)


@router.get("/api/files/download")
async def download_file(path: str = ""):
    base = _storage_dir()
    target = _safe_path(base, path)
    if not os.path.isfile(target):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(target, filename=os.path.basename(target))


@router.get("/api/files/download-folder")
async def download_folder(path: str = ""):
    base = _storage_dir()
    target = _safe_path(base, path)
    if not os.path.isdir(target):
        raise HTTPException(status_code=404, detail="Directory not found")
    def _do():
        buf = io.BytesIO()
        folder_name = os.path.basename(target) or "storage"
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(target):
                dirs[:] = [d for d in dirs if d not in (".provisions", ".boot-config", ".slice-keys", ".all_slices")]
                for fname in files:
                    full = os.path.join(root, fname)
                    arcname = os.path.relpath(full, target)
                    zf.write(full, arcname)
        buf.seek(0)
        return buf, folder_name
    buf, folder_name = await asyncio.to_thread(_do)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{folder_name}.zip"'},
    )


@router.delete("/api/files")
async def delete_file(path: str = ""):
    base = _storage_dir()
    if not path or path.strip("/") == "":
        raise HTTPException(status_code=400, detail="Cannot delete storage root")
    target = _safe_path(base, path)
    if not os.path.exists(target):
        raise HTTPException(status_code=404, detail="Path not found")
    if os.path.isdir(target):
        shutil.rmtree(target)
    else:
        os.remove(target)
    return {"deleted": path}


# ---------------------------------------------------------------------------
# VM file endpoints (SFTP)
# ---------------------------------------------------------------------------

@router.get("/api/files/vm/{slice_name}/{node_name}")
async def list_vm_files(slice_name: str, node_name: str, path: str = "/home"):
    slice_name = resolve_slice_name(slice_name)
    def _do():
        bastion, target, sftp = _get_sftp(slice_name, node_name)
        try:
            entries = []
            for attr in sftp.listdir_attr(path):
                import stat as stat_mod
                entry = {
                    "name": attr.filename,
                    "type": "dir" if stat_mod.S_ISDIR(attr.st_mode or 0) else "file",
                    "size": attr.st_size or 0,
                    "modified": datetime.fromtimestamp(attr.st_mtime or 0).isoformat() if attr.st_mtime else "",
                }
                entries.append(entry)
            return sorted(entries, key=lambda e: (e["type"] != "dir", e["name"]))
        finally:
            sftp.close()
            target.close()
            bastion.close()

    return await asyncio.to_thread(_do)


class VmDownloadRequest(BaseModel):
    remote_path: str
    dest_dir: str = ""


@router.post("/api/files/vm/{slice_name}/{node_name}/download")
async def download_vm_file(slice_name: str, node_name: str, body: VmDownloadRequest):
    slice_name = resolve_slice_name(slice_name)
    def _do():
        node_obj = _get_node(slice_name, node_name)
        base = _storage_dir()
        dest = _safe_path(base, body.dest_dir)
        os.makedirs(dest, exist_ok=True)
        filename = os.path.basename(body.remote_path)
        local_path = os.path.join(dest, filename)
        node_obj.download_file(local_path, body.remote_path)
        return {"downloaded": filename, "local_path": os.path.join(body.dest_dir, filename)}

    return await asyncio.to_thread(_do)


class VmUploadRequest(BaseModel):
    source: str
    dest: str


@router.post("/api/files/vm/{slice_name}/{node_name}/upload")
async def upload_to_vm(slice_name: str, node_name: str, body: VmUploadRequest):
    slice_name = resolve_slice_name(slice_name)
    def _do():
        base = _storage_dir()
        local_path = _safe_path(base, body.source)
        if not os.path.exists(local_path):
            raise HTTPException(status_code=404, detail="Source not found in container storage")

        node_obj = _get_node(slice_name, node_name)
        if os.path.isdir(local_path):
            node_obj.upload_directory(local_path, body.dest)
        else:
            node_obj.upload_file(local_path, body.dest)
        return {"uploaded": body.source, "remote_path": body.dest}

    return await asyncio.to_thread(_do)


@router.post("/api/files/vm/{slice_name}/{node_name}/upload-direct")
async def upload_direct_to_vm(
    slice_name: str,
    node_name: str,
    dest_path: str = Query("/home"),
    files: List[UploadFile] = File(...),
):
    """Upload files directly from the browser to a VM.

    Files are written to a temp directory, pushed to the VM via FABlib,
    then cleaned up.  The filename field may contain subdirectory segments
    (e.g. ``folder/sub/file.txt``) to preserve folder structure.
    """
    slice_name = resolve_slice_name(slice_name)
    tmp_dir = tempfile.mkdtemp(prefix="fabric_vm_upload_")
    saved: list[str] = []
    try:
        # 1. Write uploaded files to temp dir, preserving relative paths
        for f in files:
            local = os.path.join(tmp_dir, f.filename)
            os.makedirs(os.path.dirname(local), exist_ok=True)
            content = await f.read()
            with open(local, "wb") as out:
                out.write(content)
            saved.append(f.filename)

        # 2. Push to VM via FABlib (in a thread)
        def _do():
            node_obj = _get_node(slice_name, node_name)
            # Check if we have top-level directories (folder upload)
            top_items = os.listdir(tmp_dir)
            for item in top_items:
                item_path = os.path.join(tmp_dir, item)
                remote = dest_path.rstrip("/") + "/" + item
                if os.path.isdir(item_path):
                    node_obj.upload_directory(item_path, remote)
                else:
                    node_obj.upload_file(item_path, remote)

        await asyncio.to_thread(_do)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return {"uploaded": saved, "dest": dest_path}


@router.get("/api/files/vm/{slice_name}/{node_name}/download-direct")
async def download_direct_from_vm(
    slice_name: str,
    node_name: str,
    remote_path: str = Query(...),
):
    """Download a single file from a VM directly to the browser."""
    slice_name = resolve_slice_name(slice_name)
    tmp_dir = tempfile.mkdtemp(prefix="fabric_vm_dl_")
    filename = os.path.basename(remote_path) or "download"
    local_path = os.path.join(tmp_dir, filename)

    def _do():
        node_obj = _get_node(slice_name, node_name)
        node_obj.download_file(local_path, remote_path)

    await asyncio.to_thread(_do)

    if not os.path.isfile(local_path):
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail="Download from VM failed")

    # Stream the file and clean up the temp dir afterward
    def iterfile():
        try:
            with open(local_path, "rb") as f:
                while chunk := f.read(1024 * 1024):
                    yield chunk
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    return StreamingResponse(
        iterfile(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/files/vm/{slice_name}/{node_name}/download-folder")
async def download_folder_from_vm(
    slice_name: str,
    node_name: str,
    remote_path: str = Query(...),
):
    """Download a folder from a VM as a zip file to the browser."""
    slice_name = resolve_slice_name(slice_name)
    tmp_dir = tempfile.mkdtemp(prefix="fabric_vm_dldir_")

    def _do():
        bastion, target, sftp = _get_sftp(slice_name, node_name)
        try:
            _sftp_download_recursive(sftp, remote_path, tmp_dir)
        finally:
            sftp.close()
            target.close()
            bastion.close()

    await asyncio.to_thread(_do)

    folder_name = os.path.basename(remote_path.rstrip("/")) or "folder"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(tmp_dir):
            for fname in files:
                full = os.path.join(root, fname)
                arcname = os.path.relpath(full, tmp_dir)
                zf.write(full, arcname)
    shutil.rmtree(tmp_dir, ignore_errors=True)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{folder_name}.zip"'},
    )


def _sftp_download_recursive(sftp, remote_dir: str, local_dir: str):
    """Recursively download a remote directory via SFTP."""
    import stat as stat_mod
    os.makedirs(local_dir, exist_ok=True)
    for attr in sftp.listdir_attr(remote_dir):
        remote_path = f"{remote_dir.rstrip('/')}/{attr.filename}"
        local_path = os.path.join(local_dir, attr.filename)
        if stat_mod.S_ISDIR(attr.st_mode or 0):
            _sftp_download_recursive(sftp, remote_path, local_path)
        else:
            sftp.get(remote_path, local_path)


class VmReadFileRequest(BaseModel):
    path: str


@router.post("/api/files/vm/{slice_name}/{node_name}/read-content")
async def read_vm_file_content(slice_name: str, node_name: str, body: VmReadFileRequest):
    """Read a text file from a VM for in-browser editing."""
    slice_name = resolve_slice_name(slice_name)
    def _do():
        node_obj = _get_node(slice_name, node_name)
        stdout, stderr = node_obj.execute(
            f"cat {body.path!r}", quiet=True
        )
        return {"path": body.path, "content": stdout}

    return await asyncio.to_thread(_do)


class VmWriteFileRequest(BaseModel):
    path: str
    content: str


@router.post("/api/files/vm/{slice_name}/{node_name}/write-content")
async def write_vm_file_content(slice_name: str, node_name: str, body: VmWriteFileRequest):
    """Write a text file on a VM from in-browser editor."""
    slice_name = resolve_slice_name(slice_name)
    def _do():
        node_obj = _get_node(slice_name, node_name)
        # Use python to write the file to handle arbitrary content safely
        import base64
        encoded = base64.b64encode(body.content.encode("utf-8")).decode("ascii")
        cmd = f"python3 -c \"import base64; open({body.path!r},'w').write(base64.b64decode('{encoded}').decode('utf-8'))\""
        stdout, stderr = node_obj.execute(cmd, quiet=True)
        if stderr and stderr.strip():
            raise HTTPException(status_code=500, detail=stderr.strip())
        return {"path": body.path, "status": "ok"}

    return await asyncio.to_thread(_do)


class VmMkdirRequest(BaseModel):
    path: str


@router.post("/api/files/vm/{slice_name}/{node_name}/mkdir")
async def vm_mkdir(slice_name: str, node_name: str, body: VmMkdirRequest):
    """Create a directory on the VM."""
    slice_name = resolve_slice_name(slice_name)
    def _do():
        node_obj = _get_node(slice_name, node_name)
        stdout, stderr = node_obj.execute(f"mkdir -p {body.path!r}", quiet=True)
        if stderr and stderr.strip():
            raise HTTPException(status_code=500, detail=stderr.strip())
        return {"created": body.path}

    return await asyncio.to_thread(_do)


class VmDeleteRequest(BaseModel):
    path: str


@router.post("/api/files/vm/{slice_name}/{node_name}/delete")
async def vm_delete(slice_name: str, node_name: str, body: VmDeleteRequest):
    """Delete a file or directory on the VM."""
    slice_name = resolve_slice_name(slice_name)
    def _do():
        node_obj = _get_node(slice_name, node_name)
        stdout, stderr = node_obj.execute(f"rm -rf {body.path!r}", quiet=True)
        if stderr and stderr.strip():
            raise HTTPException(status_code=500, detail=stderr.strip())
        return {"deleted": body.path}

    return await asyncio.to_thread(_do)


class VmExecBody(BaseModel):
    command: str


@router.post("/api/files/vm/{slice_name}/{node_name}/execute")
async def execute_on_vm(slice_name: str, node_name: str, body: VmExecBody):
    """Execute an ad-hoc command on a VM node."""
    slice_name = resolve_slice_name(slice_name)
    def _do():
        node_obj = _get_node(slice_name, node_name)
        stdout, stderr = node_obj.execute(body.command, quiet=True)
        return {"stdout": stdout or "", "stderr": stderr or ""}

    return await asyncio.to_thread(_do)


# ---------------------------------------------------------------------------
# Provisioning endpoints
# ---------------------------------------------------------------------------

class ProvisionRequest(BaseModel):
    source: str
    slice_name: str
    node_name: str
    dest: str


@router.post("/api/files/provisions")
async def add_provision(body: ProvisionRequest):
    rules = _load_provisions(body.slice_name)
    rule = {
        "id": str(uuid.uuid4()),
        "source": body.source,
        "slice_name": body.slice_name,
        "node_name": body.node_name,
        "dest": body.dest,
    }
    rules.append(rule)
    _save_provisions(body.slice_name, rules)
    return rule


@router.get("/api/files/provisions/{slice_name}")
async def list_provisions(slice_name: str):
    slice_name = resolve_slice_name(slice_name)
    return _load_provisions(slice_name)


@router.delete("/api/files/provisions/{slice_name}/{rule_id}")
async def delete_provision(slice_name: str, rule_id: str):
    slice_name = resolve_slice_name(slice_name)
    rules = _load_provisions(slice_name)
    rules = [r for r in rules if r["id"] != rule_id]
    _save_provisions(slice_name, rules)
    return {"deleted": rule_id}


@router.post("/api/files/provisions/{slice_name}/execute")
async def execute_provisions(slice_name: str, node_name: Optional[str] = Query(None)):
    slice_name = resolve_slice_name(slice_name)
    rules = _load_provisions(slice_name)
    if node_name:
        rules = [r for r in rules if r["node_name"] == node_name]

    results = []

    def _do():
        fablib = get_fablib()
        from app.slice_registry import get_slice_uuid
        uuid = get_slice_uuid(slice_name)
        if uuid:
            try:
                slice_obj = fablib.get_slice(slice_id=uuid)
            except Exception:
                slice_obj = fablib.get_slice(slice_name)
        else:
            slice_obj = fablib.get_slice(slice_name)
        for rule in rules:
            try:
                base = _storage_dir()
                local_path = _safe_path(base, rule["source"])
                if not os.path.exists(local_path):
                    results.append({"id": rule["id"], "status": "error", "detail": "Source not found"})
                    continue

                node_obj = slice_obj.get_node(rule["node_name"])
                if os.path.isdir(local_path):
                    node_obj.upload_directory(local_path, rule["dest"])
                else:
                    node_obj.upload_file(local_path, rule["dest"])
                results.append({"id": rule["id"], "status": "ok"})
            except Exception as e:
                results.append({"id": rule["id"], "status": "error", "detail": str(e)})

    await asyncio.to_thread(_do)
    return results


# ---------------------------------------------------------------------------
# Boot config helpers
# ---------------------------------------------------------------------------

def _boot_config_dir(slice_name: str) -> str:
    d = os.path.join(_storage_dir(), ".boot-config", slice_name)
    os.makedirs(d, exist_ok=True)
    return d


def _load_boot_config(slice_name: str, node_name: str) -> dict:
    """Load boot config.  Priority: .boot-config/ JSON file, then FABlib user_data."""
    path = os.path.join(_boot_config_dir(slice_name), f"{node_name}.json")
    if os.path.isfile(path):
        with open(path) as f:
            data = json.load(f)
        data.setdefault("network", [])
        return data

    # Fallback: read from FABlib user_data (persists with slice)
    return _load_boot_config_from_fablib(slice_name, node_name)


def _load_boot_config_from_fablib(slice_name: str, node_name: str) -> dict:
    """Read boot config from FABlib node user_data."""
    import copy
    empty = {"uploads": [], "commands": [], "network": []}
    try:
        from app.routes.slices import _get_slice_obj
        slice_obj = _get_slice_obj(slice_name)
        node = slice_obj.get_node(node_name)
        user_data = copy.deepcopy(node.get_user_data())
        bc = user_data.get("boot_config")
        if bc and isinstance(bc, dict):
            bc.setdefault("uploads", [])
            bc.setdefault("commands", [])
            bc.setdefault("network", [])
            return bc
    except Exception:
        pass
    return empty


def _save_boot_config(slice_name: str, node_name: str, config: dict):
    """Save boot config to .boot-config/ JSON and to FABlib user_data."""
    # 1. Save to local JSON file (working copy for execute)
    path = os.path.join(_boot_config_dir(slice_name), f"{node_name}.json")
    with open(path, "w") as f:
        json.dump(config, f, indent=2)

    # 2. Save to FABlib user_data so it persists with the slice
    _save_boot_config_to_fablib(slice_name, node_name, config)


def _save_boot_config_to_fablib(slice_name: str, node_name: str, config: dict):
    """Write boot config into FABlib node user_data and post_boot_tasks."""
    try:
        import copy
        from app.routes.slices import _get_slice_obj
        slice_obj = _get_slice_obj(slice_name)
        node = slice_obj.get_node(name=node_name)
        # Work on a deep copy to avoid "dictionary keys changed during iteration"
        # when FABlib is concurrently iterating the live user_data dict
        user_data = copy.deepcopy(node.get_user_data())

        # Store full boot_config in user_data for round-tripping
        user_data["boot_config"] = {
            "uploads": config.get("uploads", []),
            "commands": config.get("commands", []),
            "network": config.get("network", []),
        }

        # Also set post_boot_tasks using FABlib's native format
        # so FABlib's own post-boot system can execute them on submit
        tasks = []
        storage = _storage_dir()
        for u in config.get("uploads", []):
            source = u.get("source", "")
            dest = u.get("dest", ".")
            # Resolve relative paths against storage dir
            abs_source = source if os.path.isabs(source) else os.path.join(storage, source)
            # Use upload_file for files, upload_directory for directories
            if os.path.isfile(abs_source):
                tasks.append(("upload_file", abs_source, dest))
            else:
                tasks.append(("upload_directory", abs_source, dest))
        for c in sorted(config.get("commands", []), key=lambda x: x.get("order", 0)):
            tasks.append(("execute", c.get("command", "")))
        if "fablib_data" not in user_data:
            user_data["fablib_data"] = {}
        user_data["fablib_data"]["post_boot_tasks"] = tasks

        node.set_user_data(user_data)
    except Exception as e:
        logging.warning("Could not save boot config to FABlib user_data: %s", e)


# ---------------------------------------------------------------------------
# Boot config endpoints
# ---------------------------------------------------------------------------

class BootConfigBody(BaseModel):
    uploads: list = []
    commands: list = []
    network: list = []


@router.get("/api/files/boot-config/{slice_name}/{node_name}")
async def get_boot_config(slice_name: str, node_name: str):
    slice_name = resolve_slice_name(slice_name)
    return _load_boot_config(slice_name, node_name)


@router.put("/api/files/boot-config/{slice_name}/{node_name}")
async def save_boot_config(slice_name: str, node_name: str, body: BootConfigBody):
    slice_name = resolve_slice_name(slice_name)
    config = {"uploads": body.uploads, "commands": body.commands, "network": body.network}
    _save_boot_config(slice_name, node_name, config)
    return config


@router.post("/api/files/boot-config/{slice_name}/{node_name}/execute")
async def execute_boot_config(slice_name: str, node_name: str):
    slice_name = resolve_slice_name(slice_name)
    config = _load_boot_config(slice_name, node_name)
    results = []

    def _do():
        node_obj = _get_node(slice_name, node_name)
        base = _storage_dir()

        # Resolve ~ to absolute path for SFTP uploads (SFTP doesn't expand ~)
        home_dir = None
        def _resolve_remote(path: str) -> str:
            nonlocal home_dir
            if "~" not in path:
                return path
            if home_dir is None:
                try:
                    h, _ = node_obj.execute("echo $HOME", quiet=True)
                    home_dir = (h or "").strip() or "/root"
                except Exception:
                    home_dir = "/root"
            return path.replace("~", home_dir)

        # 1. Process uploads using FABlib
        for upload in config.get("uploads", []):
            uid = upload.get("id", "?")
            try:
                local_path = _safe_path(base, upload["source"])
                dest = _resolve_remote(upload["dest"])
                # Ensure remote parent directory exists
                parent = os.path.dirname(dest)
                if parent:
                    node_obj.execute(f"mkdir -p {parent}", quiet=True)
                if os.path.isdir(local_path):
                    # FABlib upload_directory tars with the directory
                    # basename in the archive (e.g. tools/file.sh) then
                    # extracts into remote_directory_path.  So we must
                    # pass the *parent* of dest to avoid double-nesting.
                    upload_target = os.path.dirname(dest) or dest
                    node_obj.upload_directory(local_path, upload_target)
                    results.append({"type": "upload", "id": uid, "status": "ok"})
                elif os.path.isfile(local_path):
                    node_obj.upload_file(local_path, dest)
                    results.append({"type": "upload", "id": uid, "status": "ok"})
                else:
                    results.append({"type": "upload", "id": uid, "status": "error",
                                    "detail": "Source not found"})
            except Exception as e:
                results.append({"type": "upload", "id": uid, "status": "error",
                                "detail": str(e)})

        # 2. Process network config via node.execute()
        for net in sorted(config.get("network", []), key=lambda n: n.get("order", 0)):
            nid = net.get("id", "?")
            try:
                iface = net["iface"]
                mode = net.get("mode", "auto")
                if mode == "auto":
                    cmd = f"sudo dhclient {iface}"
                else:
                    ip_addr = net.get("ip", "")
                    subnet = net.get("subnet", "24")
                    cmd = f"sudo ip addr add {ip_addr}/{subnet} dev {iface} && sudo ip link set {iface} up"
                    gw = net.get("gateway")
                    if gw:
                        cmd += f" && sudo ip route add default via {gw} dev {iface}"
                stdout, stderr = node_obj.execute(cmd, quiet=True)
                if stderr and stderr.strip():
                    results.append({"type": "network", "id": nid, "status": "error",
                                    "detail": stderr.strip()})
                else:
                    results.append({"type": "network", "id": nid, "status": "ok",
                                    "detail": stdout.strip() or None})
            except Exception as e:
                results.append({"type": "network", "id": nid, "status": "error",
                                "detail": str(e)})

        # 3. Process commands (in order) via node.execute()
        for cmd_entry in sorted(config.get("commands", []), key=lambda c: c.get("order", 0)):
            cid = cmd_entry.get("id", "?")
            try:
                stdout, stderr = node_obj.execute(cmd_entry["command"], quiet=True)
                if stderr and stderr.strip():
                    results.append({"type": "command", "id": cid, "status": "error",
                                    "detail": stderr.strip()})
                else:
                    results.append({"type": "command", "id": cid, "status": "ok",
                                    "detail": stdout.strip() or None})
            except Exception as e:
                results.append({"type": "command", "id": cid, "status": "error",
                                "detail": str(e)})

    await asyncio.to_thread(_do)
    return results


@router.post("/api/files/boot-config/{slice_name}/execute-all")
async def execute_all_boot_configs(slice_name: str):
    """Run boot config (uploads, network, commands) on every node that has one."""
    slice_name = resolve_slice_name(slice_name)
    from app.routes.slices import _get_slice_obj

    def _do():
        slice_obj = _get_slice_obj(slice_name)
        nodes = slice_obj.get_nodes()
        all_results = {}
        base = _storage_dir()

        for node_obj in nodes:
            node_name = node_obj.get_name()
            config = _load_boot_config(slice_name, node_name)
            has_work = config.get("uploads") or config.get("commands") or config.get("network")
            if not has_work:
                continue

            node_results = []

            # Wait for SSH to be ready before running boot config
            ssh_ready = False
            max_ssh_attempts = 30  # 30 × 20s = 10 min max
            for attempt in range(1, max_ssh_attempts + 1):
                try:
                    node_obj.execute("echo ssh_ok", quiet=True)
                    ssh_ready = True
                    break
                except Exception:
                    if attempt < max_ssh_attempts:
                        import time
                        time.sleep(20)

            if not ssh_ready:
                node_results.append({"type": "ssh", "id": "ssh_check", "status": "error",
                                     "detail": f"SSH not available after {max_ssh_attempts} attempts"})
                all_results[node_name] = node_results
                continue

            # Resolve ~ to absolute path for SFTP uploads (SFTP doesn't expand ~)
            home_dir = None
            def _resolve_remote(path: str) -> str:
                nonlocal home_dir
                if "~" not in path:
                    return path
                if home_dir is None:
                    try:
                        h, _ = node_obj.execute("echo $HOME", quiet=True)
                        home_dir = (h or "").strip() or "/root"
                    except Exception:
                        home_dir = "/root"
                return path.replace("~", home_dir)

            # 1. Uploads
            for upload in config.get("uploads", []):
                uid = upload.get("id", "?")
                try:
                    local_path = _safe_path(base, upload["source"])
                    dest = _resolve_remote(upload["dest"])
                    # Ensure remote parent directory exists
                    parent = os.path.dirname(dest)
                    if parent:
                        node_obj.execute(f"mkdir -p {parent}", quiet=True)
                    if os.path.isdir(local_path):
                        # FABlib upload_directory tars with the directory
                        # basename in the archive, so pass the parent of
                        # dest to avoid double-nesting.
                        upload_target = os.path.dirname(dest) or dest
                        node_obj.upload_directory(local_path, upload_target)
                        node_results.append({"type": "upload", "id": uid, "status": "ok"})
                    elif os.path.isfile(local_path):
                        node_obj.upload_file(local_path, dest)
                        node_results.append({"type": "upload", "id": uid, "status": "ok"})
                    else:
                        node_results.append({"type": "upload", "id": uid, "status": "error",
                                             "detail": "Source not found"})
                except Exception as e:
                    node_results.append({"type": "upload", "id": uid, "status": "error",
                                         "detail": str(e)})

            # 2. Network config
            for net in sorted(config.get("network", []), key=lambda n: n.get("order", 0)):
                nid = net.get("id", "?")
                try:
                    iface = net["iface"]
                    mode = net.get("mode", "auto")
                    if mode == "auto":
                        cmd = f"sudo dhclient {iface}"
                    else:
                        ip_addr = net.get("ip", "")
                        subnet = net.get("subnet", "24")
                        cmd = f"sudo ip addr add {ip_addr}/{subnet} dev {iface} && sudo ip link set {iface} up"
                        gw = net.get("gateway")
                        if gw:
                            cmd += f" && sudo ip route add default via {gw} dev {iface}"
                        # Add subnet routes from L3 config
                        for route in net.get("routes", []):
                            import ipaddress as _ipmod
                            try:
                                iface_net = _ipmod.IPv4Interface(f"{ip_addr}/{subnet}")
                                route_gw = str(iface_net.network.network_address + 1)
                                cmd += f" && sudo ip route add {route} via {route_gw} dev {iface}"
                            except Exception:
                                pass
                    stdout, stderr = node_obj.execute(cmd, quiet=True)
                    if stderr and stderr.strip():
                        node_results.append({"type": "network", "id": nid, "status": "error",
                                             "detail": stderr.strip()})
                    else:
                        node_results.append({"type": "network", "id": nid, "status": "ok",
                                             "detail": stdout.strip() or None})
                except Exception as e:
                    node_results.append({"type": "network", "id": nid, "status": "error",
                                         "detail": str(e)})

            # 3. Commands
            for cmd_entry in sorted(config.get("commands", []), key=lambda c: c.get("order", 0)):
                cid = cmd_entry.get("id", "?")
                try:
                    stdout, stderr = node_obj.execute(cmd_entry["command"], quiet=True)
                    if stderr and stderr.strip():
                        node_results.append({"type": "command", "id": cid, "status": "error",
                                             "detail": stderr.strip()})
                    else:
                        node_results.append({"type": "command", "id": cid, "status": "ok",
                                             "detail": stdout.strip() or None})
                except Exception as e:
                    node_results.append({"type": "command", "id": cid, "status": "error",
                                         "detail": str(e)})

            all_results[node_name] = node_results

        return all_results

    return await asyncio.to_thread(_do)


@router.get("/api/files/boot-config/running")
def get_boot_running():
    """Get which slices currently have boot config running."""
    with _boot_lock:
        return {
            "running": list(_boot_running),
            "slices": {k: len(v) for k, v in _boot_logs.items()},
        }


@router.get("/api/files/boot-config/{slice_name}/log")
def get_boot_log(slice_name: str):
    """Get stored boot config log for a slice."""
    slice_name = resolve_slice_name(slice_name)
    with _boot_lock:
        return {
            "lines": list(_boot_logs.get(slice_name, [])),
            "running": slice_name in _boot_running,
        }


@router.post("/api/files/boot-config/{slice_name}/execute-all-stream")
async def execute_all_boot_configs_stream(slice_name: str):
    """Run boot config on every node, streaming SSE progress."""
    slice_name = resolve_slice_name(slice_name)
    import logging
    logging.getLogger("files").info(f"[boot-config-stream] called for slice={slice_name}")
    from app.routes.slices import _get_slice_obj

    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def _emit(event_type: str, data: dict):
        payload = {"event": event_type, **data}
        queue.put_nowait(f"data: {json.dumps(payload)}\n\n")
        with _boot_lock:
            _boot_logs.setdefault(slice_name, []).append(payload)

    def _stream_exec(node_obj, cmd, on_line, poll_interval=4, max_minutes=25):
        """Run cmd on a node with near-real-time output via log-file polling.

        Writes cmd to a temp script via base64 (avoids quoting issues), launches
        it in the background, then polls the log file every poll_interval seconds
        calling on_line(str) for each new line.  Returns the process exit code.
        """
        import base64, hashlib, time as _time
        key = hashlib.md5(cmd.encode()).hexdigest()[:8]
        log_f  = f"/tmp/.bc_{key}.log"
        done_f = f"/tmp/.bc_{key}.done"
        SEP    = f"__BCSEP_{key}__"

        encoded = base64.b64encode(cmd.encode()).decode()
        setup = (
            f"echo '{encoded}' | base64 -d > /tmp/.bc_{key}.sh; "
            f"chmod +x /tmp/.bc_{key}.sh; "
            f"( /tmp/.bc_{key}.sh > {log_f} 2>&1; echo $? > {done_f} ) &"
        )
        node_obj.execute(setup, quiet=True)

        last_line = 0
        for _ in range(max_minutes * 60 // poll_interval):
            poll = (
                f"tail -n +{last_line + 1} {log_f} 2>/dev/null; "
                f"printf '%s\\n' '{SEP}'; "
                f"cat {done_f} 2>/dev/null || true"
            )
            result, _ = node_obj.execute(poll, quiet=True)

            new_out, sep, rest = result.partition(SEP)
            exit_str = rest.strip() if sep else ""

            for raw in new_out.split("\n"):
                line = raw.rstrip()
                if line:
                    on_line(line)
                    last_line += 1

            if exit_str and exit_str.isdigit():
                # Flush any remaining lines written between last poll and exit
                final, _ = node_obj.execute(
                    f"tail -n +{last_line + 1} {log_f} 2>/dev/null", quiet=True
                )
                for raw in final.split("\n"):
                    line = raw.rstrip()
                    if line:
                        on_line(line)
                return int(exit_str)

            _time.sleep(poll_interval)

        return 1  # timed out

    def _do():
        with _boot_lock:
            _boot_running.add(slice_name)
            _boot_logs[slice_name] = []  # clear previous log for fresh run

        try:
            _do_inner()
        finally:
            with _boot_lock:
                _boot_running.discard(slice_name)

    def _do_inner():
        slice_obj = _get_slice_obj(slice_name)
        nodes = slice_obj.get_nodes()
        base = _storage_dir()

        # Auto-run deploy.sh from template root if it exists (once per slice, on container)
        template_dir = _load_template_dir(slice_name)
        if template_dir:
            deploy_sh = os.path.join(template_dir, "deploy.sh")
            if os.path.isfile(deploy_sh):
                _emit("step", {"node": "__slice__", "type": "deploy", "id": "deploy.sh",
                               "message": f"Running deploy.sh for slice \"{slice_name}\"..."})
                try:
                    import subprocess
                    env = {**os.environ, "SLICE_NAME": slice_name}
                    proc = subprocess.Popen(
                        ["bash", deploy_sh, slice_name],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, env=env,
                    )
                    for raw in iter(proc.stdout.readline, ""):
                        line_str = raw.rstrip()
                        if not line_str:
                            continue
                        if line_str.startswith("### PROGRESS:"):
                            msg = line_str[len("### PROGRESS:"):].strip()
                            _emit("step", {"node": "__slice__", "type": "progress", "id": "deploy.sh",
                                          "message": f"  ↳ {msg}"})
                        else:
                            _emit("output", {"node": "__slice__", "type": "deploy", "id": "deploy.sh",
                                            "message": line_str})
                    proc.wait()
                    if proc.returncode != 0:
                        _emit("error", {"node": "__slice__", "type": "deploy", "id": "deploy.sh",
                                       "message": f"deploy.sh exited with code {proc.returncode}"})
                    else:
                        _emit("output", {"node": "__slice__", "type": "deploy", "id": "deploy.sh",
                                        "message": "✓ deploy.sh complete", "status": "ok"})
                except Exception as e:
                    _emit("error", {"node": "__slice__", "type": "deploy", "id": "deploy.sh",
                                   "message": str(e)})

        for node_obj in nodes:
            node_name = node_obj.get_name()
            config = _load_boot_config(slice_name, node_name)
            has_work = config.get("uploads") or config.get("commands") or config.get("network")
            if not has_work:
                continue

            _emit("node", {"node": node_name, "message": f"Starting boot config for {node_name}..."})

            # Wait for SSH to be ready before running boot config
            _emit("step", {"node": node_name, "type": "ssh", "message": "Waiting for SSH to become ready..."})
            ssh_ready = False
            max_ssh_attempts = 30  # 30 attempts × 20s = 10 minutes max
            for attempt in range(1, max_ssh_attempts + 1):
                try:
                    node_obj.execute("echo ssh_ok", quiet=True)
                    ssh_ready = True
                    _emit("output", {"node": node_name, "type": "ssh",
                                     "message": f"SSH ready (attempt {attempt})", "status": "ok"})
                    break
                except Exception as e:
                    if attempt < max_ssh_attempts:
                        _emit("output", {"node": node_name, "type": "ssh",
                                         "message": f"SSH not ready (attempt {attempt}/{max_ssh_attempts}), retrying in 20s..."})
                        import time
                        time.sleep(20)
                    else:
                        _emit("error", {"node": node_name, "type": "ssh",
                                        "message": f"SSH not available after {max_ssh_attempts} attempts: {e}"})

            if not ssh_ready:
                _emit("error", {"node": node_name, "message": f"Skipping boot config for {node_name} — SSH not available"})
                continue

            # Resolve ~ to absolute path for SFTP uploads
            home_dir = None
            def _resolve(path: str) -> str:
                nonlocal home_dir
                if "~" not in path:
                    return path
                if home_dir is None:
                    try:
                        h, _ = node_obj.execute("echo $HOME", quiet=True)
                        home_dir = (h or "").strip() or "/root"
                    except Exception:
                        home_dir = "/root"
                return path.replace("~", home_dir)

            # 1. Uploads
            for upload in config.get("uploads", []):
                uid = upload.get("id", "?")
                _emit("step", {"node": node_name, "type": "upload", "id": uid,
                               "message": f"Uploading {upload.get('source', '?')} → {upload.get('dest', '?')}"})
                try:
                    local_path = _safe_path(base, upload["source"])
                    dest = _resolve(upload["dest"])
                    parent = os.path.dirname(dest)
                    if parent:
                        node_obj.execute(f"mkdir -p {parent}", quiet=True)
                    if os.path.isdir(local_path):
                        # FABlib upload_directory tars with the directory
                        # basename in the archive, so pass the parent of
                        # dest to avoid double-nesting.
                        upload_target = os.path.dirname(dest) or dest
                        node_obj.upload_directory(local_path, upload_target)
                    elif os.path.isfile(local_path):
                        node_obj.upload_file(local_path, dest)
                    else:
                        _emit("error", {"node": node_name, "type": "upload", "id": uid,
                                        "message": "Source not found"})
                        continue
                    _emit("output", {"node": node_name, "type": "upload", "id": uid,
                                     "message": "OK", "status": "ok"})
                except Exception as e:
                    _emit("error", {"node": node_name, "type": "upload", "id": uid,
                                    "message": str(e)})

            # 2. Network config
            for net in sorted(config.get("network", []), key=lambda n: n.get("order", 0)):
                nid = net.get("id", "?")
                iface = net.get("iface", "?")
                _emit("step", {"node": node_name, "type": "network", "id": nid,
                               "message": f"Configuring network interface {iface}"})
                try:
                    mode = net.get("mode", "auto")
                    if mode == "auto":
                        cmd = f"sudo dhclient {iface}"
                    else:
                        ip_addr = net.get("ip", "")
                        subnet = net.get("subnet", "24")
                        cmd = f"sudo ip addr add {ip_addr}/{subnet} dev {iface} && sudo ip link set {iface} up"
                        gw = net.get("gateway")
                        if gw:
                            cmd += f" && sudo ip route add default via {gw} dev {iface}"
                        # Add subnet routes from L3 config
                        for route in net.get("routes", []):
                            import ipaddress as _ipmod
                            try:
                                iface_net = _ipmod.IPv4Interface(f"{ip_addr}/{subnet}")
                                route_gw = str(iface_net.network.network_address + 1)
                                cmd += f" && sudo ip route add {route} via {route_gw} dev {iface}"
                            except Exception:
                                pass
                    stdout, stderr = node_obj.execute(cmd, quiet=True)
                    if stderr and stderr.strip():
                        _emit("error", {"node": node_name, "type": "network", "id": nid,
                                        "message": stderr.strip()})
                    else:
                        _emit("output", {"node": node_name, "type": "network", "id": nid,
                                         "message": (stdout or "").strip() or "OK", "status": "ok"})
                except Exception as e:
                    _emit("error", {"node": node_name, "type": "network", "id": nid,
                                    "message": str(e)})

            # 3. Commands — remote (on VM)
            for cmd_entry in sorted(config.get("commands", []), key=lambda c: c.get("order", 0)):
                cid = cmd_entry.get("id", "?")
                cmd = cmd_entry.get("command", "")
                if cmd_entry.get("local", False):
                    continue  # local commands are now handled by deploy.sh at template root

                # Remote command: run on the VM
                _emit("step", {"node": node_name, "type": "command", "id": cid,
                               "message": f"Running: {cmd}"})
                try:
                    def _on_line(line, _nn=node_name, _cid=cid):
                        if line.startswith("### PROGRESS:"):
                            msg = line[len("### PROGRESS:"):].strip()
                            _emit("step", {"node": _nn, "type": "progress", "id": _cid,
                                           "message": f"  ↳ {msg}"})
                        else:
                            _emit("output", {"node": _nn, "type": "command", "id": _cid,
                                             "message": line})

                    exit_code = _stream_exec(node_obj, cmd, _on_line)

                    if exit_code != 0:
                        _emit("error", {"node": node_name, "type": "command", "id": cid,
                                        "message": f"Command exited with code {exit_code}"})
                    else:
                        _emit("output", {"node": node_name, "type": "command", "id": cid,
                                         "message": "✓ Command completed", "status": "ok"})
                except Exception as e:
                    _emit("error", {"node": node_name, "type": "command", "id": cid,
                                    "message": str(e)})

            _emit("node", {"node": node_name, "message": f"Boot config complete for {node_name}", "status": "ok"})

        _emit("done", {"message": "All boot configs complete", "status": "ok"})
        queue.put_nowait(None)

    async def _stream():
        task = asyncio.get_event_loop().run_in_executor(None, _do)
        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=30)
            except asyncio.TimeoutError:
                # Send SSE keepalive comment to prevent proxy read-timeout
                yield ": keepalive\n\n"
                continue
            if msg is None:
                break
            yield msg
        await task  # propagate exceptions

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
