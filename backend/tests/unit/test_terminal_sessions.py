"""Unit tests for the in-process (JupyterLab/terminado-style) terminal manager.

The server owns the PTY; these tests spawn real shells, drive them, and assert
the buffer/broadcast/detach/cull behavior. They run on the event loop
(asyncio_mode=auto) since create() starts a reader task.
"""
import asyncio
import os
import subprocess

import pytest

import app.terminal_sessions as ts


@pytest.fixture()
def cleanup():
    created: list[str] = []
    yield created
    for sid in created:
        ts.kill(sid)


async def _wait_for(session, text: str, timeout: float = 4.0) -> bool:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if text in session.snapshot():
            return True
        await asyncio.sleep(0.05)
    return False


async def test_create_meta_and_output(cleanup):
    s = ts.create(type="local", command=["/bin/sh", "-c", "printf READY; sleep 30"])
    cleanup.append(s.id)
    assert len(s.id) == 12
    m = ts.meta(s)
    assert m["type"] == "local" and m["attached"] == 0 and m["id"] == s.id
    assert ts.exists(s.id) and ts.get(s.id) is s
    assert await _wait_for(s, "READY")
    assert s.id in [x["id"] for x in ts.list_sessions()]


async def test_buffer_replays_on_attach(cleanup):
    s = ts.create(type="local", command=["/bin/sh", "-c", "printf HELLO-REPLAY; sleep 30"])
    cleanup.append(s.id)
    assert await _wait_for(s, "HELLO-REPLAY")
    # A freshly attaching client gets the prior output (screen redraw).
    assert "HELLO-REPLAY" in s.snapshot()


async def test_broadcast_to_multiple_clients(cleanup):
    s = ts.create(type="local", command=["/bin/sh"])
    cleanup.append(s.id)
    q1 = s.attach()
    q2 = s.attach()
    assert s.attached == 2
    s.write("echo SHARED-OUT\n")
    got1 = await asyncio.wait_for(_collect_until(q1, "SHARED-OUT"), timeout=4)
    got2 = await asyncio.wait_for(_collect_until(q2, "SHARED-OUT"), timeout=4)
    assert got1 and got2


async def _collect_until(q: asyncio.Queue, needle: str) -> bool:
    acc = ""
    while True:
        chunk = await q.get()
        if chunk is None:
            return needle in acc
        acc += chunk
        if needle in acc:
            return True


async def test_detach_keeps_session_alive(cleanup):
    s = ts.create(type="local", command=["/bin/sh", "-c", "printf STILL-HERE; sleep 30"])
    cleanup.append(s.id)
    assert await _wait_for(s, "STILL-HERE")
    q = s.attach()
    s.detach(q)
    assert s.attached == 0
    assert ts.exists(s.id)            # detach != kill
    assert "STILL-HERE" in s.snapshot()


async def test_kill_removes_session(cleanup):
    s = ts.create(type="local", command=["/bin/sh", "-c", "sleep 30"])
    sid = s.id
    assert ts.kill(sid) is True
    assert ts.exists(sid) is False and ts.get(sid) is None
    assert ts.kill(sid) is False


async def test_env_reaches_process_not_argv(cleanup):
    secret = "s3cr3t-TOKEN-xyz"
    s = ts.create(
        type="ai", command=["/bin/sh", "-c", 'printf "%s" "$SECRET_TOKEN"; sleep 30'],
        env={"SECRET_TOKEN": secret},
    )
    cleanup.append(s.id)
    assert await _wait_for(s, secret)           # delivered via env
    cmdline = subprocess.run(
        ["ps", "-ww", "-o", "args=", "-p", str(s.proc.pid)],
        capture_output=True, text=True,
    ).stdout
    assert secret not in cmdline                # never on the argv


async def test_prune_idle_kills_unattached(cleanup):
    s = ts.create(type="local", command=["/bin/sh", "-c", "sleep 30"])
    cleanup.append(s.id)
    q = s.attach()
    s.detach(q)                                  # stamps detached_at
    assert ts.prune_idle(max_idle_seconds=3600) == 0   # recent → kept
    assert ts.exists(s.id)
    s.detached_at -= 7200                          # pretend it's been idle 2h
    assert ts.prune_idle(max_idle_seconds=3600) >= 1
    assert not ts.exists(s.id)


async def test_prune_removes_exited_session(cleanup):
    s = ts.create(type="local", command=["/bin/sh", "-c", "exit 0"])
    cleanup.append(s.id)
    # Wait for the shell to exit and the reader to mark it closed.
    loop = asyncio.get_event_loop()
    deadline = loop.time() + 4
    while loop.time() < deadline and not s.closed:
        await asyncio.sleep(0.05)
    assert s.closed
    assert ts.prune_idle(max_idle_seconds=10_000) >= 1
    assert not ts.exists(s.id)
