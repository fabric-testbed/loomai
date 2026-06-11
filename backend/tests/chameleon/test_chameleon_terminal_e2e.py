"""Chameleon real-provisioning terminal-persistence end-to-end test.

The Chameleon mirror of ``tests/fabric/test_fabric_terminal_e2e.py``: deploy a
real instance, open a server-held SSH terminal to it via ``POST /api/terminals``
(``type="chameleon"``), drive a command over the attach WebSocket, then detach
and reattach to the SAME session and run another command — proving today's
server-held PTY keeps the remote ``cc@`` shell alive across a client reload.

Gate: ``@pytest.mark.chameleon`` — excluded from default runs. Needs a running
backend with a live Chameleon session and an instance reachable by floating IP.

Run::

    pytest tests/chameleon/test_chameleon_terminal_e2e.py -v -s -m chameleon --timeout=1800
"""

import asyncio
import json
import os
import time

import httpx
import pytest

pytestmark = pytest.mark.chameleon

# `websockets` is the project's declared WS dependency (requirements.txt); skip
# cleanly only in an environment where it hasn't been installed.
websockets = pytest.importorskip("websockets", reason="websockets not installed")

BASE_URL = os.environ.get("LOOMAI_BASE_URL", "http://localhost:8000")
WS_BASE = BASE_URL.replace("https://", "wss://").replace("http://", "ws://")
PREFERRED_SITES = ["CHI@UC", "CHI@TACC", "KVM@TACC"]

DEPLOY_TIMEOUT = 600
INSTANCE_POLL = 15
ACTIVE_TIMEOUT = 600
TERM_READY_TIMEOUT = 300      # floating IP resolvable (POST /terminals stops 502'ing)
WS_DRIVE_TIMEOUT = 150


@pytest.fixture(scope="session")
def api():
    return httpx.Client(base_url=f"{BASE_URL}/api", timeout=60.0)


@pytest.fixture(scope="session")
def chameleon_ok(api):
    try:
        resp = api.get("/chameleon/sites")
        if resp.status_code != 200:
            pytest.skip("Chameleon not configured or unreachable")
        sites = resp.json()
    except Exception:
        pytest.skip("Backend not running or Chameleon unavailable")
    # Sites are listed even without credentials; only the ones flagged
    # `configured` can actually lease/deploy. Skip cleanly otherwise.
    configured = [s for s in sites if isinstance(s, dict) and s.get("configured")]
    if not configured:
        pytest.skip("No configured Chameleon sites (credentials not set up)")
    return configured


@pytest.fixture(scope="session")
def site(chameleon_ok):
    names = [s["name"] for s in chameleon_ok]
    for pref in PREFERRED_SITES:
        if pref in names:
            return pref
    return names[0]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_image(api: httpx.Client, site: str) -> str:
    resp = api.get(f"/chameleon/sites/{site}/images")
    if resp.status_code == 200:
        images = resp.json()
        for img in images:
            name = img.get("name", "") if isinstance(img, dict) else img
            if "Ubuntu" in name and "22" in name:
                return name
        if images:
            return images[0].get("name", images[0]) if isinstance(images[0], dict) else images[0]
    return "CC-Ubuntu22.04"


def _find_node_type(api: httpx.Client, site: str) -> str:
    resp = api.get(f"/chameleon/sites/{site}/node-types")
    if resp.status_code == 200:
        data = resp.json()
        types = data.get("node_types", data) if isinstance(data, dict) else data
        if types:
            return types[0]["name"] if isinstance(types[0], dict) else types[0]
    return "compute_skylake"


def _poll_instances_active(api: httpx.Client, slice_id: str, timeout: int = ACTIVE_TIMEOUT) -> list:
    start = time.time()
    while time.time() - start < timeout:
        resp = api.get(f"/chameleon/slices/{slice_id}")
        if resp.status_code == 200:
            resources = resp.json().get("resources", [])
            instances = [r for r in resources if r.get("type") == "instance"]
            if instances:
                if all(i.get("status") == "ACTIVE" for i in instances):
                    return instances
                if any(i.get("status") == "ERROR" for i in instances):
                    pytest.fail(f"Instance(s) entered ERROR: {instances}")
        time.sleep(INSTANCE_POLL)
    pytest.fail(f"Instances did not reach ACTIVE within {timeout}s")


