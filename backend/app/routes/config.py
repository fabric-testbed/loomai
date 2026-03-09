"""Configuration API routes for standalone FABRIC WebGUI setup."""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import shutil
import stat
import time
from typing import Optional
from urllib.parse import urlencode

import paramiko
import requests as http_requests
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.slice_registry import resolve_slice_name
from app.fablib_manager import (
    DEFAULT_CONFIG_DIR,
    is_configured,
    reset_fablib,
    get_fablib,
    _load_keys_json,
    _save_keys_json,
    _migrate_legacy_keys,
    get_default_slice_key_path,
    get_slice_key_path,
)
from app.user_context import get_user_storage, get_token_path, notify_user_changed

logger = logging.getLogger(__name__)

router = APIRouter()

# Read version from frontend/src/version.ts (single source of truth)
def _read_version() -> str:
    for candidate in [
        os.path.join(os.path.dirname(__file__), '..', '..', 'frontend', 'src', 'version.ts'),  # dev (backend/)
        '/app/VERSION',  # Docker image
    ]:
        try:
            with open(candidate) as f:
                content = f.read()
            m = re.search(r'[\"\'](\d+\.\d+\.\d+)', content)
            if m:
                return m.group(1)
        except OSError:
            continue
    return "0.0.0"

CURRENT_VERSION = _read_version()

DOCKER_HUB_REPO = os.environ.get("DOCKER_REPO", "fabrictestbed/loomai-dev")
DOCKER_HUB_TAGS_URL = f"https://hub.docker.com/v2/repositories/{DOCKER_HUB_REPO}/tags/"

# Simple in-memory cache for update checks (1 hour TTL)
_update_cache: dict = {"result": None, "timestamp": 0.0}
_UPDATE_CACHE_TTL = 3600  # seconds

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _config_dir() -> str:
    return os.environ.get("FABRIC_CONFIG_DIR", DEFAULT_CONFIG_DIR)


def _ensure_config_dir() -> str:
    d = _config_dir()
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


def _token_path() -> str:
    return get_token_path()


def _read_token() -> Optional[dict]:
    path = _token_path()
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        return json.load(f)


