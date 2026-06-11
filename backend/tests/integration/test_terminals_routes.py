"""Integration tests for persistent-terminal routes + attach WebSocket auth.

Builds a minimal app with just the terminal router so we don't pay the full
main.py lifespan cost. Exercises real tmux on the dedicated socket.
"""
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import app.terminal_sessions as ts
from app.routes import terminal as term_routes
from app import auth as _auth

pytestmark = pytest.mark.skipif(not ts.is_available(), reason="tmux not installed")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FABRIC_STORAGE_DIR", str(tmp_path))
    # Default: auth off (standalone dev-style) unless a test flips it.
    monkeypatch.setattr(_auth, "is_auth_enabled", lambda: False)
    app = FastAPI()
    app.include_router(term_routes.router)
    created: list[str] = []
    with TestClient(app) as c:
        c._created = created  # type: ignore[attr-defined]
        yield c
    for sid in created:
        ts.kill(sid)


def _create(client) -> dict:
    r = client.post("/api/terminals", json={"type": "local"})
    assert r.status_code == 200, r.text
    meta = r.json()
    client._created.append(meta["id"])  # type: ignore[attr-defined]
    return meta


def test_create_returns_id_and_ticket(client):
    meta = _create(client)
    assert meta["type"] == "local"
    assert len(meta["id"]) == 12
    assert meta["ticket"].startswith(meta["id"] + ".")


def test_list_and_delete(client):
    meta = _create(client)
    ids = [m["id"] for m in client.get("/api/terminals").json()]
    assert meta["id"] in ids

    assert client.delete(f"/api/terminals/{meta['id']}").status_code == 200
    ids2 = [m["id"] for m in client.get("/api/terminals").json()]
    assert meta["id"] not in ids2
    assert client.delete(f"/api/terminals/{meta['id']}").status_code == 404


def test_ticket_for_unknown_session_404(client):
    assert client.post("/api/terminals/deadbeefdead/ticket").status_code == 404


def test_unsupported_type_rejected(client):
    assert client.post("/api/terminals", json={"type": "ai"}).status_code == 400


def test_attach_requires_auth_when_enabled(client, monkeypatch):
    """The headline regression: with auth ON, an unauthenticated attach is
    rejected (closed) before the socket is accepted."""
    meta = _create(client)
    monkeypatch.setattr(_auth, "is_auth_enabled", lambda: True)

    # No ticket, no cookie → server closes with 1008 before accept.
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/ws/terminal/attach/{meta['id']}") as ws:
            ws.receive_text()
    assert exc.value.code == 1008

    # A bogus ticket is likewise rejected.
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/ws/terminal/attach/{meta['id']}?ticket=not.a.real.ticket"
        ) as ws:
            ws.receive_text()


def test_ssh_argv_builder(monkeypatch):
    from app.routes import terminal as term
    monkeypatch.setattr(term, "_get_ssh_config", lambda slice_name=None: {
        "bastion_host": "bastion.example",
        "bastion_username": "buser",
        "bastion_key": "/keys/bastion",
        "slice_key": "/keys/slice",
    })
    argv = term._build_node_ssh_argv("sl", "10.0.0.5", "ubuntu")
    assert argv[0] == "ssh" and "-tt" in argv
    assert argv[-1] == "ubuntu@10.0.0.5"
    assert "/keys/slice" in argv                       # -i slice key
    proxy = [a for a in argv if a.startswith("ProxyCommand=")]
    assert proxy and "buser@bastion.example" in proxy[0] and "/keys/bastion" in proxy[0]
    # IPv6-safe bracketed forwarding spec (bare %h:%p breaks on IPv6 mgmt IPs).
    assert "-W [%h]:%p" in proxy[0]


def test_ssh_argv_ipv6_target(monkeypatch):
    from app.routes import terminal as term
    monkeypatch.setattr(term, "_get_ssh_config", lambda slice_name=None: {
        "bastion_host": "bastion.example", "bastion_username": "buser",
        "bastion_key": "/keys/bastion", "slice_key": "/keys/slice",
    })
    ipv6 = "2001:400:a100:3080:f816:3eff:feb3:9d4"
    argv = term._build_node_ssh_argv("sl", ipv6, "ubuntu")
    assert argv[-1] == f"ubuntu@{ipv6}"               # bare IPv6 is a valid ssh destination


