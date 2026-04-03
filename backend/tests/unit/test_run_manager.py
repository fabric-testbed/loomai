"""Tests for the run manager — background weave script execution.

Mocks subprocess.Popen and file I/O to avoid launching real processes.
"""

from __future__ import annotations

import json
import os
import time
from unittest.mock import MagicMock, patch, mock_open

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate_run_manager(tmp_path):
    """Redirect run storage to tmp_path and clear module-level state."""
    import app.run_manager as rm

    # Save and clear state
    old_active = rm._active_runs.copy()
    old_stopped = rm._stopped_runs.copy()
    rm._active_runs.clear()
    rm._stopped_runs.clear()

    with patch("app.run_manager.get_user_storage", return_value=str(tmp_path)):
        yield tmp_path

    # Restore
    rm._active_runs.clear()
    rm._active_runs.update(old_active)
    rm._stopped_runs.clear()
    rm._stopped_runs.update(old_stopped)


# ---------------------------------------------------------------------------
# Sanitize slice name
# ---------------------------------------------------------------------------

class TestSanitizeSliceName:
    def test_normal_name(self):
        from app.run_manager import _sanitize_slice_name
        assert _sanitize_slice_name("my-slice") == "my-slice"

    def test_spaces_replaced(self):
        from app.run_manager import _sanitize_slice_name
        assert _sanitize_slice_name("my slice name") == "my-slice-name"

    def test_special_chars(self):
        from app.run_manager import _sanitize_slice_name
        assert _sanitize_slice_name("slice@v2!test") == "slice-v2-test"

    def test_consecutive_hyphens_collapsed(self):
        from app.run_manager import _sanitize_slice_name
        assert _sanitize_slice_name("a--b---c") == "a-b-c"

    def test_leading_trailing_stripped(self):
        from app.run_manager import _sanitize_slice_name
        assert _sanitize_slice_name("-hello-") == "hello"
        assert _sanitize_slice_name("@foo@") == "foo"

    def test_empty_string(self):
        from app.run_manager import _sanitize_slice_name
        assert _sanitize_slice_name("") == ""


# ---------------------------------------------------------------------------
# Start run
# ---------------------------------------------------------------------------

class TestStartRun:
    def test_start_creates_metadata(self, _isolate_run_manager):
        tmp_path = _isolate_run_manager
        import app.run_manager as rm

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.returncode = None
        mock_proc.wait = MagicMock()  # Block forever

        with patch("app.run_manager.subprocess.Popen", return_value=mock_proc), \
             patch("app.run_manager.os.getpgid", return_value=12345), \
             patch("app.run_manager.get_call_manager") as mock_cm:
            mock_cm.return_value.invalidate = MagicMock()

            run_id = rm.start_run(
                weave_dir_name="my-weave",
                weave_name="My Weave",
                script="weave.sh",
                script_path="/path/to/weave.sh",
                cwd="/path/to",
                slice_name="test-slice",
            )

        assert run_id.startswith("run-")

        # Verify meta.json was written
        meta_path = os.path.join(tmp_path, ".runs", run_id, "meta.json")
        assert os.path.isfile(meta_path)
        with open(meta_path) as f:
            meta = json.load(f)
        assert meta["weave_name"] == "My Weave"
        assert meta["slice_name"] == "test-slice"
        assert meta["status"] == "running"
        assert meta["pid"] == 12345

    def test_start_with_script_args(self, _isolate_run_manager):
        tmp_path = _isolate_run_manager
        import app.run_manager as rm

        mock_proc = MagicMock()
        mock_proc.pid = 99999
        mock_proc.returncode = None
        mock_proc.wait = MagicMock()

        with patch("app.run_manager.subprocess.Popen", return_value=mock_proc), \
             patch("app.run_manager.os.getpgid", return_value=99999), \
             patch("app.run_manager.get_call_manager") as mock_cm:
            mock_cm.return_value.invalidate = MagicMock()

            run_id = rm.start_run(
                weave_dir_name="w",
                weave_name="W",
                script="weave.sh",
                script_path="/w/weave.sh",
                cwd="/w",
                script_args={"SLICE_NAME": "custom-name", "NUM_RUNS": "3"},
            )

        meta_path = os.path.join(tmp_path, ".runs", run_id, "meta.json")
        with open(meta_path) as f:
            meta = json.load(f)
        assert meta["slice_name"] == "custom-name"
        assert meta["args"]["NUM_RUNS"] == "3"

    def test_start_sanitizes_slice_name(self, _isolate_run_manager):
        tmp_path = _isolate_run_manager
        import app.run_manager as rm

        mock_proc = MagicMock()
        mock_proc.pid = 11111
        mock_proc.returncode = None
        mock_proc.wait = MagicMock()

        with patch("app.run_manager.subprocess.Popen", return_value=mock_proc), \
             patch("app.run_manager.os.getpgid", return_value=11111), \
             patch("app.run_manager.get_call_manager") as mock_cm:
            mock_cm.return_value.invalidate = MagicMock()

            run_id = rm.start_run(
                weave_dir_name="w",
                weave_name="W",
                script="weave.sh",
                script_path="/w/weave.sh",
                cwd="/w",
                slice_name="My Slice@v2!",
            )

        meta_path = os.path.join(tmp_path, ".runs", run_id, "meta.json")
        with open(meta_path) as f:
            meta = json.load(f)
        assert meta["slice_name"] == "My-Slice-v2"


