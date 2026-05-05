"""Tracking headers for LoomAI Hub outgoing HTTP requests.

Simpler than the backend module — Hub always identifies as hub-0.1.0
and passes user identity from session context.
"""

from __future__ import annotations

_HUB_VERSION = "hub-0.1.0"


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
