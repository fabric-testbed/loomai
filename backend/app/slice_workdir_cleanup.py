"""One-time cleanup of the retired per-slice working directories.

LoomAI used to create ``{storage}/<slice_name>/`` for every slice (on create
and on every view) as a JupyterLab scratch folder, seeded with weave files
when a slice was loaded from a weave, and renamed to ``<name>-<uuid>`` when the
slice died. Nothing read them and most stayed empty, so the feature was removed.

On the first startup after that change, each folder in the storage root whose
name matches a known slice (``<name>`` or ``<name>-<uuid>``) is:

- deleted when it holds only empty directories (checked fail-closed and
  removed with ``rmdir``, never ``rmtree``), or
- moved to ``{storage}/archived_slice_folders/`` otherwise, so no user file is
  ever deleted.

Matching only registry slice names, skipping reserved and dot-prefixed names
and symlinks, and running once (marker file) keeps unrelated folders safe —
including one a user creates later that happens to share a slice name.
"""

from __future__ import annotations

import glob
import json
import logging
import os
import shutil

logger = logging.getLogger(__name__)

ARCHIVE_DIR_NAME = "archived_slice_folders"
_MARKER = os.path.join(".loomai", "migrations", "slice_workdirs_removed")

# Top-level entries LoomAI or its tools own; never treated as slice folders
# even when a slice shares the name.
_RESERVED = {
    ARCHIVE_DIR_NAME, "fabric_config", "my_artifacts", "my_slices", "notebooks",
    "users", "work", "lost+found",
    # AI-tool workspaces seeded into the storage root.
    "aider", "antigravity", "claude", "codex", "crush", "deepagents", "goose",
    "opencode", "pi", "agents", "skills", "home",
}


def _registry_slices(storage: str) -> set[str]:
    """Return every slice folder name the registries know: name and name-uuid."""
    paths = [os.path.join(storage, "my_slices", "registry.json")]
    for pattern in (
        os.path.join(storage, ".loomai", "users", "*", "my_slices", "registry.json"),
        os.path.join(storage, "users", "*", "my_slices", "registry.json"),
    ):
        paths.extend(glob.glob(pattern))
    names: set[str] = set()
    for path in paths:
        try:
            with open(path) as f:
                slices = (json.load(f) or {}).get("slices", {}) or {}
        except (OSError, ValueError):
            continue
        for key, entry in slices.items():
            entry = entry if isinstance(entry, dict) else {}
            name = entry.get("name") or key
            if not name:
                continue
            names.add(name)
            uuid = entry.get("uuid") or ""
            if uuid and not uuid.startswith("draft-"):
                names.add(f"{name}-{uuid}")
    return names


def _empty_dirs_bottom_up(path: str) -> list[str] | None:
    """Return every directory under *path* (deepest first) if the tree holds
    nothing but directories, else None.

    Fails closed: a file, a symlink (to anything), or any directory that can't
    be listed means the tree is treated as holding user content. ``os.walk``
    silently skips unreadable subdirectories by default, which would make an
    uninspected subtree look empty.
    """
    def _raise(err: OSError) -> None:
        raise err

    dirs_bottom_up: list[str] = []
    try:
        for root, dirs, files in os.walk(path, topdown=False, onerror=_raise, followlinks=False):
            if files:
                return None
            if any(os.path.islink(os.path.join(root, d)) for d in dirs):
                return None
            dirs_bottom_up.append(root)
    except OSError:
        return None
    return dirs_bottom_up


def _remove_empty_tree(dirs_bottom_up: list[str]) -> None:
    """Remove directories deepest first with rmdir, which refuses anything
    non-empty, so content that appears after the scan can't be deleted."""
    for d in dirs_bottom_up:
        os.rmdir(d)


def cleanup_slice_workdirs(storage: str) -> dict[str, list[str]]:
    """Remove empty / archive non-empty legacy slice folders once.

    Returns the folder names removed and moved (empty when already done).
    """
    result: dict[str, list[str]] = {"removed": [], "moved": []}
    marker = os.path.join(storage, _MARKER)
    if os.path.exists(marker) or not os.path.isdir(storage):
        return result

    known = _registry_slices(storage)
    archive_dir = os.path.join(storage, ARCHIVE_DIR_NAME)
    for entry in sorted(os.listdir(storage)):
        if entry.startswith(".") or entry in _RESERVED or entry not in known:
            continue
        path = os.path.join(storage, entry)
        if os.path.islink(path) or not os.path.isdir(path):
            continue
        try:
            empty_dirs = _empty_dirs_bottom_up(path)
            if empty_dirs is not None:
                _remove_empty_tree(empty_dirs)
                result["removed"].append(entry)
                continue
            dst = os.path.join(archive_dir, entry)
            if os.path.exists(dst):
                logger.warning("Left slice folder %s in place: %s already exists", path, dst)
                continue
            os.makedirs(archive_dir, exist_ok=True)
            shutil.move(path, dst)
            result["moved"].append(entry)
        except OSError:
            logger.warning("Could not clean up slice folder %s", path, exc_info=True)

    os.makedirs(os.path.dirname(marker), exist_ok=True)
    with open(marker, "w") as f:
        json.dump(result, f)
    if result["removed"] or result["moved"]:
        logger.info(
            "Retired per-slice folders: removed %d empty, moved %d to %s/",
            len(result["removed"]), len(result["moved"]), ARCHIVE_DIR_NAME,
        )
    return result