# ---------------------------------------------------------------------------
# List runs
# ---------------------------------------------------------------------------

class TestListRuns:
    def test_list_empty(self, _isolate_run_manager):
        from app.run_manager import list_runs
        assert list_runs() == []

    def test_list_with_completed_run(self, _isolate_run_manager):
        tmp_path = _isolate_run_manager
        from app.run_manager import list_runs

        # Create a completed run manually
        run_dir = tmp_path / ".runs" / "run-abc123"
        run_dir.mkdir(parents=True)
        meta = {
            "run_id": "run-abc123",
            "status": "done",
            "exit_code": 0,
            "weave_name": "test",
        }
        (run_dir / "meta.json").write_text(json.dumps(meta))

        runs = list_runs()
        assert len(runs) == 1
        assert runs[0]["run_id"] == "run-abc123"
        assert runs[0]["status"] == "done"

    def test_list_running_without_active_marks_unknown(self, _isolate_run_manager):
        """A run that says 'running' but has no active tracking and no live PID -> unknown."""
        tmp_path = _isolate_run_manager
        from app.run_manager import list_runs

        run_dir = tmp_path / ".runs" / "run-orphan"
        run_dir.mkdir(parents=True)
        meta = {
            "run_id": "run-orphan",
            "status": "running",
            "pid": 999999999,  # Definitely not alive
        }
        (run_dir / "meta.json").write_text(json.dumps(meta))

        runs = list_runs()
        assert len(runs) == 1
        assert runs[0]["status"] == "unknown"


# ---------------------------------------------------------------------------
# Get run
# ---------------------------------------------------------------------------

class TestGetRun:
    def test_get_existing(self, _isolate_run_manager):
        tmp_path = _isolate_run_manager
        from app.run_manager import get_run

        run_dir = tmp_path / ".runs" / "run-x"
        run_dir.mkdir(parents=True)
        meta = {"run_id": "run-x", "status": "done"}
        (run_dir / "meta.json").write_text(json.dumps(meta))

        result = get_run("run-x")
        assert result is not None
        assert result["run_id"] == "run-x"

    def test_get_nonexistent(self, _isolate_run_manager):
        from app.run_manager import get_run
        assert get_run("does-not-exist") is None


# ---------------------------------------------------------------------------
# Get run output
# ---------------------------------------------------------------------------

class TestGetRunOutput:
    def test_output_from_log_file(self, _isolate_run_manager):
        tmp_path = _isolate_run_manager
        from app.run_manager import get_run_output

        run_dir = tmp_path / ".runs" / "run-log"
        run_dir.mkdir(parents=True)
        log_path = run_dir / "output.log"
        log_path.write_text("Hello, World!\nLine 2\n")

        meta = {"run_id": "run-log", "status": "done", "log_path": str(log_path)}
        (run_dir / "meta.json").write_text(json.dumps(meta))

        output, offset = get_run_output("run-log", 0)
        assert "Hello, World!" in output
        assert offset > 0

    def test_output_incremental_read(self, _isolate_run_manager):
        tmp_path = _isolate_run_manager
        from app.run_manager import get_run_output

        run_dir = tmp_path / ".runs" / "run-inc"
        run_dir.mkdir(parents=True)
        log_path = run_dir / "output.log"
        log_path.write_text("AAABBB")

        meta = {"run_id": "run-inc", "status": "done", "log_path": str(log_path)}
        (run_dir / "meta.json").write_text(json.dumps(meta))

        # Read first 3 bytes
        output1, off1 = get_run_output("run-inc", 0)
        assert output1 == "AAABBB"

        # Read from the end — should return empty
        output2, off2 = get_run_output("run-inc", off1)
        assert output2 == ""
        assert off2 == off1

    def test_output_no_log_file(self, _isolate_run_manager):
        tmp_path = _isolate_run_manager
        from app.run_manager import get_run_output

        run_dir = tmp_path / ".runs" / "run-nolog"
        run_dir.mkdir(parents=True)
        meta = {"run_id": "run-nolog", "status": "done"}
        (run_dir / "meta.json").write_text(json.dumps(meta))

        output, offset = get_run_output("run-nolog", 0)
        assert output == ""
        assert offset == 0

    def test_output_nonexistent_run(self, _isolate_run_manager):
        from app.run_manager import get_run_output
        output, offset = get_run_output("nonexistent", 0)
        assert output == ""


