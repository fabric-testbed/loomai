"""SPHERE / MergeTB routes — projects, experiments, realizations, materializations.

All endpoints are gated by the ``sphere.enabled`` setting; when disabled every
route returns 404 so the frontend never sees SPHERE data (mirrors the Chameleon
router). The backend talks to the Merge portal over gRPC via ``sphere_manager``;
the blocking gRPC calls are offloaded to a worker thread so they never stall the
event loop.

See docs/SPHERE_INTEGRATION.md.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from contextlib import contextmanager

from fastapi import APIRouter, Body, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app import settings_manager, sphere_manager
from app.graph_builder import build_sphere_realization_graph

logger = logging.getLogger(__name__)
router = APIRouter(tags=["sphere"])


def _require_enabled() -> None:
    if not settings_manager.is_sphere_enabled():
        raise HTTPException(404, "SPHERE integration is disabled")


def _resolve_project(project: str | None) -> str:
    proj = (project or settings_manager.get_sphere_default_project() or "").strip()
    if not proj:
        raise HTTPException(
            400, "No SPHERE project specified and no default_project configured")
    return proj


async def _run(fn, *args, **kwargs):
    """Offload a blocking sphere_manager call to a worker thread."""
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    except HTTPException:
        raise
    except Exception as exc:  # surface portal/gRPC errors as 502
        logger.warning("SPHERE call failed: %s", exc)
        raise HTTPException(502, f"SPHERE portal error: {exc}") from exc


# --------------------------------------------------------------------------- #
# Status / discovery
# --------------------------------------------------------------------------- #
@router.get("/api/sphere/status")
async def sphere_status():
    """SPHERE integration status. Always 200 (even when disabled) so the UI can
    show the toggle state, mirroring /api/chameleon/status."""
    cfg = settings_manager.get_sphere_settings()
    return {
        "enabled": settings_manager.is_sphere_enabled(),
        "configured": settings_manager.is_sphere_configured(),
        "grpc_endpoint": cfg.get("grpc_endpoint", sphere_manager.SPHERE_DEFAULTS["grpc_endpoint"]),
        "default_project": settings_manager.get_sphere_default_project(),
    }


@router.get("/api/sphere/projects")
async def sphere_projects():
    _require_enabled()
    return await _run(sphere_manager.get_configured_projects)


# --------------------------------------------------------------------------- #
# Experiments
# --------------------------------------------------------------------------- #
@router.get("/api/sphere/experiments")
async def sphere_list_experiments(project: str | None = Query(None)):
    _require_enabled()
    proj = _resolve_project(project)
    sess = sphere_manager.get_session(proj)
    return await _run(sess.list_experiments, proj)


@router.post("/api/sphere/experiments")
async def sphere_create_experiment(
    experiment: str = Body(..., embed=True),
    description: str = Body("", embed=True),
    project: str | None = Body(None, embed=True),
):
    _require_enabled()
    proj = _resolve_project(project)
    # Fail fast with a clear message instead of a portal INVALID_ARGUMENT 502.
    if not re.match(r"^[a-z][a-z0-9]{0,62}$", experiment or ""):
        raise HTTPException(
            400,
            "Invalid experiment name. Must start with a lowercase letter and "
            "contain only lowercase letters and digits (no hyphens, underscores, "
            "spaces, or uppercase), max 63 characters.")
    sess = sphere_manager.get_session(proj)
    return await _run(sess.create_experiment, experiment, description)


@router.delete("/api/sphere/experiments/{experiment}")
async def sphere_delete_experiment(experiment: str, project: str | None = Query(None)):
    _require_enabled()
    proj = _resolve_project(project)
    sess = sphere_manager.get_session(proj)
    return await _run(sess.delete_experiment, experiment, proj)


@router.get("/api/sphere/experiments/{experiment}/model")
async def sphere_experiment_model(experiment: str, project: str | None = Query(None)):
    """The experiment's latest pushed model as a builder topology (nodes+facility,
    links+addrs), reconstructed from the compiled model."""
    _require_enabled()
    proj = _resolve_project(project)
    sess = sphere_manager.get_session(proj)
    return await _run(sess.get_experiment_model, experiment, proj)


@router.post("/api/sphere/experiments/{experiment}/package")
async def sphere_package_experiment(
    experiment: str,
    name: str = Body(..., embed=True),
    description: str = Body("", embed=True),
    description_short: str = Body("", embed=True),
    description_long: str = Body("", embed=True),
    dir_name: str | None = Body(None, embed=True),
    realization: str = Body("r0", embed=True),
    scripts: list[dict] = Body(default=[], embed=True),
    include_notebook: bool = Body(True, embed=True),
    tags: list[str] | None = Body(None, embed=True),
    project: str | None = Body(None, embed=True),
):
    """Package a SPHERE experiment into a reproducible weave under my_artifacts.

    Bundles the regenerated mergexp model, a lifecycle driver (recreate on Run),
    author-supplied per-node setup scripts, a starter analysis notebook, and a
    ``sphere-experiment-v1`` manifest. The result shows up in Libraries and can
    be published to the FABRIC Artifact Manager.
    """
    _require_enabled()
    from app import sphere_weave
    from app.user_context import get_artifacts_dir

    proj = _resolve_project(project)
    sess = sphere_manager.get_session(proj)
    # Prefer the realization's topology (the materialized truth) — an experiment's
    # pushed model revisions are content-hash keyed with no reliable ordering, so
    # "latest model" is ambiguous. Fall back to the model only when unrealized.
    topology = await _run(sess.get_realization_topology, experiment, realization, proj)
    if not topology.get("found"):
        topology = await _run(sess.get_experiment_model, experiment, proj)
    if not topology.get("found"):
        raise HTTPException(
            400, f"Experiment '{experiment}' has no realization or pushed model to "
                 "package. Realize/push a model first.")
    artifacts_dir = get_artifacts_dir()
    os.makedirs(artifacts_dir, exist_ok=True)
    try:
        result = await asyncio.to_thread(
            sphere_weave.package_experiment,
            artifacts_dir=artifacts_dir, name=name, description=description,
            description_short=description_short, description_long=description_long,
            dir_name=dir_name, experiment=experiment, realization=realization,
            project=proj, topology=topology, scripts=scripts,
            include_notebook=include_notebook, tags=tags,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    # Invalidate the templates listing cache so the new weave appears immediately.
    try:
        from app.routes.templates import _invalidate_templates_cache
        _invalidate_templates_cache()
    except Exception:  # pragma: no cover - best effort
        pass
    return result


# --------------------------------------------------------------------------- #
# Models — compile (validate) and push a mergexp topology to an experiment
# --------------------------------------------------------------------------- #
@router.post("/api/sphere/models/compile")
async def sphere_compile_model(
    model: str = Body(..., embed=True),
    project: str | None = Body(None, embed=True),
):
    _require_enabled()
    proj = _resolve_project(project)
    sess = sphere_manager.get_session(proj)
    return await _run(sess.compile_model, model)


@router.post("/api/sphere/models")
async def sphere_push_model(
    model: str = Body(..., embed=True),
    experiment: str = Body(..., embed=True),
    tag: str | None = Body(None, embed=True),
    branch: str | None = Body(None, embed=True),
    project: str | None = Body(None, embed=True),
):
    _require_enabled()
    proj = _resolve_project(project)
    sess = sphere_manager.get_session(proj)
    revision = await _run(sess.push_model, model, experiment, tag, branch)
    return {"revision": revision, "experiment": experiment, "tag": tag, "branch": branch}


# --------------------------------------------------------------------------- #
# Realizations
# --------------------------------------------------------------------------- #
@router.get("/api/sphere/realizations")
async def sphere_list_realizations(
    project: str | None = Query(None),
    all: bool = Query(False, description="List all visible realizations, not just the user's"),
    summary: bool = Query(False),
    state: bool = Query(False, description="Derive per-realization state (complete/failed/pending) + error"),
):
    _require_enabled()
    proj = _resolve_project(project)
    sess = sphere_manager.get_session(proj)
    return await _run(sess.list_realizations, all, summary, state)


@router.get("/api/sphere/realizations/{experiment}/{realization}")
async def sphere_get_realization(
    experiment: str, realization: str, project: str | None = Query(None),
):
    _require_enabled()
    proj = _resolve_project(project)
    sess = sphere_manager.get_session(proj)
    return await _run(sess.get_realization, experiment, realization)


@router.get("/api/sphere/realizations/{experiment}/{realization}/graph")
async def sphere_realization_graph(
    experiment: str, realization: str, project: str | None = Query(None),
):
    """Cytoscape.js graph elements for a SPHERE realization."""
    _require_enabled()
    proj = _resolve_project(project)
    sess = sphere_manager.get_session(proj)
    data = await _run(sess.get_realization, experiment, realization)
    # GetRealization wraps as {result: {realization, diagnostics}}; the contract
    # fixture is already the bare realization. Unwrap whichever we got.
    obj = data.get("result", data) if isinstance(data, dict) else data
    realization_obj = obj.get("realization", obj) if isinstance(obj, dict) else obj
    return build_sphere_realization_graph(realization_obj)


@router.post("/api/sphere/realizations")
async def sphere_realize(
    experiment: str = Body(..., embed=True),
    realization: str = Body(..., embed=True),
    tag: str | None = Body(None, embed=True),
    branch: str | None = Body(None, embed=True),
    revision: str | None = Body(None, embed=True),
    duration: str | None = Body(None, embed=True),
    project: str | None = Body(None, embed=True),
):
    _require_enabled()
    proj = _resolve_project(project)
    sess = sphere_manager.get_session(proj)
    return await _run(sess.realize, experiment, realization,
                      tag=tag, branch=branch, revision=revision, duration=duration)


@router.delete("/api/sphere/realizations/{experiment}/{realization}")
async def sphere_relinquish(
    experiment: str, realization: str, project: str | None = Query(None),
):
    _require_enabled()
    proj = _resolve_project(project)
    sess = sphere_manager.get_session(proj)
    return await _run(sess.relinquish, experiment, realization)


# --------------------------------------------------------------------------- #
# Materializations
# --------------------------------------------------------------------------- #
@router.post("/api/sphere/materializations")
async def sphere_materialize(
    experiment: str = Body(..., embed=True),
    realization: str = Body(..., embed=True),
    project: str | None = Body(None, embed=True),
):
    _require_enabled()
    proj = _resolve_project(project)
    sess = sphere_manager.get_session(proj)
    return await _run(sess.materialize, experiment, realization)


@router.get("/api/sphere/materializations/{experiment}/{realization}")
async def sphere_get_materialization(
    experiment: str, realization: str, project: str | None = Query(None),
    status: bool = Query(True, description="Include task status"),
):
    _require_enabled()
    proj = _resolve_project(project)
    sess = sphere_manager.get_session(proj)
    status_ms = 1 if status else 0
    return await _run(sess.get_materialization, experiment, realization,
                      status_ms=status_ms)


@router.delete("/api/sphere/materializations/{experiment}/{realization}")
async def sphere_dematerialize(
    experiment: str, realization: str, project: str | None = Query(None),
):
    _require_enabled()
    proj = _resolve_project(project)
    sess = sphere_manager.get_session(proj)
    return await _run(sess.dematerialize, experiment, realization)


# --------------------------------------------------------------------------- #
# XDCs (Experiment Data Conduits) — jump containers used to reach nodes
# --------------------------------------------------------------------------- #
@router.get("/api/sphere/xdcs")
async def sphere_list_xdcs(
    project: str | None = Query(None),
    status: bool = Query(False, description="Include per-XDC readiness status"),
):
    _require_enabled()
    proj = _resolve_project(project)
    sess = sphere_manager.get_session(proj)
    return await _run(sess.list_xdcs, proj, status)


@router.post("/api/sphere/xdcs")
async def sphere_create_xdc(
    xdc: str = Body(..., embed=True),
    type: str = Body("shared", embed=True),
    project: str | None = Body(None, embed=True),
):
    _require_enabled()
    proj = _resolve_project(project)
    sess = sphere_manager.get_session(proj)
    return await _run(sess.create_xdc, xdc, proj, type)


@router.delete("/api/sphere/xdcs/{xdc}")
async def sphere_delete_xdc(xdc: str, project: str | None = Query(None)):
    _require_enabled()
    proj = _resolve_project(project)
    sess = sphere_manager.get_session(proj)
    return await _run(sess.delete_xdc, xdc, proj)


@router.post("/api/sphere/xdcs/{xdc}/attach")
async def sphere_attach_xdc(
    xdc: str,
    experiment: str = Body(..., embed=True),
    realization: str = Body(..., embed=True),
    project: str | None = Body(None, embed=True),
):
    _require_enabled()
    proj = _resolve_project(project)
    sess = sphere_manager.get_session(proj)
    return await _run(sess.attach_xdc, xdc, experiment, realization, proj)


@router.post("/api/sphere/xdcs/{xdc}/detach")
async def sphere_detach_xdc(
    xdc: str,
    experiment: str = Body(..., embed=True),
    realization: str = Body(..., embed=True),
    project: str | None = Body(None, embed=True),
):
    _require_enabled()
    proj = _resolve_project(project)
    sess = sphere_manager.get_session(proj)
    return await _run(sess.detach_xdc, xdc, experiment, realization, proj)


@router.get("/api/sphere/jump-hosts")
async def sphere_jump_hosts(project: str | None = Query(None)):
    _require_enabled()
    proj = _resolve_project(project)
    sess = sphere_manager.get_session(proj)
    return await _run(sess.get_xdc_jump_hosts)


# --------------------------------------------------------------------------- #
# Inventory — facilities, resources, allocation pools
# --------------------------------------------------------------------------- #
@router.get("/api/sphere/inventory")
async def sphere_inventory(project: str | None = Query(None)):
    """Facilities + resources + pools for the project inventory view."""
    _require_enabled()
    proj = _resolve_project(project)
    sess = sphere_manager.get_session(proj)
    return await _run(sess.get_inventory)


# --------------------------------------------------------------------------- #
# File upload — scp a file to a node's home dir through the XDC jump chain
# --------------------------------------------------------------------------- #
@contextmanager
def _ssh_cfg(details: dict):
    """Write the ssh config (+ key/cert) for a node, yield its path, and remove
    the temp dir afterwards so private key material does not accumulate on disk."""
    from app.routes.terminal import write_sphere_ssh_config
    cfg_path, err = write_sphere_ssh_config(details)
    if not cfg_path:
        raise RuntimeError(err)
    try:
        yield cfg_path
    finally:
        shutil.rmtree(os.path.dirname(cfg_path), ignore_errors=True)


# Sentinel node value meaning "the XDC container itself" rather than an
# experiment node. The file-manager routes accept it so the same browse/upload/
# download/edit machinery targets the XDC's own filesystem (where its JupyterLab
# serves from) — see _resolve_node.
_XDC_TARGET = "__xdc__"


def _ssh_alias(details: dict) -> str:
    """The ssh config Host alias to target — ``sphere-xdc`` for an XDC target,
    else ``sphere-node`` (the default)."""
    return details.get("ssh_target") or "sphere-node"


def _node_ssh(details: dict, remote_cmd: str, timeout: int = 60) -> str:
    """Blocking: run a shell command on the target and return stdout."""
    alias = _ssh_alias(details)
    with _ssh_cfg(details) as cfg:
        proc = subprocess.run(["ssh", "-F", cfg, alias, remote_cmd],
                              capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"ssh exited {proc.returncode}")
    return proc.stdout


def _scp_to_node(details: dict, local_path: str, remote_path: str) -> None:
    """Blocking: scp *local_path* to the target at *remote_path* (relative to ~)."""
    alias = _ssh_alias(details)
    with _ssh_cfg(details) as cfg:
        proc = subprocess.run(["scp", "-F", cfg, "-q", local_path, f"{alias}:{remote_path}"],
                              capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"scp exited {proc.returncode}")


def _scp_from_node(details: dict, remote_path: str, local_path: str) -> None:
    """Blocking: scp the target's *remote_path* down to *local_path*."""
    alias = _ssh_alias(details)
    with _ssh_cfg(details) as cfg:
        proc = subprocess.run(["scp", "-F", cfg, "-q", f"{alias}:{remote_path}", local_path],
                              capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"scp exited {proc.returncode}")


