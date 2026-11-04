"""Tests for the one-time retirement of per-slice working directories."""

import json

from app.slice_workdir_cleanup import ARCHIVE_DIR_NAME, cleanup_slice_workdirs


def _registry(path, slices):
    path.mkdir(parents=True, exist_ok=True)
    (path / "registry.json").write_text(json.dumps({"slices": slices}))


def _storage(tmp_path):
    _registry(tmp_path / "my_slices", {
        "MySlice": {"name": "MySlice", "uuid": "1c7d4b16"},
        "cryoem": {"name": "cryoem", "uuid": "draft-abc"},
        "codex": {"name": "codex", "uuid": "u-codex"},
    })
    return tmp_path


def test_removes_empty_and_archives_non_empty(tmp_path):
    storage = _storage(tmp_path)
    (storage / "MySlice").mkdir()
    (storage / "MySlice" / ".ipynb_checkpoints").mkdir(parents=True)  # no files
    (storage / "MySlice-1c7d4b16").mkdir()
    (storage / "MySlice-1c7d4b16" / "results.csv").write_text("x")
    (storage / "cryoem").mkdir()
    (storage / "cryoem" / "notes.ipynb").write_text("{}")

    result = cleanup_slice_workdirs(str(storage))

    assert result["removed"] == ["MySlice"]
    assert sorted(result["moved"]) == ["MySlice-1c7d4b16", "cryoem"]
    assert not (storage / "MySlice").exists()
    assert (storage / ARCHIVE_DIR_NAME / "MySlice-1c7d4b16" / "results.csv").read_text() == "x"
    assert (storage / ARCHIVE_DIR_NAME / "cryoem" / "notes.ipynb").exists()


def test_leaves_unrelated_reserved_dot_and_symlinked_folders(tmp_path):
    storage = _storage(tmp_path)
    (storage / "my_own_project").mkdir()           # not a slice name
    (storage / "codex").mkdir()                    # reserved, even though a slice has the name
    (storage / ".MySlice").mkdir()                 # dot-prefixed
    target = tmp_path / "elsewhere"
    target.mkdir()
    (storage / "MySlice").symlink_to(target)       # symlink

    result = cleanup_slice_workdirs(str(storage))

    assert result == {"removed": [], "moved": []}
    for name in ("my_own_project", "codex", ".MySlice", "MySlice"):
        assert (storage / name).exists()


def test_draft_uuid_is_not_used_for_archive_names(tmp_path):
    storage = _storage(tmp_path)
    (storage / "cryoem-draft-abc").mkdir()

    assert cleanup_slice_workdirs(str(storage))["removed"] == []
    assert (storage / "cryoem-draft-abc").exists()


def test_runs_once(tmp_path):
    storage = _storage(tmp_path)
    cleanup_slice_workdirs(str(storage))
    (storage / "MySlice").mkdir()  # a folder the user creates later

    assert cleanup_slice_workdirs(str(storage)) == {"removed": [], "moved": []}
    assert (storage / "MySlice").exists()


def test_destination_conflict_leaves_folder_in_place(tmp_path):
    storage = _storage(tmp_path)
    (storage / "cryoem").mkdir()
    (storage / "cryoem" / "a.txt").write_text("new")
    (storage / ARCHIVE_DIR_NAME / "cryoem").mkdir(parents=True)

    assert cleanup_slice_workdirs(str(storage))["moved"] == []
    assert (storage / "cryoem" / "a.txt").read_text() == "new"


def test_reads_multi_user_registries(tmp_path):
    _registry(tmp_path / ".loomai" / "users" / "u1" / "my_slices", {
        "other": {"name": "other", "uuid": "u-other"},
    })
    (tmp_path / "other").mkdir()

    assert cleanup_slice_workdirs(str(tmp_path))["removed"] == ["other"]


def test_unreadable_subfolder_is_archived_not_deleted(tmp_path):
    import os
    import pytest

    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root can read any directory")
    storage = _storage(tmp_path)
    hidden = storage / "MySlice" / "private"
    hidden.mkdir(parents=True)
    (hidden / "data.bin").write_text("keep me")
    hidden.chmod(0)
    try:
        result = cleanup_slice_workdirs(str(storage))
    finally:
        moved = storage / ARCHIVE_DIR_NAME / "MySlice" / "private"
        (moved if moved.exists() else hidden).chmod(0o755)

    assert result["removed"] == []
    assert result["moved"] == ["MySlice"]
    assert (storage / ARCHIVE_DIR_NAME / "MySlice" / "private" / "data.bin").read_text() == "keep me"


def test_symlinks_inside_count_as_content(tmp_path):
    storage = _storage(tmp_path)
    target = tmp_path / "datasets"
    target.mkdir()
    (storage / "MySlice").mkdir()
    (storage / "MySlice" / "data").symlink_to(target)          # link to a directory
    (storage / "cryoem").mkdir()
    (storage / "cryoem" / "gone").symlink_to(tmp_path / "nope")  # broken link

    result = cleanup_slice_workdirs(str(storage))

    assert result["removed"] == []
    assert sorted(result["moved"]) == ["MySlice", "cryoem"]
    assert (storage / ARCHIVE_DIR_NAME / "MySlice" / "data").is_symlink()
    assert target.exists()
