"""HTTP client wrapper for the LoomAI backend API."""

from __future__ import annotations

import os
import sys
from typing import Any, Optional
from urllib.parse import urlsplit

import click
import httpx


class CliError(click.ClickException):
    """User-friendly CLI error with optional HTTP status context."""

    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


# The session cookie is a credential for the *local* backend only, so it is
# never attached to a non-loopback target (e.g. an externally-set LOOMAI_URL).
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _session_cookie_header(base_url: str) -> dict[str, str]:
    """Return an auth cookie header sourced from the LoomAI terminal env.

    The standalone backend authenticates /api/* requests with the
    ``loomai_session`` cookie. Browser-launched local terminals receive the
    raw signed cookie value in ``LOOMAI_SESSION_COOKIE`` so the CLI can call the
    same local API without storing credentials or prompting separately.

    The cookie is only attached when *base_url* targets a loopback host — it is
    a local-backend credential and must never be forwarded to a remote or
    attacker-controlled URL. CR/LF values are rejected to avoid header
    injection; an absent cookie is a no-op.
    """
    session_cookie = os.environ.get("LOOMAI_SESSION_COOKIE", "")
    if not session_cookie or "\n" in session_cookie or "\r" in session_cookie:
        return {}
    host = (urlsplit(base_url).hostname or "").lower()
    if host not in _LOOPBACK_HOSTS:
        return {}
    return {"Cookie": f"loomai_session={session_cookie}"}


class Client:
    """Thin wrapper around httpx for calling the LoomAI backend."""

    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        cookie_header = _session_cookie_header(self.base_url)
        headers = dict(cookie_header)
        # AI-tool sessions export LOOMAI_ACTOR=agent so the backend applies the
        # agent lease cap; a person's own terminal does not set it.
        if os.environ.get("LOOMAI_ACTOR", "").strip().lower() == "agent":
            headers["X-LoomAI-Actor"] = "agent"
        # follow_redirects stays off (httpx default) so the session cookie in
        # the default headers can't be replayed to a redirect Location on
        # another origin. When the cookie is attached (loopback target) we also
        # disable trust_env so an HTTP(S)_PROXY environment variable can't route
        # the credential-bearing request through a proxy — httpx defaults to
        # trust_env=True, which would honor a proxy even for localhost.
        self._http = httpx.Client(base_url=f"{self.base_url}/api", timeout=timeout,
                                  follow_redirects=False,
                                  trust_env=not cookie_header,
                                  headers=headers)

    def get(self, path: str, params: Optional[dict] = None) -> Any:
        return self._request("GET", path, params=params)

    def post(self, path: str, json: Optional[dict] = None, params: Optional[dict] = None) -> Any:
        return self._request("POST", path, json=json, params=params)

    def post_file(self, path: str, files: dict, params: Optional[dict] = None) -> Any:
        return self._request("POST", path, files=files, params=params)

    def put(self, path: str, json: Optional[dict] = None, params: Optional[dict] = None) -> Any:
        return self._request("PUT", path, json=json, params=params)

    def delete(self, path: str, params: Optional[dict] = None) -> Any:
        return self._request("DELETE", path, params=params)

    def _request(self, method: str, path: str, **kwargs) -> Any:
        try:
            resp = self._http.request(method, path, **kwargs)
        except httpx.ConnectError:
            raise CliError(
                f"Cannot connect to LoomAI backend at {self.base_url}\n"
                f"Is the backend running? Set LOOMAI_URL to override."
            )
        except httpx.TimeoutException:
            raise CliError(f"Request timed out: {method} {path}")

        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            raise CliError(f"API error {resp.status_code}: {detail}", resp.status_code)

        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()

    def close(self):
        self._http.close()
