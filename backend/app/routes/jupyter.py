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

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.http_pool import fabric_client, ai_client
from app.user_context import get_user_storage, register_user_changed_callback
from app.tool_installer import is_tool_installed, get_tool_binary_path, get_tool_env

router = APIRouter(tags=["jupyter"])
logger = logging.getLogger(__name__)

def _jupyter_port() -> int:
    from app.settings_manager import get_jupyter_port
    return get_jupyter_port()

_jupyter_proc: subprocess.Popen | None = None


def _workdir() -> str:
    """Return the JupyterLab root directory.

    Always uses the root storage dir (``/home/fabric/work``) so that
    top-level symlinks (``my_artifacts/``, ``fabric_config/``, etc.)
    are visible.  In multi-user mode the symlinks point to the active
    user's directories — see ``_ensure_user_symlinks`` in config.py.
    """
    from app.settings_manager import get_root_storage_dir
    d = get_root_storage_dir()
    os.makedirs(d, exist_ok=True)
    return d


# Stop JupyterLab when the active user changes so it restarts with
# the updated symlinks on next access.
def _on_user_changed() -> None:
    global _jupyter_proc
    if _jupyter_proc and _jupyter_proc.poll() is None:
        logger.info("User changed — stopping JupyterLab (pid=%d)", _jupyter_proc.pid)
        try:
            os.killpg(os.getpgid(_jupyter_proc.pid), signal.SIGTERM)
            _jupyter_proc.wait(timeout=5)
        except Exception:
            try:
                _jupyter_proc.kill()
            except Exception:
                pass
    _jupyter_proc = None

register_user_changed_callback(_on_user_changed)


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


