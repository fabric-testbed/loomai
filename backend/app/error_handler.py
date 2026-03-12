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

_GENERIC_500_MESSAGE = "An internal error occurred. Check server logs for details."


def install_error_handlers(app: FastAPI) -> None:
    """Register exception handlers that sanitise 500 details and catch unhandled errors."""

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        if exc.status_code == 500:
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            logger.error("HTTP 500 for %s %s: %s", request.method, request.url.path, detail)
            if _SENSITIVE_PATTERNS.search(detail) or len(detail) > 200:
                detail = _GENERIC_500_MESSAGE
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
