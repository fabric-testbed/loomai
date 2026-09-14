"""Tracking headers for LoomAI Hub outgoing HTTP requests.

Simpler than the backend module — Hub identifies itself by version and
passes user identity from session context.
"""

from __future__ import annotations

from app import __version__

_HUB_VERSION = f"hub-{__version__}"


def get_tracking_headers(username: str = "") -> dict[str, str]:
    """Return tracking headers for Hub requests.

    Args:
        username: The FABRIC username from session context (optional).
    """
    return {
        "X-LoomAI-Version": _HUB_VERSION,
        "X-LoomAI-Source": "loomai-hub",
        "X-LoomAI-User": username or "unknown",
    }
