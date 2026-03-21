"""Storage and context management.

Supports both single-user (legacy) and multi-user layouts::

    Legacy (no user_registry.json):
        /home/fabric/work/              # FABRIC_STORAGE_DIR
            fabric_config/
            my_artifacts/
            my_slices/
            ...

    Multi-user (user_registry.json present):
        /home/fabric/work/
            .loomai/user_registry.json
            users/<uuid>/
                fabric_config/
                my_artifacts/
                my_slices/
                .loomai/settings.json
                ...
"""

from __future__ import annotations

import logging
import os
from typing import Callable

logger = logging.getLogger(__name__)

_BASE_STORAGE: str | None = None

# ---------------------------------------------------------------------------
# Base storage
# ---------------------------------------------------------------------------

def _base_storage() -> str:
    global _BASE_STORAGE
    if _BASE_STORAGE is None:
        from app.settings_manager import get_storage_dir
        _BASE_STORAGE = get_storage_dir()
    return _BASE_STORAGE


def _invalidate_base_storage() -> None:
    """Clear the cached base storage path (called on user switch)."""
    global _BASE_STORAGE
    _BASE_STORAGE = None


# ---------------------------------------------------------------------------
# Token file resolution
# ---------------------------------------------------------------------------

def get_token_path() -> str:
    """Return the path to the FABRIC id_token JSON file.

    Delegates to ``settings_manager.get_token_path()`` which preserves
    the same resolution order: FABRIC_TOKEN_FILE env → ~/.tokens.json →
    settings-based config_dir/id_token.json.
    """
    from app.settings_manager import get_token_path as _get
    return _get()


# ---------------------------------------------------------------------------
# Local artifacts directory
# ---------------------------------------------------------------------------

def get_artifacts_dir() -> str:
    """Return the local artifacts directory — delegates to settings_manager."""
    from app.settings_manager import get_artifacts_dir as _get
    return _get()


def get_slices_dir() -> str:
    """Return the slices directory for drafts and registry — delegates to settings_manager."""
    from app.settings_manager import get_slices_dir as _get
    return _get()


# ---------------------------------------------------------------------------
# User storage — multi-user aware
# ---------------------------------------------------------------------------

def get_user_storage() -> str:
    """Return the effective storage directory.

    If a user registry exists and an active user is set, returns the
    per-user directory ``users/{uuid}/``. Otherwise returns the flat
    ``FABRIC_STORAGE_DIR`` root (legacy single-user mode).
    """
    from app.user_registry import get_user_storage_dir
    user_dir = get_user_storage_dir()
    if user_dir is not None:
        os.makedirs(user_dir, exist_ok=True)
        return user_dir
    d = _base_storage()
    os.makedirs(d, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# User-changed notification
# ---------------------------------------------------------------------------

_on_user_changed_callbacks: list[Callable[[], None]] = []


def register_user_changed_callback(cb: Callable[[], None]) -> None:
    """Register a callback invoked when the active user changes."""
    _on_user_changed_callbacks.append(cb)


def notify_user_changed() -> None:
    """Call when the token/user changes to invalidate caches."""
    logger.info("User/token changed — notifying callbacks")
    _invalidate_base_storage()
    for cb in _on_user_changed_callbacks:
        try:
            cb()
        except Exception as e:
            logger.warning("User-changed callback error: %s", e)
