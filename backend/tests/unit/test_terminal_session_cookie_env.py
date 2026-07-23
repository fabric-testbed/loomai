"""Tests for _local_terminal_env: PATH + session-cookie propagation.

Browser-created local terminals must forward the signed loomai_session cookie
into the child process (as LOOMAI_SESSION_COOKIE) so the loomai CLI can call the
local backend API — but only when standalone auth is enabled, and never with a
CR/LF value that could inject headers.
"""
from __future__ import annotations

from types import SimpleNamespace

from app.routes import terminal


def _request(cookie: str = ""):
    cookies = {}
    if cookie:
        cookies["loomai_session"] = cookie
    return SimpleNamespace(cookies=cookies)


def test_local_terminal_env_includes_tools_path(monkeypatch):
    monkeypatch.setattr(terminal, "get_tool_env", lambda: {"PATH": "/tools:/usr/bin"})
    monkeypatch.setattr(terminal._auth, "is_auth_enabled", lambda: False)

    env = terminal._local_terminal_env(_request())

    assert env["PATH"] == "/tools:/usr/bin"
    assert "LOOMAI_SESSION_COOKIE" not in env


def test_local_terminal_env_propagates_session_cookie(monkeypatch):
    monkeypatch.setattr(terminal, "get_tool_env", lambda: {"PATH": "/tools:/usr/bin"})
    monkeypatch.setattr(terminal._auth, "is_auth_enabled", lambda: True)

    env = terminal._local_terminal_env(_request("1234.abcd"))

    assert env["LOOMAI_SESSION_COOKIE"] == "1234.abcd"


def test_local_terminal_env_skips_cookie_when_auth_disabled(monkeypatch):
    monkeypatch.setattr(terminal, "get_tool_env", lambda: {"PATH": "/tools:/usr/bin"})
    monkeypatch.setattr(terminal._auth, "is_auth_enabled", lambda: False)

    env = terminal._local_terminal_env(_request("1234.abcd"))

    assert "LOOMAI_SESSION_COOKIE" not in env


def test_local_terminal_env_rejects_newline_cookie(monkeypatch):
    monkeypatch.setattr(terminal, "get_tool_env", lambda: {"PATH": "/tools:/usr/bin"})
    monkeypatch.setattr(terminal._auth, "is_auth_enabled", lambda: True)

    env = terminal._local_terminal_env(_request("1234.abcd\r\nInjected: header"))

    assert "LOOMAI_SESSION_COOKIE" not in env
