"""Tests for the /api/auth/check gate used by nginx auth_request.

Verifies the endpoint's behavior *through* AuthMiddleware, since that is what
nginx relies on to authorize the embedded-tool proxies.
"""
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app import auth as _auth


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("FABRIC_STORAGE_DIR", str(tmp_path))
    _auth._session_secret = None  # isolate signing secret to this tmp dir
    application = FastAPI()
    application.add_middleware(_auth.AuthMiddleware)
    application.include_router(_auth.router)
    try:
        yield application
    finally:
        _auth._session_secret = None


def test_check_passes_when_auth_disabled(app, monkeypatch):
    monkeypatch.setattr(_auth, "is_auth_enabled", lambda: False)
    with TestClient(app) as c:
        r = c.get("/api/auth/check")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_check_rejects_without_session(app, monkeypatch):
    monkeypatch.setattr(_auth, "is_auth_enabled", lambda: True)
    with TestClient(app) as c:
        r = c.get("/api/auth/check")
    assert r.status_code == 401


def test_check_passes_with_valid_session(app, tmp_path, monkeypatch):
    monkeypatch.setattr(_auth, "is_auth_enabled", lambda: True)
    _auth.write_password_hash("hunter2")
    with TestClient(app) as c:
        # /login is public; it sets the session cookie the client then reuses.
        assert c.post("/api/auth/login", json={"password": "hunter2"}).status_code == 200
        r = c.get("/api/auth/check")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_check_rejects_bad_password_login(app, monkeypatch):
    monkeypatch.setattr(_auth, "is_auth_enabled", lambda: True)
    _auth._login_fails.clear()
    _auth.write_password_hash("hunter2")
    with TestClient(app) as c:
        assert c.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
        assert c.get("/api/auth/check").status_code == 401
    _auth._login_fails.clear()


def test_login_brute_force_lockout(app, monkeypatch):
    monkeypatch.setattr(_auth, "is_auth_enabled", lambda: True)
    _auth._login_fails.clear()
    _auth.write_password_hash("hunter2")
    with TestClient(app) as c:
        for _ in range(_auth._LOGIN_MAX_FAILS):
            assert c.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
        # Locked out now — even the correct password is refused with 429.
        r = c.post("/api/auth/login", json={"password": "wrong"})
        assert r.status_code == 429
        assert "Retry-After" in r.headers
        assert c.post("/api/auth/login", json={"password": "hunter2"}).status_code == 429
    _auth._login_fails.clear()