def test_ssh_create_route(client, monkeypatch):
    from app.routes import terminal as term
    monkeypatch.setattr(term, "_lookup_node_ssh", lambda s, n: ("10.0.0.5", "ubuntu"))
    # Don't spawn a real ssh in the test — use a harmless placeholder command.
    monkeypatch.setattr(term, "_build_node_ssh_argv",
                        lambda s, ip, u: ["/bin/sh", "-c", "sleep 30"])
    r = client.post("/api/terminals", json={
        "type": "ssh", "sliceName": "sl", "nodeName": "n1", "managementIp": "10.0.0.5",
    })
    assert r.status_code == 200, r.text
    meta = r.json()
    client._created.append(meta["id"])  # type: ignore[attr-defined]
    assert meta["type"] == "ssh"
    assert meta["label"] == "n1"
    assert meta["ticket"].startswith(meta["id"] + ".")
    assert ts.exists(meta["id"])


def test_ssh_create_requires_slice_and_node(client):
    assert client.post("/api/terminals", json={"type": "ssh"}).status_code == 400


def test_chameleon_key_path_requires_named_match_for_named_keypair(tmp_path, monkeypatch):
    from app.routes import chameleon as chm
    import app.settings_manager as sm

    monkeypatch.setenv("FABRIC_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(sm, "load_settings", lambda: {"chameleon": {}})
    generic = tmp_path / "chameleon_key"
    generic.write_text("generic")
    named = tmp_path / "chameleon_key_project-key"
    named.write_text("named")

    assert chm.get_chameleon_key_path("CHI@TACC", "project-key") == str(named)
    named.unlink()
    assert chm.get_chameleon_key_path("CHI@TACC", "project-key") == ""
    assert chm.get_chameleon_key_path("CHI@TACC", "loomai-key") == str(generic)


def test_chameleon_record_key_lookup_uses_slice_node_metadata():
    from app.routes import chameleon as chm
    from app.routes import terminal as term

    with chm._chameleon_slices_lock:
        old = dict(chm._chameleon_slices)
        chm._chameleon_slices.clear()
        chm._chameleon_slices["slice-1"] = {
            "site": "CHI@TACC",
            "nodes": [{"instance_id": "inst-1", "key_name": "project-key"}],
        }
    try:
        assert term._lookup_chameleon_record_key_name("CHI@TACC", "inst-1") == "project-key"
    finally:
        with chm._chameleon_slices_lock:
            chm._chameleon_slices.clear()
            chm._chameleon_slices.update(old)


def test_chameleon_argv_builder(monkeypatch):
    from app.routes import terminal as term
    import app.routes.chameleon as chm
    monkeypatch.setattr(chm, "get_chameleon_key_path", lambda site, key_name="": "/keys/chi")
    argv = term._build_chameleon_ssh_argv("CHI@TACC", "1.2.3.4", "project-key")
    assert argv[0] == "ssh" and "-tt" in argv
    assert argv[-1] == "cc@1.2.3.4"
    assert "/keys/chi" in argv


def test_chameleon_argv_builder_reports_missing_keypair(monkeypatch):
    from app.routes import terminal as term
    import app.routes.chameleon as chm
    monkeypatch.setattr(chm, "get_chameleon_key_path", lambda site, key_name="": "/keys/generic")
    argv = term._build_chameleon_ssh_argv("CHI@TACC", "1.2.3.4", "")
    assert argv[0:2] == ["/bin/bash", "-lc"]
    assert "does not report a Nova keypair" in argv[2]
    assert "/keys/generic" not in argv[2]


def test_chameleon_create_route(client, monkeypatch):
    from app.routes import terminal as term
    monkeypatch.setattr(term, "_lookup_chameleon_ip", lambda site, iid: ("1.2.3.4", "myinst", "project-key"))
    monkeypatch.setattr(term, "_build_chameleon_ssh_argv",
                        lambda site, ip, key_name="": ["/bin/sh", "-c", "sleep 30"])
    r = client.post("/api/terminals", json={
        "type": "chameleon", "chameleonInstanceId": "i-1", "chameleonSite": "CHI@TACC",
    })
    assert r.status_code == 200, r.text
    meta = r.json()
    client._created.append(meta["id"])  # type: ignore[attr-defined]
    assert meta["type"] == "chameleon" and meta["label"] == "myinst"
    assert ts.exists(meta["id"])


def test_chameleon_create_requires_params(client):
    assert client.post("/api/terminals", json={"type": "chameleon"}).status_code == 400


def test_ai_create_route(tmp_path, monkeypatch):
    """The AI create route turns a prepared launch into a tmux session + ticket.

    build_ai_tool_launch is mocked so the test needs no API key or tool install.
    """
    monkeypatch.setenv("FABRIC_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(_auth, "is_auth_enabled", lambda: False)
    from app.routes import ai_terminal

    async def fake_launch(tool, model="", cwd="", progress_cb=None):
        return (["/bin/sh", "-c", "sleep 60"], {"FAKE_KEY": "v"}, str(tmp_path))

    monkeypatch.setattr(ai_terminal, "build_ai_tool_launch", fake_launch)

    app = FastAPI()
    app.include_router(ai_terminal.router)
    created: list[str] = []
    try:
        with TestClient(app) as c:
            # Unknown tool rejected.
            assert c.post("/api/terminals/ai", json={"tool": "nope"}).status_code == 400
            # Known tool → tmux session + ticket.
            r = c.post("/api/terminals/ai", json={"tool": "claude"})
            assert r.status_code == 200, r.text
            meta = r.json()
            created.append(meta["id"])
            assert meta["type"] == "ai-claude"
            assert meta["ticket"].startswith(meta["id"] + ".")
            assert ts.exists(meta["id"])
    finally:
        for sid in created:
            ts.kill(sid)


def test_ssh_terminal_requires_auth(client, monkeypatch):
    """SSH node terminal closes before accept when auth is on and no cookie."""
    monkeypatch.setattr(_auth, "is_auth_enabled", lambda: True)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/terminal/myslice/node1") as ws:
            ws.receive_text()
    assert exc.value.code == 1008


def test_chameleon_terminal_requires_auth(client, monkeypatch):
    """Chameleon terminal closes before accept when auth is on and no cookie."""
    monkeypatch.setattr(_auth, "is_auth_enabled", lambda: True)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/terminal/chameleon/inst-123?site=CHI@TACC") as ws:
            ws.receive_text()
    assert exc.value.code == 1008


def test_legacy_container_requires_auth(client, monkeypatch):
    """Legacy /ws/terminal/container is now gated (closes the unauth RCE)."""
    monkeypatch.setattr(_auth, "is_auth_enabled", lambda: True)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/terminal/container") as ws:
            ws.receive_text()
    assert exc.value.code == 1008


def test_logs_ws_requires_auth(client, monkeypatch):
    """The log-tail socket is gated too."""
    monkeypatch.setattr(_auth, "is_auth_enabled", lambda: True)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/logs") as ws:
            ws.receive_text()
    assert exc.value.code == 1008


def test_attach_with_valid_ticket_accepts(client, monkeypatch):
    meta = _create(client)
    monkeypatch.setattr(_auth, "is_auth_enabled", lambda: True)
    # Fresh ticket from the authed control-plane endpoint.
    ticket = client.post(f"/api/terminals/{meta['id']}/ticket").json()["ticket"]
    with client.websocket_connect(
        f"/ws/terminal/attach/{meta['id']}?ticket={ticket}"
    ) as ws:
        # tmux paints the pane on attach; we should receive *something*.
        ws.send_text('{"type":"resize","cols":80,"rows":24}')
        data = ws.receive_text()
        assert isinstance(data, str)