def _decode_jwt_payload(token: str) -> dict:
    """Decode JWT payload without verification (token is trusted from CM)."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT format")
    payload = parts[1]
    # Fix base64 padding
    payload += "=" * (4 - len(payload) % 4)
    decoded = base64.urlsafe_b64decode(payload)
    return json.loads(decoded)


def _file_exists(name: str) -> bool:
    return os.path.isfile(os.path.join(_config_dir(), name))


def _get_ai_api_key() -> str:
    """Read the FABRIC_AI_API_KEY value from fabric_rc."""
    rc_path = os.path.join(_config_dir(), "fabric_rc")
    if os.path.isfile(rc_path):
        with open(rc_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("export FABRIC_AI_API_KEY="):
                    return line.split("=", 1)[1]
    return ""


def _get_nrp_api_key() -> str:
    """Read the NRP_API_KEY value from fabric_rc."""
    rc_path = os.path.join(_config_dir(), "fabric_rc")
    if os.path.isfile(rc_path):
        with open(rc_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("export NRP_API_KEY="):
                    return line.split("=", 1)[1]
    return ""


def _read_project_id_from_rc() -> str:
    """Read FABRIC_PROJECT_ID from fabric_rc file (stable on disk).

    Unlike os.environ, this is not affected by temporary env var mutations
    in reconcile_projects.
    """
    rc_path = os.path.join(_config_dir(), "fabric_rc")
    if os.path.isfile(rc_path):
        with open(rc_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("export FABRIC_PROJECT_ID="):
                    return line.split("=", 1)[1]
    return os.environ.get("FABRIC_PROJECT_ID", "")


def _storage_dir() -> str:
    return get_user_storage()


def _slice_keys_dir() -> str:
    """Return the .slice-keys sidecar directory for per-slice key assignments."""
    d = os.path.join(_storage_dir(), ".slice-keys")
    os.makedirs(d, exist_ok=True)
    return d


def _key_fingerprint(priv_path: str) -> str:
    """Get fingerprint string from a private key file."""
    try:
        from app.routes.terminal import _load_private_key
        k = _load_private_key(priv_path)
        fp_bytes = k.get_fingerprint()
        return ":".join(f"{b:02x}" for b in fp_bytes)
    except Exception:
        return ""


def _key_pub_str(priv_path: str, pub_path: str) -> str:
    """Get public key string, preferring .pub file, falling back to deriving from private."""
    if os.path.isfile(pub_path):
        with open(pub_path) as f:
            return f.read().strip()
    try:
        from app.routes.terminal import _load_private_key
        k = _load_private_key(priv_path)
        return f"{k.get_name()} {k.get_base64()}"
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# GET /api/config — overall status
# ---------------------------------------------------------------------------

@router.get("/api/config")
def get_config_status():
    config_dir = _config_dir()
    token_data = _read_token()
    token_info = None

    if token_data and "id_token" in token_data:
        try:
            payload = _decode_jwt_payload(token_data["id_token"])
            token_info = {
                "email": payload.get("email", ""),
                "name": payload.get("name", ""),
                "uuid": payload.get("uuid", ""),
                "exp": payload.get("exp"),
                "projects": payload.get("projects", []),
            }
        except Exception:
            token_info = {"error": "Could not decode token"}

    # Check fabric_rc for project_id and AI API key
    project_id = ""
    bastion_username = ""
    ai_api_key = ""
    nrp_api_key = ""
    rc_path = os.path.join(config_dir, "fabric_rc")
    if os.path.isfile(rc_path):
        with open(rc_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("export FABRIC_PROJECT_ID="):
                    project_id = line.split("=", 1)[1]
                elif line.startswith("export FABRIC_BASTION_USERNAME="):
                    bastion_username = line.split("=", 1)[1]
                elif line.startswith("export FABRIC_AI_API_KEY="):
                    ai_api_key = line.split("=", 1)[1]
                elif line.startswith("export NRP_API_KEY="):
                    nrp_api_key = line.split("=", 1)[1]

    # Read public key contents for display
    bastion_pub_key = ""
    bastion_key_fingerprint = ""

    bastion_pub_path = os.path.join(config_dir, "fabric_bastion_key.pub")
    if os.path.isfile(bastion_pub_path):
        with open(bastion_pub_path) as f:
            bastion_pub_key = f.read().strip()

    bastion_priv_path = os.path.join(config_dir, "fabric_bastion_key")
    if os.path.isfile(bastion_priv_path):
        bastion_key_fingerprint = _key_fingerprint(bastion_priv_path)
        if not bastion_pub_key:
            bastion_pub_key = _key_pub_str(bastion_priv_path, bastion_pub_path)

    # Migrate and get default slice key info
    _migrate_legacy_keys(config_dir)
    keys_data = _load_keys_json(config_dir)
    default_key = keys_data.get("default", "default")
    priv_path, pub_path = get_default_slice_key_path(config_dir)
    slice_pub_key = _key_pub_str(priv_path, pub_path)
    slice_key_fingerprint = _key_fingerprint(priv_path) if os.path.isfile(priv_path) else ""
    has_slice_key = os.path.isfile(priv_path) and os.path.isfile(pub_path)

    return {
        "configured": is_configured(),
        "has_token": os.path.isfile(get_token_path()),
        "has_bastion_key": _file_exists("fabric_bastion_key"),
        "has_slice_key": has_slice_key,
        "token_info": token_info,
        "project_id": project_id,
        "bastion_username": bastion_username,
        "bastion_pub_key": bastion_pub_key,
        "bastion_key_fingerprint": bastion_key_fingerprint,
        "slice_pub_key": slice_pub_key,
        "slice_key_fingerprint": slice_key_fingerprint,
        "default_slice_key": default_key,
        "slice_key_sets": keys_data.get("keys", []),
        "ai_api_key_set": bool(ai_api_key),
        "nrp_api_key_set": bool(nrp_api_key),
    }


# ---------------------------------------------------------------------------
# POST /api/config/token — upload token JSON file
# ---------------------------------------------------------------------------

@router.post("/api/config/token")
async def upload_token(file: UploadFile = File(...)):
    content = await file.read()
    try:
        token_data = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON file")

    if "id_token" not in token_data:
        raise HTTPException(status_code=400, detail="Token file must contain 'id_token' field")

    d = _ensure_config_dir()
    # Dual-write: ~/.tokens.json (JupyterHub convention) + config_dir/id_token.json (FABlib)
    for tp in [os.path.join(os.path.expanduser("~"), ".tokens.json"),
               os.path.join(d, "id_token.json")]:
        os.makedirs(os.path.dirname(tp), exist_ok=True)
        with open(tp, "w") as f:
            json.dump(token_data, f, indent=2)
        os.chmod(tp, stat.S_IRUSR | stat.S_IWUSR)

    reset_fablib()
    notify_user_changed()

    return {"status": "ok", "message": "Token uploaded successfully"}


# ---------------------------------------------------------------------------
# GET /api/config/login — return CM OAuth login URL
# ---------------------------------------------------------------------------

@router.get("/api/config/login")
def get_login_url():
    params: dict = {
        "scope": "all",
        "lifetime": "4",
    }
    # Include current project_id so the token is scoped to the active project
    pid = os.environ.get("FABRIC_PROJECT_ID", "")
    if pid:
        params["project_id"] = pid
    cm_url = "https://cm.fabric-testbed.net/credmgr/tokens/create_cli?" + urlencode(params)
    return {"login_url": cm_url}


# ---------------------------------------------------------------------------
# POST /api/config/token/paste — accept pasted token JSON text
# ---------------------------------------------------------------------------

class TokenPasteRequest(BaseModel):
    token_text: str


@router.post("/api/config/token/paste")
def paste_token(req: TokenPasteRequest):
    text = req.token_text.strip()
    try:
        token_data = json.loads(text)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON. Paste the complete token JSON from Credential Manager.")

    if "id_token" not in token_data:
        raise HTTPException(status_code=400, detail="Token JSON must contain an 'id_token' field")

    d = _ensure_config_dir()
    # Dual-write: ~/.tokens.json (JupyterHub convention) + config_dir/id_token.json (FABlib)
    for tp in [os.path.join(os.path.expanduser("~"), ".tokens.json"),
               os.path.join(d, "id_token.json")]:
        os.makedirs(os.path.dirname(tp), exist_ok=True)
        with open(tp, "w") as f:
            json.dump(token_data, f, indent=2)
        os.chmod(tp, stat.S_IRUSR | stat.S_IWUSR)

    reset_fablib()
    notify_user_changed()

    return {"status": "ok", "message": "Token saved successfully"}


# ---------------------------------------------------------------------------
# GET /api/config/callback — OAuth callback from CM
# ---------------------------------------------------------------------------

@router.get("/api/config/callback")
def oauth_callback(id_token: str, refresh_token: str = ""):
    d = _ensure_config_dir()
    token_data = {
        "id_token": id_token,
        "refresh_token": refresh_token,
    }
    # Dual-write: ~/.tokens.json (JupyterHub convention) + config_dir/id_token.json (FABlib)
    for tp in [os.path.join(os.path.expanduser("~"), ".tokens.json"),
               os.path.join(d, "id_token.json")]:
        os.makedirs(os.path.dirname(tp), exist_ok=True)
        with open(tp, "w") as f:
            json.dump(token_data, f, indent=2)
        os.chmod(tp, stat.S_IRUSR | stat.S_IWUSR)

    # Reset FABlib and notify caches so all views use the new account
    reset_fablib()
    notify_user_changed()

    # Redirect back to frontend with success indicator
    base_url = os.environ.get("WEBGUI_BASE_URL", "http://localhost:3000")
    return RedirectResponse(url=f"{base_url}/?configLogin=success")


# ---------------------------------------------------------------------------
# GET /api/config/projects — decode JWT + query UIS for projects & bastion_login
# ---------------------------------------------------------------------------

@router.get("/api/config/projects")
def get_projects():
    token_data = _read_token()
    if not token_data or "id_token" not in token_data:
        raise HTTPException(status_code=400, detail="No token available. Upload or login first.")

    id_token = token_data["id_token"]

    # Decode JWT for projects
    try:
        payload = _decode_jwt_payload(id_token)
    except Exception:
        raise HTTPException(status_code=400, detail="Could not decode token")

    projects = payload.get("projects", [])

    # Derive bastion_login from JWT claims
    bastion_login = ""
    try:
        email = payload.get("email", "")
        sub = payload.get("sub", "")
        if email and sub:
            username = email.split("@")[0]
            cilogon_id = sub.rstrip("/").rsplit("/", 1)[-1]
            if cilogon_id.isdigit():
                bastion_login = f"{username}_{cilogon_id.zfill(10)}"
    except Exception:
        pass

    return {
        "projects": projects,
        "bastion_login": bastion_login,
        "email": payload.get("email", ""),
        "name": payload.get("name", ""),
    }


# ---------------------------------------------------------------------------
# POST /api/config/keys/bastion — upload bastion private key
# ---------------------------------------------------------------------------

@router.post("/api/config/keys/bastion")
async def upload_bastion_key(file: UploadFile = File(...)):
    content = await file.read()
    d = _ensure_config_dir()
    path = os.path.join(d, "fabric_bastion_key")
    with open(path, "wb") as f:
        f.write(content)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    return {"status": "ok", "message": "Bastion key uploaded"}


# ---------------------------------------------------------------------------
# Slice Key Set Management
# ---------------------------------------------------------------------------

@router.get("/api/config/keys/slice/list")
def list_slice_key_sets():
    """List all named key sets with fingerprints."""
    config_dir = _config_dir()
    _migrate_legacy_keys(config_dir)
    data = _load_keys_json(config_dir)
    default_name = data.get("default", "default")
    result = []
    for name in data.get("keys", []):
        priv_path, pub_path = get_slice_key_path(config_dir, name)
        fp = _key_fingerprint(priv_path) if os.path.isfile(priv_path) else ""
        pub = _key_pub_str(priv_path, pub_path)
        result.append({
            "name": name,
            "is_default": name == default_name,
            "fingerprint": fp,
            "pub_key": pub,
        })
    return result


@router.post("/api/config/keys/slice")
async def upload_slice_keys(
    private_key: UploadFile = File(...),
    public_key: UploadFile = File(...),
    key_name: str = Query("default"),
):
    config_dir = _ensure_config_dir()
    _migrate_legacy_keys(config_dir)

    key_dir = os.path.join(config_dir, "slice_keys", key_name)
    os.makedirs(key_dir, exist_ok=True)

    priv_content = await private_key.read()
    pub_content = await public_key.read()

    priv_path = os.path.join(key_dir, "slice_key")
    with open(priv_path, "wb") as f:
        f.write(priv_content)
    os.chmod(priv_path, stat.S_IRUSR | stat.S_IWUSR)

    pub_path = os.path.join(key_dir, "slice_key.pub")
    with open(pub_path, "wb") as f:
        f.write(pub_content)
    os.chmod(pub_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)

    # Register in keys.json
    data = _load_keys_json(config_dir)
    if key_name not in data.get("keys", []):
        data.setdefault("keys", []).append(key_name)
    _save_keys_json(config_dir, data)

    # Also maintain legacy flat copies for the default key set
    if key_name == data.get("default", "default"):
        _sync_default_flat_copies(config_dir, key_name)

    return {"status": "ok", "message": f"Slice keys uploaded to set '{key_name}'"}


@router.post("/api/config/keys/slice/generate")
def generate_slice_keys(key_name: str = Query("default")):
    config_dir = _ensure_config_dir()
    _migrate_legacy_keys(config_dir)

    key_dir = os.path.join(config_dir, "slice_keys", key_name)
    os.makedirs(key_dir, exist_ok=True)

    key = paramiko.RSAKey.generate(2048)

    priv_path = os.path.join(key_dir, "slice_key")
    key.write_private_key_file(priv_path)
    os.chmod(priv_path, stat.S_IRUSR | stat.S_IWUSR)

    pub_key_str = f"{key.get_name()} {key.get_base64()} fabric-webgui-generated"
    pub_path = os.path.join(key_dir, "slice_key.pub")
    with open(pub_path, "w") as f:
        f.write(pub_key_str + "\n")
    os.chmod(pub_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)

    # Register in keys.json
    data = _load_keys_json(config_dir)
    if key_name not in data.get("keys", []):
        data.setdefault("keys", []).append(key_name)
    _save_keys_json(config_dir, data)

    # Maintain legacy flat copies for default key set
    if key_name == data.get("default", "default"):
        _sync_default_flat_copies(config_dir, key_name)

    return {
        "status": "ok",
        "public_key": pub_key_str,
        "message": f"Slice keys generated in set '{key_name}'. Add the public key to your FABRIC portal profile.",
    }


@router.put("/api/config/keys/slice/default")
def set_default_slice_key(key_name: str = Query(...)):
    """Set which key set is the default."""
    config_dir = _config_dir()
    _migrate_legacy_keys(config_dir)
    data = _load_keys_json(config_dir)

    if key_name not in data.get("keys", []):
        raise HTTPException(status_code=404, detail=f"Key set '{key_name}' not found")

    data["default"] = key_name
    _save_keys_json(config_dir, data)

    # Sync flat copies and update fabric_rc
    _sync_default_flat_copies(config_dir, key_name)
    _update_fabric_rc_slice_keys(config_dir, key_name)

    # Reset FABlib so it picks up new key paths
    reset_fablib()

    return {"status": "ok", "default": key_name}


@router.delete("/api/config/keys/slice/{key_name}")
def delete_slice_key_set(key_name: str):
    """Delete a named key set. Cannot delete the current default."""
    config_dir = _config_dir()
    _migrate_legacy_keys(config_dir)
    data = _load_keys_json(config_dir)

    if key_name == data.get("default", "default"):
        raise HTTPException(status_code=400, detail="Cannot delete the default key set. Change default first.")

    if key_name not in data.get("keys", []):
        raise HTTPException(status_code=404, detail=f"Key set '{key_name}' not found")

    # Remove from registry
    data["keys"] = [k for k in data["keys"] if k != key_name]
    _save_keys_json(config_dir, data)

    # Remove directory
    key_dir = os.path.join(config_dir, "slice_keys", key_name)
    if os.path.isdir(key_dir):
        shutil.rmtree(key_dir)

    return {"status": "ok", "deleted": key_name}


def _sync_default_flat_copies(config_dir: str, key_name: str) -> None:
    """Copy the named key set to flat slice_key/slice_key.pub for legacy compatibility."""
    priv_src, pub_src = get_slice_key_path(config_dir, key_name)
    priv_dst = os.path.join(config_dir, "slice_key")
    pub_dst = os.path.join(config_dir, "slice_key.pub")
    if os.path.isfile(priv_src):
        shutil.copy2(priv_src, priv_dst)
    if os.path.isfile(pub_src):
        shutil.copy2(pub_src, pub_dst)


def _update_fabric_rc_slice_keys(config_dir: str, key_name: str) -> None:
    """Update FABRIC_SLICE_*_KEY_FILE in fabric_rc to point to the named key set."""
    rc_path = os.path.join(config_dir, "fabric_rc")
    if not os.path.isfile(rc_path):
        return
    priv_path, pub_path = get_slice_key_path(config_dir, key_name)
    with open(rc_path) as f:
        lines = f.readlines()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("export FABRIC_SLICE_PRIVATE_KEY_FILE="):
            new_lines.append(f"export FABRIC_SLICE_PRIVATE_KEY_FILE={priv_path}\n")
        elif stripped.startswith("export FABRIC_SLICE_PUBLIC_KEY_FILE="):
            new_lines.append(f"export FABRIC_SLICE_PUBLIC_KEY_FILE={pub_path}\n")
        else:
            new_lines.append(line)
    with open(rc_path, "w") as f:
        f.writelines(new_lines)


# ---------------------------------------------------------------------------
# Per-Slice Key Assignment
# ---------------------------------------------------------------------------

@router.get("/api/config/slice-key/{slice_name}")
def get_slice_key_assignment(slice_name: str):
    """Get the key set assigned to a specific slice."""
    slice_name = resolve_slice_name(slice_name)
    path = os.path.join(_slice_keys_dir(), f"{slice_name}.json")
    if os.path.isfile(path):
        with open(path) as f:
            data = json.load(f)
        return {"slice_name": slice_name, "slice_key_id": data.get("slice_key_id", "")}
    return {"slice_name": slice_name, "slice_key_id": ""}


class SliceKeyAssignment(BaseModel):
    slice_key_id: str


@router.put("/api/config/slice-key/{slice_name}")
def set_slice_key_assignment(slice_name: str, body: SliceKeyAssignment):
    """Assign a key set to a slice."""
    slice_name = resolve_slice_name(slice_name)
    config_dir = _config_dir()
    _migrate_legacy_keys(config_dir)
    data = _load_keys_json(config_dir)

    if body.slice_key_id and body.slice_key_id not in data.get("keys", []):
        raise HTTPException(status_code=404, detail=f"Key set '{body.slice_key_id}' not found")

    path = os.path.join(_slice_keys_dir(), f"{slice_name}.json")
    if body.slice_key_id:
        with open(path, "w") as f:
            json.dump({"slice_key_id": body.slice_key_id}, f, indent=2)
    else:
        # Empty string means "use default" — remove the assignment file
        if os.path.isfile(path):
            os.remove(path)

    return {"status": "ok", "slice_name": slice_name, "slice_key_id": body.slice_key_id}


# ---------------------------------------------------------------------------
# GET /api/projects — all user projects from the Core API
# ---------------------------------------------------------------------------

@router.get("/api/projects")
def list_user_projects():
    """Return all projects the user belongs to, queried from the FABRIC Core API."""
    try:
        fablib = get_fablib()
        mgr = fablib.get_manager()
        projects = mgr.get_project_info()  # returns [{name, uuid}, ...]
        # Read from fabric_rc (stable on disk) instead of os.environ which
        # can be temporarily mutated by reconcile_projects during its scan.
        current_id = _read_project_id_from_rc()
        return {"projects": projects, "active_project_id": current_id}
    except RuntimeError:
        raise HTTPException(status_code=400, detail="FABRIC is not configured yet.")
    except Exception as e:
        logger.warning("Failed to query projects from Core API: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to query projects: {e}")


# ---------------------------------------------------------------------------
# POST /api/projects/switch — switch active project
# ---------------------------------------------------------------------------

class ProjectSwitchRequest(BaseModel):
    project_id: str


@router.post("/api/projects/switch")
def switch_project(req: ProjectSwitchRequest):
    """Switch the active project in-memory and persist to fabric_rc."""
    try:
        fablib = get_fablib()
    except RuntimeError:
        raise HTTPException(status_code=400, detail="FABRIC is not configured yet.")

    # Update in-memory via FABlib
    fablib.set_project_id(req.project_id)
    os.environ["FABRIC_PROJECT_ID"] = req.project_id

    # Update the SliceManager's project_id so token refresh uses the new project
    mgr = fablib.get_manager()
    mgr.project_id = req.project_id

    # Force token refresh scoped to the new project
    token_refreshed = False
    try:
        refresh_token = mgr.get_refresh_token()
        if refresh_token:
            mgr.refresh_tokens(refresh_token=refresh_token)
            token_refreshed = True
    except Exception:
        pass  # Token refresh is best-effort

    # Persist to fabric_rc
    config_dir = _config_dir()
    rc_path = os.path.join(config_dir, "fabric_rc")
    if os.path.isfile(rc_path):
        with open(rc_path) as f:
            lines = f.readlines()
        new_lines = []
        found = False
        for line in lines:
            if line.strip().startswith("export FABRIC_PROJECT_ID="):
                new_lines.append(f"export FABRIC_PROJECT_ID={req.project_id}\n")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"export FABRIC_PROJECT_ID={req.project_id}\n")
        with open(rc_path, "w") as f:
            f.writelines(new_lines)

    result: dict = {"status": "ok", "project_id": req.project_id, "token_refreshed": token_refreshed}
    if not token_refreshed:
        # Provide a CM login URL scoped to the new project so the frontend
        # can redirect the user to re-authenticate with a project-scoped token.
        login_url = "https://cm.fabric-testbed.net/credmgr/tokens/create_cli?" + urlencode({
            "scope": "all",
            "lifetime": "4",
            "project_id": req.project_id,
        })
        result["warning"] = (
            "Your token does not have a refresh capability. "
            "Click 'Re-authenticate' in Settings to get a token for this project."
        )
        result["login_url"] = login_url
    return result


# ---------------------------------------------------------------------------
# POST /api/config/save — write fabric_rc and reset FABlib
# ---------------------------------------------------------------------------

class ConfigSaveRequest(BaseModel):
    # Required
    project_id: str
    bastion_username: str
    # Service hosts
    credmgr_host: str = "cm.fabric-testbed.net"
    orchestrator_host: str = "orchestrator.fabric-testbed.net"
    core_api_host: str = "uis.fabric-testbed.net"
    bastion_host: str = "bastion.fabric-testbed.net"
    am_host: str = "artifacts.fabric-testbed.net"
    # Logging
    log_level: str = "INFO"
    log_file: str = "/tmp/fablib/fablib.log"
    # Advanced
    avoid: str = ""
    ssh_command_line: str = (
        "ssh -i {{ _self_.private_ssh_key_file }} "
        "-F {config_dir}/ssh_config "
        "{{ _self_.username }}@{{ _self_.management_ip }}"
    )
    # AI Companion
    litellm_api_key: str = ""
    nrp_api_key: str = ""


@router.post("/api/config/save")
def save_config(req: ConfigSaveRequest):
    d = _ensure_config_dir()

    if not os.path.isfile(get_token_path()):
        raise HTTPException(status_code=400, detail="Token is required before saving configuration")

    # Resolve ssh_command_line config_dir placeholder
    ssh_cmd = req.ssh_command_line.replace("{config_dir}", d)

    # Get default key paths for fabric_rc
    _migrate_legacy_keys(d)
    priv_path, pub_path = get_default_slice_key_path(d)

    # Preserve existing keys if the fields are empty (user didn't change them)
    ai_key = req.litellm_api_key or _get_ai_api_key()
    nrp_key = req.nrp_api_key or _get_nrp_api_key()

    fabric_rc = f"""export FABRIC_CREDMGR_HOST={req.credmgr_host}
