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
        _BASE_STORAGE = os.environ.get("FABRIC_STORAGE_DIR", "/home/fabric/work")
    return _BASE_STORAGE


# ---------------------------------------------------------------------------
# Token file resolution
# ---------------------------------------------------------------------------

def get_token_path() -> str:
    """Return the path to the FABRIC id_token JSON file.

    Resolution order:
    1. ``FABRIC_TOKEN_FILE`` env var (explicit override)
    2. ``~/.tokens.json`` if it exists (JupyterHub convention)
    3. ``{FABRIC_CONFIG_DIR}/id_token.json`` (legacy / FABlib default)
    """
    explicit = os.environ.get("FABRIC_TOKEN_FILE")
    if explicit:
        return explicit

    home_tokens = os.path.join(os.path.expanduser("~"), ".tokens.json")
    if os.path.isfile(home_tokens):
        return home_tokens

    config_dir = os.environ.get(
        "FABRIC_CONFIG_DIR",
        os.path.join(_base_storage(), "fabric_config"),
    )
    return os.path.join(config_dir, "id_token.json")


# ---------------------------------------------------------------------------
# Local artifacts directory
# ---------------------------------------------------------------------------

def get_artifacts_dir() -> str:
    """Return the local artifacts directory.

    All artifact types (weaves, VM templates, recipes, notebooks) are stored
    in ``{FABRIC_STORAGE_DIR}/my_artifacts/``.
    """
    d = os.path.join(_base_storage(), "my_artifacts")
    os.makedirs(d, exist_ok=True)
    return d


def get_slices_dir() -> str:
    """Return the slices directory for drafts and registry.

    Drafts and the slice registry are stored in:
    ``{FABRIC_STORAGE_DIR}/my_slices/``.
    """
    d = os.path.join(_base_storage(), "my_slices")
    os.makedirs(d, exist_ok=True)
    return d


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
