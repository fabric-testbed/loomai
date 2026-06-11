"""FABRIC real-provisioning terminal-persistence end-to-end test.

Exercises today's *server-held PTY* node terminals against a real FABRIC node:
provision a 1-node slice, open an SSH terminal via ``POST /api/terminals``
(the server runs ``ssh`` to the node through the bastion and holds the PTY),
drive a command over the attach WebSocket, then **detach and reattach** to the
SAME session and run another command — proving the remote shell survives a
client disconnect (browser reload) the way JupyterLab terminals do.

Gate: ``@pytest.mark.fabric`` — excluded from default runs. Needs a running
backend with valid FABRIC credentials.

Run::

    pytest tests/fabric/test_fabric_terminal_e2e.py -v -s -m fabric --timeout=1200
"""

import asyncio
import json
import os
import time

import httpx
import pytest

pytestmark = pytest.mark.fabric

# `websockets` is the project's declared WS dependency (requirements.txt); skip
# cleanly only in an environment where it hasn't been installed.
websockets = pytest.importorskip("websockets", reason="websockets not installed")

BASE_URL = os.environ.get("LOOMAI_BASE_URL", "http://localhost:8000")
WS_BASE = BASE_URL.replace("https://", "wss://").replace("http://", "ws://")

SUBMIT_TIMEOUT = 120
STABLE_TIMEOUT = 600
POLL_INTERVAL = 15
EXEC_TIMEOUT = 60
SSH_WAIT_TIMEOUT = 300        # node reachable via the bastion ('echo ok') after StableOK
TERM_READY_TIMEOUT = 240      # node SSH/mgmt-IP resolvable (POST /terminals stops 502'ing)
WS_DRIVE_TIMEOUT = 120        # PTY attach + ssh handshake + command echo


@pytest.fixture(scope="session")
def api():
    return httpx.Client(base_url=f"{BASE_URL}/api", timeout=60.0)


@pytest.fixture(scope="session")
def fabric_ok(api):
    """Ensure FABRIC is configured with a valid token."""
    try:
        resp = api.get("/config")
        if resp.status_code != 200:
            pytest.skip("Backend not running")
        data = resp.json()
        exp = data.get("token_info", {}).get("exp", 0)
        if exp * 1000 < time.time() * 1000:
            pytest.skip("FABRIC token expired — re-login required")
        return data
    except Exception:
        pytest.skip("Backend not running or unreachable")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wait_stable_ok(api: httpx.Client, name: str, timeout: int = STABLE_TIMEOUT) -> dict:
    start = time.time()
    while time.time() - start < timeout:
        resp = api.get(f"/slices/{name}")
        if resp.status_code == 200:
            data = resp.json()
            state = data.get("state", "")
            if state == "StableOK":
                return data
            if state in ("StableError", "Dead"):
                pytest.fail(f"Slice '{name}' entered {state}: {data.get('error_messages', [])}")
        time.sleep(POLL_INTERVAL)
    pytest.fail(f"Slice '{name}' did not reach StableOK within {timeout}s")


def _cleanup_slice(api: httpx.Client, name: str):
    try:
        api.delete(f"/slices/{name}", timeout=120.0)
    except Exception:
        pass


def _exec_on_node(api: httpx.Client, slice_name: str, node_name: str, command: str,
                  timeout: int = EXEC_TIMEOUT) -> dict:
    resp = api.post(f"/files/vm/{slice_name}/{node_name}/execute",
                    json={"command": command}, timeout=float(timeout))
    resp.raise_for_status()
    return resp.json()


def _wait_ssh_ready(api: httpx.Client, slice_name: str, node_name: str,
                    timeout: int = SSH_WAIT_TIMEOUT) -> bool:
    """Poll until the node answers over the bastion. A node can be StableOK
    before sshd / the mgmt route is up, and the server-held PTY's ssh would then
    die with 'stdio forwarding failed' — so gate the attach on real reachability."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = _exec_on_node(api, slice_name, node_name, "echo ok", timeout=20)
            if "ok" in (r.get("stdout") or ""):
                return True
        except Exception:
            pass
        time.sleep(10)
    return False


def _create_ssh_terminal_when_ready(api: httpx.Client, name: str, node: str,
                                    timeout: int = TERM_READY_TIMEOUT) -> dict:
    """POST /terminals for an SSH node session, retrying while the node's mgmt
    IP / SSH is still coming up (the route returns 502 until resolvable)."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = api.post("/terminals", json={"type": "ssh", "sliceName": name, "nodeName": node})
        if r.status_code == 200:
            return r.json()
        last = r
        time.sleep(10)
    detail = f"{last.status_code}: {last.text}" if last is not None else "no response"
    pytest.fail(f"SSH terminal for {name}/{node} never became creatable ({detail})")


