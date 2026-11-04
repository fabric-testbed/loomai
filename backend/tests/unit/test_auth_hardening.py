"""Session revocation, trusted client IP, and WebSocket Origin checks."""
import os
import stat
from types import SimpleNamespace

import pytest


@pytest.fixture()
def auth(tmp_path, monkeypatch):
    monkeypatch.setenv("FABRIC_STORAGE_DIR", str(tmp_path))
    monkeypatch.delenv("LOOMAI_TRUST_PROXY", raising=False)
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    import app.auth as a
    prev_secret, prev_rev = a._session_secret, a._revocation_cache
    a._session_secret = None
    a._revocation_cache = None
    (tmp_path / ".loomai").mkdir()
    a.write_password_hash("first")
    try:
        yield a
    finally:
        a._session_secret, a._revocation_cache = prev_secret, prev_rev


class TestSessionRevocation:
    def test_token_validates_and_has_generation(self, auth):
        tok = auth._make_session_token()
        assert tok.count(".") == 2
        assert auth._validate_session_token(tok)

    def test_password_change_invalidates_existing_tokens(self, auth):
        old = auth._make_session_token()
        auth.write_password_hash("second")
        assert not auth._validate_session_token(old)
        assert auth._validate_session_token(auth._make_session_token())

    def test_logout_revokes_all_tokens(self, auth):
        old = auth._make_session_token()
        auth.revoke_all_sessions()
        assert not auth._validate_session_token(old)
        assert auth._validate_session_token(auth._make_session_token())
        # Persisted: a restart (cold cache) still rejects the old token.
        auth._revocation_cache = None
        assert not auth._validate_session_token(old)

    def test_two_logouts_within_one_second_revoke_the_token_between_them(self, auth, monkeypatch):
        import time as _t
        monkeypatch.setattr(_t, "time", lambda: 1_800_000_000)  # freeze the clock
        auth.revoke_all_sessions()
        between = auth._make_session_token()
        assert auth._validate_session_token(between)
        auth.revoke_all_sessions()                 # same second
        assert not auth._validate_session_token(between)

    def test_legacy_two_part_token_rejected(self, auth):
        assert not auth._validate_session_token("1700000000.deadbeef")

    def test_logout_route_revokes(self, auth):
        old = auth._make_session_token()
        auth.auth_logout()
        assert not auth._validate_session_token(old)


def _req(peer, xff=None):
    headers = {"x-forwarded-for": xff} if xff else {}
    return SimpleNamespace(headers=headers, client=SimpleNamespace(host=peer) if peer else None)


class TestClientIp:
    def test_direct_peer_ignores_forwarded_header(self, auth):
        # A remote client cannot pick its lockout key.
        assert auth._client_ip(_req("203.0.113.9", "1.1.1.1")) == "203.0.113.9"

    def test_behind_own_nginx_uses_the_entry_nginx_added(self, auth):
        # nginx appends the real client to whatever the client sent.
        assert auth._client_ip(_req("127.0.0.1", "1.1.1.1, 203.0.113.9")) == "203.0.113.9"
        assert auth._client_ip(_req("127.0.0.1", "203.0.113.9")) == "203.0.113.9"

    def test_loopback_without_header_is_loopback(self, auth):
        assert auth._client_ip(_req("127.0.0.1")) == "127.0.0.1"

    def test_trusted_proxy_opt_in(self, auth, monkeypatch):
        monkeypatch.setenv("LOOMAI_TRUST_PROXY", "1")
        assert auth._client_ip(_req("10.0.0.5", "1.1.1.1, 203.0.113.9")) == "203.0.113.9"

    def test_no_client(self, auth):
        assert auth._client_ip(_req(None)) == "unknown"


class TestWebSocketOrigin:
    @pytest.fixture()
    def ta(self, auth):
        import app.terminal_auth as ta
        return ta

    def test_same_origin_allowed(self, ta):
        assert ta.origin_allowed({"origin": "https://loomai.example.org", "host": "loomai.example.org"})
        assert ta.origin_allowed({"origin": "http://localhost:8000", "host": "localhost:8000"})

    def test_dev_server_origin_allowed_by_default_list(self, ta):
        assert ta.origin_allowed({"origin": "http://localhost:3000", "host": "localhost:8000"})

    def test_foreign_origin_rejected(self, ta):
        assert not ta.origin_allowed({"origin": "https://evil.example", "host": "localhost:8000"})

    def test_missing_origin_allowed(self, ta):
        assert ta.origin_allowed({"host": "localhost:8000"})

    def test_cors_env_overrides_list(self, ta, monkeypatch):
        monkeypatch.setenv("CORS_ORIGINS", "https://portal.example")
        assert ta.origin_allowed({"origin": "https://portal.example/", "host": "api.example"})
        assert not ta.origin_allowed({"origin": "http://localhost:3000", "host": "api.example"})

    def test_ws_authorized_rejects_foreign_origin_even_with_auth_disabled(self, ta, monkeypatch):
        monkeypatch.setenv("LOOMAI_NO_AUTH", "1")
        ws = SimpleNamespace(headers={"origin": "https://evil.example", "host": "localhost:8000"}, cookies={})
        assert not ta.ws_authorized(ws)
        # Same-origin passes, and with auth disabled nothing else is required.
        ws_ok = SimpleNamespace(headers={"origin": "http://localhost:8000", "host": "localhost:8000"}, cookies={})
        assert ta.ws_authorized(ws_ok) is True


class TestHarnessConfigMode:
    def test_owner_only_sets_0600(self, tmp_path):
        from app.routes.ai_terminal import _owner_only
        p = tmp_path / "cfg.json"
        p.write_text("{}")
        p.chmod(0o644)
        _owner_only(str(p))
        assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
