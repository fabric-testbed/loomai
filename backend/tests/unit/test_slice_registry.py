"""Tests for app.slice_registry — JSON file operations with tmp_path."""

import json
import os
from unittest.mock import patch

import pytest

from app.slice_registry import (
    register_slice,
    update_slice_state,
    get_slice_uuid,
    resolve_slice_id,
    resolve_slice_name,
    archive_slice,
    archive_all_terminal,
    unregister_slice,
    get_all_entries,
    bulk_register,
    bulk_tag_project,
    TERMINAL_STATES,
)


@pytest.fixture(autouse=True)
def isolated_registry(storage_dir):
    """Every test gets an isolated storage_dir (from conftest.py)."""
    pass


# ---------------------------------------------------------------------------
# register_slice
# ---------------------------------------------------------------------------

class TestRegisterSlice:
    def test_register_new(self):
        register_slice("test-slice", uuid="uuid-1", state="Draft")
        assert get_slice_uuid("test-slice") == "uuid-1"

    def test_register_updates_existing(self):
        register_slice("test-slice", uuid="uuid-1", state="Draft")
        register_slice("test-slice", uuid="uuid-2", state="Configuring")
        assert get_slice_uuid("test-slice") == "uuid-2"

    def test_register_preserves_uuid_if_empty(self):
        register_slice("test-slice", uuid="uuid-1")
        register_slice("test-slice", state="StableOK")
        assert get_slice_uuid("test-slice") == "uuid-1"

    def test_register_with_project_id(self):
        register_slice("test-slice", uuid="uuid-1", project_id="proj-1")
        entries = get_all_entries()
        assert entries["test-slice"]["project_id"] == "proj-1"

    def test_register_sets_timestamps(self):
        register_slice("test-slice", uuid="uuid-1")
        entries = get_all_entries()
        entry = entries["test-slice"]
        assert "created_at" in entry
        assert "updated_at" in entry


# ---------------------------------------------------------------------------
# update_slice_state
# ---------------------------------------------------------------------------

class TestUpdateSliceState:
    def test_update_existing(self):
        register_slice("s1", uuid="u1", state="Draft")
        update_slice_state("s1", "Configuring")
        entries = get_all_entries()
        assert entries["s1"]["state"] == "Configuring"

    def test_update_creates_if_missing(self):
        update_slice_state("new-slice", "StableOK", uuid="u2")
        entries = get_all_entries()
        assert "new-slice" in entries
        assert entries["new-slice"]["state"] == "StableOK"

    def test_update_uuid(self):
        register_slice("s1", uuid="old-uuid")
        update_slice_state("s1", "Configuring", uuid="new-uuid")
        assert get_slice_uuid("s1") == "new-uuid"

    def test_new_uuid_unarchives(self):
        register_slice("s1", uuid="u1")
        archive_slice("s1")
        update_slice_state("s1", "Configuring", uuid="u2")
        entries = get_all_entries(include_archived=False)
        assert "s1" in entries

    def test_has_errors_updated(self):
        register_slice("s1", uuid="u1")
        update_slice_state("s1", "StableError", has_errors=True)
        entries = get_all_entries()
        assert entries["s1"]["has_errors"] is True


# ---------------------------------------------------------------------------
# resolve_slice_id / resolve_slice_name
# ---------------------------------------------------------------------------

class TestResolveSlice:
    def test_resolve_by_uuid(self):
        register_slice("my-slice", uuid="abc-123")
        assert resolve_slice_id("abc-123") == "my-slice"

    def test_resolve_unknown_uuid(self):
        assert resolve_slice_id("nonexistent") is None

    def test_resolve_empty(self):
        assert resolve_slice_id("") is None

    def test_resolve_name_by_uuid(self):
        register_slice("my-slice", uuid="abc-123")
        assert resolve_slice_name("abc-123") == "my-slice"

    def test_resolve_name_fallback(self):
        assert resolve_slice_name("unknown-string") == "unknown-string"


# ---------------------------------------------------------------------------
# archive_slice
# ---------------------------------------------------------------------------

