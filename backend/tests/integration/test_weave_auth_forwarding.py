"""Auth forwarding coverage for background weave helpers."""

from __future__ import annotations

import importlib.util
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _load_chameleon_helper():
    helper_path = (
        Path(__file__).resolve().parents[2]
        / "default_artifacts"
        / "Chameleon_SSH_Slice"
        / "chameleon_ssh_slice.py"
    )
    spec = importlib.util.spec_from_file_location("chameleon_ssh_slice_test", helper_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def auth_settings_server(tmp_path, monkeypatch):
    from app import auth as auth_mod
    from app.routes import config

    storage = tmp_path / "storage"
    storage.mkdir()
    monkeypatch.setenv("FABRIC_STORAGE_DIR", str(storage))
    monkeypatch.setenv("LOOMAI_AUTH_ENABLED", "1")
    monkeypatch.delenv("LOOMAI_NO_AUTH", raising=False)
    monkeypatch.delenv("LOOMAI_BASE_PATH", raising=False)
    auth_mod._session_secret = None

    app = FastAPI()
    app.add_middleware(auth_mod.AuthMiddleware)
    app.include_router(config.router)

    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            access_log=False,
            log_level="error",
            lifespan="off",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 5
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=2)
        raise RuntimeError("Test auth server did not start")

    try:
        yield f"http://127.0.0.1:{port}", auth_mod._make_session_token()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        auth_mod._session_secret = None


def test_chameleon_helper_uses_session_cookie_for_protected_settings(
    auth_settings_server,
    monkeypatch,
):
    base_url, session_cookie = auth_settings_server
    helper = _load_chameleon_helper()

    monkeypatch.setenv("LOOMAI_API_URL", f"{base_url}/api")
    monkeypatch.delenv("LOOMAI_SESSION_COOKIE", raising=False)
    with pytest.raises(RuntimeError, match="HTTP 401"):
        helper.loomai_request("GET", "/settings", timeout=5)

    monkeypatch.setenv("LOOMAI_SESSION_COOKIE", session_cookie)
    settings = helper.loomai_request("GET", "/settings", timeout=5)

    assert isinstance(settings, dict)
    assert "loomai_session" not in str(settings)
