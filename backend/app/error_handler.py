"""Centralized error handler middleware for the FastAPI application."""

from __future__ import annotations

import logging
import re

from fastapi import FastAPI
from fastapi.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

_SENSITIVE_PATTERNS = re.compile(
    r"/home/|Traceback|paramiko|ssh|password|token|secret",
    re.IGNORECASE,
)
_SECRET_VALUE_RE = re.compile(
    r"(?i)\b(token|secret|password|api[_-]?key|bearer)\b\s*[:=]\s*['\"]?[^\s'\";,]+"
)
_BEARER_VALUE_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/\-=]+")
_PATH_RE = re.compile(r"(?<!\w)/(?:home|tmp|var|app|workspace)[^\s,;)\]}\"']*")

_GENERIC_500_MESSAGE = "An internal error occurred. Check server logs for details."
_MAX_SAFE_DETAIL_CHARS = 240


def _sanitize_500_detail(detail: str) -> str:
    """Redact local paths/secrets and keep the useful front of 500 details."""
    raw = str(detail or "").strip()
    if not raw:
        return _GENERIC_500_MESSAGE
    lines: list[str] = []
    for line in raw.splitlines():
        item = line.strip()
        if not item:
            continue
        if item.startswith(("Traceback ", "File ", "raise ")):
            continue
        lines.append(item)
    text = " ".join(lines or [raw])
    text = _SECRET_VALUE_RE.sub(lambda match: f"{match.group(1)}=[redacted]", text)
    text = _BEARER_VALUE_RE.sub("Bearer [redacted]", text)
    text = _PATH_RE.sub("[path]", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return _GENERIC_500_MESSAGE
    if len(text) > _MAX_SAFE_DETAIL_CHARS:
        text = f"{text[:_MAX_SAFE_DETAIL_CHARS - 3].rstrip()}..."
    return text


def _sanitize_structured_500_detail(value):
    """Recursively preserve structured 500 details while sanitizing strings."""
    if isinstance(value, dict):
        return {key: _sanitize_structured_500_detail(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_structured_500_detail(item) for item in value]
    if isinstance(value, str):
        if _SENSITIVE_PATTERNS.search(value) or len(value) > 200:
            return _sanitize_500_detail(value)
        return value
    return value


def install_error_handlers(app: FastAPI) -> None:
    """Register exception handlers that sanitise 500 details and catch unhandled errors."""

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        if exc.status_code == 500:
            detail = exc.detail
            logger.error("HTTP 500 for %s %s: %s", request.method, request.url.path, detail)
            if isinstance(detail, (dict, list)):
                detail = _sanitize_structured_500_detail(detail)
            else:
                detail = str(detail)
                if _SENSITIVE_PATTERNS.search(detail) or len(detail) > 200:
                    detail = _sanitize_500_detail(detail)
            return JSONResponse(status_code=500, content={"detail": detail})
        # Non-500 HTTPExceptions pass through unchanged
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception for %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": _GENERIC_500_MESSAGE},
        )
