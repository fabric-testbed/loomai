"""Tests for the reservation manager — scheduled slice submissions."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_reservations_file(tmp_path):
    """Point the reservation manager at a temp file."""
    import app.reservation_manager as rm
    rm._RESERVATIONS_FILE = str(tmp_path / ".loomai" / "reservations.json")
    return rm._RESERVATIONS_FILE


@pytest.fixture(autouse=True)
def _reset_module(tmp_path):
    """Reset the module-level cached path between tests."""
    import app.reservation_manager as rm
    old = rm._RESERVATIONS_FILE
    path = _set_reservations_file(tmp_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    yield
    rm._RESERVATIONS_FILE = old


# ---------------------------------------------------------------------------
# load_reservations
# ---------------------------------------------------------------------------

class TestLoadReservations:
    def test_no_file_returns_empty(self, tmp_path):
        from app.reservation_manager import load_reservations
        result = load_reservations()
        assert result == []

    def test_existing_file(self, tmp_path):
        from app.reservation_manager import load_reservations
        import app.reservation_manager as rm

        path = rm._RESERVATIONS_FILE
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump([{"id": "r1", "status": "pending"}], f)

        result = load_reservations()
        assert len(result) == 1
        assert result[0]["id"] == "r1"

    def test_corrupt_json_returns_empty(self, tmp_path):
        from app.reservation_manager import load_reservations
        import app.reservation_manager as rm

        path = rm._RESERVATIONS_FILE
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("not-json{{{")

        result = load_reservations()
        assert result == []


# ---------------------------------------------------------------------------
# save_reservations
# ---------------------------------------------------------------------------

class TestSaveReservations:
    def test_writes_json(self, tmp_path):
        from app.reservation_manager import save_reservations, load_reservations

        data = [{"id": "r1", "status": "pending"}, {"id": "r2", "status": "active"}]
        save_reservations(data)

        loaded = load_reservations()
        assert len(loaded) == 2
        assert loaded[0]["id"] == "r1"

    def test_creates_parent_dirs(self, tmp_path):
        import app.reservation_manager as rm
        from app.reservation_manager import save_reservations

        # Point to a deeply nested path that doesn't exist
        rm._RESERVATIONS_FILE = str(tmp_path / "deep" / "nested" / "reservations.json")
        save_reservations([])
        assert os.path.isfile(rm._RESERVATIONS_FILE)


# ---------------------------------------------------------------------------
# add_reservation
# ---------------------------------------------------------------------------

class TestAddReservation:
    def test_creates_and_persists(self, tmp_path):
        from app.reservation_manager import add_reservation, load_reservations

        res = add_reservation({
            "slice_name": "my-slice",
            "scheduled_time": "2026-04-01T12:00:00Z",
            "duration_hours": 8,
        })

        assert res["slice_name"] == "my-slice"
        assert res["status"] == "pending"
        assert res["duration_hours"] == 8
        assert res["error"] is None
        assert "id" in res

        # Verify persisted
        loaded = load_reservations()
        assert len(loaded) == 1
        assert loaded[0]["id"] == res["id"]

    def test_defaults(self, tmp_path):
        from app.reservation_manager import add_reservation

        res = add_reservation({
            "slice_name": "test",
            "scheduled_time": "2026-04-01T00:00:00Z",
        })
        assert res["duration_hours"] == 24
        assert res["auto_submit"] is True

    def test_multiple_reservations(self, tmp_path):
        from app.reservation_manager import add_reservation, load_reservations

        add_reservation({"slice_name": "s1", "scheduled_time": "2026-04-01T00:00:00Z"})
        add_reservation({"slice_name": "s2", "scheduled_time": "2026-04-02T00:00:00Z"})

        loaded = load_reservations()
        assert len(loaded) == 2


# ---------------------------------------------------------------------------
# cancel_reservation
# ---------------------------------------------------------------------------

class TestCancelReservation:
    def test_cancel_existing(self, tmp_path):
        from app.reservation_manager import add_reservation, cancel_reservation, load_reservations

        res = add_reservation({"slice_name": "s1", "scheduled_time": "2026-04-01T00:00:00Z"})
        assert cancel_reservation(res["id"]) is True
        assert load_reservations() == []

    def test_cancel_nonexistent(self, tmp_path):
        from app.reservation_manager import cancel_reservation
        assert cancel_reservation("does-not-exist") is False


# ---------------------------------------------------------------------------
# check_and_execute_reservations
# ---------------------------------------------------------------------------

class TestCheckAndExecute:
    def test_no_pending(self, tmp_path):
        from app.reservation_manager import check_and_execute_reservations, save_reservations

        save_reservations([{"id": "r1", "status": "active", "scheduled_time": "2020-01-01T00:00:00Z"}])
        executed = check_and_execute_reservations()
        assert executed == []

    def test_future_reservation_not_executed(self, tmp_path):
        from app.reservation_manager import add_reservation, check_and_execute_reservations

        future = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        add_reservation({"slice_name": "future-slice", "scheduled_time": future})

        executed = check_and_execute_reservations()
        assert executed == []

    def test_due_reservation_auto_submit(self, tmp_path):
        from app.reservation_manager import add_reservation, check_and_execute_reservations, load_reservations

        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        add_reservation({
            "slice_name": "due-slice",
            "scheduled_time": past,
            "auto_submit": True,
        })

        mock_slice = MagicMock()
        mock_fablib = MagicMock()
        mock_fablib.get_slice.return_value = mock_slice

        with patch("app.fablib_manager.get_fablib", return_value=mock_fablib), \
             patch("app.fablib_manager.is_configured", return_value=True):
            executed = check_and_execute_reservations()

        assert len(executed) == 1
        assert executed[0]["status"] == "active"
        mock_slice.submit.assert_called_once_with(wait=False)

        # Verify persisted
        loaded = load_reservations()
        assert loaded[0]["status"] == "active"

    def test_due_reservation_not_configured(self, tmp_path):
        from app.reservation_manager import add_reservation, check_and_execute_reservations

        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        add_reservation({
            "slice_name": "fail-slice",
            "scheduled_time": past,
            "auto_submit": True,
        })

        with patch("app.fablib_manager.is_configured", return_value=False):
            executed = check_and_execute_reservations()

        assert len(executed) == 1
        assert executed[0]["status"] == "failed"
        assert "not configured" in executed[0]["error"].lower()

    def test_due_reservation_submit_error(self, tmp_path):
        from app.reservation_manager import add_reservation, check_and_execute_reservations

        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        add_reservation({
            "slice_name": "err-slice",
            "scheduled_time": past,
            "auto_submit": True,
        })

        mock_fablib = MagicMock()
        mock_fablib.get_slice.side_effect = RuntimeError("Slice not found")

        with patch("app.fablib_manager.get_fablib", return_value=mock_fablib), \
             patch("app.fablib_manager.is_configured", return_value=True):
            executed = check_and_execute_reservations()

        assert len(executed) == 1
        assert executed[0]["status"] == "failed"
        assert "Slice not found" in executed[0]["error"]

    def test_due_reservation_no_auto_submit(self, tmp_path):
        from app.reservation_manager import add_reservation, check_and_execute_reservations

        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        add_reservation({
            "slice_name": "manual-slice",
            "scheduled_time": past,
            "auto_submit": False,
        })

        executed = check_and_execute_reservations()
        assert len(executed) == 1
        assert executed[0]["status"] == "active"

    def test_invalid_scheduled_time_skipped(self, tmp_path):
        from app.reservation_manager import save_reservations, check_and_execute_reservations

        save_reservations([{
            "id": "r1",
            "status": "pending",
            "scheduled_time": "not-a-date",
            "auto_submit": True,
            "slice_name": "bad",
        }])

        executed = check_and_execute_reservations()
        assert executed == []
