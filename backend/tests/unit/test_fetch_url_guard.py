"""SSRF guard for the assistant's fetch_webpage tool."""
import asyncio
import socket
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.routes import ai_chat


def _resolve_to(monkeypatch, ip: str | None):
    """Make every hostname resolve to *ip* (or fail when None)."""
    def fake_getaddrinfo(host, port, *args, **kwargs):
        if ip is None:
            raise socket.gaierror("no such host")
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (ip, port))]
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


def test_public_host_allowed(monkeypatch):
    _resolve_to(monkeypatch, "93.184.216.34")
    assert ai_chat._fetch_url_problem("https://example.com/page") is None


@pytest.mark.parametrize("ip", [
    "127.0.0.1",        # loopback: the backend itself (auth is off on loopback in hosted mode)
    "10.0.0.5",         # RFC1918: other pods, the hub
    "172.16.4.2",
    "192.168.1.1",
    "169.254.169.254",  # cloud metadata
    "100.64.0.1",       # CGNAT
    "0.0.0.0",
    "::1",
    "fd00::1",          # IPv6 ULA
    "fe80::1",          # IPv6 link-local
])
def test_non_public_addresses_blocked(monkeypatch, ip):
    _resolve_to(monkeypatch, ip)
    problem = ai_chat._fetch_url_problem("http://evil.example/x")
    assert problem and "non-public" in problem


def test_any_resolved_address_counts(monkeypatch):
    # A host with one public and one private address is still blocked.
    def fake_getaddrinfo(host, port, *a, **k):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port)),
        ]
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    assert ai_chat._fetch_url_problem("http://split.example/") is not None


@pytest.mark.parametrize("url, fragment", [
    ("ftp://example.com/f", "http(s)"),
    ("file:///etc/passwd", "http(s)"),
    ("http://localhost:8000/api/files/content", "not public"),
    ("http://metadata.google.internal/computeMetadata/v1/", "not public"),
    ("http://loomai-hub.loomai.svc.cluster.local:8081/", "not public"),
    ("http://user:pw@example.com/", "credentials"),
    ("http:///nohost", "no host"),
    ("http://example.com:99999/", "port"),
])
def test_bad_urls_rejected_before_dns(monkeypatch, url, fragment):
    _resolve_to(monkeypatch, "93.184.216.34")
    problem = ai_chat._fetch_url_problem(url)
    assert problem and fragment in problem


def test_unresolvable_host_rejected(monkeypatch):
    _resolve_to(monkeypatch, None)
    assert "resolve" in ai_chat._fetch_url_problem("http://nope.invalid/")


def _response(url, status, headers=None, text=""):
    req = httpx.Request("GET", url)
    return httpx.Response(status, headers=headers or {}, text=text, request=req)


def test_redirect_to_internal_host_is_refused(monkeypatch):
    # Public host answers with a redirect to loopback: the hop is re-checked.
    def fake_getaddrinfo(host, port, *a, **k):
        ip = "127.0.0.1" if host == "localhost" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    from app import http_pool
    first = _response("https://example.com/", 302,
                      {"location": "http://localhost:8000/api/files/content?path=x"})
    monkeypatch.setattr(http_pool, "web_client", MagicMock(get=AsyncMock(return_value=first)))

    with pytest.raises(ValueError, match="refusing to fetch http://localhost:8000"):
        asyncio.run(ai_chat._fetch_public_url("https://example.com/"))


def test_public_redirect_is_followed_once_rechecked(monkeypatch):
    _resolve_to(monkeypatch, "93.184.216.34")
    from app import http_pool
    first = _response("https://example.com/a", 301, {"location": "/b"})
    final = _response("https://example.com/b", 200, text="hello")
    client = MagicMock(get=AsyncMock(side_effect=[first, final]))
    monkeypatch.setattr(http_pool, "web_client", client)

    resp = asyncio.run(ai_chat._fetch_public_url("https://example.com/a"))

    assert resp.text == "hello"
    assert [str(c.args[0]) for c in client.get.await_args_list] == [
        "https://example.com/a", "https://example.com/b",
    ]


def test_fetch_webpage_reports_refusal(monkeypatch):
    _resolve_to(monkeypatch, "127.0.0.1")
    out = asyncio.run(ai_chat._execute_fetch_webpage("http://internal.example/"))
    assert "refusing to fetch" in out
