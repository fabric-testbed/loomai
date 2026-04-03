"""Background run manager — executes weave scripts detached from HTTP connections.

Runs persist across browser disconnects. Output is captured to log files on
disk so clients can reconnect and resume streaming at any point.

Storage layout::

    {FABRIC_STORAGE_DIR}/.runs/
        {run_id}/
            meta.json       # status, timestamps, weave info
            output.log      # captured stdout/stderr

"""
from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import re

from app.fabric_call_manager import get_call_manager

from app.user_context import get_user_storage

logger = logging.getLogger(__name__)


def _sanitize_slice_name(name: str) -> str:
    """Sanitize a slice name to match what weave.sh does.

    Replaces non-alphanumeric/hyphen chars with hyphens, collapses runs of
    hyphens, and strips leading/trailing hyphens.  This ensures the name
    stored in meta.json matches the name the script actually uses.
    """
    s = re.sub(r"[^a-zA-Z0-9-]", "-", name)
    s = re.sub(r"-{2,}", "-", s)
    return s.strip("-")

_RUNS_SUBDIR = ".runs"


def _runs_dir() -> str:
    d = os.path.join(get_user_storage(), _RUNS_SUBDIR)
    os.makedirs(d, exist_ok=True)
    return d


def _run_dir(run_id: str) -> str:
    return os.path.join(_runs_dir(), run_id)


# ---------------------------------------------------------------------------
# In-memory tracking of active runs
# ---------------------------------------------------------------------------

@dataclass
class ActiveRun:
    run_id: str
    proc: subprocess.Popen | None  # None for recovered runs (PID-only tracking)
    thread: threading.Thread
    meta: dict[str, Any] = field(default_factory=dict)
    pid: int = 0
    pgid: int = 0


_active_runs: dict[str, ActiveRun] = {}
_stopped_runs: set[str] = set()  # runs explicitly stopped by user (not errors)
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start_run(
    weave_dir_name: str,
    weave_name: str,
    script: str,
    script_path: str,
    cwd: str,
    script_args: dict[str, str] | None = None,
    slice_name: str = "",
    log_path: str | None = None,
) -> str:
    """Start a background run. Returns the run_id.

    Args:
        script_args: Dict of env vars to pass to the script (e.g. SLICE_NAME, NUM_RUNS).
        slice_name: Legacy param — used if script_args doesn't contain SLICE_NAME.
        log_path: If provided, write output to this path instead of .runs/{run_id}/output.log.
    """
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    rdir = _run_dir(run_id)
    os.makedirs(rdir, exist_ok=True)

    # Merge legacy slice_name with new args dict
    args = dict(script_args or {})
    if slice_name and "SLICE_NAME" not in args:
        args["SLICE_NAME"] = slice_name
    # Sanitize SLICE_NAME so meta matches what weave.sh actually uses
    if args.get("SLICE_NAME"):
        args["SLICE_NAME"] = _sanitize_slice_name(args["SLICE_NAME"])

    # Resolve log path — use provided weave log or default to .runs/{run_id}/output.log
    actual_log_path = log_path if log_path else os.path.join(rdir, "output.log")

    meta = {
        "run_id": run_id,
        "weave_dir_name": weave_dir_name,
        "weave_name": weave_name,
        "script": script,
        "slice_name": args.get("SLICE_NAME", ""),
        "args": args,
        "status": "running",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "finished_at": None,
        "exit_code": None,
        "log_path": actual_log_path,
    }
    _write_meta(run_id, meta)

    # Weave runs typically create/modify slices — invalidate cache so the
    # next frontend poll picks up changes even in STEADY mode (max_age=300).
    get_call_manager().invalidate("slices:list")

    env = {**os.environ, **args}
    cmd = ["bash", script_path]
    # Pass SLICE_NAME as positional arg for backward compat with scripts using $1
    if args.get("SLICE_NAME"):
        cmd.append(args["SLICE_NAME"])

    log_fd = open(actual_log_path, "w")

    proc = subprocess.Popen(
        cmd,
        stdout=log_fd,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
        cwd=cwd,
        # Ensure the process survives even if the parent thread dies
        start_new_session=True,
    )

    # Persist PID/PGID/weave_dir so we can recover after backend restart
    pid = proc.pid
    try:
        pgid = os.getpgid(pid)
    except OSError:
        pgid = pid
    meta["pid"] = pid
    meta["pgid"] = pgid
    meta["weave_dir"] = cwd
    _write_meta(run_id, meta)

    t = threading.Thread(
        target=_wait_for_proc,
        args=(run_id, proc, log_fd),
        daemon=True,
    )
    t.start()

    with _lock:
        _active_runs[run_id] = ActiveRun(
            run_id=run_id, proc=proc, thread=t, meta=meta,
            pid=pid, pgid=pgid,
        )

    logger.info("Started background run %s: %s", run_id, " ".join(cmd))
    return run_id


