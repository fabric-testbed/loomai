"""Configuration API routes for standalone FABRIC WebGUI setup."""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import shutil
import secrets
import stat
import time
from typing import Optional
from urllib.parse import urlencode

import httpx
import paramiko
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.http_pool import fabric_client
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

# ---------------------------------------------------------------------------
# Multi-user symlink management
# ---------------------------------------------------------------------------

_SYMLINKED_DIRS = ["fabric_config", "my_artifacts", "my_slices", "notebooks"]


def _ensure_user_symlinks(uuid: str) -> None:
    """Create or update top-level symlinks to the active user's directories.

    In multi-user mode the per-user data lives under ``users/{uuid}/``.
    This function maintains symlinks at the storage root so that tools
    reading the filesystem directly (JupyterLab, terminal, etc.) always
    see the active user's data at the well-known paths.
    """
    from app import settings_manager

    root = settings_manager.get_root_storage_dir()
    user_dir = os.path.join(root, "users", uuid)

    for name in _SYMLINKED_DIRS:
        link_path = os.path.join(root, name)
        target = os.path.join(user_dir, name)
        os.makedirs(target, exist_ok=True)

        if os.path.islink(link_path):
            current = os.readlink(link_path)
            if current == target:
                continue  # already correct
            os.unlink(link_path)
        elif os.path.isdir(link_path):
            # Real directory from legacy/single-user layout — back it up
            backup = link_path + ".pre-multiuser"
            if not os.path.exists(backup):
                os.rename(link_path, backup)
                logger.info("Backed up %s → %s", name, backup + "/")
            else:
                shutil.rmtree(link_path)
        elif os.path.exists(link_path):
            os.unlink(link_path)

        os.symlink(target, link_path)
        logger.info("Symlinked %s → users/%s/%s", name, uuid, name)


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
    """Return FABRIC AI API key from settings."""
    from app.settings_manager import get_fabric_api_key
    return get_fabric_api_key()


def _get_nrp_api_key() -> str:
    """Return NRP API key from settings."""
    from app.settings_manager import get_nrp_api_key
    return get_nrp_api_key()


def _read_project_id_from_rc() -> str:
    """Return FABRIC project ID from settings (stable on disk).

    Unlike os.environ, this is not affected by temporary env var mutations
    in reconcile_projects.
    """
    from app.settings_manager import get_project_id
    return get_project_id()


