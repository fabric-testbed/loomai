"""In-memory background jobs for long assistant operations."""
from __future__ import annotations

import asyncio
import datetime as _dt
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

_MAX_JOBS = 128
_COMPLETED_TTL_SECONDS = 2 * 60 * 60


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _jsonable(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, default=str))
    except Exception:
        return str(value)


@dataclass
class AssistantJob:
    job_id: str
    kind: str
    metadata: dict[str, Any] = field(default_factory=dict)
    status: str = "queued"
    created_at: str = field(default_factory=_now_iso)
    started_at: str | None = None
    finished_at: str | None = None
    result: Any = None
    error: str | None = None


_jobs: dict[str, AssistantJob] = {}
_lock = asyncio.Lock()


async def _prune_locked() -> None:
    cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(seconds=_COMPLETED_TTL_SECONDS)

    def _finished_before(job: AssistantJob) -> bool:
        if job.status not in {"ready", "failed"} or not job.finished_at:
            return False
        try:
            return _dt.datetime.fromisoformat(job.finished_at) < cutoff
        except ValueError:
            return False

    for job_id in [jid for jid, job in _jobs.items() if _finished_before(job)]:
        _jobs.pop(job_id, None)

    if len(_jobs) <= _MAX_JOBS:
        return
    completed = [
        job
        for job in _jobs.values()
        if job.status in {"ready", "failed"}
    ]
    completed.sort(key=lambda job: job.finished_at or job.created_at)
    for job in completed[: max(0, len(_jobs) - _MAX_JOBS)]:
        _jobs.pop(job.job_id, None)


async def _run_job(
    job_id: str,
    work: Callable[[], Awaitable[Any]],
) -> None:
    async with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job.status = "running"
        job.started_at = _now_iso()

    try:
        result = await work()
    except Exception as exc:
        logger.exception("Assistant job %s failed", job_id)
        async with _lock:
            job = _jobs.get(job_id)
            if job:
                job.status = "failed"
                job.finished_at = _now_iso()
                job.error = str(exc)
    else:
        async with _lock:
            job = _jobs.get(job_id)
            if job:
                job.status = "ready"
                job.finished_at = _now_iso()
                job.result = _jsonable(result)


async def start_job(
    kind: str,
    work: Callable[[], Awaitable[Any]],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Start a detached async job and return its identifier."""
    job_id = f"job-{uuid.uuid4().hex[:12]}"
    async with _lock:
        _jobs[job_id] = AssistantJob(
            job_id=job_id,
            kind=kind,
            metadata=_jsonable(metadata or {}),
        )
        await _prune_locked()
    asyncio.create_task(_run_job(job_id, work))
    return job_id


def _job_payload(job: AssistantJob) -> dict[str, Any]:
    payload = {
        "job_id": job.job_id,
        "kind": job.kind,
        "status": job.status,
        "ready": job.status == "ready",
        "done": job.status in {"ready", "failed"},
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        **job.metadata,
    }
    if job.result is not None:
        payload["result"] = job.result
        if isinstance(job.result, dict):
            payload.setdefault("slice_state", job.result.get("state"))
            payload.setdefault("slice_name", job.result.get("name") or job.result.get("slice_name"))
    if job.error:
        payload["error"] = job.error
    return payload


async def get_job_status(
    job_id: str,
    wait_seconds: int = 0,
    poll_interval: float = 2.0,
) -> dict[str, Any]:
    """Return current status, optionally long-polling until the job completes."""
    deadline = asyncio.get_running_loop().time() + max(0, min(int(wait_seconds or 0), 300))
    interval = max(0.25, min(float(poll_interval or 2.0), 10.0))
    while True:
        async with _lock:
            await _prune_locked()
            job = _jobs.get(job_id)
            if not job:
                return {
                    "job_id": job_id,
                    "status": "not_found",
                    "ready": False,
                    "done": True,
                    "error": "Unknown job_id",
                }
            payload = _job_payload(job)
        if payload["done"] or asyncio.get_running_loop().time() >= deadline:
            return payload
        await asyncio.sleep(min(interval, max(0.0, deadline - asyncio.get_running_loop().time())))


async def _clear_jobs_for_tests() -> None:
    async with _lock:
        _jobs.clear()