def _cleanup_slice(api: httpx.Client, slice_id: str):
    try:
        api.delete(f"/chameleon/slices/{slice_id}", params={"delete_resources": True}, timeout=120.0)
    except Exception:
        pass


def _create_chameleon_terminal_when_ready(api: httpx.Client, instance_id: str, site: str,
                                          timeout: int = TERM_READY_TIMEOUT) -> dict:
    """POST /terminals for a Chameleon session, retrying while the floating IP
    is still associating (the route 502s until the instance has a reachable IP)."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = api.post("/terminals", json={
            "type": "chameleon", "chameleonInstanceId": instance_id, "chameleonSite": site,
        })
        if r.status_code == 200:
            return r.json()
        last = r
        time.sleep(10)
    detail = f"{last.status_code}: {last.text}" if last is not None else "no response"
    pytest.fail(f"Chameleon terminal for {instance_id} never became creatable ({detail})")


def _attach_drive(session_id: str, ticket: str, command: str, marker: str,
                  total_timeout: int = WS_DRIVE_TIMEOUT) -> str:
    """Attach to the data-plane WebSocket, send *command* (re-sending until its
    output appears), and return the accumulated output once *marker* shows up.
    Opens and closes a fresh connection — modelling a browser attach/reload."""
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

class TestChameleonTerminalPersistence:
    def test_instance_terminal_survives_detach_reattach(self, api, site, chameleon_ok):
        slug = f"e2e-chi-term-{int(time.time())}"
        stamp = str(int(time.time()))
        cmd_a = f"echo MARK_{stamp}_A=$((6*7))"
        want_a = f"MARK_{stamp}_A=42"
        cmd_b = f"echo MARK_{stamp}_B=$((100+23))"
        want_b = f"MARK_{stamp}_B=123"

        slice_id = None
        sid = None
        try:
            # Deploy a single instance.
            resp = api.post("/chameleon/slices", json={"name": slug, "site": site})
            assert resp.status_code == 200, f"Create slice failed: {resp.text}"
            slice_id = resp.json()["id"]
            assert api.post(f"/chameleon/drafts/{slice_id}/nodes", json={
                "name": "node1", "node_type": _find_node_type(api, site),
                "image": _find_image(api, site), "site": site,
            }).status_code == 200
            assert api.post(f"/chameleon/drafts/{slice_id}/deploy", json={
                "lease_name": slug, "duration_hours": 1, "full_deploy": True,
            }, timeout=DEPLOY_TIMEOUT).status_code == 200

            instances = _poll_instances_active(api, slice_id)
            instance_id = instances[0]["id"]

            # 1. Open a server-held SSH terminal to the instance (cc@<floating-ip>).
            meta = _create_chameleon_terminal_when_ready(api, instance_id, site)
            sid = meta["id"]
            assert meta["type"] == "chameleon"
            assert meta["ticket"].startswith(sid + ".")
            assert sid in [s["id"] for s in api.get("/terminals").json()]

            # 2. Attach + run a command — proves ssh-to-instance + PTY I/O.
            out1 = _attach_drive(sid, meta["ticket"], cmd_a, want_a)
            assert want_a in out1, f"first command never executed; got:\n{out1[-800:]}"

            # 3. Reattach with a fresh ticket and run a NEW command — proves the
            #    same remote shell is still alive (not just a buffer replay).
            assert sid in [s["id"] for s in api.get("/terminals").json()]
            tk = api.post(f"/terminals/{sid}/ticket")
            assert tk.status_code == 200
            out2 = _attach_drive(sid, tk.json()["ticket"], cmd_b, want_b)
            assert want_b in out2, f"reattached shell did not execute; got:\n{out2[-800:]}"

            # 4. Explicit close kills the session.
            assert api.delete(f"/terminals/{sid}").status_code == 200
            assert api.post(f"/terminals/{sid}/ticket").status_code == 404
            sid = None
        finally:
            if sid:
                api.delete(f"/terminals/{sid}")
            if slice_id:
                _cleanup_slice(api, slice_id)
