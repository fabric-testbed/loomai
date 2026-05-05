"""Tracking headers injected into outgoing HTTP requests.

Provides X-LoomAI-Version, X-LoomAI-User, and X-LoomAI-IP headers
for usage tracking and misuse detection on API server side.
"""

from __future__ import annotations

import logging
import threading
import urllib.request

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_cache: dict[str, str] | None = None


def _resolve_public_ip() -> str:
    """Fetch public IP once (best-effort, non-blocking on failure)."""
    for url in ("https://checkip.amazonaws.com", "https://api.ipify.org"):
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                return resp.read().decode().strip()
        except Exception:
            continue
    return "unknown"


def _build_cache() -> dict[str, str]:
    """Build the header dict (called once, then cached)."""
    from app.routes.config import CURRENT_VERSION

    try:
        from app import settings_manager
        user = settings_manager.get_bastion_username() or "unknown"
    except Exception:
        user = "unknown"

    ip = _resolve_public_ip()

    headers = {
        "X-LoomAI-Version": CURRENT_VERSION,
        "X-LoomAI-User": user,
        "X-LoomAI-IP": ip,
    }
    logger.info(
        "Tracking headers initialized: version=%s, user=%s, ip=%s",
        CURRENT_VERSION, user, ip,
    )
    return headers


def get_tracking_headers() -> dict[str, str]:
    """Return cached tracking headers, building them lazily on first call."""
    global _cache
    if _cache is not None:
        return _cache
    with _lock:
        if _cache is not None:
            return _cache
        _cache = _build_cache()
        return _cache


def invalidate_cache() -> None:
    """Clear cached headers so they are rebuilt on next access.

    Call after login, config change, or user switch so the
    X-LoomAI-User header picks up the new identity.
    """
    global _cache
    with _lock:
        _cache = None
    logger.debug("Tracking headers cache invalidated")


def add_tracking_headers(headers: dict[str, str]) -> dict[str, str]:
    """Merge tracking headers into an existing headers dict.

    Useful for urllib.request.Request calls where headers are a plain dict.
    """
    headers.update(get_tracking_headers())
    return headers
