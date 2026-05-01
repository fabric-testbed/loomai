"""Standalone Docker password authentication.

Provides session-cookie auth for standalone Docker deployments.
Disabled in K8s mode (LOOMAI_BASE_PATH set) and dev mode (LOOMAI_NO_AUTH=1).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time

import bcrypt
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Session cookie config
_COOKIE_NAME = "loomai_session"
_SESSION_MAX_AGE = 7 * 24 * 3600  # 7 days


# ---------------------------------------------------------------------------
# Mode detection
# ---------------------------------------------------------------------------

def is_auth_enabled() -> bool:
    """Return True if password auth should be enforced."""
    # K8s mode — Hub handles auth
    if os.environ.get("LOOMAI_BASE_PATH"):
        return False
    # Explicit opt-out
    if os.environ.get("LOOMAI_NO_AUTH", "").strip() == "1":
        return False
    # Standalone mode flag set by entrypoint.sh
    return os.environ.get("LOOMAI_AUTH_ENABLED", "").strip() == "1"


# ---------------------------------------------------------------------------
# Password hash storage
# ---------------------------------------------------------------------------

def _hash_file_path() -> str:
    storage = os.environ.get("FABRIC_STORAGE_DIR", "/home/fabric/work")
    return os.path.join(storage, ".loomai", "password_hash")


def _get_password_hash() -> bytes | None:
    path = _hash_file_path()
    try:
        with open(path, "rb") as f:
            return f.read().strip()
    except FileNotFoundError:
        return None


def write_password_hash(password: str) -> None:
    """Hash *password* with bcrypt and persist to disk."""
    path = _hash_file_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
    with open(path, "wb") as f:
        f.write(hashed)
    os.chmod(path, 0o600)


def verify_password(password: str) -> bool:
    stored = _get_password_hash()
    if not stored:
        return False
    try:
        return bcrypt.checkpw(password.encode(), stored)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Stateless session tokens (HMAC-signed timestamp)
# ---------------------------------------------------------------------------

_session_secret: bytes | None = None


def _get_session_secret() -> bytes:
    """Return a per-process secret (regenerated on container restart)."""
    global _session_secret  # noqa: PLW0603
    if _session_secret is None:
        _session_secret = os.urandom(32)
    return _session_secret


def _make_session_token() -> str:
    ts = str(int(time.time()))
    sig = hmac.new(_get_session_secret(), ts.encode(), hashlib.sha256).hexdigest()
    return f"{ts}.{sig}"


def _validate_session_token(token: str) -> bool:
    try:
        ts_str, sig = token.split(".", 1)
        ts = int(ts_str)
    except (ValueError, AttributeError):
        return False
    if time.time() - ts > _SESSION_MAX_AGE:
        return False
    expected = hmac.new(_get_session_secret(), ts_str.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/status")
def auth_status():
    """Tell the frontend whether auth is enabled."""
    return {"auth_enabled": is_auth_enabled()}


@router.post("/login")
async def auth_login(request: Request):
    """Validate password and set session cookie."""
    body = await request.json()
    password = body.get("password", "")

    if not verify_password(password):
        return JSONResponse({"error": "Invalid password"}, status_code=401)

    token = _make_session_token()
    resp = JSONResponse({"ok": True})
    resp.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=_SESSION_MAX_AGE,
        path="/",
    )
    return resp


@router.post("/logout")
def auth_logout():
    """Clear session cookie."""
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(key=_COOKIE_NAME, path="/")
    return resp


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

# Paths that never require auth
_PUBLIC_PATHS = frozenset({
    "/api/auth/login",
    "/api/auth/status",
    "/api/auth/logout",
    "/api/health",
})


class AuthMiddleware(BaseHTTPMiddleware):
    """Check session cookie on every request when auth is enabled."""

    async def dispatch(self, request: Request, call_next):
        if not is_auth_enabled():
            return await call_next(request)

        path = request.url.path

        # Allow public paths
        if path in _PUBLIC_PATHS:
            return await call_next(request)

        # Allow static files (frontend assets)
        if not path.startswith("/api/") and not path.startswith("/ws/"):
            return await call_next(request)

        # Check session cookie
        token = request.cookies.get(_COOKIE_NAME)
        if token and _validate_session_token(token):
            return await call_next(request)

        return JSONResponse(
            {"detail": "Authentication required"},
            status_code=401,
        )