export FABRIC_ORCHESTRATOR_HOST={req.orchestrator_host}
export FABRIC_CORE_API_HOST={req.core_api_host}
export FABRIC_AM_HOST={req.am_host}
export FABRIC_TOKEN_LOCATION={d}/id_token.json
export FABRIC_BASTION_HOST={req.bastion_host}
export FABRIC_BASTION_USERNAME={req.bastion_username}
export FABRIC_BASTION_KEY_LOCATION={d}/fabric_bastion_key
export FABRIC_BASTION_SSH_CONFIG_FILE={d}/ssh_config
export FABRIC_SLICE_PUBLIC_KEY_FILE={pub_path}
export FABRIC_SLICE_PRIVATE_KEY_FILE={priv_path}
export FABRIC_PROJECT_ID={req.project_id}
export FABRIC_LOG_LEVEL={req.log_level}
export FABRIC_LOG_FILE={req.log_file}
export FABRIC_AVOID={req.avoid}
export FABRIC_SSH_COMMAND_LINE="{ssh_cmd}"
export FABRIC_AI_API_KEY={ai_key}
export NRP_API_KEY={nrp_key}
"""

    rc_path = os.path.join(d, "fabric_rc")
    with open(rc_path, "w") as f:
        f.write(fabric_rc)

    # Write ssh_config for bastion proxy jump
    ssh_config = f"""UserKnownHostsFile /dev/null