def list_runs() -> list[dict[str, Any]]:
    """List all runs (active and completed)."""
    rdir = _runs_dir()
    results = []
    for name in sorted(os.listdir(rdir), reverse=True):
        meta_path = os.path.join(rdir, name, "meta.json")
        if os.path.isfile(meta_path):
            try:
                with open(meta_path) as f:
                    meta = json.load(f)
                # Check if supposedly-running process is actually still alive
                if meta.get("status") == "running":
                    with _lock:
                        active = _active_runs.get(name)
                    if active:
                        # Have an ActiveRun — check proc or PID
                        if active.proc is not None:
                            if active.proc.poll() is not None:
                                meta["status"] = "unknown"
                        elif active.pid and not _is_pid_alive(active.pid):
                            meta["status"] = "unknown"
                    else:
                        # No ActiveRun tracked — check PID from meta
                        pid = meta.get("pid")
                        if pid and _is_pid_alive(pid):
                            pass  # still running, keep status
                        else:
                            meta["status"] = "unknown"
                results.append(meta)
            except Exception:
                pass
    return results


def get_run(run_id: str) -> dict[str, Any] | None:
    """Get run metadata."""
    meta_path = os.path.join(_run_dir(run_id), "meta.json")
    if not os.path.isfile(meta_path):
        return None
    with open(meta_path) as f:
        return json.load(f)


def get_run_output(run_id: str, offset: int = 0) -> tuple[str, int]:
    """Read run output from the given byte offset.

    Returns (new_output, new_offset) so the caller can poll incrementally.
    Uses the log_path stored in meta.json if present, otherwise falls back
    to the default .runs/{run_id}/output.log.
    """
    # Resolve log path from meta if available
    meta = get_run(run_id)
    log_path = (meta or {}).get("log_path") or os.path.join(_run_dir(run_id), "output.log")
    if not os.path.isfile(log_path):
        return "", 0
    size = os.path.getsize(log_path)
    if offset >= size:
        return "", offset
    with open(log_path, "r", errors="replace") as f:
        f.seek(offset)
        data = f.read()
    return data, size


def stop_run(run_id: str) -> bool:
    """Stop a running process with graceful shutdown.

    Shutdown sequence:
    1. SIGTERM to process group — triggers weave.sh trap (e.g. slice deletion)
    2. Wait up to 30s for PID to die (FABRIC slice deletion can take 30+ seconds)
    3. If still alive: SIGKILL process group as last resort

    Marks the run as user-stopped so _wait_for_proc/_wait_for_pid records it
    as "done" rather than "error".
    """
    with _lock:
        active = _active_runs.get(run_id)
        if not active:
            # No ActiveRun — check if meta has a PID we can kill directly
            meta = get_run(run_id)
            if not meta or meta.get("status") != "running":
                return False
            pid = meta.get("pid")
            pgid = meta.get("pgid")
            if not pid or not _is_pid_alive(pid):
                return False
            _stopped_runs.add(run_id)
            # Fall through to PID-based shutdown below
            return _stop_by_pid(run_id, pid, pgid or pid)
        _stopped_runs.add(run_id)
        pid = active.pid or (active.proc.pid if active.proc else 0)
        pgid = active.pgid or pid

    return _stop_by_pid(run_id, pid, pgid)


def _stop_by_pid(run_id: str, pid: int, pgid: int) -> bool:
    """Send SIGTERM to process group, wait for graceful shutdown, then SIGKILL."""
    # Step 1: SIGTERM to process group
    try:
        os.killpg(pgid, signal.SIGTERM)
        logger.info("Sent SIGTERM to process group %d for run %s", pgid, run_id)
    except ProcessLookupError:
        logger.info("Process group %d already dead for run %s", pgid, run_id)
        return True
    except OSError as e:
        logger.warning("Failed to SIGTERM pgid %d for run %s: %s", pgid, run_id, e)
        # Try individual PID as fallback
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return True

    # Step 2: Wait up to 30s for graceful shutdown (weave.sh trap / slice deletion)
    for _ in range(60):  # 60 * 0.5s = 30s
        if not _is_pid_alive(pid):
            logger.info("Process %d exited gracefully for run %s", pid, run_id)
            return True
        time.sleep(0.5)

    # Step 3: SIGKILL if still alive
    logger.warning("Process %d still alive after 30s, sending SIGKILL for run %s", pid, run_id)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except OSError:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass

    # Brief wait for SIGKILL to take effect
    for _ in range(10):  # 5s
        if not _is_pid_alive(pid):
            break
        time.sleep(0.5)

    return True