def _fetch_uis_person(id_token: str, user_uuid: str) -> dict:
    """Synchronous UIS people fetch for use with FabricCallManager cache."""
    resp = httpx.get(
        f"https://uis.fabric-testbed.net/people/{user_uuid}",
        headers={"Authorization": f"Bearer {id_token}"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _handle_token_write(token_data: dict) -> None:
    """Handle multi-user registration when a token is written.

    If a registry exists and the new token is for a different user,
    registers the new user and switches to them.
    If no registry exists but there's already a token for a different user,
    triggers migration to multi-user layout.
    """
    from app import user_registry

    id_token = token_data.get("id_token", "")
    if not id_token:
        return
    try:
        new_payload = _decode_jwt_payload(id_token)
        new_uuid = new_payload.get("uuid", "")
        new_name = new_payload.get("name", "")
        new_email = new_payload.get("email", "")
        if not new_uuid:
            return
    except Exception:
        return

    reg = user_registry.load_registry()

    if reg is not None:
        # Registry exists — register/update and switch if different
        user_registry.add_user(new_uuid, new_name, new_email)
        current_active = reg.get("active_user")
        if current_active != new_uuid:
            user_registry.set_active_user(new_uuid)
            user_registry.ensure_user_dir(new_uuid)
            # Write token to new user's config dir
            new_user_dir = user_registry.get_user_storage_dir(new_uuid)
            if new_user_dir:
                cfg_dir = os.path.join(new_user_dir, "fabric_config")
                os.makedirs(cfg_dir, exist_ok=True)
                tp = os.path.join(cfg_dir, "id_token.json")
                with open(tp, "w") as f:
                    json.dump(token_data, f, indent=2)
                os.chmod(tp, stat.S_IRUSR | stat.S_IWUSR)
            _do_user_switch(new_uuid)
    else:
        # No registry — check if there's already a token for a different user
        existing_token = _read_token()
        if existing_token and "id_token" in existing_token:
            try:
                existing_payload = _decode_jwt_payload(existing_token["id_token"])
                existing_uuid = existing_payload.get("uuid", "")
                if existing_uuid and existing_uuid != new_uuid:
                    # Different user! Trigger migration
                    existing_name = existing_payload.get("name", "")
                    existing_email = existing_payload.get("email", "")
                    _migrate_to_multi_user(existing_uuid, existing_name, existing_email)
                    # Register and switch to the new user
                    user_registry.add_user(new_uuid, new_name, new_email)
                    user_registry.set_active_user(new_uuid)
                    user_registry.ensure_user_dir(new_uuid)
                    # Write token to new user's config dir
                    new_user_dir = user_registry.get_user_storage_dir(new_uuid)
                    if new_user_dir:
                        cfg_dir = os.path.join(new_user_dir, "fabric_config")
                        os.makedirs(cfg_dir, exist_ok=True)
                        tp = os.path.join(cfg_dir, "id_token.json")
                        with open(tp, "w") as f:
                            json.dump(token_data, f, indent=2)
                        os.chmod(tp, stat.S_IRUSR | stat.S_IWUSR)
                    _do_user_switch(new_uuid)
            except Exception:
                pass  # Can't decode existing token — just proceed normally


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

    # Read settings from settings_manager
    from app import settings_manager
    project_id = settings_manager.get_project_id()
    bastion_username = settings_manager.get_bastion_username()
    ai_api_key = settings_manager.get_fabric_api_key()
    nrp_api_key = settings_manager.get_nrp_api_key()

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

    # Auto-register user and handle multi-user migration
    _handle_token_write(token_data)

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
def get_login_url(origin: str = Query(None)):
    """Return CM OAuth login URL with redirect_uri pointing to our callback.

    The CM requires ``redirect_uri`` to point to ``http://localhost:PORT/...``.
    We use the caller-supplied *origin* (from ``window.location.origin``) when
    available so the redirect works regardless of which port the UI is served on.
    Falls back to ``WEBGUI_BASE_URL`` or ``http://localhost:3000``.
    """
    base = origin or os.environ.get("WEBGUI_BASE_URL", "http://localhost:3000")
    params: dict = {
        "scope": "all",
        "lifetime": "4",
        "redirect_uri": f"{base}/api/config/callback",
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

    # Auto-register user and handle multi-user migration
    _handle_token_write(token_data)

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
# GET/POST /api/config/callback — OAuth callback from CM
# ---------------------------------------------------------------------------

def _process_oauth_callback(id_token: str, refresh_token: str = "") -> RedirectResponse:
    """Shared logic for GET/POST callback — writes token, generates keys, and redirects."""
    logger.info("oauth_callback: received token delivery (id_token len=%d)", len(id_token))
    token_data = {
        "id_token": id_token,
        "refresh_token": refresh_token,
    }

    # Auto-register user and handle multi-user migration
    try:
        _handle_token_write(token_data)
    except Exception as e:
        logger.warning("oauth_callback: _handle_token_write error (continuing): %s", e)

    d = _ensure_config_dir()
    # Dual-write: ~/.tokens.json (JupyterHub convention) + config_dir/id_token.json (FABlib)
    for tp in [os.path.join(os.path.expanduser("~"), ".tokens.json"),
               os.path.join(d, "id_token.json")]:
        os.makedirs(os.path.dirname(tp), exist_ok=True)
        with open(tp, "w") as f:
            json.dump(token_data, f, indent=2)
        os.chmod(tp, stat.S_IRUSR | stat.S_IWUSR)
        logger.info("oauth_callback: wrote token to %s", tp)

    # Reset FABlib and notify caches so all views use the new account
    reset_fablib()
    notify_user_changed()

    # --- Inline key generation + project setup ---
    # The frontend auto-setup flow may not trigger reliably (popup/polling race).
    # Generate bastion key + set project here so config is ready on redirect.
    try:
        payload = _decode_jwt_payload(id_token)
        jwt_projects = payload.get("projects", [])
        user_email = payload.get("email", "")
        user_uuid = payload.get("uuid", "")

        # Pick the first non-service project
        provisionable = [p for p in jwt_projects
                         if not re.match(r'^SERVICE\s*[-–—]', p.get("name", ""), re.IGNORECASE)]
        project_id = ""
        if provisionable:
            project_id = provisionable[0].get("uuid", "")
        elif jwt_projects:
            project_id = jwt_projects[0].get("uuid", "")

        if project_id:
            logger.info("oauth_callback: setting project_id=%s for %s", project_id, user_email)
            from app import settings_manager
            settings = settings_manager.load_settings()
            settings["fabric"]["project_id"] = project_id

            # Resolve bastion_username
            bastion_login = ""
            try:
                email = payload.get("email", "")
                sub = payload.get("sub", "")
                if email and sub:
                    username = email.split("@")[0].replace(".", "_")
                    cilogon_id = sub.rstrip("/").rsplit("/", 1)[-1]
                    if cilogon_id.isdigit():
                        bastion_login = f"{username}_{cilogon_id.zfill(10)}"
            except Exception:
                pass
            if bastion_login:
                settings["fabric"]["bastion_username"] = bastion_login

            settings_manager.save_settings(settings)
            settings_manager.apply_env_vars(settings)

            config_dir = d
            core_api_host = settings.get("fabric", {}).get("hosts", {}).get("core_api", "uis.fabric-testbed.net")

            # Generate bastion key via Core API
            bastion_priv_path = os.path.join(config_dir, "fabric_bastion_key")
            if not os.path.isfile(bastion_priv_path):
                logger.info("oauth_callback: generating bastion key via Core API (%s)", core_api_host)
                try:
                    resp = httpx.post(
                        f"https://{core_api_host}/sshkeys",
                        headers={"Authorization": f"Bearer {id_token}", "Content-Type": "application/json"},
                        json={"keytype": "bastion", "comment": f"loomai-bastion-{secrets.token_hex(4)}",
                              "description": "bastion-key-via-loomai", "store_pubkey": True},
                        timeout=15,
                    )
                    logger.info("oauth_callback: Core API /sshkeys responded %d", resp.status_code)
                    if resp.status_code >= 400:
                        logger.warning("oauth_callback: Core API /sshkeys error: %s", resp.text[:500])
                    resp.raise_for_status()
                    results = resp.json().get("results", [])
                    if results:
                        priv = results[0].get("private_openssh", "")
                        pub = results[0].get("public_openssh", "")
                        if priv:
                            with open(bastion_priv_path, "w") as f:
                                f.write(priv)
                            os.chmod(bastion_priv_path, stat.S_IRUSR | stat.S_IWUSR)
                            logger.info("oauth_callback: bastion key written to %s", bastion_priv_path)
                        if pub:
                            pub_path = os.path.join(config_dir, "fabric_bastion_key.pub")
                            with open(pub_path, "w") as f:
                                f.write(pub)
                            os.chmod(pub_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
                    else:
                        logger.warning("oauth_callback: Core API /sshkeys returned empty results")
                except Exception as e:
                    logger.warning("oauth_callback: bastion key generation failed: %s", e, exc_info=True)
            else:
                logger.info("oauth_callback: bastion key already exists at %s", bastion_priv_path)

            # Generate slice keys if missing
            from app.fablib_manager import get_default_slice_key_path
            priv_path, pub_path = get_default_slice_key_path(config_dir)
            if not os.path.isfile(priv_path):
                logger.info("oauth_callback: generating slice keys")
                try:
                    import subprocess
                    os.makedirs(os.path.dirname(priv_path), exist_ok=True)
                    subprocess.run(["ssh-keygen", "-t", "rsa", "-b", "3072", "-f", priv_path, "-N", "", "-q"],
                                   check=True, timeout=10)
                    logger.info("oauth_callback: slice keys written to %s", priv_path)
                except Exception as e:
                    logger.warning("oauth_callback: slice key generation failed: %s", e)

            # Create FABRIC LLM API key
            existing_ai_key = settings_manager.get_fabric_api_key()
            if not existing_ai_key:
                try:
                    cm_host = settings.get("fabric", {}).get("hosts", {}).get("credmgr", "cm.fabric-testbed.net")
                    auth_headers = {"Authorization": f"Bearer {id_token}"}
                    # Check for existing keys first
                    api_key = ""
                    try:
                        keys_resp = httpx.get(f"https://{cm_host}/credmgr/tokens/llm_keys",
                                              headers=auth_headers, timeout=15)
                        if keys_resp.status_code == 200:
                            for k in keys_resp.json().get("data", []):
                                key_val = k.get("details", {}).get("api_key", "")
                                if key_val:
                                    api_key = key_val
                                    logger.info("oauth_callback: reusing existing LLM key")
                                    break
                    except Exception:
                        pass
                    if not api_key:
                        import uuid as _uuid
                        resp = httpx.post(
                            f"https://{cm_host}/credmgr/tokens/create_llm",
                            params={"key_name": f"loomai-{_uuid.uuid4().hex[:8]}",
                                    "comment": "Auto-created by LoomAI", "duration": 30},
                            headers=auth_headers, timeout=15,
                        )
                        resp.raise_for_status()
                        llm_data = resp.json().get("data", [{}])
                        if llm_data:
                            api_key = llm_data[0].get("details", {}).get("api_key", "")
                    if api_key:
                        settings = settings_manager.load_settings()
                        settings["ai"]["fabric_api_key"] = api_key
                        settings_manager.save_settings(settings)
                        settings_manager.apply_env_vars(settings)
                        logger.info("oauth_callback: LLM API key saved")
                except Exception as e:
                    logger.warning("oauth_callback: LLM key creation failed: %s", e)

            # Re-reset FABlib so it picks up the project + keys
            reset_fablib()
            notify_user_changed()

    except Exception as e:
        logger.warning("oauth_callback: inline setup error (non-fatal): %s", e, exc_info=True)

    # Redirect back to frontend with success indicator
    base_url = os.environ.get("WEBGUI_BASE_URL", "http://localhost:3000")
    return RedirectResponse(url=f"{base_url}/?configLogin=success")


@router.get("/api/config/callback")
def oauth_callback_get(id_token: str, refresh_token: str = ""):
    return _process_oauth_callback(id_token, refresh_token)


@router.post("/api/config/callback")
def oauth_callback_post(id_token: str = "", refresh_token: str = ""):
    """Accept token via POST (some CM flows use form submission)."""
    if not id_token:
        raise HTTPException(status_code=400, detail="Missing id_token")
    return _process_oauth_callback(id_token, refresh_token)


# ---------------------------------------------------------------------------
# GET /api/config/projects — decode JWT + query UIS for projects & bastion_login
# ---------------------------------------------------------------------------

@router.get("/api/config/projects")
async def get_projects():
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

    # Get bastion_login from UIS API (authoritative source), cached for 10 min
    bastion_login = ""
    user_uuid = payload.get("uuid", "")
    if user_uuid and id_token:
        try:
            from app.fabric_call_manager import get_call_manager
            cm = get_call_manager()
            data = await cm.get(
                f"uis:people:{user_uuid}",
                fetcher=lambda: _fetch_uis_person(id_token, user_uuid),
                max_age=600,
            )
            results = data.get("results", [])
            if results:
                bastion_login = results[0].get("bastion_login", "")
        except Exception as e:
            logger.warning("UIS bastion_login lookup failed: %s", e)

    if not bastion_login:
        # Fallback: derive from JWT (replace dots with underscores to match FABRIC convention)
        try:
            email = payload.get("email", "")
            sub = payload.get("sub", "")
            if email and sub:
                username = email.split("@")[0].replace(".", "_")
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

class AutoSetupRequest(BaseModel):
    project_id: str


@router.post("/api/config/auto-setup")
async def auto_setup(req: AutoSetupRequest):
    """One-call post-login setup: set project, derive bastion username, save config, generate keys."""
    token_data = _read_token()
    if not token_data or "id_token" not in token_data:
        raise HTTPException(status_code=400, detail="No token available. Login first.")

    id_token = token_data["id_token"]
    try:
        payload = _decode_jwt_payload(id_token)
    except Exception:
        raise HTTPException(status_code=400, detail="Could not decode token")

    user_email = payload.get("email", "")
    user_name = payload.get("name", "")
    user_uuid = payload.get("uuid", "")

    # Resolve bastion_username from UIS API (authoritative), with JWT fallback
    bastion_login = ""
    if user_uuid and id_token:
        try:
            from app.fabric_call_manager import get_call_manager
            cm = get_call_manager()
            data = await cm.get(
                f"uis:people:{user_uuid}",
                fetcher=lambda: _fetch_uis_person(id_token, user_uuid),
                max_age=600,
            )
            results = data.get("results", [])
            if results:
                bastion_login = results[0].get("bastion_login", "")
        except Exception as e:
            logger.warning("auto-setup: UIS bastion_login lookup failed: %s", e)

    if not bastion_login:
        try:
            email = payload.get("email", "")
            sub = payload.get("sub", "")
            if email and sub:
                username = email.split("@")[0].replace(".", "_")
                cilogon_id = sub.rstrip("/").rsplit("/", 1)[-1]
                if cilogon_id.isdigit():
                    bastion_login = f"{username}_{cilogon_id.zfill(10)}"
        except Exception:
            pass

    # Update settings with project_id and bastion_username, then save (generates fabric_rc + ssh_config)
    from app import settings_manager
    settings = settings_manager.load_settings()
    settings["fabric"]["project_id"] = req.project_id
    if bastion_login:
        settings["fabric"]["bastion_username"] = bastion_login
    settings_manager.save_settings(settings)
    settings_manager.apply_env_vars(settings)

    config_dir = _ensure_config_dir()
    core_api_host = settings.get("fabric", {}).get("hosts", {}).get("core_api", "uis.fabric-testbed.net")

    # Generate bastion key via Core API if none exist locally
    bastion_key_generated = False
    bastion_key_error = ""
    bastion_priv_path = os.path.join(config_dir, "fabric_bastion_key")
    bastion_pub_path = os.path.join(config_dir, "fabric_bastion_key.pub")
    if not os.path.isfile(bastion_priv_path):
        logger.info("auto-setup: bastion key not found at %s, requesting from Core API (%s)",
                     bastion_priv_path, core_api_host)
        try:
            resp = httpx.post(
                f"https://{core_api_host}/sshkeys",
                headers={
                    "Authorization": f"Bearer {id_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "keytype": "bastion",
                    "comment": f"loomai-bastion-{secrets.token_hex(4)}",
                    "description": "bastion-key-via-loomai",
                    "store_pubkey": True,
                },
                timeout=15,
            )
            logger.info("auto-setup: Core API /sshkeys responded %d", resp.status_code)
            if resp.status_code >= 400:
                body = resp.text[:500]
                logger.warning("auto-setup: Core API /sshkeys error body: %s", body)
                bastion_key_error = f"Core API returned {resp.status_code}: {body}"
            resp.raise_for_status()
            results = resp.json().get("results", [])
            if results:
                key_data = results[0]
                priv_content = key_data.get("private_openssh", "")
                pub_content = key_data.get("public_openssh", "")
                if priv_content:
                    with open(bastion_priv_path, "w") as f:
                        f.write(priv_content)
                    os.chmod(bastion_priv_path, stat.S_IRUSR | stat.S_IWUSR)
                    bastion_key_generated = True
                    logger.info("auto-setup: bastion private key written to %s", bastion_priv_path)
                else:
                    logger.warning("auto-setup: Core API returned result but no private_openssh key. Keys in response: %s",
                                   list(key_data.keys()))
                    bastion_key_error = "Core API response missing private_openssh"
                if pub_content:
                    with open(bastion_pub_path, "w") as f:
                        f.write(pub_content)
                    os.chmod(bastion_pub_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
            else:
                logger.warning("auto-setup: Core API /sshkeys returned empty results array. Full response: %s",
                               resp.text[:500])
                bastion_key_error = "Core API returned empty results"
        except Exception as e:
            logger.warning("auto-setup: bastion key generation failed: %s", e, exc_info=True)
            if not bastion_key_error:
                bastion_key_error = str(e)
    else:
        logger.info("auto-setup: bastion key already exists at %s", bastion_priv_path)

    # Generate slice keys if none exist
    slice_keys_generated = False
    _migrate_legacy_keys(config_dir)
    priv_path, pub_path = get_default_slice_key_path(config_dir)
    if not os.path.isfile(priv_path) or not os.path.isfile(pub_path):
        key = paramiko.RSAKey.generate(2048)
        key_dir = os.path.dirname(priv_path)
        os.makedirs(key_dir, exist_ok=True)
        key.write_private_key_file(priv_path)
        os.chmod(priv_path, stat.S_IRUSR | stat.S_IWUSR)
        pub_key_str = f"{key.get_name()} {key.get_base64()} fabric-webgui-generated"
        with open(pub_path, "w") as f:
            f.write(pub_key_str + "\n")
        os.chmod(pub_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
        # Register in keys.json
        data = _load_keys_json(config_dir)
        if "default" not in data.get("keys", []):
            data.setdefault("keys", []).append("default")
        _save_keys_json(config_dir, data)
        _sync_default_flat_copies(config_dir, "default")
        slice_keys_generated = True

    # Create FABRIC LLM API key via Credential Manager if none configured
    llm_key_created = False
    llm_key_error = ""
    existing_ai_key = settings_manager.get_fabric_api_key()
    if not existing_ai_key:
        try:
            cm_host = settings.get("fabric", {}).get("hosts", {}).get("credmgr", "cm.fabric-testbed.net")
            auth_headers = {"Authorization": f"Bearer {id_token}"}

            # Check for existing LLM keys first — reuse if one exists
            api_key = ""
            try:
                keys_resp = httpx.get(
                    f"https://{cm_host}/credmgr/tokens/llm_keys",
                    headers=auth_headers,
                    timeout=15,
                )
                if keys_resp.status_code == 200:
                    existing_keys = keys_resp.json().get("data", [])
                    for k in existing_keys:
                        details = k.get("details", {})
                        key_val = details.get("api_key", "")
                        if key_val:
                            api_key = key_val
                            logger.info("auto-setup: reusing existing FABRIC LLM key '%s'", details.get("key_name", ""))
                            break
            except Exception:
                pass  # Fall through to create

            # Create a new key if none found
            if not api_key:
                import uuid as _uuid
                key_name = f"loomai-{_uuid.uuid4().hex[:8]}"
                resp = httpx.post(
                    f"https://{cm_host}/credmgr/tokens/create_llm",
                    params={
                        "key_name": key_name,
                        "comment": "Auto-created by LoomAI login",
                        "duration": 30,
                    },
                    headers=auth_headers,
                    timeout=15,
                )
                resp.raise_for_status()
                llm_data = resp.json().get("data", [{}])
                if llm_data:
                    api_key = llm_data[0].get("details", {}).get("api_key", "")

            if api_key:
                # Persist the key in settings
                settings = settings_manager.load_settings()
                settings["ai"]["fabric_api_key"] = api_key
                settings_manager.save_settings(settings)
                settings_manager.apply_env_vars(settings)
                llm_key_created = True
                logger.info("auto-setup: FABRIC LLM API key saved")
        except Exception as e:
            llm_key_error = str(e)
            logger.warning("auto-setup: LLM key creation failed (non-fatal): %s", e)

    reset_fablib()

    # Refresh the token so it is scoped to the selected project.
    # The OAuth callback token may be scoped to a different project.
    try:
        fablib = get_fablib()
        mgr = fablib.get_manager()
        mgr.project_id = req.project_id
        refresh_token = mgr.get_refresh_token()
        if refresh_token:
            mgr.refresh_tokens(refresh_token=refresh_token)
            logger.info("auto-setup: token refreshed for project %s", req.project_id)
    except Exception as e:
        logger.warning("auto-setup: token refresh for project failed (non-fatal): %s", e)

    return {
        "status": "ok",
        "email": user_email,
        "name": user_name,
        "uuid": user_uuid,
        "project_id": req.project_id,
        "bastion_username": bastion_login,
        "bastion_key_generated": bastion_key_generated,
        "bastion_key_error": bastion_key_error,
        "slice_keys_generated": slice_keys_generated,
        "llm_key_created": llm_key_created,
        "llm_key_error": llm_key_error,
    }


# ---------------------------------------------------------------------------
# POST /api/config/llm-key — standalone LLM key creation
# ---------------------------------------------------------------------------

@router.post("/api/config/llm-key")
async def create_llm_key():
    """Create or retrieve a FABRIC LLM API key via Credential Manager."""
    token_data = _read_token()
    if not token_data or "id_token" not in token_data:
        raise HTTPException(status_code=401, detail="Not authenticated. Login first.")

    id_token = token_data["id_token"]
    try:
        payload = _decode_jwt_payload(id_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Could not decode token")

    # Check token expiry
    exp = payload.get("exp")
    if exp and time.time() > exp:
        raise HTTPException(status_code=401, detail="Token expired. Please re-login.")

    from app import settings_manager
    settings = settings_manager.load_settings()
    cm_host = settings.get("fabric", {}).get("hosts", {}).get("credmgr", "cm.fabric-testbed.net")
    auth_headers = {"Authorization": f"Bearer {id_token}"}

    try:
        # Check for existing LLM keys first
        api_key = ""
        try:
            keys_resp = httpx.get(
                f"https://{cm_host}/credmgr/tokens/llm_keys",
                headers=auth_headers,
                timeout=15,
            )
            if keys_resp.status_code == 200:
                existing_keys = keys_resp.json().get("data", [])
                for k in existing_keys:
                    details = k.get("details", {})
                    key_val = details.get("api_key", "")
                    if key_val:
                        api_key = key_val
                        logger.info("llm-key: reusing existing FABRIC LLM key '%s'", details.get("key_name", ""))
                        break
        except Exception:
            pass

        created = False
        if not api_key:
            import uuid as _uuid
            key_name = f"loomai-{_uuid.uuid4().hex[:8]}"
            resp = httpx.post(
                f"https://{cm_host}/credmgr/tokens/create_llm",
                params={
                    "key_name": key_name,
                    "comment": "Created by LoomAI settings",
                    "duration": 30,
                },
                headers=auth_headers,
                timeout=15,
            )
            resp.raise_for_status()
            llm_data = resp.json().get("data", [{}])
            if llm_data:
                api_key = llm_data[0].get("details", {}).get("api_key", "")
            created = True

        if api_key:
            settings = settings_manager.load_settings()
            settings["ai"]["fabric_api_key"] = api_key
            settings_manager.save_settings(settings)
            settings_manager.apply_env_vars(settings)
            return {"status": "ok", "created": created, "message": "FABRIC LLM key saved"}

        return {"status": "error", "created": False, "message": "No API key returned from Credential Manager"}
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=500, detail=f"Credential Manager error: {e.response.status_code}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM key creation failed: {e}")


# ---------------------------------------------------------------------------
# POST /api/config/logout — clear session
# ---------------------------------------------------------------------------

@router.post("/api/config/logout")
def logout():
    """Clear authentication tokens and reset session state."""
    config_dir = _config_dir()

    # Delete token files from all known locations
    token_paths = [
        os.path.join(config_dir, "id_token.json"),
        os.path.join(os.path.expanduser("~"), ".tokens.json"),
    ]
    # Also check settings-based token path (may differ in multi-user setups)
    try:
        from app.settings_manager import get_token_path as _get_tp
        settings_tp = _get_tp()
        if settings_tp not in token_paths:
            token_paths.append(settings_tp)
    except Exception:
        pass

    for tp in token_paths:
        try:
            if os.path.isfile(tp) or os.path.islink(tp):
                os.unlink(tp)
                logger.info("logout: removed %s", tp)
        except OSError as e:
            logger.warning("logout: failed to remove %s: %s", tp, e)

    # Reset FABlib singleton FIRST (this reloads fabric_rc and restores env vars)
    reset_fablib()

    # Clear stale env vars AFTER reset_fablib so they stay cleared
    # (reset_fablib reloads fabric_rc which restores them)
    for var in ("FABRIC_PROJECT_ID", "FABRIC_BASTION_USERNAME"):
        os.environ.pop(var, None)

    # Notify caches
    notify_user_changed()

    return {"status": "ok"}


@router.post("/api/config/keys/bastion/generate")
async def generate_bastion_key(force: bool = Query(False)):
    """Generate a new bastion SSH key pair via the FABRIC Core API."""
    token_data = _read_token()
    if not token_data or "id_token" not in token_data:
        raise HTTPException(status_code=401, detail="No token available. Login first.")

    id_token = token_data["id_token"]
    config_dir = _ensure_config_dir()
    bastion_priv_path = os.path.join(config_dir, "fabric_bastion_key")

    if not force and os.path.isfile(bastion_priv_path):
        return {"status": "exists", "generated": False}

    from app import settings_manager
    s = settings_manager.load_settings()
    core_api_host = s.get("fabric", {}).get("hosts", {}).get("core_api", "uis.fabric-testbed.net")

    try:
        resp = httpx.post(
            f"https://{core_api_host}/sshkeys",
            headers={"Authorization": f"Bearer {id_token}", "Content-Type": "application/json"},
            json={"keytype": "bastion", "comment": f"loomai-bastion-{secrets.token_hex(4)}",
                  "description": "bastion-key-via-loomai", "store_pubkey": True},
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if not results:
            raise HTTPException(status_code=502, detail="Core API returned empty results")
        priv = results[0].get("private_openssh", "")
        pub = results[0].get("public_openssh", "")
        if not priv:
            raise HTTPException(status_code=502, detail="Core API did not return a private key")
        with open(bastion_priv_path, "w") as f:
            f.write(priv)
        os.chmod(bastion_priv_path, stat.S_IRUSR | stat.S_IWUSR)
        if pub:
            pub_path = os.path.join(config_dir, "fabric_bastion_key.pub")
            with open(pub_path, "w") as f:
                f.write(pub)
            os.chmod(pub_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
        reset_fablib()
        return {"status": "ok", "generated": True}
    except httpx.HTTPStatusError as e:
        logger.warning("generate_bastion_key: Core API error: %s", e.response.text[:500])
        raise HTTPException(status_code=e.response.status_code, detail=f"Core API error: {e.response.text[:300]}")
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("generate_bastion_key: failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Key generation failed: {e}")


@router.post("/api/config/keys/bastion")
async def upload_bastion_key(file: UploadFile = File(...)):
    content = await file.read()
    d = _ensure_config_dir()
    path = os.path.join(d, "fabric_bastion_key")
    logger.info("Bastion key upload → %s (config_dir=%s)", path, d)
    with open(path, "wb") as f:
        f.write(content)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    reset_fablib()
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
    """Switch the active project: update settings, refresh token, reset FABlib."""
    try:
        fablib = get_fablib()
    except RuntimeError:
        raise HTTPException(status_code=400, detail="FABRIC is not configured yet.")

    # 1. Persist project_id to settings.json → regenerates fabric_rc with new PROJECT_ID
    from app import settings_manager
    settings = settings_manager.load_settings()
    settings["fabric"]["project_id"] = req.project_id
    settings_manager.save_settings(settings)
    settings_manager.apply_env_vars(settings)

    # 2. Attempt token refresh scoped to the new project
    token_refreshed = False
    try:
        mgr = fablib.get_manager()
        mgr.project_id = req.project_id
        refresh_token = mgr.get_refresh_token()
        if refresh_token:
            mgr.refresh_tokens(refresh_token=refresh_token)
            token_refreshed = True
            logger.info("switch_project: token refreshed for project %s", req.project_id)
    except Exception as e:
        logger.warning("switch_project: token refresh failed: %s", e)

    # 3. Reset FABlib singleton so it recreates with new project/token/env
    reset_fablib()
    notify_user_changed()

    result: dict = {"status": "ok", "project_id": req.project_id, "token_refreshed": token_refreshed}
    if not token_refreshed:
        # Token refresh failed — frontend should trigger OAuth re-login
        # scoped to the new project
        result["warning"] = (
            "Token could not be refreshed for the new project. "
            "Please re-login to get a project-scoped token."
        )
        result["needs_relogin"] = True
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
    if not os.path.isfile(get_token_path()):
        raise HTTPException(status_code=400, detail="Token is required before saving configuration")

    # Preserve existing keys if the fields are empty (user didn't change them)
    ai_key = req.litellm_api_key or _get_ai_api_key()
    nrp_key = req.nrp_api_key or _get_nrp_api_key()

    # Update settings.json (which also regenerates fabric_rc + ssh_config)
    from app import settings_manager
    settings = settings_manager.load_settings()

    settings["fabric"]["project_id"] = req.project_id
    settings["fabric"]["bastion_username"] = req.bastion_username
    settings["fabric"]["hosts"]["credmgr"] = req.credmgr_host
    settings["fabric"]["hosts"]["orchestrator"] = req.orchestrator_host
    settings["fabric"]["hosts"]["core_api"] = req.core_api_host
    settings["fabric"]["hosts"]["bastion"] = req.bastion_host
    settings["fabric"]["hosts"]["artifact_manager"] = req.am_host
    settings["fabric"]["logging"]["level"] = req.log_level
    settings["paths"]["log_file"] = req.log_file
    settings["fabric"]["avoid_sites"] = [s.strip() for s in req.avoid.split(",") if s.strip()] if req.avoid else []
    settings["fabric"]["ssh_command_line"] = req.ssh_command_line
    settings["ai"]["fabric_api_key"] = ai_key
    settings["ai"]["nrp_api_key"] = nrp_key

    settings_manager.save_settings(settings)
    settings_manager.apply_env_vars(settings)
    logger.info("save_config: config_dir=%s, bastion_key=%s",
                settings.get("paths", {}).get("config_dir", ""),
                settings.get("paths", {}).get("bastion_key_file", ""))

    # Reset FABlib so it picks up the new config
    reset_fablib()

    return {"status": "ok", "configured": is_configured()}


# ---------------------------------------------------------------------------
# POST /api/config/rebuild-storage — re-initialize storage layout
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
async def check_update():
    """Check Docker Hub for a newer version of the application image."""
    now = time.time()

    # Return cached result if still fresh
    if _update_cache["result"] and (now - _update_cache["timestamp"]) < _UPDATE_CACHE_TTL:
        return _update_cache["result"]

    current_parsed = _parse_semver(CURRENT_VERSION)

    try:
        resp = await fabric_client.get(
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

@router.get("/api/config/ai-tools")
def get_ai_tools() -> dict[str, bool]:
    """Return which AI companion tools are enabled."""
    from app.settings_manager import get_ai_tools
    return get_ai_tools()


@router.post("/api/config/ai-tools")
def set_ai_tools_endpoint(body: dict[str, bool]) -> dict[str, bool]:
    """Update AI companion tool toggles."""
    from app import settings_manager
    settings_manager.set_ai_tools(body)
    return settings_manager.get_ai_tools()


# ---------------------------------------------------------------------------
# GET /api/settings — full settings.json
# PUT /api/settings — replace settings
# ---------------------------------------------------------------------------

@router.get("/api/views/status")
def views_status():
    """Return which top-level views are enabled."""
    from app.settings_manager import is_chameleon_enabled
    from app.settings_manager import _get_settings
    views = _get_settings().get("views", {})
    return {
        "fabric_enabled": True,  # always on
        "chameleon_enabled": is_chameleon_enabled(),
        "composite_enabled": views.get("composite_enabled", False),
    }


@router.get("/api/settings")
def get_settings():
    """Return the full settings.json contents."""
    from app import settings_manager
    return settings_manager.load_settings()


@router.put("/api/settings")
def put_settings(body: dict, background_tasks: BackgroundTasks):
    """Replace settings, regenerate derived files, reset FABlib.

    Also triggers background propagation of AI config to all tool
    workspaces so changes to API keys and server URLs take effect
    without a container restart.
    """
    from app import settings_manager
    settings_manager.save_settings(body)
    settings_manager.apply_env_vars(body)
    reset_fablib()

    # Propagate AI config changes to all tool workspaces in the background
    from app.routes.ai_terminal import propagate_ai_configs
    background_tasks.add_task(propagate_ai_configs)

    return settings_manager.load_settings()


# ---------------------------------------------------------------------------
# Tool configuration management
# ---------------------------------------------------------------------------

@router.get("/api/config/tool-configs")
def get_tool_configs():
    """List per-tool config status."""
    from app import settings_manager
    return settings_manager.get_tool_config_status()


@router.post("/api/config/tool-configs/{tool}/reset")
def reset_tool_config(tool: str):
    """Reset a tool's config to Docker image defaults."""
    from app import settings_manager
    try:
        settings_manager.reset_tool_config(tool)
        return {"status": "ok", "tool": tool}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ---------------------------------------------------------------------------
# Claude Code config file management
# ---------------------------------------------------------------------------

_CLAUDE_EDITABLE_FILES = [
    "settings.json",
    "settings.local.json",
    "CLAUDE.md",
    ".mcp.json",
]


@router.get("/api/config/claude-code/files")
def get_claude_config_files():
    """List Claude Code config files in persistent storage with content."""
    from app import settings_manager
    backup_dir = settings_manager.get_tool_config_dir("claude-code")
    files = []
    for fname in _CLAUDE_EDITABLE_FILES:
        path = os.path.join(backup_dir, fname)
        if os.path.isfile(path):
            try:
                with open(path, "r") as f:
                    content = f.read()
                files.append({"name": fname, "content": content})
            except Exception:
                files.append({"name": fname, "content": ""})
        else:
            files.append({"name": fname, "content": None})
    # Include login status from .credentials.json
    creds_path = os.path.join(backup_dir, ".credentials.json")
    logged_in = False
    account_email = None
    if os.path.isfile(creds_path):
        try:
            with open(creds_path) as f:
                creds = json.load(f)
            logged_in = bool(creds.get("claudeAiOauth", {}).get("accessToken"))
        except Exception:
            pass
    claude_json_path = os.path.join(backup_dir, ".claude.json")
    if os.path.isfile(claude_json_path):
        try:
            with open(claude_json_path) as f:
                cj = json.load(f)
            account_email = cj.get("oauthAccount", {}).get("emailAddress")
        except Exception:
            pass
    return {"files": files, "logged_in": logged_in, "account_email": account_email}


class ClaudeConfigUpdate(BaseModel):
    content: str


@router.put("/api/config/claude-code/files/{filename:path}")
def update_claude_config_file(filename: str, body: ClaudeConfigUpdate):
    """Update a Claude Code config file in persistent storage."""
    if filename not in _CLAUDE_EDITABLE_FILES:
        raise HTTPException(status_code=400, detail=f"File '{filename}' is not editable")
    from app import settings_manager
    backup_dir = settings_manager.get_tool_config_dir("claude-code")
    path = os.path.join(backup_dir, filename)
    # Validate JSON files
    if filename.endswith(".json"):
        try:
            json.loads(body.content)
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")
    with open(path, "w") as f:
        f.write(body.content)
    return {"status": "ok", "filename": filename}


@router.post("/api/config/claude-code/backup")
def trigger_claude_backup():
    """Manually trigger a backup of Claude Code config from ~/.claude/ to persistent storage."""
    from app.routes.ai_terminal import _backup_claude_config
    _backup_claude_config()
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Multi-user management
# ---------------------------------------------------------------------------

def _auto_register_token_user(token_data: dict) -> None:
    """Decode JWT from token_data and register/update user in registry."""
    from app import user_registry

    id_token = token_data.get("id_token", "")
    if not id_token:
        return
    try:
        payload = _decode_jwt_payload(id_token)
        uuid = payload.get("uuid", "")
        name = payload.get("name", "")
        email = payload.get("email", "")
        if not uuid:
            return

        # Check if this is a different user than the current active
        current_active = user_registry.get_active_user_uuid()
        reg = user_registry.load_registry()

        if reg is not None:
            # Registry exists — register/update user and set as active
            user_registry.add_user(uuid, name, email)
            if current_active and current_active != uuid:
                user_registry.set_active_user(uuid)
                _do_user_switch(uuid)
        else:
            # No registry yet — if this is the first token, just register
            # The registry will be created but system stays in multi-user mode
            # only when there's a second user
            pass
    except Exception as e:
        logger.debug("Auto-register token user failed (non-fatal): %s", e)


def _do_user_switch(uuid: str) -> None:
    """Perform all side effects of switching to a different user."""
    from app import user_registry, settings_manager
    from app.user_context import notify_user_changed

    logger.info("User switch → %s", uuid)

    # Ensure user directory exists and update top-level symlinks
    user_registry.ensure_user_dir(uuid)
    _ensure_user_symlinks(uuid)

    # Invalidate settings cache so it reloads from the new user's dir
    settings_manager.invalidate_settings_cache()

    # Symlink ~/.tokens.json to the new user's token file
    user_dir = user_registry.get_user_storage_dir(uuid)
    if user_dir:
        token_src = os.path.join(user_dir, "fabric_config", "id_token.json")
        home_tokens = os.path.join(os.path.expanduser("~"), ".tokens.json")
        if os.path.isfile(token_src):
            try:
                if os.path.islink(home_tokens) or os.path.isfile(home_tokens):
                    os.unlink(home_tokens)
                os.symlink(token_src, home_tokens)
            except OSError as e:
                logger.warning("Failed to symlink ~/.tokens.json: %s", e)

    # Reload settings from the new user's scope and apply env vars
    settings = settings_manager.load_settings()

    # Persist settings for new users — generates fabric_rc + ssh_config
    # so the config dir is fully initialized before the user uploads keys
    config_dir = settings.get("paths", {}).get("config_dir", "")
    rc_path = os.path.join(config_dir, "fabric_rc") if config_dir else ""
    if config_dir and not os.path.isfile(rc_path):
        logger.info("User switch: generating initial config files in %s", config_dir)
        settings_manager.save_settings(settings)

    settings_manager.apply_env_vars(settings)
    logger.debug("User switch: FABRIC_CONFIG_DIR=%s, bastion_key=%s",
                 os.environ.get("FABRIC_CONFIG_DIR", ""),
                 settings.get("paths", {}).get("bastion_key_file", ""))

    # Notify all caches (resets FABlib, etc.)
    notify_user_changed()
    reset_fablib()


def _migrate_to_multi_user(first_uuid: str, first_name: str, first_email: str) -> None:
    """Migrate from flat single-user layout into users/{uuid}/ for the first user."""
    from app import user_registry
    import shutil as _shutil

    storage = os.environ.get("FABRIC_STORAGE_DIR", "/home/fabric/work")
    user_dir = os.path.join(storage, "users", first_uuid)

    if os.path.isdir(user_dir):
        logger.info("User dir %s already exists — skipping migration", user_dir)
        user_registry.add_user(first_uuid, first_name, first_email)
        return

    os.makedirs(user_dir, exist_ok=True)

    # Move user-specific directories from flat root to per-user dir
    dirs_to_move = [
        "fabric_config",
        "my_artifacts",
        "my_slices",
    ]
    for d in dirs_to_move:
        src = os.path.join(storage, d)
        dst = os.path.join(user_dir, d)
        if os.path.isdir(src) and not os.path.exists(dst):
            _shutil.copytree(src, dst)
            logger.info("Copied %s -> users/%s/%s", d, first_uuid, d)

    # Copy .loomai/settings.json if it exists
    src_settings = os.path.join(storage, ".loomai", "settings.json")
    dst_settings_dir = os.path.join(user_dir, ".loomai")
    if os.path.isfile(src_settings):
        os.makedirs(dst_settings_dir, exist_ok=True)
        _shutil.copy2(src_settings, os.path.join(dst_settings_dir, "settings.json"))

    # Register the first user and set up top-level symlinks
    user_registry.add_user(first_uuid, first_name, first_email)
    _ensure_user_symlinks(first_uuid)
    logger.info("Migrated flat layout to multi-user for %s (%s)", first_name, first_uuid)


@router.get("/api/users")
def list_users():
    """List registered users with active flag."""
    from app import user_registry

    users = user_registry.list_users()
    active = user_registry.get_active_user_uuid()

    return {
        "active_user": active,
        "users": [
            {**u, "is_active": u["uuid"] == active}
            for u in users
        ],
    }


class UserSwitchRequest(BaseModel):
    uuid: str


@router.post("/api/users/switch")
def switch_user(req: UserSwitchRequest):
    """Switch the active user."""
    from app import user_registry

    try:
        user_registry.set_active_user(req.uuid)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    _do_user_switch(req.uuid)

    return {"status": "ok", "active_user": req.uuid}


@router.delete("/api/users/{uuid}")
def delete_user(uuid: str, delete_data: bool = Query(False)):
    """Remove a user from the registry. Optionally delete their data."""
    from app import user_registry

    try:
        user_registry.remove_user(uuid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    if delete_data:
        user_dir = user_registry.get_user_storage_dir(uuid)
        if user_dir and os.path.isdir(user_dir):
            shutil.rmtree(user_dir)

    return {"status": "ok", "removed": uuid}


@router.post("/api/users/migrate-current")
def migrate_current_user():
    """Migrate flat single-user layout into multi-user layout.

    Reads the current token to identify the user, creates users/{uuid}/,
    and moves data there. This is called automatically when a second user
    token is detected, but can also be triggered manually.
    """
    from app import user_registry

    # Check if already in multi-user mode
    reg = user_registry.load_registry()
    if reg is not None and len(reg.get("users", [])) > 0:
        return {"status": "ok", "message": "Already in multi-user mode", "users": len(reg["users"])}

    # Read current token to get user identity
    token_data = _read_token()
    if not token_data or "id_token" not in token_data:
        raise HTTPException(status_code=400, detail="No token available. Upload a token first.")

    try:
        payload = _decode_jwt_payload(token_data["id_token"])
    except Exception:
        raise HTTPException(status_code=400, detail="Could not decode current token")

    uuid = payload.get("uuid", "")
    name = payload.get("name", "")
    email = payload.get("email", "")
    if not uuid:
        raise HTTPException(status_code=400, detail="Token does not contain a user UUID")

    _migrate_to_multi_user(uuid, name, email)
    _do_user_switch(uuid)

    return {"status": "ok", "message": f"Migrated to multi-user mode for {name}", "uuid": uuid}


# ---------------------------------------------------------------------------
# POST /api/settings/test/{setting_name} — validate individual settings
# POST /api/settings/test-all — validate all settings concurrently
# ---------------------------------------------------------------------------

async def _test_token() -> dict:
    """Check that the token file exists, is valid JSON with id_token, and not expired."""
    try:
        token_data = _read_token()
        if not token_data:
            return {"ok": False, "message": "Token file not found"}
        if "id_token" not in token_data:
            return {"ok": False, "message": "Token file missing 'id_token' field"}

        payload = _decode_jwt_payload(token_data["id_token"])
        exp = payload.get("exp")
        if not exp:
            return {"ok": False, "message": "Token has no expiration field"}

        from datetime import datetime, timezone
        expires_at = datetime.fromtimestamp(exp, tz=timezone.utc).isoformat()
        if time.time() > exp:
            return {"ok": False, "message": "Token is expired", "expires_at": expires_at}

        return {"ok": True, "message": "Token is valid", "expires_at": expires_at}
    except Exception as e:
        return {"ok": False, "message": f"Token check failed: {e}"}


async def _test_bastion_ssh() -> dict:
    """Test SSH connectivity to the FABRIC bastion host."""
    try:
        from app import settings_manager
        settings = settings_manager.load_settings()
        bastion_host = settings["fabric"]["hosts"].get("bastion", "bastion.fabric-testbed.net")
        bastion_username = settings["fabric"].get("bastion_username", "")
        bastion_key_path = settings["paths"].get("bastion_key_file", "")

        if not bastion_username:
            return {"ok": False, "message": "Bastion username not configured"}
        if not bastion_key_path or not os.path.isfile(bastion_key_path):
            return {"ok": False, "message": "Bastion SSH key not found"}

        import asyncio
        loop = asyncio.get_event_loop()

        def _do_ssh_test():
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            t0 = time.time()
            try:
                client.connect(
                    hostname=bastion_host,
                    username=bastion_username,
                    key_filename=bastion_key_path,
                    timeout=5,
                    look_for_keys=False,
                    allow_agent=False,
                )
                latency = int((time.time() - t0) * 1000)
                return {"ok": True, "message": f"Connected to {bastion_host}", "latency_ms": latency}
            except Exception as e:
                latency = int((time.time() - t0) * 1000)
                return {"ok": False, "message": f"SSH connection failed: {e}", "latency_ms": latency}
            finally:
                client.close()

        return await loop.run_in_executor(None, _do_ssh_test)
    except Exception as e:
        return {"ok": False, "message": f"Bastion SSH test failed: {e}"}


async def _test_fablib() -> dict:
    """Check if FABlib is configured and can be initialized."""
    try:
        if not is_configured():
            return {"ok": False, "message": "FABlib is not configured (missing token, keys, or config)"}

        try:
            fablib = get_fablib()
            if fablib is None:
                return {"ok": False, "message": "get_fablib() returned None"}
        except Exception as e:
            return {"ok": False, "message": f"FABlib initialization failed: {e}"}

        return {"ok": True, "message": "FABlib is configured and initialized"}
    except Exception as e:
        return {"ok": False, "message": f"FABlib check failed: {e}"}


async def _test_ai_server() -> dict:
    """Ping the FABRIC AI server and check /v1/models."""
    try:
        from app import settings_manager
        url = settings_manager.get_ai_server_url()
        api_key = settings_manager.get_fabric_api_key()

        if not url:
            return {"ok": False, "message": "AI server URL not configured"}

        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        t0 = time.time()
        resp = await fabric_client.get(
            f"{url}/v1/models",
            headers=headers,
            timeout=5,
        )
        latency = int((time.time() - t0) * 1000)

        if resp.status_code != 200:
            return {"ok": False, "message": f"AI server returned {resp.status_code}", "latency_ms": latency}

        data = resp.json()
        models = data.get("data", [])
        model_count = len(models)
        return {"ok": True, "message": f"AI server reachable ({model_count} models)", "latency_ms": latency, "model_count": model_count}
    except Exception as e:
        return {"ok": False, "message": f"AI server test failed: {e}"}


async def _test_nrp_server() -> dict:
    """Ping the NRP/Nautilus AI server and check /v1/models."""
    try:
        from app import settings_manager
        url = settings_manager.get_nrp_server_url()
        api_key = settings_manager.get_nrp_api_key()

        if not url:
            return {"ok": False, "message": "NRP server URL not configured"}

        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        t0 = time.time()
        resp = await fabric_client.get(
            f"{url}/v1/models",
            headers=headers,
            timeout=5,
        )
        latency = int((time.time() - t0) * 1000)

        if resp.status_code != 200:
            return {"ok": False, "message": f"NRP server returned {resp.status_code}", "latency_ms": latency}

        data = resp.json()
        models = data.get("data", [])
        model_count = len(models)
        return {"ok": True, "message": f"NRP server reachable ({model_count} models)", "latency_ms": latency, "model_count": model_count}
    except Exception as e:
        return {"ok": False, "message": f"NRP server test failed: {e}"}


async def _test_project() -> dict:
    """Validate the current project_id against the FABRIC Core API."""
    try:
        from app import settings_manager
        settings = settings_manager.load_settings()
        project_id = settings["fabric"].get("project_id", "")
        core_api_host = settings["fabric"]["hosts"].get("core_api", "uis.fabric-testbed.net")

        if not project_id:
            return {"ok": False, "message": "No project_id configured"}

        token_data = _read_token()
        if not token_data or "id_token" not in token_data:
            return {"ok": False, "message": "No token available to validate project"}

        id_token = token_data["id_token"]
        resp = await fabric_client.get(
            f"https://{core_api_host}/projects/{project_id}",
            headers={"Authorization": f"Bearer {id_token}"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        results = data.get("results", [data])
        proj = results[0] if results else data
        project_name = proj.get("name", "")

        return {"ok": True, "message": f"Project '{project_name}' is valid", "project_name": project_name}
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {"ok": False, "message": f"Project {project_id} not found"}
        return {"ok": False, "message": f"Core API error: {e.response.status_code}"}
    except Exception as e:
        return {"ok": False, "message": f"Project validation failed: {e}"}


_SETTING_TESTS = {
    "token": _test_token,
    "bastion_ssh": _test_bastion_ssh,
    "fablib": _test_fablib,
    "ai_server": _test_ai_server,
    "nrp_server": _test_nrp_server,
    "project": _test_project,
}


@router.post("/api/settings/test/{setting_name}")
async def test_setting(setting_name: str):
    """Test an individual setting for validity."""
    test_fn = _SETTING_TESTS.get(setting_name)
    if not test_fn:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown setting '{setting_name}'. Valid: {', '.join(_SETTING_TESTS.keys())}",
        )
    return await test_fn()


@router.post("/api/settings/test-all")
async def test_all_settings():
    """Run all setting tests concurrently and return results."""
    import asyncio
    tasks = {name: fn() for name, fn in _SETTING_TESTS.items()}
    results_list = await asyncio.gather(*tasks.values(), return_exceptions=True)
    results = {}
    for name, result in zip(tasks.keys(), results_list):
        if isinstance(result, Exception):
            results[name] = {"ok": False, "message": f"Test threw exception: {result}"}
        else:
            results[name] = result
    return results
