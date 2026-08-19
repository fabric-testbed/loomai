"""Structured error envelope helpers shared by LoomAI route families.

FC17-3 shipped the pattern in the tunnels routes; FC18-2 extends it to the
remaining route families (templates/weave-runs, artifacts, recipes,
files/boot-config, jupyter). Error responses use::

    {"error": "<STABLE_CODE>", "detail": "<actionable text>", ...extra}

as the ``HTTPException.detail`` value. ``safe_error_detail`` redacts obvious
local paths and secret assignments from exception-derived text while keeping
the actionable front of the message.
"""
from __future__ import annotations

import re

_SECRET_VALUE_RE = re.compile(
    r"(?i)\b(token|secret|password|api[_-]?key|bearer)\b\s*[:=]\s*['\"]?[^\s'\";,]+"
)
_PATH_RE = re.compile(r"(?<!\w)/(?:home|tmp|var|app|workspace)[^\s,;)\]}\"']*")


def safe_error_detail(exc: Exception | str) -> str:
    """Return sanitized single-line text from an exception or message."""
    text = str(exc).strip() or (exc.__class__.__name__ if isinstance(exc, Exception) else "")
    text = _SECRET_VALUE_RE.sub(lambda match: f"{match.group(1)}=[redacted]", text)
    text = _PATH_RE.sub("[path]", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 500:
        text = f"{text[:497].rstrip()}..."
    return text


def error_detail(error: str, detail: str, **extra) -> dict:
    """Build a structured error envelope for ``HTTPException.detail``."""
    return {"error": error, "detail": detail, **extra}