def delete_run(run_id: str) -> bool:
    """Delete a completed run's data."""
    meta = get_run(run_id)
    if not meta:
        return False
    if meta.get("status") == "running":
        stop_run(run_id)
    rdir = _run_dir(run_id)
    import shutil
    shutil.rmtree(rdir, ignore_errors=True)
    with _lock:
        _active_runs.pop(run_id, None)
    return True


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _write_meta(run_id: str, meta: dict[str, Any]) -> None:
    meta_path = os.path.join(_run_dir(run_id), "meta.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)


def _clear_weave_active_run(meta: dict[str, Any]) -> None:
    """Remove the active_run entry from the weave's weave.json when a run finishes."""
    weave_dir = meta.get("weave_dir")
    if not weave_dir:
        return
    weave_json_path = os.path.join(weave_dir, "weave.json")
    if not os.path.isfile(weave_json_path):
        return
    try:
        with open(weave_json_path) as f:
            weave_data = json.load(f)
        if "active_run" in weave_data:
            del weave_data["active_run"]
            with open(weave_json_path, "w") as f:
                json.dump(weave_data, f, indent=2)
    except Exception as e:
        logger.debug("Failed to clear active_run from weave.json: %s", e)


def _wait_for_proc(
    run_id: str,
    proc: subprocess.Popen,
    log_fd,
) -> None:
    """Wait for the subprocess to finish and update metadata."""
    try:
        proc.wait()  # No timeout — run until completion
    except Exception:
        pass
    finally:
        try:
            log_fd.close()
        except Exception:
            pass

    exit_code = proc.returncode

    # If the user clicked Stop, treat it as a clean exit regardless of
    # the signal exit code (SIGTERM=-15, SIGKILL=-9).
    with _lock:
        was_stopped = run_id in _stopped_runs
        _stopped_runs.discard(run_id)
        _active_runs.pop(run_id, None)

    meta = get_run(run_id) or {}
    if was_stopped:
        meta["status"] = "done"
        meta["exit_code"] = 0
    else:
        meta["status"] = "done" if exit_code == 0 else "error"
        meta["exit_code"] = exit_code
    meta["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _write_meta(run_id, meta)
    _clear_weave_active_run(meta)

    # Weave finished — invalidate slice cache so frontend sees final state
    get_call_manager().invalidate("slices:list")

    logger.info("Background run %s finished (exit_code=%s)", run_id, exit_code)


# ---------------------------------------------------------------------------
# PID helpers
# ---------------------------------------------------------------------------

def _is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is still running."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # Process exists but we can't signal it


def _wait_for_pid(run_id: str, pid: int) -> None:
    """Poll until a PID exits, then update metadata.

    Used for recovered runs where we don't have a Popen object.
    """
    while _is_pid_alive(pid):
        time.sleep(2)

    # Process exited — update metadata
    with _lock:
        was_stopped = run_id in _stopped_runs
        _stopped_runs.discard(run_id)
        _active_runs.pop(run_id, None)

    meta = get_run(run_id) or {}
    if was_stopped:
        meta["status"] = "done"
        meta["exit_code"] = 0
    else:
        # Can't get exit code for recovered PIDs; mark done (natural exit)
        meta["status"] = "done"
        meta["exit_code"] = None
    meta["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _write_meta(run_id, meta)
    _clear_weave_active_run(meta)
    logger.info("Recovered run %s (pid=%d) finished", run_id, pid)


# ---------------------------------------------------------------------------
# Recovery on startup — reconnect to alive PIDs or mark interrupted
# ---------------------------------------------------------------------------

def recover_stale_runs() -> None:
    """Recover runs that say 'running' by checking if their PID is still alive.

    If the PID is alive, create a monitoring thread to track it.
    If the PID is dead (or missing), mark the run as 'interrupted'.
    """
    rdir = _runs_dir()
    if not os.path.isdir(rdir):
        return
    for name in os.listdir(rdir):
        meta_path = os.path.join(rdir, name, "meta.json")
        if not os.path.isfile(meta_path):
            continue
        try:
            with open(meta_path) as f:
                meta = json.load(f)
            if meta.get("status") != "running":
                continue

            pid = meta.get("pid")
            pgid = meta.get("pgid", pid)

            if pid and _is_pid_alive(pid):
                # Process still alive — reconnect by starting a monitor thread
                t = threading.Thread(
                    target=_wait_for_pid,
                    args=(name, pid),
                    daemon=True,
                )
                t.start()
                with _lock:
                    _active_runs[name] = ActiveRun(
                        run_id=name,
                        proc=None,
                        thread=t,
                        meta=meta,
                        pid=pid,
                        pgid=pgid or pid,
                    )
                logger.info(
                    "Recovered running process for run %s (pid=%d)", name, pid
                )
            else:
                # PID dead or missing — mark interrupted
                meta["status"] = "interrupted"
                meta["finished_at"] = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                )
                _write_meta(name, meta)
                get_call_manager().invalidate("slices:list")
                logger.info("Marked stale run %s as interrupted", name)
        except Exception:
            pass