# ---------------------------------------------------------------------------
# Stop run
# ---------------------------------------------------------------------------

class TestStopRun:
    def test_stop_nonexistent(self, _isolate_run_manager):
        from app.run_manager import stop_run
        assert stop_run("nonexistent") is False

    def test_stop_active_run(self, _isolate_run_manager):
        tmp_path = _isolate_run_manager
        import app.run_manager as rm
        from app.run_manager import stop_run, ActiveRun

        mock_proc = MagicMock()
        mock_proc.pid = 42
        mock_thread = MagicMock()

        # Create run dir with meta
        run_dir = tmp_path / ".runs" / "run-stop"
        run_dir.mkdir(parents=True)
        meta = {"run_id": "run-stop", "status": "running", "pid": 42, "pgid": 42}
        (run_dir / "meta.json").write_text(json.dumps(meta))

        rm._active_runs["run-stop"] = ActiveRun(
            run_id="run-stop",
            proc=mock_proc,
            thread=mock_thread,
            meta=meta,
            pid=42,
            pgid=42,
        )

        with patch("app.run_manager.os.killpg") as mock_killpg, \
             patch("app.run_manager._is_pid_alive", return_value=False):
            result = stop_run("run-stop")

        assert result is True
        mock_killpg.assert_called()

    def test_stop_completed_run_returns_false(self, _isolate_run_manager):
        tmp_path = _isolate_run_manager
        from app.run_manager import stop_run

        run_dir = tmp_path / ".runs" / "run-done"
        run_dir.mkdir(parents=True)
        meta = {"run_id": "run-done", "status": "done", "pid": 42}
        (run_dir / "meta.json").write_text(json.dumps(meta))

        result = stop_run("run-done")
        assert result is False


# ---------------------------------------------------------------------------
# Delete run
# ---------------------------------------------------------------------------

class TestDeleteRun:
    def test_delete_completed(self, _isolate_run_manager):
        tmp_path = _isolate_run_manager
        from app.run_manager import delete_run, get_run

        run_dir = tmp_path / ".runs" / "run-del"
        run_dir.mkdir(parents=True)
        meta = {"run_id": "run-del", "status": "done"}
        (run_dir / "meta.json").write_text(json.dumps(meta))

        result = delete_run("run-del")
        assert result is True
        assert get_run("run-del") is None

    def test_delete_nonexistent(self, _isolate_run_manager):
        from app.run_manager import delete_run
        assert delete_run("does-not-exist") is False

    def test_delete_running_stops_first(self, _isolate_run_manager):
        tmp_path = _isolate_run_manager
        from app.run_manager import delete_run

        run_dir = tmp_path / ".runs" / "run-running"
        run_dir.mkdir(parents=True)
        meta = {"run_id": "run-running", "status": "running", "pid": 999999999}
        (run_dir / "meta.json").write_text(json.dumps(meta))

        with patch("app.run_manager.stop_run", return_value=True) as mock_stop:
            result = delete_run("run-running")

        assert result is True
        mock_stop.assert_called_once_with("run-running")


# ---------------------------------------------------------------------------
# _wait_for_proc
# ---------------------------------------------------------------------------

class TestWaitForProc:
    def test_normal_exit(self, _isolate_run_manager):
        tmp_path = _isolate_run_manager
        import app.run_manager as rm

        run_dir = tmp_path / ".runs" / "run-wait"
        run_dir.mkdir(parents=True)
        meta = {"run_id": "run-wait", "status": "running"}
        (run_dir / "meta.json").write_text(json.dumps(meta))

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_log_fd = MagicMock()

        with patch("app.run_manager.get_call_manager") as mock_cm:
            mock_cm.return_value.invalidate = MagicMock()
            rm._wait_for_proc("run-wait", mock_proc, mock_log_fd)

        mock_log_fd.close.assert_called()
        updated_meta = rm.get_run("run-wait")
        assert updated_meta["status"] == "done"
        assert updated_meta["exit_code"] == 0

    def test_error_exit(self, _isolate_run_manager):
        tmp_path = _isolate_run_manager
        import app.run_manager as rm

        run_dir = tmp_path / ".runs" / "run-err"
        run_dir.mkdir(parents=True)
        meta = {"run_id": "run-err", "status": "running"}
        (run_dir / "meta.json").write_text(json.dumps(meta))

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_log_fd = MagicMock()

        with patch("app.run_manager.get_call_manager") as mock_cm:
            mock_cm.return_value.invalidate = MagicMock()
            rm._wait_for_proc("run-err", mock_proc, mock_log_fd)

        updated_meta = rm.get_run("run-err")
        assert updated_meta["status"] == "error"
        assert updated_meta["exit_code"] == 1

    def test_stopped_run_marked_done(self, _isolate_run_manager):
        """A run stopped by user should be marked done, even with signal exit code."""
        tmp_path = _isolate_run_manager
        import app.run_manager as rm

        run_dir = tmp_path / ".runs" / "run-stopped"
        run_dir.mkdir(parents=True)
        meta = {"run_id": "run-stopped", "status": "running"}
        (run_dir / "meta.json").write_text(json.dumps(meta))

        # Mark as user-stopped
        rm._stopped_runs.add("run-stopped")

        mock_proc = MagicMock()
        mock_proc.returncode = -15  # SIGTERM exit code
        mock_log_fd = MagicMock()

        with patch("app.run_manager.get_call_manager") as mock_cm:
            mock_cm.return_value.invalidate = MagicMock()
            rm._wait_for_proc("run-stopped", mock_proc, mock_log_fd)

        updated_meta = rm.get_run("run-stopped")
        assert updated_meta["status"] == "done"
        assert updated_meta["exit_code"] == 0  # Overridden for user-stopped