def _configure_jupyter_ai(env: dict) -> None:
    """Write Jupyter AI config with all eligible LLM providers.

    Reads FABRIC, NRP, and custom provider settings to populate the
    Jupyter AI config file so every model the user has access to appears
    in the Jupyter AI chat sidebar dropdown.  Also sets OPENAI_* env vars
    for the primary (FABRIC) provider.
    """
    from app import settings_manager

    fabric_key = settings_manager.get_fabric_api_key()
    nrp_key = settings_manager.get_nrp_api_key()
    fabric_url = settings_manager.get_ai_server_url()
    nrp_url = settings_manager.get_nrp_server_url()
    default_model = settings_manager.get_default_model()
    settings = settings_manager.load_settings()
    custom_providers = settings.get("ai", {}).get("custom_providers", [])

    if not fabric_key and not nrp_key and not custom_providers:
        return  # No providers configured

    # Set primary env vars (FABRIC takes precedence)
    primary_key = fabric_key or nrp_key
    primary_url = fabric_url if fabric_key else nrp_url
    if primary_key:
        env["OPENAI_API_KEY"] = primary_key
        env["OPENAI_API_BASE"] = f"{primary_url}/v1"
        env["OPENAI_BASE_URL"] = f"{primary_url}/v1"

    # Build per-model fields for Jupyter AI config
    fields: dict = {}

    # Try to get cached model list (from the health check cache)
    fabric_models: list[str] = []
    nrp_models: list[str] = []
    try:
        from app.routes.ai_terminal import _model_ids, _fetch_models, _fetch_nrp_models
        if fabric_key:
            fabric_models = _model_ids(_fetch_models(fabric_key))
        if nrp_key:
            nrp_models = _model_ids(_fetch_nrp_models(nrp_key))
    except Exception:
        # Fall back to just the default model
        if default_model:
            fabric_models = [default_model]

    # Register FABRIC models
    for mid in fabric_models:
        fields[f"openai-chat:{mid}"] = {"openai_api_base": f"{fabric_url}/v1"}

    # Register NRP models with their own key
    for mid in nrp_models:
        entry: dict = {"openai_api_base": f"{nrp_url}/v1"}
        if nrp_key and nrp_key != fabric_key:
            entry["openai_api_key"] = nrp_key
        fields[f"openai-chat:{mid}"] = entry

    # Register custom provider models
    for cp in custom_providers:
        cp_name = cp.get("name", "custom")
        cp_url = cp.get("base_url", "")
        cp_key = cp.get("api_key", "")
        if not cp_url:
            continue
        try:
            from app.routes.ai_terminal import _model_ids
            import urllib.request
            req = urllib.request.Request(
                f"{cp_url.rstrip('/')}/v1/models",
                headers={"Authorization": f"Bearer {cp_key}"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = json.loads(resp.read())
            for m in body.get("data", []):
                mid = m["id"]
                entry = {"openai_api_base": f"{cp_url.rstrip('/')}/v1"}
                if cp_key:
                    entry["openai_api_key"] = cp_key
                fields[f"openai-chat:{mid}"] = entry
        except Exception:
            pass  # Skip unreachable providers

    if not fields:
        return

    # Determine default model for Jupyter AI
    if not default_model:
        default_model = fabric_models[0] if fabric_models else nrp_models[0] if nrp_models else ""
    if not default_model:
        return

    # Build API keys dict
    api_keys: dict = {}
    if fabric_key:
        api_keys["OPENAI_API_KEY"] = fabric_key

    # Write Jupyter AI config
    jupyter_ai_dir = os.path.expanduser("~/.jupyter/jupyter_ai")
    os.makedirs(jupyter_ai_dir, exist_ok=True)
    ai_config = {
        "model_provider_id": f"openai-chat:{default_model}",
        "embeddings_provider_id": None,
        "api_keys": api_keys,
        "fields": fields,
    }
    config_path = os.path.join(jupyter_ai_dir, "config.json")
    with open(config_path, "w") as f:
        json.dump(ai_config, f, indent=2)

    model_count = len(fields)
    providers = []
    if fabric_models:
        providers.append(f"FABRIC({len(fabric_models)})")
    if nrp_models:
        providers.append(f"NRP({len(nrp_models)})")
    if custom_providers:
        providers.append("custom")
    logger.info("Jupyter AI configured: %d models from %s, default=%s",
                model_count, "+".join(providers), default_model)

    # Write FABRIC-enhanced system prompt for Jupyter AI
    _configure_jupyter_ai_prompt()


def _configure_jupyter_ai_prompt() -> None:
    """Patch Jupyter AI's system prompt with FABRIC context and copy skills/agents.

    Writes a jupyter_server_config.py snippet that monkey-patches the
    CHAT_SYSTEM_PROMPT constant at JupyterLab startup, giving Jupyternaut
    deep FABRIC testbed knowledge.  Also copies shared skills and agents
    to a location Jupyter AI users can reference.
    """
    # Build a compact FABRIC system prompt (subset of FABRIC_AI.md)
    fabric_prompt_lines = [
        "",
        "",
        "You are running inside a FABRIC testbed container with full access to FABlib and the loomai CLI.",
        "You are an expert on the FABRIC testbed — a national research infrastructure for networking and distributed systems experiments.",
        "",
        "Key facts:",
        "- FABRIC provides bare-metal and VM resources across 29+ sites in the US and internationally",
        "- Users create 'slices' (virtual topologies) with nodes, networks, and specialized hardware (GPUs, FPGAs, SmartNICs)",
        "- FABlib is the Python library for managing slices: `from fabrictestbed_extensions.fablib.fablib import FablibManager`",
        "- The `loomai` CLI is available for slice management, SSH, file transfer, monitoring, and AI assistant",
        "- Run `loomai --help` to see all available commands",
        "",
        "Common FABlib patterns:",
        "```python",
        "from fabrictestbed_extensions.fablib.fablib import FablibManager",
        "fablib = FablibManager()",
        "",
        "# List slices",
        "slices = fablib.get_slices()",
        "for s in slices: print(f'{s.get_name()}: {s.get_state()}')",
        "",
        "# Create a slice",
        "slice = fablib.new_slice(name='my-experiment')",
        "node = slice.add_node(name='node1', site='RENC', cores=4, ram=16, disk=100)",
        "slice.submit()",
        "slice.wait_ssh()",
        "",
        "# SSH and execute",
        "node = slice.get_node('node1')",
        "stdout, stderr = node.execute('hostname')",
        "```",
        "",
        "Common loomai CLI commands:",
        "- `loomai slices list` — list all slices",
        "- `loomai ssh <slice> <node>` — SSH to a node",
        "- `loomai exec <slice> <node> 'command'` — run a command on a node",
        "- `loomai sites list` — list FABRIC sites with availability",
        "- `loomai weaves list` — list available weave templates",
        "",
        "When writing FABRIC code, always use proper error handling and resource cleanup.",
        "Suggest `loomai` CLI commands when users ask about managing their experiments.",
    ]
    fabric_context = "\n".join(fabric_prompt_lines)

    # Write a startup hook that patches the system prompt
    jupyter_dir = os.path.expanduser("~/.jupyter")
    os.makedirs(jupyter_dir, exist_ok=True)
    config_path = os.path.join(jupyter_dir, "jupyter_server_config.py")

    patch_code = f'''
# --- FABRIC AI context (auto-generated by Loomai) ---
def _patch_jupyter_ai_prompt():
    """Inject FABRIC context into Jupyter AI system prompt."""
    try:
        import jupyter_ai_magics.providers as _providers
        _orig = _providers.CHAT_SYSTEM_PROMPT
        _fabric_context = """{fabric_context}"""
        _providers.CHAT_SYSTEM_PROMPT = _orig + _fabric_context
    except Exception:
        pass  # jupyter-ai not installed or API changed
_patch_jupyter_ai_prompt()
del _patch_jupyter_ai_prompt
# --- end FABRIC AI context ---
'''

    # Read existing config, replace or append the FABRIC section
    existing = ""
    if os.path.isfile(config_path):
        with open(config_path) as f:
            existing = f.read()

    marker_start = "# --- FABRIC AI context (auto-generated by Loomai) ---"
    marker_end = "# --- end FABRIC AI context ---"
    if marker_start in existing:
        # Replace existing section
        before = existing[:existing.index(marker_start)]
        after_marker = existing[existing.index(marker_end) + len(marker_end):]
        existing = before.rstrip() + "\n" + after_marker.lstrip()

    with open(config_path, "w") as f:
        f.write(existing.rstrip() + "\n" + patch_code)

    # Copy skills and agents to a Jupyter-accessible location for reference
    ai_tools_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                 "ai-tools", "shared")
    jupyter_fabric_dir = os.path.join(jupyter_dir, "fabric_context")
    os.makedirs(jupyter_fabric_dir, exist_ok=True)

    for subdir in ("skills", "agents"):
        src_dir = os.path.join(ai_tools_dir, subdir)
        dst_dir = os.path.join(jupyter_fabric_dir, subdir)
        if os.path.isdir(src_dir):
            os.makedirs(dst_dir, exist_ok=True)
            for fname in os.listdir(src_dir):
                if fname.endswith(".md"):
                    src = os.path.join(src_dir, fname)
                    dst = os.path.join(dst_dir, fname)
                    shutil.copy2(src, dst)

    # Copy FABRIC_AI.md as reference
    fabric_ai_path = os.path.join(ai_tools_dir, "FABRIC_AI.md")
    if os.path.isfile(fabric_ai_path):
        shutil.copy2(fabric_ai_path, os.path.join(jupyter_fabric_dir, "FABRIC_AI.md"))

    logger.info("Jupyter AI FABRIC prompt configured, %s skills + agents copied to %s",
                len(os.listdir(os.path.join(jupyter_fabric_dir, "skills")))
                if os.path.isdir(os.path.join(jupyter_fabric_dir, "skills")) else 0,
                jupyter_fabric_dir)


@router.post("/api/jupyter/start")
async def start_jupyter():
    """Start JupyterLab rooted at the base work directory."""
    global _jupyter_proc

    port = _jupyter_port()
    if _jupyter_proc and _jupyter_proc.poll() is None:
        return {"port": port, "status": "running"}

    workdir = _workdir()

    if not is_tool_installed("jupyterlab"):
        return {"install_required": True, "tool": "jupyterlab", "status": "not_installed"}

    jupyter_bin = get_tool_binary_path("jupyterlab") or "jupyter"
    cmd = [
        jupyter_bin, "lab",
        "--no-browser",
        "--ip=0.0.0.0",
        f"--port={port}",
        "--ServerApp.token=",
        "--ServerApp.password=",
        "--ServerApp.disable_check_xsrf=True",
        "--ServerApp.allow_origin=*",
        "--ServerApp.allow_remote_access=True",
        "--ServerApp.base_url=/jupyter/",
        f"--ServerApp.root_dir={workdir}",
        # Use bash for JupyterLab terminals
        "--ServerApp.terminado_settings={'shell_command': ['/bin/bash']}",
    ]

    env = {**os.environ}
    env.update({k: v for k, v in get_tool_env().items() if k == "PATH"})

    # Configure Jupyter AI with all eligible LLM providers (writes jupyter_server_config.py)
    _configure_jupyter_ai(env)

    # Ensure ~/.jupyter dir exists for Jupyter AI config
    jupyter_conf_dir = os.path.join(os.path.expanduser("~"), ".jupyter")
    os.makedirs(jupyter_conf_dir, exist_ok=True)

    # Clean any stale collaboration extension configs from previous versions
    labconfig_dir = os.path.join(jupyter_conf_dir, "labconfig")
    if os.path.isdir(labconfig_dir):
        page_config_path = os.path.join(labconfig_dir, "page_config.json")
        if os.path.isfile(page_config_path):
            os.remove(page_config_path)

    try:
        _jupyter_proc = subprocess.Popen(
            cmd, cwd=workdir, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid,
        )
        logger.info("JupyterLab started pid=%d on :%d workdir=%s",
                     _jupyter_proc.pid, port, workdir)
    except Exception:
        logger.exception("Failed to start JupyterLab")
        return {"error": "Failed to start JupyterLab — is jupyterlab installed?",
                "status": "error"}

    # Poll until JupyterLab is actually listening (up to 30s)
    import socket
    for _attempt in range(30):
        await asyncio.sleep(1)
        # Check if process died
        if _jupyter_proc.poll() is not None:
            return {"error": "JupyterLab process exited unexpectedly", "status": "error"}
        # Check if port is accepting connections
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                logger.info("JupyterLab ready on :%d after %ds", port, _attempt + 1)
                return {"port": port, "status": "running"}
        except (ConnectionRefusedError, OSError, socket.timeout):
            continue

    # Timed out waiting — process is running but not accepting connections yet
    logger.warning("JupyterLab started but not responding after 30s")
    return {"port": port, "status": "running"}


@router.post("/api/jupyter/stop")
async def stop_jupyter():
    """Stop the running JupyterLab server."""
    await _stop_jupyter()
    return {"status": "stopped"}


@router.get("/api/jupyter/status")
async def jupyter_status():
    """Check JupyterLab server status and readiness."""
    import socket
    running = _jupyter_proc is not None and _jupyter_proc.poll() is None
    if not running:
        return {"port": None, "status": "stopped"}
    port = _jupyter_port()
    # Check if actually listening (not just process alive)
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return {"port": port, "status": "running", "ready": True}
    except (ConnectionRefusedError, OSError, socket.timeout):
        return {"port": port, "status": "starting", "ready": False}


class ThemeRequest(BaseModel):
    theme: str  # "dark" or "light"


@router.post("/api/jupyter/theme")
async def set_jupyter_theme(req: ThemeRequest):
    """Set JupyterLab theme via its settings API."""
    running = _jupyter_proc is not None and _jupyter_proc.poll() is None
    if not running:
        return {"status": "not_running"}

    jlab_theme = "JupyterLab Dark" if req.theme == "dark" else "JupyterLab Light"
    settings_url = f"http://127.0.0.1:{_jupyter_port()}/jupyter/lab/api/settings/@jupyterlab/apputils-extension:themes"

    try:
        r = await fabric_client.put(
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
    from app.settings_manager import get_notebooks_dir
    return get_notebooks_dir()


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
    """Read the artifact_uuid from weave.json in an artifact directory."""
    weave_path = os.path.join(artifact_dir, "weave.json")
    if os.path.isfile(weave_path):
        try:
            with open(weave_path) as f:
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
        "port": _jupyter_port(),
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
    description_long: str = ""
    visibility: str = "author"
    project_uuid: str = ""
    tags: list[str] = []


@router.post("/api/notebooks/{name}/publish-fork")
async def publish_fork(name: str, req: PublishForkRequest):
    """Publish the working copy as a forked artifact.

    Reads the original artifact_uuid from weave.json and includes
    fork provenance in the new artifact's metadata.
    """
    safe = _sanitize_name(name)
    work_dir = os.path.join(_notebooks_workdir(), safe)
    if not os.path.isdir(work_dir):
        raise HTTPException(status_code=404, detail=f"No workspace for '{name}' — launch it first")

    # Read original metadata for fork provenance from weave.json
    artifact_dir = os.path.join(_artifacts_dir(), safe)
    original_uuid = ""
    original_title = ""
    weave_path = os.path.join(artifact_dir, "weave.json")
    if os.path.isfile(weave_path):
        try:
            with open(weave_path) as f:
                meta = json.load(f)
            original_uuid = meta.get("artifact_uuid", "")
            original_title = meta.get("name", safe)
        except Exception:
            pass

    # Update the workspace metadata with fork info before publishing
    work_weave_path = os.path.join(work_dir, "weave.json")
    work_meta = {}
    if os.path.isfile(work_weave_path):
        try:
            with open(work_weave_path) as f:
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

    with open(work_weave_path, "w") as f:
        json.dump(work_meta, f, indent=2)

    # Use the artifacts publish flow
    from app.routes.artifacts import _get_auth_headers, ARTIFACT_API, _cache
    import tarfile
    import tempfile

    headers = _get_auth_headers()
    if not headers:
        raise HTTPException(status_code=401, detail="No FABRIC token configured — cannot publish")

    # Step 1: Create artifact record (include title and tags upfront)
    from app.routes.artifacts import _make_descriptions
    desc_short, desc_long = _make_descriptions(req.description, req.title, "notebook", req.description_long)
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
        r = await fabric_client.post(
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
        r = await fabric_client.put(
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
            with open(tar_path, "rb") as fh:
                r = await ai_client.post(
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
