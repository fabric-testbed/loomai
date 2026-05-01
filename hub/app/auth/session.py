"""Signed cookie session management using itsdangerous."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from fastapi import Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import settings

logger = logging.getLogger(__name__)

COOKIE_NAME = "loomai-hub-session"

_serializer: URLSafeTimedSerializer | None = None


def _get_serializer() -> URLSafeTimedSerializer:
    """Lazy-init the serializer so settings are fully loaded."""
    global _serializer
    if _serializer is None:
        _serializer = URLSafeTimedSerializer(settings.cookie_secret_bytes)
    return _serializer


def create_session_cookie(username: str, extra: dict[str, Any] | None = None) -> str:
    """Create a signed session cookie value.

    Args:
        username: The hub username (FABRIC UUID).
        extra: Optional extra claims to embed in the session.

    Returns:
        Signed cookie string.
    """
    payload: dict[str, Any] = {"username": username, "ts": int(time.time())}
    if extra:
        payload.update(extra)
    return _get_serializer().dumps(payload)


def validate_session_cookie(cookie: str) -> dict[str, Any] | None:
    """Validate and decode a session cookie.

    Args:
        cookie: The signed cookie string.

    Returns:
        Decoded session dict, or None if invalid/expired.
    """
    try:
        data = _get_serializer().loads(cookie, max_age=settings.COOKIE_MAX_AGE)
        return data
    except SignatureExpired:
        logger.debug("Session cookie expired")
        return None
    except BadSignature:
        logger.warning("Invalid session cookie signature")
        return None
    except Exception:
        logger.exception("Unexpected error validating session cookie")
        return None


def get_current_user(request: Request) -> dict[str, Any] | None:
    """Extract and validate the session from a request.

    This is intended as a FastAPI dependency.

    Args:
        request: The incoming FastAPI request.

    Returns:
        Session dict with at least 'username', or None if not authenticated.
    """
    cookie = request.cookies.get(COOKIE_NAME)
    if not cookie:
        return None
    return validate_session_cookie(cookie)