def _list_node_dir(details: dict, path: str) -> list[dict]:
    """Blocking: list a directory on the node (parsed `ls -lAp`)."""
    out = _node_ssh(details, f"ls -lAp --time-style=long-iso -- {shlex.quote(path)}")
    entries: list[dict] = []
    for line in out.splitlines():
        if not line or line.startswith("total "):
            continue
        parts = line.split(None, 7)
        if len(parts) < 8:
            continue
        perms, _links, _owner, _group, size, _date, _time, name = parts
        is_dir = perms.startswith("d")
        is_link = perms.startswith("l")
        if " -> " in name:
            name = name.split(" -> ", 1)[0]
        name = name.rstrip("/")
        if name in (".", ".."):
            continue
        entries.append({
            "name": name,
            "size": int(size) if size.isdigit() else 0,
            "dir": is_dir,
            "symlink": is_link,
        })
    entries.sort(key=lambda e: (not e["dir"], e["name"].lower()))
    return entries


async def _resolve_node(experiment: str, realization: str, node: str, xdc: str, proj: str) -> dict:
    try:
        # The XDC sentinel targets the XDC container itself (its own filesystem /
        # JupyterLab home) rather than an experiment node.
        if node == _XDC_TARGET:
            return await asyncio.to_thread(sphere_manager.resolve_xdc_ssh, xdc, proj)
        return await asyncio.to_thread(
            sphere_manager.resolve_node_ssh, node, realization, experiment, proj, xdc)
    except Exception as exc:
        raise HTTPException(502, f"Could not resolve SPHERE node: {exc}") from exc


