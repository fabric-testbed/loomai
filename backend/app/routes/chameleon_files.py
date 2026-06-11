"""File operations (list, read, write, upload, download, execute) on
Chameleon Cloud instances.

Mirrors the FABRIC /api/files/vm/{slice}/{node}/... endpoint surface but
connects directly (or via bastion) to a Chameleon instance's floating IP
using the same SSH key lookup as the WebSocket terminal endpoint.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import posixpath
import shlex
import stat as stat_mod
import tempfile
from datetime import datetime
from pathlib import PurePosixPath
from typing import List

import paramiko
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chameleon-files"])


def _normalize_remote_path(path: str, *, default: str = "/home/cc") -> str:
    """Normalize a remote absolute path and reject parent traversal."""
    if "\x00" in path:
        raise HTTPException(status_code=400, detail="Path contains invalid characters")
    raw = path.strip() or default
    if ".." in PurePosixPath(raw.replace("\\", "/")).parts:
        raise HTTPException(status_code=400, detail="Path traversal not allowed")
    normalized = posixpath.normpath(raw)
    if not normalized.startswith("/"):
        normalized = posixpath.normpath(posixpath.join(default, normalized))
    if ".." in PurePosixPath(normalized).parts:
        raise HTTPException(status_code=400, detail="Path traversal not allowed")
    return normalized


def _safe_upload_relative_path(filename: str | None) -> str:
    """Return a safe relative upload path, preserving folder uploads."""
    raw = (filename or "").replace("\\", "/")
    if any(ch in raw for ch in ("\x00", "\r", "\n", '"')):
        raise HTTPException(status_code=400, detail=f"Unsafe upload path: {filename}")
    if raw.startswith("/"):
        raise HTTPException(status_code=400, detail=f"Unsafe upload path: {filename}")
    candidate = raw.strip("/")
    if not candidate:
        raise HTTPException(status_code=400, detail="Uploaded file is missing a filename")
    path = PurePosixPath(candidate)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise HTTPException(status_code=400, detail=f"Unsafe upload path: {filename}")
    if path.parts and ":" in path.parts[0]:
        raise HTTPException(status_code=400, detail=f"Unsafe upload path: {filename}")
    return path.as_posix()


def _join_remote_under(base: str, relative_path: str) -> str:
    """Join a safe relative path under a normalized remote base."""
    base_norm = _normalize_remote_path(base)
    rel = _safe_upload_relative_path(relative_path)
    remote = posixpath.normpath(posixpath.join(base_norm, rel))
    if remote != base_norm and not remote.startswith(base_norm.rstrip("/") + "/"):
        raise HTTPException(status_code=400, detail="Path traversal not allowed")
    return remote


def _safe_download_name(remote_path: str, fallback: str) -> str:
    name = posixpath.basename(posixpath.normpath(remote_path)) or fallback
    return _safe_upload_relative_path(name).replace("/", "_")


# ---------------------------------------------------------------------------
# SSH connection helpers
# ---------------------------------------------------------------------------

def _resolve_instance_ip(instance_id: str, site: str) -> tuple[str, str]:
    """Return (ip, instance_name) for a Chameleon instance.

    Picks the floating IP if present, otherwise the first non-private address.
    Raises HTTPException on failure.
    """
    from app.chameleon_manager import get_session
    try:
        session = get_session(site)
        result = session.api_get("compute", f"/servers/{instance_id}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Chameleon API error: {e}")
    srv = result.get("server", result)
    ip = None
    for _net_name, addrs in (srv.get("addresses") or {}).items():
        for addr in addrs:
            if addr.get("OS-EXT-IPS:type") == "floating":
                ip = addr.get("addr")
                break
        if ip:
            break
    if not ip:
        # Fallback — first any-address
        for _net_name, addrs in (srv.get("addresses") or {}).items():
            for addr in addrs:
                if addr.get("addr"):
                    ip = addr["addr"]
                    break
            if ip:
                break
    if not ip:
        raise HTTPException(
            status_code=400,
            detail="Instance has no IP address (associate a floating IP first)",
        )
    return ip, srv.get("name", "instance")


def _load_chameleon_pkey(site: str) -> paramiko.PKey | None:
    """Load the Chameleon SSH private key for a site, trying RSA/Ed25519/ECDSA."""
    from app.routes.chameleon import get_chameleon_key_path
    key_path = get_chameleon_key_path(site)
    if not key_path or not os.path.isfile(key_path):
        return None
    for key_cls in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
        try:
            return key_cls.from_private_key_file(key_path)
        except Exception:
            continue
    return None


def _open_chameleon_ssh(instance_id: str, site: str) -> tuple[paramiko.SSHClient, paramiko.SFTPClient, str, str]:
    """Open an SSH+SFTP connection to a Chameleon instance.

    Returns (client, sftp, ip, username). Caller is responsible for closing
    sftp and client when done.
    """
    ip, _name = _resolve_instance_ip(instance_id, site)
    username = "cc"  # Chameleon default for all CC-* images
    pkey = _load_chameleon_pkey(site)
    if not pkey:
        raise HTTPException(
            status_code=500,
            detail=f"No Chameleon SSH key found for {site}",
        )
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=ip,
            port=22,
            username=username,
            pkey=pkey,
            timeout=15,
            allow_agent=False,
            look_for_keys=False,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"SSH connection to {ip} failed: {e}",
        )
    try:
        sftp = client.open_sftp()
    except Exception as e:
        client.close()
        raise HTTPException(status_code=500, detail=f"SFTP open failed: {e}")
    return client, sftp, ip, username


# ---------------------------------------------------------------------------
# File operations
# ---------------------------------------------------------------------------

@router.get("/api/files/chameleon/{instance_id}")
async def list_chameleon_files(instance_id: str, site: str = Query(...), path: str = "/home"):
    remote_path = _normalize_remote_path(path, default="/home/cc")

    def _do():
        client, sftp, _ip, _user = _open_chameleon_ssh(instance_id, site)
        try:
            entries = []
            for attr in sftp.listdir_attr(remote_path):
                entries.append({
                    "name": attr.filename,
                    "type": "dir" if stat_mod.S_ISDIR(attr.st_mode or 0) else "file",
                    "size": attr.st_size or 0,
                    "modified": datetime.fromtimestamp(attr.st_mtime or 0).isoformat() if attr.st_mtime else "",
                })
            return sorted(entries, key=lambda e: (e["type"] != "dir", e["name"]))
        finally:
            sftp.close()
            client.close()
    return await asyncio.to_thread(_do)


class PathRequest(BaseModel):
    path: str


class WriteContentRequest(BaseModel):
    path: str
    content: str


class ExecuteRequest(BaseModel):
    command: str


@router.post("/api/files/chameleon/{instance_id}/read-content")
async def read_chameleon_file_content(instance_id: str, body: PathRequest, site: str = Query(...)):
    remote_path = _normalize_remote_path(body.path)

    def _do():
        client, sftp, _ip, _user = _open_chameleon_ssh(instance_id, site)
        try:
            with sftp.file(remote_path, "r") as f:
                content = f.read()
            if isinstance(content, bytes):
                try:
                    content = content.decode("utf-8")
                except UnicodeDecodeError:
                    content = content.decode("latin-1")
            return {"path": remote_path, "content": content}
        finally:
            sftp.close()
            client.close()
    return await asyncio.to_thread(_do)


@router.post("/api/files/chameleon/{instance_id}/write-content")
async def write_chameleon_file_content(instance_id: str, body: WriteContentRequest, site: str = Query(...)):
    remote_path = _normalize_remote_path(body.path)

    def _do():
        client, sftp, _ip, _user = _open_chameleon_ssh(instance_id, site)
        try:
            with sftp.file(remote_path, "w") as f:
                f.write(body.content)
            return {"path": remote_path, "status": "written"}
        finally:
            sftp.close()
            client.close()
    return await asyncio.to_thread(_do)


@router.post("/api/files/chameleon/{instance_id}/mkdir")
async def chameleon_mkdir(instance_id: str, body: PathRequest, site: str = Query(...)):
    remote_path = _normalize_remote_path(body.path)

    def _do():
        client, sftp, _ip, _user = _open_chameleon_ssh(instance_id, site)
        try:
            sftp.mkdir(remote_path)
            return {"created": remote_path}
        finally:
            sftp.close()
            client.close()
    return await asyncio.to_thread(_do)


@router.post("/api/files/chameleon/{instance_id}/delete")
async def chameleon_delete(instance_id: str, body: PathRequest, site: str = Query(...)):
    remote_path = _normalize_remote_path(body.path)

    def _do():
        client, sftp, _ip, _user = _open_chameleon_ssh(instance_id, site)
        try:
            try:
                attr = sftp.stat(remote_path)
                is_dir = stat_mod.S_ISDIR(attr.st_mode or 0)
            except IOError as e:
                raise HTTPException(status_code=404, detail=str(e))
            if is_dir:
                # Remove directory recursively via rm -rf (safer than SFTP recursive)
                _stdin, stdout, stderr = client.exec_command(f"rm -rf -- {shlex.quote(remote_path)}")
                exit_code = stdout.channel.recv_exit_status()
                if exit_code != 0:
                    err = stderr.read().decode("utf-8", errors="replace")
                    raise HTTPException(status_code=500, detail=f"Delete failed: {err}")
            else:
                sftp.remove(remote_path)
            return {"deleted": remote_path}
        finally:
            sftp.close()
            client.close()
    return await asyncio.to_thread(_do)


@router.post("/api/files/chameleon/{instance_id}/execute")
async def chameleon_execute(instance_id: str, body: ExecuteRequest, site: str = Query(...)):
    def _do():
        client, sftp, _ip, _user = _open_chameleon_ssh(instance_id, site)
        try:
            _stdin, stdout, stderr = client.exec_command(body.command, timeout=60)
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            return {"stdout": out, "stderr": err}
        finally:
            sftp.close()
            client.close()
    return await asyncio.to_thread(_do)


@router.post("/api/files/chameleon/{instance_id}/upload-direct")
async def upload_direct_to_chameleon(
    instance_id: str,
    site: str = Query(...),
    dest_path: str = Query("/home/cc"),
    files: List[UploadFile] = File(...),
):
    """Upload files directly from the browser to a Chameleon instance.

    The filename field may contain subdirectory segments (e.g.
    ``folder/sub/file.txt``) to preserve folder structure.
    """
    tmp_dir = tempfile.mkdtemp(prefix="chameleon_upload_")
    uploaded: list[str] = []
    dest_base = _normalize_remote_path(dest_path)
    upload_paths = [(f, _safe_upload_relative_path(f.filename)) for f in files]
    try:
        # Save uploaded files to temp dir
        for f, safe_name in upload_paths:
            local = os.path.realpath(os.path.join(tmp_dir, *safe_name.split("/")))
            tmp_resolved = os.path.realpath(tmp_dir)
            if local != tmp_resolved and not local.startswith(tmp_resolved + os.sep):
                raise HTTPException(status_code=400, detail="Path traversal not allowed")
            os.makedirs(os.path.dirname(local), exist_ok=True)
            content = await f.read()
            with open(local, "wb") as out:
                out.write(content)

        def _do():
            client, sftp, _ip, _user = _open_chameleon_ssh(instance_id, site)
            try:
                # Ensure destination dir exists
                try:
                    sftp.stat(dest_base)
                except IOError:
                    client.exec_command(f"mkdir -p -- {shlex.quote(dest_base)}")[1].channel.recv_exit_status()
                for _f, safe_name in upload_paths:
                    local = os.path.join(tmp_dir, *safe_name.split("/"))
                    remote = _join_remote_under(dest_base, safe_name)
                    remote_dir = posixpath.dirname(remote)
                    if remote_dir and remote_dir != dest_base:
                        # Ensure nested dirs exist
                        client.exec_command(f"mkdir -p -- {shlex.quote(remote_dir)}")[1].channel.recv_exit_status()
                    sftp.put(local, remote)
                    uploaded.append(safe_name)
                return {"uploaded": uploaded}
            finally:
                sftp.close()
                client.close()

        return await asyncio.to_thread(_do)
    finally:
        import shutil as _shutil
        _shutil.rmtree(tmp_dir, ignore_errors=True)


@router.get("/api/files/chameleon/{instance_id}/download-direct")
async def download_direct_from_chameleon(
    instance_id: str,
    remote_path: str = Query(...),
    site: str = Query(...),
):
    """Stream a file from a Chameleon instance to the browser."""
    remote_path = _normalize_remote_path(remote_path)

    def _do() -> bytes:
        client, sftp, _ip, _user = _open_chameleon_ssh(instance_id, site)
        try:
            with sftp.file(remote_path, "rb") as f:
                return f.read()
        finally:
            sftp.close()
            client.close()

    content = await asyncio.to_thread(_do)
    filename = _safe_download_name(remote_path, "download")
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/files/chameleon/{instance_id}/download-folder")
async def download_folder_from_chameleon(
    instance_id: str,
    remote_path: str = Query(...),
    site: str = Query(...),
):
    """Tar up a remote directory on a Chameleon instance and stream the archive."""
    remote_path = _normalize_remote_path(remote_path)

    def _do() -> bytes:
        client, sftp, _ip, _user = _open_chameleon_ssh(instance_id, site)
        try:
            # Use tar via exec_command to create an archive on the fly
            parent = posixpath.dirname(remote_path.rstrip("/")) or "/"
            name = posixpath.basename(remote_path.rstrip("/")) or "folder"
            cmd = f"cd {shlex.quote(parent)} && tar czf - -- {shlex.quote(name)}"
            _stdin, stdout, stderr = client.exec_command(cmd)
            data = stdout.read()
            err = stderr.read().decode("utf-8", errors="replace")
            exit_code = stdout.channel.recv_exit_status()
            if exit_code != 0:
                raise HTTPException(status_code=500, detail=f"tar failed: {err}")
            return data
        finally:
            sftp.close()
            client.close()

    content = await asyncio.to_thread(_do)
    name = _safe_download_name(remote_path, "folder")
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{name}.tar.gz"'},
    )
