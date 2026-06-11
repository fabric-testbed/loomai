"""Unit tests for terminal attach tickets and the persistent server secret."""
import pytest


@pytest.fixture()
def ticketing(tmp_path, monkeypatch):
    """Point auth + terminal_auth at an isolated storage dir without reloading
    the modules (reloading a core module mid-suite destabilizes other tests).
    The secret path is read from the env at call time, so resetting the cached
    globals is enough."""
    monkeypatch.setenv("FABRIC_STORAGE_DIR", str(tmp_path))
    import app.auth as auth
    import app.terminal_auth as ta
    prev_secret = auth._session_secret
    auth._session_secret = None
    ta._used_nonces.clear()
    try:
        yield auth, ta
    finally:
        # Don't leak this test's tmp secret / nonces into the rest of the suite.
        auth._session_secret = prev_secret
        ta._used_nonces.clear()


def test_secret_is_persisted_and_stable(ticketing, tmp_path):
    auth, _ = ticketing
    s1 = auth.get_server_secret()
    assert len(s1) >= 32
    # Persisted to disk with locked-down perms.
    secret_file = tmp_path / ".loomai" / "session_secret"
    assert secret_file.exists()
    assert (secret_file.stat().st_mode & 0o777) == 0o600
    # Stable across a fresh process (clear in-memory cache, reread file).
    auth._session_secret = None
    s2 = auth.get_server_secret()
    assert s1 == s2


def test_ticket_round_trip(ticketing):
    _, ta = ticketing
    tok = ta.mint_ticket("abc123def456")
    assert ta.verify_ticket(tok, "abc123def456") is True


def test_ticket_is_single_use(ticketing):
    _, ta = ticketing
    tok = ta.mint_ticket("sess0001")
    assert ta.verify_ticket(tok, "sess0001") is True
    # Replay rejected.
    assert ta.verify_ticket(tok, "sess0001") is False


def test_ticket_bound_to_session(ticketing):
    _, ta = ticketing
    tok = ta.mint_ticket("sessAAAA")
    assert ta.verify_ticket(tok, "sessBBBB") is False


def test_ticket_expires(ticketing):
    _, ta = ticketing
    tok = ta.mint_ticket("sessTTTT", ttl=1)
    # Force expiry without sleeping.
    sid, exp, nonce, sig = tok.split(".", 3)
    stale = f"{sid}.{int(exp) - 10}.{nonce}.{sig}"
    assert ta.verify_ticket(stale, "sessTTTT") is False


def test_tampered_ticket_rejected(ticketing):
    _, ta = ticketing
    tok = ta.mint_ticket("sessXXXX")
    sid, exp, nonce, sig = tok.split(".", 3)
    forged = f"{sid}.{exp}.{nonce}.{'0' * len(sig)}"
    assert ta.verify_ticket(forged, "sessXXXX") is False


def test_garbage_ticket_rejected(ticketing):
    _, ta = ticketing
    assert ta.verify_ticket("", "x") is False
    assert ta.verify_ticket("not-a-ticket", "x") is False
    assert ta.verify_ticket("a.b.c.d", "x") is False
