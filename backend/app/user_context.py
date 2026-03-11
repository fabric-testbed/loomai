"""Storage and context management.

Single-user layout — everything lives directly under FABRIC_STORAGE_DIR::

    /home/fabric/work/              # FABRIC_STORAGE_DIR (Docker volume)
        fabric_config/              # FABRIC_CONFIG_DIR
            fabric_rc
            fabric_bastion_key[.pub]
            ssh_config
            slice_keys/
            id_token.json           # FABlib-compat copy of ~/.tokens.json
        my_artifacts/               # local artifacts (weaves, templates, recipes, notebooks)
        my_slices/                  # drafts and slice registry
        notebooks/                  # JupyterLab notebook workspaces
        .artifact-originals/        # pristine copies keyed by UUID
        .boot_info/                 # template deployment metadata
        .monitoring/                # slice monitoring state
        .slice-keys/                # per-slice SSH key assignments
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
# User storage — returns base storage (single-user)
# ---------------------------------------------------------------------------

def get_user_storage() -> str:
    """Return the storage directory.

    Always returns ``FABRIC_STORAGE_DIR`` — this is a single-user container.
    """
    d = _base_storage()
    os.makedirs(d, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# User-changed notification (kept for API compatibility)
# ---------------------------------------------------------------------------

_on_user_changed_callbacks: list[Callable[[], None]] = []


def register_user_changed_callback(cb: Callable[[], None]) -> None:
    """Register a callback invoked when the active user changes."""
    _on_user_changed_callbacks.append(cb)


def notify_user_changed() -> None:
    """Call when the token changes to invalidate caches."""
    logger.info("Token changed — notifying callbacks")
    for cb in _on_user_changed_callbacks:
        try:
            cb()
        except Exception as e:
            logger.warning("User-changed callback error: %s", e)