@router.post("/api/sphere/upload")
async def sphere_upload(
    file: UploadFile = File(...),
    experiment: str = Form(...),
    realization: str = Form(...),
    node: str = Form(...),
    xdc: str = Form(...),
    project: str | None = Form(None),
    dest: str | None = Form(None),
):
    """Upload a file to a node via scp through the XDC. *dest* is an optional
    target directory (relative to the login home); default is the home dir."""
    _require_enabled()
    proj = _resolve_project(project)
    remote_name = os.path.basename(file.filename or "upload").strip() or "upload"
    dest_dir = (dest or "").strip().rstrip("/")
    remote_path = f"{shlex.quote(dest_dir)}/{shlex.quote(remote_name)}" if dest_dir else shlex.quote(remote_name)
    details = await _resolve_node(experiment, realization, node, xdc, proj)

    tmp_dir = tempfile.mkdtemp(prefix="sphere-upload-")
    tmp_path = os.path.join(tmp_dir, remote_name)
    max_bytes = 5 * 1024 ** 3  # 5 GB cap to protect the backend's /tmp
    written = 0
    try:
        with open(tmp_path, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(413, "Upload exceeds the 5 GB limit")
                out.write(chunk)
        await asyncio.to_thread(_scp_to_node, details, tmp_path, remote_path)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Upload failed: {exc}") from exc
    finally:
        try:
            os.remove(tmp_path)
            os.rmdir(tmp_dir)
        except OSError:
            pass
    return {"ok": True, "node": node, "path": f"{dest_dir + '/' if dest_dir else '~/'}{remote_name}"}


@router.get("/api/sphere/files")
async def sphere_list_files(
    experiment: str = Query(...), realization: str = Query(...), node: str = Query(...),
    xdc: str = Query(...), path: str = Query("."), project: str | None = Query(None),
):
    """List a directory on a node (file manager) via ssh through the XDC."""
    _require_enabled()
    proj = _resolve_project(project)
    details = await _resolve_node(experiment, realization, node, xdc, proj)
    try:
        entries = await asyncio.to_thread(_list_node_dir, details, path or ".")
    except Exception as exc:
        raise HTTPException(502, f"List failed: {exc}") from exc
    return {"path": path or ".", "entries": entries}


@router.get("/api/sphere/files/download")
async def sphere_download_file(
    experiment: str = Query(...), realization: str = Query(...), node: str = Query(...),
    xdc: str = Query(...), path: str = Query(...), project: str | None = Query(None),
):
    """Download a file from a node via scp through the XDC."""
    _require_enabled()
    proj = _resolve_project(project)
    details = await _resolve_node(experiment, realization, node, xdc, proj)
    name = os.path.basename(path.rstrip("/")) or "download"
    tmp_dir = tempfile.mkdtemp(prefix="sphere-dl-")
    tmp_path = os.path.join(tmp_dir, name)
    try:
        await asyncio.to_thread(_scp_from_node, details, shlex.quote(path), tmp_path)
    except Exception as exc:
        raise HTTPException(502, f"Download failed: {exc}") from exc

    def _cleanup():
        try:
            os.remove(tmp_path); os.rmdir(tmp_dir)
        except OSError:
            pass
    return FileResponse(tmp_path, filename=name, background=BackgroundTask(_cleanup))


@router.post("/api/sphere/files/delete")
async def sphere_delete_file(
    experiment: str = Body(..., embed=True),
    realization: str = Body(..., embed=True),
    node: str = Body(..., embed=True),
    xdc: str = Body(..., embed=True),
    path: str = Body(..., embed=True),
    project: str | None = Body(None, embed=True),
):
    """Delete a file or directory on a node via ssh through the XDC."""
    _require_enabled()
    proj = _resolve_project(project)
    if not path or path.strip() in ("", ".", "/", "~", "./"):
        raise HTTPException(400, "Refusing to delete that path")
    details = await _resolve_node(experiment, realization, node, xdc, proj)
    try:
        await asyncio.to_thread(_node_ssh, details, f"rm -rf -- {shlex.quote(path)}")
    except Exception as exc:
        raise HTTPException(502, f"Delete failed: {exc}") from exc
    return {"ok": True, "path": path}


@router.post("/api/sphere/files/mkdir")
async def sphere_mkdir(
    experiment: str = Body(..., embed=True),
    realization: str = Body(..., embed=True),
    node: str = Body(..., embed=True),
    xdc: str = Body(..., embed=True),
    path: str = Body(..., embed=True),
    project: str | None = Body(None, embed=True),
):
    """Create a directory on a node."""
    _require_enabled()
    proj = _resolve_project(project)
    details = await _resolve_node(experiment, realization, node, xdc, proj)
    try:
        await asyncio.to_thread(_node_ssh, details, f"mkdir -p -- {shlex.quote(path)}")
    except Exception as exc:
        raise HTTPException(502, f"Mkdir failed: {exc}") from exc
    return {"created": path}


@router.post("/api/sphere/files/read")
async def sphere_read_file(
    experiment: str = Body(..., embed=True),
    realization: str = Body(..., embed=True),
    node: str = Body(..., embed=True),
    xdc: str = Body(..., embed=True),
    path: str = Body(..., embed=True),
    project: str | None = Body(None, embed=True),
):
    """Read a text file from a node (for in-browser editing). Capped so a huge
    (or pseudo-) file can't exhaust backend memory."""
    _require_enabled()
    proj = _resolve_project(project)
    details = await _resolve_node(experiment, realization, node, xdc, proj)
    limit = 5_000_000  # 5 MB — this is an editor, not a bulk download
    try:
        content = await asyncio.to_thread(
            _node_ssh, details, f"head -c {limit} -- {shlex.quote(path)}")
    except Exception as exc:
        raise HTTPException(502, f"Read failed: {exc}") from exc
    truncated = len(content.encode("utf-8", "replace")) >= limit
    return {"path": path, "content": content, "truncated": truncated}


@router.post("/api/sphere/files/write")
async def sphere_write_file(
    experiment: str = Body(..., embed=True),
    realization: str = Body(..., embed=True),
    node: str = Body(..., embed=True),
    xdc: str = Body(..., embed=True),
    path: str = Body(..., embed=True),
    content: str = Body("", embed=True),
    project: str | None = Body(None, embed=True),
):
    """Write a text file on a node (from the in-browser editor)."""
    _require_enabled()
    proj = _resolve_project(project)
    details = await _resolve_node(experiment, realization, node, xdc, proj)
    tmp_dir = tempfile.mkdtemp(prefix="sphere-write-")
    tmp_path = os.path.join(tmp_dir, os.path.basename(path) or "file")
    try:
        with open(tmp_path, "w") as fh:
            fh.write(content)
        await asyncio.to_thread(_scp_to_node, details, tmp_path, shlex.quote(path))
    except Exception as exc:
        raise HTTPException(502, f"Write failed: {exc}") from exc
    finally:
        try:
            os.remove(tmp_path); os.rmdir(tmp_dir)
        except OSError:
            pass
    return {"path": path, "status": "ok"}


@router.get("/api/sphere/files/download-folder")
async def sphere_download_folder(
    experiment: str = Query(...), realization: str = Query(...), node: str = Query(...),
    xdc: str = Query(...), path: str = Query(...), project: str | None = Query(None),
):
    """Download a directory from a node as a .tgz (tar streamed over ssh to a
    temp file — not held in memory)."""
    _require_enabled()
    proj = _resolve_project(project)
    details = await _resolve_node(experiment, realization, node, xdc, proj)
    name = os.path.basename(path.rstrip("/")) or "folder"
    out_dir = tempfile.mkdtemp(prefix="sphere-tgz-")
    out_path = os.path.join(out_dir, f"{name}.tgz")

    def _tar() -> None:
        alias = _ssh_alias(details)
        with _ssh_cfg(details) as cfg:
            cmd = (f"tar -czf - -C {shlex.quote(os.path.dirname(path) or '.')} "
                   f"{shlex.quote(name)}")
            with open(out_path, "wb") as out:
                proc = subprocess.run(["ssh", "-F", cfg, alias, cmd],
                                      stdout=out, stderr=subprocess.PIPE, timeout=600)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode(errors="replace").strip() or "tar failed")

    try:
        await asyncio.to_thread(_tar)
    except Exception as exc:
        shutil.rmtree(out_dir, ignore_errors=True)
        raise HTTPException(502, f"Folder download failed: {exc}") from exc

    def _cleanup():
        shutil.rmtree(out_dir, ignore_errors=True)
    return FileResponse(out_path, media_type="application/gzip", filename=f"{name}.tgz",
                        background=BackgroundTask(_cleanup))


