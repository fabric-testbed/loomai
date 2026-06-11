"""Unit tests for Chameleon auth session construction."""

import base64
import json
import urllib.parse

import app.chameleon_manager as cm


class FakeResponse:
    def __init__(self, body: dict, headers: dict[str, str] | None = None):
        self._body = json.dumps(body).encode()
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._body


def test_oidc_password_auth_exchanges_access_token_and_rescopes(monkeypatch):
    cfg = {
        "auth_type": "password",
        "auth_url": "https://chi.uc.chameleoncloud.org:5000/v3",
        "username": "user@example.org",
        "password": "secret",
        "project_id": "project-id",
        "identity_provider": "chameleon",
        "protocol": "openid",
        "discovery_endpoint": "https://auth.example.org/.well-known/openid-configuration",
        "client_id": "keystone-uc-prod",
        "client_secret": "none",
        "access_token_type": "access_token",
        "openid_scope": "openid profile",
    }
    calls = []

    def fake_urlopen(req, timeout):
        calls.append(req)
        url = req.full_url if hasattr(req, "full_url") else req
        if url == cfg["discovery_endpoint"]:
            return FakeResponse({"token_endpoint": "https://auth.example.org/token"})
        if url == "https://auth.example.org/token":
            form = urllib.parse.parse_qs(req.data.decode())
            assert form["grant_type"] == ["password"]
            assert form["username"] == [cfg["username"]]
            assert form["password"] == [cfg["password"]]
            assert form["scope"] == [cfg["openid_scope"]]
            expected_basic = base64.b64encode(b"keystone-uc-prod:none").decode()
            assert req.headers["Authorization"] == f"Basic {expected_basic}"
            return FakeResponse({"access_token": "oidc-access-token"})
        if url.endswith("/OS-FEDERATION/identity_providers/chameleon/protocols/openid/auth"):
            assert req.headers["Authorization"] == "Bearer oidc-access-token"
            return FakeResponse({"token": {}}, {"X-Subject-Token": "unscoped-token"})
        if url.endswith("/auth/tokens"):
            body = json.loads(req.data.decode())
            assert body["auth"]["identity"]["methods"] == ["token"]
            assert body["auth"]["identity"]["token"]["id"] == "unscoped-token"
            assert body["auth"]["scope"]["project"]["id"] == "project-id"
            return FakeResponse({
                "token": {
                    "project": {"id": "project-id"},
                    "expires_at": "2030-01-01T00:00:00Z",
                    "catalog": [
                        {
                            "type": "reservation",
                            "endpoints": [{"interface": "public", "url": "https://blazar.example.org"}],
                        }
                    ],
                }
            }, {"X-Subject-Token": "scoped-token"})
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(cm.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(cm, "add_tracking_headers", lambda headers: headers)

    session = cm._ChameleonSession("CHI@UC", cfg, "cache-key")
    assert session.get_token() == "scoped-token"
    assert session.get_endpoint("reservation") == "https://blazar.example.org"
    assert [req.full_url if hasattr(req, "full_url") else req for req in calls] == [
        cfg["discovery_endpoint"],
        "https://auth.example.org/token",
        "https://chi.uc.chameleoncloud.org:5000/v3/OS-FEDERATION/identity_providers/chameleon/protocols/openid/auth",
        "https://chi.uc.chameleoncloud.org:5000/v3/auth/tokens",
    ]


def test_get_session_uses_shared_password_auth_credentials(monkeypatch):
    created = {}
    site_cfg = {
        "auth_type": "password",
        "auth_url": "https://chi.uc.chameleoncloud.org:5000/v3",
        "project_id": "project-id",
        "client_id": "keystone-uc-prod",
    }

    class FakeSession:
        def __init__(self, site, cfg, cache_key):
            created["site"] = site
            created["cfg"] = cfg
            created["cache_key"] = cache_key

    monkeypatch.setattr(cm, "_ChameleonSession", FakeSession)
    monkeypatch.setattr(cm, "_sessions", {})
    monkeypatch.setattr("app.settings_manager.is_chameleon_enabled", lambda: True)
    monkeypatch.setattr("app.settings_manager.get_chameleon_site_config", lambda site: site_cfg)
    monkeypatch.setattr(
        "app.settings_manager.get_chameleon_password_auth",
        lambda: {"username": "user@example.org", "password": "secret"},
    )
    monkeypatch.setattr("app.settings_manager.is_chameleon_site_configured", lambda site: True)

    session = cm.get_session("CHI@UC")

    assert isinstance(session, FakeSession)
    assert created["site"] == "CHI@UC"
    assert created["cfg"]["username"] == "user@example.org"
    assert created["cfg"]["password"] == "secret"
    assert created["cfg"]["project_id"] == "project-id"
    assert "user@example.org" in created["cache_key"]


def test_list_oidc_projects_uses_unscoped_federation_projects(monkeypatch):
    cfg = {
        "auth_type": "password",
        "auth_url": "https://chi.uc.chameleoncloud.org:5000/v3",
        "username": "user@example.org",
        "password": "secret",
        "identity_provider": "chameleon",
        "protocol": "openid",
        "discovery_endpoint": "https://auth.example.org/.well-known/openid-configuration",
        "client_id": "keystone-uc-prod",
        "client_secret": "none",
        "access_token_type": "access_token",
        "openid_scope": "openid profile",
    }

    def fake_urlopen(req, timeout):
        url = req.full_url if hasattr(req, "full_url") else req
        if url == cfg["discovery_endpoint"]:
            return FakeResponse({"token_endpoint": "https://auth.example.org/token"})
        if url == "https://auth.example.org/token":
            return FakeResponse({"access_token": "oidc-access-token"})
        if url.endswith("/OS-FEDERATION/identity_providers/chameleon/protocols/openid/auth"):
            return FakeResponse({"token": {}}, {"X-Subject-Token": "unscoped-token"})
        if url.endswith("/OS-FEDERATION/projects"):
            assert req.headers["X-auth-token"] == "unscoped-token"
            return FakeResponse({
                "projects": [
                    {"id": "project-a-id", "name": "Project A"},
                    {"id": "project-b-id", "name": "Project B"},
                ]
            })
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(cm.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(cm, "add_tracking_headers", lambda headers: headers)

    session = cm._ChameleonSession("CHI@UC", cfg, "cache-key")
    assert session.list_oidc_projects() == [
        {"id": "project-a-id", "name": "Project A"},
        {"id": "project-b-id", "name": "Project B"},
    ]


def test_authentication_rejects_project_mismatch(monkeypatch):
    cfg = {
        "auth_type": "application_credential",
        "auth_url": "https://chi.uc.chameleoncloud.org:5000/v3",
        "app_credential_id": "cred-id",
        "app_credential_secret": "cred-secret",
        "project_id": "configured-project",
    }

    def fake_urlopen(req, timeout):
        return FakeResponse({
            "token": {
                "project": {"id": "actual-project"},
                "expires_at": "2030-01-01T00:00:00Z",
                "catalog": [],
            }
        }, {"X-Subject-Token": "scoped-token"})

    monkeypatch.setattr(cm.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(cm, "add_tracking_headers", lambda headers: headers)

    session = cm._ChameleonSession("CHI@UC", cfg, "cache-key")
    try:
        session.get_token()
    except RuntimeError as exc:
        assert "settings specify configured-project" in str(exc)
    else:
        raise AssertionError("expected project mismatch to fail")