# ---------------------------------------------------------------------------
# _clear_weave_active_run
# ---------------------------------------------------------------------------

class TestClearWeaveActiveRun:
    def test_clears_active_run(self, _isolate_run_manager):
        tmp_path = _isolate_run_manager
        from app.run_manager import _clear_weave_active_run

        weave_dir = tmp_path / "my-weave"
        weave_dir.mkdir()
        weave_json = weave_dir / "weave.json"
        weave_json.write_text(json.dumps({"name": "test", "active_run": "run-123"}))

        _clear_weave_active_run({"weave_dir": str(weave_dir)})

        data = json.loads(weave_json.read_text())
        assert "active_run" not in data

    def test_no_weave_dir(self, _isolate_run_manager):
        from app.run_manager import _clear_weave_active_run
        # Should not crash
        _clear_weave_active_run({})
        _clear_weave_active_run({"weave_dir": "/nonexistent"})


# ---------------------------------------------------------------------------
# _is_pid_alive
# ---------------------------------------------------------------------------

class TestIsPidAlive:
    def test_alive_pid(self):
        from app.run_manager import _is_pid_alive
        # Our own process is definitely alive
        assert _is_pid_alive(os.getpid()) is True

    def test_dead_pid(self):
        from app.run_manager import _is_pid_alive
        # PID 999999999 is almost certainly not alive
        assert _is_pid_alive(999999999) is False


# ---------------------------------------------------------------------------
# recover_stale_runs
# ---------------------------------------------------------------------------

class TestRecoverStaleRuns:
    def test_marks_dead_run_interrupted(self, _isolate_run_manager):
        tmp_path = _isolate_run_manager
        import app.run_manager as rm

        run_dir = tmp_path / ".runs" / "run-stale"
        run_dir.mkdir(parents=True)
        meta = {"run_id": "run-stale", "status": "running", "pid": 999999999}
        (run_dir / "meta.json").write_text(json.dumps(meta))

        with patch("app.run_manager.get_call_manager") as mock_cm:
            mock_cm.return_value.invalidate = MagicMock()
            rm.recover_stale_runs()

        updated = rm.get_run("run-stale")
        assert updated["status"] == "interrupted"

    def test_reconnects_alive_run(self, _isolate_run_manager):
        tmp_path = _isolate_run_manager
        import app.run_manager as rm

        run_dir = tmp_path / ".runs" / "run-alive"
        run_dir.mkdir(parents=True)
        meta = {"run_id": "run-alive", "status": "running", "pid": os.getpid(), "pgid": os.getpid()}
        (run_dir / "meta.json").write_text(json.dumps(meta))

        rm.recover_stale_runs()

        assert "run-alive" in rm._active_runs
        active = rm._active_runs["run-alive"]
        assert active.pid == os.getpid()
        assert active.proc is None  # Recovered runs don't have a Popen

    def test_skips_completed_runs(self, _isolate_run_manager):
        tmp_path = _isolate_run_manager
        import app.run_manager as rm

        run_dir = tmp_path / ".runs" / "run-done"
        run_dir.mkdir(parents=True)
        meta = {"run_id": "run-done", "status": "done", "pid": 42}
        (run_dir / "meta.json").write_text(json.dumps(meta))

        rm.recover_stale_runs()
        assert "run-done" not in rm._active_runs

    def test_empty_runs_dir(self, _isolate_run_manager):
        import app.run_manager as rm
        # Should not crash with empty .runs dir
        rm.recover_stale_runs()