@router.post("/api/sphere/xdcs/{xdc}/seed-weave")
async def sphere_seed_weave_to_xdc(
    xdc: str,
    weave: str = Body(..., embed=True),
    dest: str | None = Body(None, embed=True),
    project: str | None = Body(None, embed=True),
):
    """Copy a packaged weave's notebook + setup scripts (+ model, README) from
    LoomAI's ``my_artifacts`` onto the **XDC** so they appear in its JupyterLab.

    The XDC is a separate container from LoomAI; packaging writes to LoomAI
    storage, so this is what actually puts the files where the XDC's JupyterLab
    can see them. ``dest`` defaults to ``~/<weave>``.
    """
    _require_enabled()
    from app.user_context import get_artifacts_dir

    proj = _resolve_project(project)
    # Locate + validate the weave dir (no traversal out of my_artifacts).
    base = os.path.realpath(get_artifacts_dir())
    src = os.path.realpath(os.path.join(base, weave))
    if not (src == base or src.startswith(base + os.sep)) or not os.path.isdir(src):
        raise HTTPException(404, f"Weave '{weave}' not found")

    # Collect the files worth seeding (skip logs / caches).
    pairs: list[tuple[str, str]] = []
    for root, _dirs, names in os.walk(src):
        if "__pycache__" in root or ".ipynb_checkpoints" in root:
            continue
        for fn in names:
            if fn.endswith((".pyc", ".log")):
                continue
            abs = os.path.join(root, fn)
            rel = os.path.relpath(abs, src)
            pairs.append((abs, rel))
    if not pairs:
        raise HTTPException(400, "Weave has no files to seed")

    dest_dir = (dest or os.path.basename(src)).strip().strip("/") or os.path.basename(src)
    if not re.match(r"^[A-Za-z0-9._/-]+$", dest_dir) or ".." in dest_dir.split("/"):
        raise HTTPException(400, "Invalid destination")

    details = await _resolve_node("", "", _XDC_TARGET, xdc, proj)

    def _push() -> int:
        alias = _ssh_alias(details)
        subdirs = sorted({os.path.dirname(r) for _a, r in pairs if os.path.dirname(r)})
        with _ssh_cfg(details) as cfg:
            mkdirs = [dest_dir] + [f"{dest_dir}/{d}" for d in subdirs]
            mk = "mkdir -p " + " ".join(shlex.quote(d) for d in mkdirs)
            p = subprocess.run(["ssh", "-F", cfg, alias, mk],
                               capture_output=True, text=True, timeout=60)
            if p.returncode != 0:
                raise RuntimeError(p.stderr.strip() or "mkdir failed")
            for abs_path, rel in pairs:
                remote = f"{dest_dir}/{rel}"
                sp = subprocess.run(["scp", "-F", cfg, "-q", abs_path, f"{alias}:{remote}"],
                                    capture_output=True, text=True, timeout=300)
                if sp.returncode != 0:
                    raise RuntimeError(sp.stderr.strip() or f"scp {rel} failed")
        return len(pairs)

    try:
        count = await asyncio.to_thread(_push)
    except Exception as exc:
        raise HTTPException(502, f"Seed to XDC failed: {exc}") from exc
    return {"ok": True, "xdc": xdc, "dest": f"~/{dest_dir}", "files": count}
