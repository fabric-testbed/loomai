"""Short-lived, single-use attach tickets for terminal WebSockets.

The terminal data-plane WebSocket (`/ws/terminal/attach/{id}`) bypasses the
HTTP `AuthMiddleware` (Starlette `BaseHTTPMiddleware` does not run for the
websocket scope). To authenticate it without a cookie round-trip we mint a
ticket from the *authenticated* `POST /api/terminals` HTTP endpoint and verify
it in the websocket handler before `accept()`.

A ticket is bound to a single session id, expires in ~60s, and is single-use
(nonce tracked in-process). It is signed with the persistent server secret
(`auth.get_server_secret`) so it stays valid across a backend restart — which
matters because the underlying tmux session survives the restart too.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time

from urllib.parse import urlsplit

from app import auth as _auth
from app.auth import get_server_secret

# Same defaults as main.py's CORS allowlist; CORS_ORIGINS overrides both.
_DEFAULT_ORIGINS = ("http://localhost:3000", "http://localhost:5173", "https://cm.fabric-testbed.net")


def _allowed_origins() -> frozenset[str]:
    env = os.environ.get("CORS_ORIGINS", "")
    if env:
        return frozenset(o.strip().rstrip("/").lower() for o in env.split(",") if o.strip())
    return frozenset(o.lower() for o in _DEFAULT_ORIGINS)


def origin_allowed(headers) -> bool:
    """Reject a WebSocket handshake from a foreign page.

    Browsers always send ``Origin`` on WebSocket upgrades and the
    ``loomai_session`` cookie rides along (SameSite=Lax does not cover
    WebSockets), so without this any site could open a terminal shell in the
    user's container. Same-origin (``Origin`` host == ``Host``) or a CORS
    allowlist entry passes; a missing ``Origin`` (non-browser client, which
    still needs the cookie or a ticket) passes. Applied in every auth mode.
    """
    origin = (headers.get("origin") or "").strip()
    if not origin:
        return True
    parts = urlsplit(origin)
    host = (headers.get("host") or "").strip().lower()
    if parts.netloc and host and parts.netloc.lower() == host:
        return True
    return origin.rstrip("/").lower() in _allowed_origins()

# Default lifetime of an attach ticket, in seconds.
TICKET_TTL = 60

# Used nonces -> expiry epoch. Pruned lazily on each verify. Single-process,
# single-user container, so an in-memory set is sufficient.
_used_nonces: dict[str, int] = {}


def _prune(now: int) -> None:
    if len(_used_nonces) < 256:
        # Cheap path: only prune when the map grows.
        expired = [n for n, exp in _used_nonces.items() if exp < now]
    else:
        expired = [n for n, exp in _used_nonces.items() if exp < now]
    for n in expired:
        _used_nonces.pop(n, None)


def _sign(payload: str) -> str:
    return hmac.new(get_server_secret(), payload.encode(), hashlib.sha256).hexdigest()


def mint_ticket(session_id: str, ttl: int = TICKET_TTL) -> str:
    """Return a signed, single-use ticket bound to *session_id*.

    Format: ``<session_id>.<exp>.<nonce>.<sig>`` where ``sig`` covers the first
    three fields. ``session_id`` must not contain ``.``.
    """
    if "." in session_id:
        raise ValueError("session_id must not contain '.'")
    exp = int(time.time()) + max(1, int(ttl))
    nonce = os.urandom(12).hex()
    payload = f"{session_id}.{exp}.{nonce}"
    return f"{payload}.{_sign(payload)}"


def verify_ticket(token: str, session_id: str) -> bool:
    """Return True if *token* is a valid, unexpired, unused ticket for *session_id*.

    Marks the nonce as used on success so the ticket cannot be replayed.
    """
    if not token:
        return False
    try:
        sid, exp_str, nonce, sig = token.split(".", 3)
        exp = int(exp_str)
    except (ValueError, AttributeError):
        return False

    # Constant-time signature check first.
    payload = f"{sid}.{exp_str}.{nonce}"
    if not hmac.compare_digest(sig, _sign(payload)):
        return False

    # Binding + freshness.
    if not hmac.compare_digest(sid, session_id):
        return False
    now = int(time.time())
    if exp < now:
        return False

    # Single-use.
    _prune(now)
    if nonce in _used_nonces:
        return False
    _used_nonces[nonce] = exp
    return True


def ws_authorized(websocket, session_id: str = "", ticket: str = "") -> bool:
    """Authorize a terminal WebSocket before ``accept()``.

    WebSocket handshakes bypass the HTTP ``AuthMiddleware`` (Starlette
    ``BaseHTTPMiddleware`` runs only for the http scope), so every terminal
    socket must call this first. Accepts a valid single-use attach *ticket*
    (bound to *session_id*) or the same-origin ``loomai_session`` cookie. When
    auth is disabled (dev / K8s-hub mode) it is a no-op pass.
    """
    if not origin_allowed(websocket.headers):
        return False
    if not _auth.is_auth_enabled():
        return True
    if ticket and verify_ticket(ticket, session_id):
        return True
    cookie = websocket.cookies.get(_auth._COOKIE_NAME)
    return bool(cookie and _auth._validate_session_token(cookie))