def _attach_drive(session_id: str, ticket: str, command: str, marker: str,
                  total_timeout: int = WS_DRIVE_TIMEOUT) -> str:
    """Attach to the data-plane WebSocket, send *command* (re-sending until its
    output appears, to ride out ssh-handshake latency), and return the
    accumulated output once *marker* shows up. Opens and closes a fresh
    connection — modelling a browser attach/reload cycle."""
    uri = f"{WS_BASE}/ws/terminal/attach/{session_id}?ticket={ticket}"

    async def _run() -> str:
        buf = ""
        async with websockets.connect(uri, open_timeout=30, max_size=None) as ws:
            loop = asyncio.get_event_loop()
            await ws.send(json.dumps({"type": "resize", "cols": 120, "rows": 40}))
            deadline = loop.time() + total_timeout
            last_send = 0.0
            while loop.time() < deadline:
                if loop.time() - last_send > 8:
                    await ws.send(json.dumps({"type": "input", "data": command + "\n"}))
                    last_send = loop.time()
                try:
                    data = await asyncio.wait_for(ws.recv(), timeout=2)
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    break
                if isinstance(data, (bytes, bytearray)):
                    data = data.decode("utf-8", "ignore")
                buf += data
                if marker in buf:
                    return buf
        return buf

    return asyncio.run(_run())


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

class TestFabricTerminalPersistence:
    def test_node_terminal_survives_detach_reattach(self, api, fabric_ok):
        name = f"e2e-fab-term-{int(time.time())}"
        stamp = str(int(time.time()))
        # Markers use arithmetic the shell must *evaluate*, so finding them proves
        # remote execution (not just the PTY echoing our keystrokes back).
        cmd_a = f"echo MARK_{stamp}_A=$((6*7))"
        want_a = f"MARK_{stamp}_A=42"
        cmd_b = f"echo MARK_{stamp}_B=$((100+23))"
        want_b = f"MARK_{stamp}_B=123"

        sid = None
        try:
            assert api.post(f"/slices?name={name}").status_code == 200
            assert api.post(f"/slices/{name}/nodes", json={
                "name": "node1", "site": "auto", "cores": 2, "ram": 8, "disk": 10,
                "image": "default_ubuntu_22",
            }).status_code == 200
            assert api.post(f"/slices/{name}/submit", timeout=SUBMIT_TIMEOUT).status_code == 200
            _wait_stable_ok(api, name)
            assert _wait_ssh_ready(api, name, "node1"), \
                "node never became SSH-reachable via the bastion"

            # 1. Open a server-held SSH terminal to the node.
            meta = _create_ssh_terminal_when_ready(api, name, "node1")
            sid = meta["id"]
            assert meta["type"] == "ssh"
            assert meta["ticket"].startswith(sid + ".")
            assert sid in [s["id"] for s in api.get("/terminals").json()]

            # 2. Attach + run a command — proves ssh-to-real-node + PTY I/O.
            out1 = _attach_drive(sid, meta["ticket"], cmd_a, want_a)
            assert want_a in out1, f"first command never executed on node; got:\n{out1[-800:]}"

            # 3. Session is still alive server-side after the client detached.
            assert sid in [s["id"] for s in api.get("/terminals").json()]

            # 4. Reattach with a FRESH ticket and run a NEW command. want_b was
            #    never in the buffer before, so seeing it proves the same remote
            #    shell is still live (true persistence, not just buffer replay).
            tk = api.post(f"/terminals/{sid}/ticket")
            assert tk.status_code == 200
            out2 = _attach_drive(sid, tk.json()["ticket"], cmd_b, want_b)
            assert want_b in out2, f"reattached shell did not execute; got:\n{out2[-800:]}"

            # 5. Explicit close kills the session for everyone.
            assert api.delete(f"/terminals/{sid}").status_code == 200
            assert api.post(f"/terminals/{sid}/ticket").status_code == 404
            sid = None
        finally:
            if sid:
                api.delete(f"/terminals/{sid}")
            _cleanup_slice(api, name)
