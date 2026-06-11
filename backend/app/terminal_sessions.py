"""In-process terminal sessions (JupyterLab / terminado-style).

The server owns the PTY. A session holds the child process + master fd, a
background reader that broadcasts output to every attached WebSocket client and
into a bounded scrollback buffer, and the current terminal size. A browser
reload reattaches to the same session and replays the buffer to redraw the
screen — no tmux, so the shell is rendered exactly (correct sizing, no status
bar). Shells survive browser disconnects and reconnects (incl. from another
browser/machine — multiple clients share one view); they do not survive a
backend process restart.
"""
from __future__ import annotations

import asyncio
import codecs
import fcntl
import logging
import os
import pty
import signal
import struct
import subprocess
import termios
import time
import uuid

logger = logging.getLogger(__name__)

# Bytes are decoded to text incrementally (so multibyte chars split across reads
# aren't corrupted); the scrollback is capped in characters.
SCROLLBACK_CHARS = 200_000
_READ_CHUNK = 65536


class TerminalSession:
    def __init__(self, session_id: str, type: str, label: str,
                 proc: subprocess.Popen, master_fd: int):
        self.id = session_id
        self.type = type
        self.label = label or type
        self.created = int(time.time())
        self.proc = proc
        self.master_fd = master_fd
        self.cols = 120
        self.rows = 30
        self.detached_at = 0
        self.closed = False

        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._buffer = ""               # decoded scrollback (text)
        self._clients: set[asyncio.Queue] = set()
        self._reader_task: asyncio.Task | None = None

    # --- output ---------------------------------------------------------
    def _ingest(self, data: bytes) -> str:
        text = self._decoder.decode(data)
        if text:
            self._buffer += text
            if len(self._buffer) > SCROLLBACK_CHARS:
                self._buffer = self._buffer[-SCROLLBACK_CHARS:]
        return text

    def snapshot(self) -> str:
        """Recent output to replay so a (re)attaching client redraws."""
        return self._buffer

    # --- client (WebSocket) attach/detach -------------------------------
    def attach(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._clients.add(q)
        self.detached_at = 0
        return q

    def detach(self, q: asyncio.Queue) -> None:
        self._clients.discard(q)
        if not self._clients:
            self.detached_at = int(time.time())

    @property
    def attached(self) -> int:
        return len(self._clients)

    # --- input / resize -------------------------------------------------
    def write(self, data: str) -> None:
        try:
            os.write(self.master_fd, data.encode("utf-8"))
        except OSError:
            pass

    def resize(self, cols: int, rows: int) -> None:
        self.cols, self.rows = cols, rows
        try:
            fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ,
                        struct.pack("HHHH", rows, cols, 0, 0))
        except OSError:
            pass


_sessions: dict[str, TerminalSession] = {}


def is_available() -> bool:
    """Always available — no external dependency (unlike the old tmux backend)."""
    return True


async def _run_reader(session: TerminalSession) -> None:
    """Drain the PTY master without holding a thread: the fd is non-blocking, so
    we read what's available and sleep briefly when idle. Cancelled by kill()."""
    try:
        while not session.closed:
            try:
                data = os.read(session.master_fd, _READ_CHUNK)
            except (BlockingIOError, InterruptedError):
                await asyncio.sleep(0.02)        # nothing ready yet
                continue
            except OSError:
                break                            # fd closed
            if not data:
                break                            # EOF — child exited
            text = session._ingest(data)
            if text:
                for q in list(session._clients):
                    q.put_nowait(text)
    except asyncio.CancelledError:
        raise
    except Exception:                  # noqa: BLE001
        logger.debug("terminal reader stopped", exc_info=True)
    finally:
        session.closed = True
        for q in list(session._clients):
            q.put_nowait(None)         # signal end-of-stream to attached clients


def create(*, type: str, command: list[str], label: str = "",
           cwd: str | None = None, env: dict | None = None) -> TerminalSession:
    """Spawn a PTY-backed session and start its reader. Must be called with a
    running event loop (i.e. from an async route/test).

    *command* is the argv (e.g. ``["/bin/bash", "-l"]`` or an AI tool). *env* is
    a tool-specific overlay merged onto the process environment — secrets go
    here, never onto the argv.
    """
    session_id = uuid.uuid4().hex[:12]
    master_fd, slave_fd = pty.openpty()
    os.set_blocking(master_fd, False)   # reader polls; never holds a thread
    # Sane initial size so the first paint isn't garbled before the client's
    # resize arrives.
    try:
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 120, 0, 0))
    except OSError:
        pass

    full_env = {**os.environ, "TERM": "xterm-256color"}
    if env:
        full_env.update(env)
    run_cwd = cwd if (cwd and os.path.isdir(cwd)) else None

    proc = subprocess.Popen(
        command,
        stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
        cwd=run_cwd,
        preexec_fn=os.setsid,
        env=full_env,
        close_fds=True,
    )
    os.close(slave_fd)

    session = TerminalSession(session_id, type, label, proc, master_fd)
    session._reader_task = asyncio.create_task(_run_reader(session))
    _sessions[session_id] = session
    logger.info("Created terminal session %s (type=%s)", session_id, type)
    return session


def get(session_id: str) -> TerminalSession | None:
    return _sessions.get(session_id)


def exists(session_id: str) -> bool:
    return session_id in _sessions


def meta(session: TerminalSession) -> dict:
    return {
        "id": session.id,
        "type": session.type,
        "label": session.label,
        "created": session.created,
        "attached": session.attached,
    }


def list_sessions() -> list[dict]:
    return [meta(s) for s in _sessions.values()]


def kill(session_id: str) -> bool:
    session = _sessions.pop(session_id, None)
    if not session:
        return False
    session.closed = True
    if session._reader_task:
        session._reader_task.cancel()
    try:
        os.killpg(os.getpgid(session.proc.pid), signal.SIGTERM)
    except Exception:                  # noqa: BLE001
        try:
            session.proc.terminate()
        except Exception:              # noqa: BLE001
            pass
    try:
        os.close(session.master_fd)
    except OSError:
        pass
    logger.info("Killed terminal session %s", session_id)
    return True


def prune_idle(max_idle_seconds: int) -> int:
    """Kill exited sessions and sessions with no attached client idle longer
    than *max_idle_seconds*. Returns the number killed."""
    now = int(time.time())
    killed = 0
    for sid, s in list(_sessions.items()):
        if s.closed:
            kill(sid)
            killed += 1
            continue
        if s.attached == 0 and s.detached_at and now - s.detached_at > max_idle_seconds:
            kill(sid)
            killed += 1
    return killed