class TestArchiveSlice:
    def test_archive_hides_from_default_list(self):
        register_slice("s1", uuid="u1")
        archive_slice("s1")
        entries = get_all_entries(include_archived=False)
        assert "s1" not in entries

    def test_archive_visible_when_requested(self):
        register_slice("s1", uuid="u1")
        archive_slice("s1")
        entries = get_all_entries(include_archived=True)
        assert "s1" in entries
        assert entries["s1"]["archived"] is True


# ---------------------------------------------------------------------------
# archive_all_terminal
# ---------------------------------------------------------------------------

class TestArchiveAllTerminal:
    def test_archives_terminal_states(self):
        register_slice("dead", uuid="u1", state="Dead")
        register_slice("closing", uuid="u2", state="Closing")
        register_slice("ok", uuid="u3", state="StableOK")
        archived = archive_all_terminal()
        assert "dead" in archived
        assert "closing" in archived
        assert "ok" not in archived

    def test_returns_empty_when_none(self):
        register_slice("ok", uuid="u1", state="StableOK")
        archived = archive_all_terminal()
        assert archived == []

    def test_does_not_re_archive(self):
        register_slice("dead", uuid="u1", state="Dead")
        archive_all_terminal()
        # Second call shouldn't include already-archived
        result = archive_all_terminal()
        assert result == []


# ---------------------------------------------------------------------------
# unregister_slice
# ---------------------------------------------------------------------------

class TestUnregisterSlice:
    def test_removes_entry(self):
        register_slice("s1", uuid="u1")
        unregister_slice("s1")
        entries = get_all_entries(include_archived=True)
        assert "s1" not in entries

    def test_unregister_nonexistent_is_noop(self):
        unregister_slice("nonexistent")  # should not raise


# ---------------------------------------------------------------------------
# get_all_entries
# ---------------------------------------------------------------------------

class TestGetAllEntries:
    def test_empty_registry(self):
        entries = get_all_entries()
        assert entries == {}

    def test_excludes_archived_by_default(self):
        register_slice("s1", uuid="u1")
        register_slice("s2", uuid="u2")
        archive_slice("s1")
        entries = get_all_entries()
        assert "s1" not in entries
        assert "s2" in entries

    def test_filters_by_project_id(self):
        register_slice("s1", uuid="u1", project_id="proj-A")
        register_slice("s2", uuid="u2", project_id="proj-B")
        entries = get_all_entries(project_id="proj-A")
        assert "s1" in entries
        assert "s2" not in entries


# ---------------------------------------------------------------------------
# bulk_register
# ---------------------------------------------------------------------------

class TestBulkRegister:
    def test_registers_multiple(self):
        entries = [
            {"name": "s1", "uuid": "u1", "state": "StableOK"},
            {"name": "s2", "uuid": "u2", "state": "Configuring"},
        ]
        bulk_register(entries)
        all_entries = get_all_entries()
        assert "s1" in all_entries
        assert "s2" in all_entries
        assert all_entries["s1"]["state"] == "StableOK"

    def test_preserves_existing_archived_state(self):
        register_slice("s1", uuid="u1", state="Draft")
        archive_slice("s1")
        bulk_register([{"name": "s1", "uuid": "u1", "state": "StableOK"}])
        entries = get_all_entries(include_archived=True)
        assert entries["s1"]["archived"] is True


# ---------------------------------------------------------------------------
# bulk_tag_project
# ---------------------------------------------------------------------------

class TestBulkTagProject:
    def test_tags_matching_entries(self):
        register_slice("s1", uuid="u1")
        register_slice("s2", uuid="u2")
        count = bulk_tag_project({"u1": "proj-X", "u2": "proj-Y"})
        assert count == 2
        entries = get_all_entries()
        assert entries["s1"]["project_id"] == "proj-X"
        assert entries["s2"]["project_id"] == "proj-Y"

    def test_skips_unmatched_uuids(self):
        register_slice("s1", uuid="u1")
        count = bulk_tag_project({"nonexistent": "proj-X"})
        assert count == 0

    def test_no_update_when_same_project(self):
        register_slice("s1", uuid="u1", project_id="proj-X")
        count = bulk_tag_project({"u1": "proj-X"})
        assert count == 0
