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
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.user_context import get_user_storage

logger = logging.getLogger(__name__)

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
    proc: subprocess.Popen
    thread: threading.Thread
    meta: dict[str, Any] = field(default_factory=dict)


_active_runs: dict[str, ActiveRun] = {}
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
) -> str:
    """Start a background run. Returns the run_id.

    Args:
        script_args: Dict of env vars to pass to the script (e.g. SLICE_NAME, NUM_RUNS).
        slice_name: Legacy param — used if script_args doesn't contain SLICE_NAME.
    """
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    rdir = _run_dir(run_id)
    os.makedirs(rdir, exist_ok=True)

    # Merge legacy slice_name with new args dict
    args = dict(script_args or {})
    if slice_name and "SLICE_NAME" not in args:
        args["SLICE_NAME"] = slice_name

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
    }
    _write_meta(run_id, meta)

    log_path = os.path.join(rdir, "output.log")
    env = {**os.environ, **args}
    cmd = ["bash", script_path]
    # Pass SLICE_NAME as positional arg for backward compat with scripts using $1
    if args.get("SLICE_NAME"):
        cmd.append(args["SLICE_NAME"])

    log_fd = open(log_path, "w")

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

    t = threading.Thread(
        target=_wait_for_proc,
        args=(run_id, proc, log_fd),
        daemon=True,
    )
    t.start()

    with _lock:
        _active_runs[run_id] = ActiveRun(
            run_id=run_id, proc=proc, thread=t, meta=meta,
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
                    if not active or active.proc.poll() is not None:
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
    """
    log_path = os.path.join(_run_dir(run_id), "output.log")
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
    """Stop a running process."""
    with _lock:
        active = _active_runs.get(run_id)
    if not active:
        return False
    try:
        active.proc.terminate()
        # Give it a moment to terminate gracefully
        try:
            active.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            active.proc.kill()
        return True
    except Exception:
        return False


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
    meta = get_run(run_id) or {}
    meta["status"] = "done" if exit_code == 0 else "error"
    meta["exit_code"] = exit_code
    meta["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _write_meta(run_id, meta)

    with _lock:
        _active_runs.pop(run_id, None)

    logger.info("Background run %s finished (exit_code=%s)", run_id, exit_code)


# ---------------------------------------------------------------------------
# Recovery on startup — mark stale "running" entries
# ---------------------------------------------------------------------------

def recover_stale_runs() -> None:
    """Mark runs that say 'running' but have no active process as 'interrupted'."""
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
            if meta.get("status") == "running":
                meta["status"] = "interrupted"
                meta["finished_at"] = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                )
                _write_meta(name, meta)
                logger.info("Marked stale run %s as interrupted", name)
        except Exception:
            pass
