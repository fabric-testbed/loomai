"""Tests for the CLI session-cookie header sourced from LOOMAI_SESSION_COOKIE."""
from __future__ import annotations

from loomai_cli.client import Client, _session_cookie_header

LOCAL = "http://localhost:8000"


def test_session_cookie_header_absent(monkeypatch):
    monkeypatch.delenv("LOOMAI_SESSION_COOKIE", raising=False)

    assert _session_cookie_header(LOCAL) == {}


def test_session_cookie_header_present(monkeypatch):
    monkeypatch.setenv("LOOMAI_SESSION_COOKIE", "1234.abcd")

    assert _session_cookie_header(LOCAL) == {"Cookie": "loomai_session=1234.abcd"}


def test_session_cookie_header_present_loopback_ip(monkeypatch):
    monkeypatch.setenv("LOOMAI_SESSION_COOKIE", "1234.abcd")

    assert _session_cookie_header("http://127.0.0.1:8000") == {"Cookie": "loomai_session=1234.abcd"}


def test_session_cookie_header_rejects_newline(monkeypatch):
    monkeypatch.setenv("LOOMAI_SESSION_COOKIE", "1234.abcd\nInjected: header")

    assert _session_cookie_header(LOCAL) == {}


def test_session_cookie_header_rejects_carriage_return(monkeypatch):
    monkeypatch.setenv("LOOMAI_SESSION_COOKIE", "1234.abcd\r\nInjected: header")

    assert _session_cookie_header(LOCAL) == {}


def test_session_cookie_header_not_sent_to_remote_host(monkeypatch):
    """The local session cookie must never leak to a non-loopback URL."""
    monkeypatch.setenv("LOOMAI_SESSION_COOKIE", "1234.abcd")

    assert _session_cookie_header("https://evil.example.com") == {}
    assert _session_cookie_header("http://10.0.0.5:8000") == {}


def test_client_disables_proxy_when_cookie_attached(monkeypatch):
    """With the cookie attached, trust_env is off so HTTP(S)_PROXY can't route
    the credential-bearing request through a proxy."""
    monkeypatch.setenv("LOOMAI_SESSION_COOKIE", "1234.abcd")

    client = Client(LOCAL)
    try:
        assert client._http._trust_env is False
        assert "cookie" in {k.lower() for k in client._http.headers}
    finally:
        client.close()


def test_client_keeps_proxy_for_remote_no_cookie(monkeypatch):
    """Remote targets get no cookie and retain normal env-proxy behavior."""
    monkeypatch.setenv("LOOMAI_SESSION_COOKIE", "1234.abcd")

    client = Client("https://loomai.example.com")
    try:
        assert client._http._trust_env is True
        assert "cookie" not in {k.lower() for k in client._http.headers}
    finally:
        client.close()