StrictHostKeyChecking no
ServerAliveInterval 120

Host bastion.fabric-testbed.net
    User {req.bastion_username}
    ForwardAgent yes
    Hostname %h
    IdentityFile {d}/fabric_bastion_key
    IdentitiesOnly yes

Host * !bastion.fabric-testbed.net
    ProxyJump {req.bastion_username}@bastion.fabric-testbed.net:22
"""
    ssh_config_path = os.path.join(d, "ssh_config")
    with open(ssh_config_path, "w") as f:
        f.write(ssh_config)

    # Reset FABlib so it picks up the new config
    reset_fablib()

    return {"status": "ok", "configured": is_configured()}


# ---------------------------------------------------------------------------
# POST /api/config/rebuild-storage — re-initialize storage and re-seed templates
# ---------------------------------------------------------------------------

@router.post("/api/config/rebuild-storage")
def rebuild_storage():
    """Re-initialize storage directories."""
    storage = get_user_storage()

    # Ensure all storage subdirectories exist
    from app.user_context import get_artifacts_dir, get_slices_dir
    get_artifacts_dir()   # creates my_artifacts/
    get_slices_dir()      # creates my_slices/
    subdirs = [".slice-keys"]
    dirs_created = 2  # count the shared dirs
    for sd in subdirs:
        path = os.path.join(storage, sd)
        if not os.path.isdir(path):
            os.makedirs(path, exist_ok=True)
            dirs_created += 1

    return {
        "status": "ok",
        "directories": len(subdirs),
        "directories_created": dirs_created,
    }


# ---------------------------------------------------------------------------
# GET /api/config/check-update — check Docker Hub for newer version
# ---------------------------------------------------------------------------

def _parse_semver(tag: str) -> tuple:
    """Parse a semver-like tag into a comparable tuple. Returns () on failure."""
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)(?:-(.+))?$", tag)
    if not m:
        return ()
    major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
    pre = m.group(4) or ""
    # Pre-release sorts before release: "beta" < "" (no pre-release)
    # Use (0, pre) for pre-release, (1, "") for release so release > pre-release
    pre_tuple = (0, pre) if pre else (1, "")
    return (major, minor, patch, pre_tuple)


@router.get("/api/config/check-update")
def check_update():
    """Check Docker Hub for a newer version of the application image."""
    now = time.time()

    # Return cached result if still fresh
    if _update_cache["result"] and (now - _update_cache["timestamp"]) < _UPDATE_CACHE_TTL:
        return _update_cache["result"]

    current_parsed = _parse_semver(CURRENT_VERSION)

    try:
        resp = http_requests.get(
            DOCKER_HUB_TAGS_URL,
            params={"page_size": 25, "ordering": "last_updated"},
            timeout=10,
        )
        resp.raise_for_status()
        tags_data = resp.json().get("results", [])
    except Exception as e:
        logger.debug("Docker Hub check failed: %s", e)
        result = {
            "current_version": CURRENT_VERSION,
            "latest_version": CURRENT_VERSION,
            "update_available": False,
            "docker_hub_url": f"https://hub.docker.com/r/{DOCKER_HUB_REPO}",
            "published_at": None,
        }
        _update_cache["result"] = result
        _update_cache["timestamp"] = now
        return result

    # Find the latest semver tag
    best_tag = ""
    best_parsed: tuple = ()
    best_date = None
    for entry in tags_data:
        tag_name = entry.get("name", "")
        parsed = _parse_semver(tag_name)
        if not parsed:
            continue
        if parsed > best_parsed:
            best_parsed = parsed
            best_tag = tag_name
            best_date = entry.get("last_updated")

    if not best_tag:
        best_tag = CURRENT_VERSION

    update_available = best_parsed > current_parsed if best_parsed and current_parsed else False

    result = {
        "current_version": CURRENT_VERSION,
        "latest_version": best_tag,
        "update_available": update_available,
        "docker_hub_url": f"https://hub.docker.com/r/{DOCKER_HUB_REPO}",
        "published_at": best_date,
    }
    _update_cache["result"] = result
    _update_cache["timestamp"] = now
    return result


# ---------------------------------------------------------------------------
# AI Companion tool toggles
# ---------------------------------------------------------------------------

_DEFAULT_AI_TOOLS = {"aider": True, "opencode": True, "crush": True, "claude": True}


def _ai_tools_path() -> str:
    storage = os.environ.get("FABRIC_STORAGE_DIR", "/home/fabric/work")
    return os.path.join(storage, ".ai_tools.json")


def _load_ai_tools() -> dict[str, bool]:
    path = _ai_tools_path()
    if os.path.isfile(path):
        try:
            with open(path) as f:
                data = json.load(f)
            # Merge with defaults so new tools are always present
            merged = dict(_DEFAULT_AI_TOOLS)
            merged.update({k: bool(v) for k, v in data.items() if k in _DEFAULT_AI_TOOLS})
            return merged
        except Exception:
            pass
    return dict(_DEFAULT_AI_TOOLS)


@router.get("/api/config/ai-tools")
def get_ai_tools() -> dict[str, bool]:
    """Return which AI companion tools are enabled."""
    return _load_ai_tools()


@router.post("/api/config/ai-tools")
def set_ai_tools(body: dict[str, bool]) -> dict[str, bool]:
    """Update AI companion tool toggles."""
    current = _load_ai_tools()
    for k in current:
        if k in body:
            current[k] = bool(body[k])
    path = _ai_tools_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(current, f, indent=2)
    return current
