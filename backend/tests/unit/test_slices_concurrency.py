"""Per-slice locks, dirty drafts, submit markers, reconcile isolation."""
import os
import threading
from unittest.mock import MagicMock, patch

import pytest

from app.routes import slices


@pytest.fixture(autouse=True)
def _clean_state():
    with slices._draft_lock:
        slices._draft_slices.clear()
        slices._draft_is_new.clear()
        slices._draft_dirty.clear()
        slices._submitting.clear()
    slices._reconcile_idle.set()
    yield
    with slices._draft_lock:
        slices._draft_slices.clear()
        slices._draft_is_new.clear()
        slices._draft_dirty.clear()
        slices._submitting.clear()
    slices._reconcile_idle.set()


def test_slice_lock_is_per_name_and_reentrant():
    a1, a2, b = slices._slice_lock("a"), slices._slice_lock("a"), slices._slice_lock("b")
    assert a1 is a2 and a1 is not b
    with a1:
        with a1:  # RLock: the same thread may re-enter
            assert True


def test_mutation_decorator_holds_lock_and_marks_dirty(monkeypatch):
    monkeypatch.setattr(slices, "_resolve_slice_name", lambda n: n)
    with slices._draft_lock:
        slices._draft_slices["s"] = object()
        slices._draft_is_new["s"] = False
    @slices._slice_mutation
    def handler(slice_name: str, payload: int) -> dict:
        return {"ok": payload}

    assert handler(slice_name="s", payload=1) == {"ok": 1}  # kwargs, as FastAPI calls it
    assert handler("s", 2) == {"ok": 2}                     # positional also works
    assert "s" in slices._draft_dirty
    assert handler.__wrapped__ is not None  # FastAPI reads the real signature


def test_mutation_decorator_blocks_other_threads():
    with slices._draft_lock:
        slices._draft_slices["s"] = object()
    entered = threading.Event()
    release = threading.Event()

    @slices._slice_mutation
    def slow(slice_name: str):
        entered.set()
        release.wait(2)
        return "done"

    with patch.object(slices, "_resolve_slice_name", lambda n: n):
        t = threading.Thread(target=slow, args=("s",))
        t.start()
        entered.wait(2)
        # Another thread cannot take the slice lock while the handler runs.
        assert not slices._slice_lock("s").acquire(blocking=False)
        release.set()
        t.join(2)
        assert slices._slice_lock("s").acquire(blocking=False)
        slices._slice_lock("s").release()


def test_locked_decorator_does_not_mark_dirty():
    with slices._draft_lock:
        slices._draft_slices["s"] = object()

    @slices._slice_locked
    def read(slice_name: str):
        return "r"

    with patch.object(slices, "_resolve_slice_name", lambda n: n):
        assert read("s") == "r"
    assert "s" not in slices._draft_dirty


def test_pop_draft_clears_dirty():
    with slices._draft_lock:
        slices._draft_slices["s"] = object()
        slices._draft_dirty.add("s")
    slices._pop_draft("s")
    assert "s" not in slices._draft_dirty


def test_begin_and_end_submit_publish_snapshot(monkeypatch):
    draft = object()
    with slices._draft_lock:
        slices._draft_slices["s"] = draft
        slices._draft_is_new["s"] = True
        slices._draft_dirty.add("s")
    monkeypatch.setattr(slices, "_serialize", lambda obj, dirty=False: {"name": "s", "id": "draft-1", "state": "Draft", "nodes": [1]})

    obj, is_new = slices._begin_submit("s")

    assert obj is draft and is_new is True
    assert slices._get_draft("s") is None          # popped
    snap = slices._submitting["s"]
    assert snap["state"] == "Submitting" and snap["dirty"] is False and snap["nodes"] == [1]
    assert "s" not in slices._draft_dirty

    slices._end_submit("s")
    assert "s" not in slices._submitting


def test_begin_submit_without_draft_publishes_nothing():
    assert slices._begin_submit("missing") == (None, True)
    assert "missing" not in slices._submitting


def test_persistent_draft_scan_skips_submitting_slice(tmp_path, monkeypatch):
    d = tmp_path / "subm"
    d.mkdir()
    (d / "topology.graphml").write_text("<graphml/>")
    (d / "meta.json").write_text('{"name": "subm"}')
    monkeypatch.setattr(slices, "_drafts_dir", lambda: str(tmp_path))
    fablib = MagicMock()
    monkeypatch.setattr(slices, "get_fablib", lambda: fablib)
    monkeypatch.setattr(slices, "_ensure_project_id", lambda f: None)
    monkeypatch.setattr(slices, "get_slice_uuid", lambda n: "draft-x")
    with slices._draft_lock:
        slices._submitting["subm"] = {"name": "subm", "state": "Submitting"}

    slices._load_persistent_drafts()

    fablib.new_slice.assert_not_called()
    assert "subm" not in slices._draft_slices


def test_ensure_project_id_waits_for_reconcile(monkeypatch):
    monkeypatch.setenv("FABRIC_PROJECT_ID", "p1")
    fablib = MagicMock()
    slices._reconcile_idle.clear()
    threading.Timer(0.1, slices._reconcile_idle.set).start()
    slices._ensure_project_id(fablib)       # returns once reconcile finishes
    fablib.set_project_id.assert_called_once_with("p1")
