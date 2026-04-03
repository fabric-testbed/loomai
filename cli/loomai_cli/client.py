"""HTTP client wrapper for the LoomAI backend API."""

from __future__ import annotations

import sys
from typing import Any, Optional

import click
import httpx


class CliError(click.ClickException):
    """User-friendly CLI error with optional HTTP status context."""

    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


class Client:
    """Thin wrapper around httpx for calling the LoomAI backend."""

    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self._http = httpx.Client(base_url=f"{self.base_url}/api", timeout=timeout)

    def get(self, path: str, params: Optional[dict] = None) -> Any:
        return self._request("GET", path, params=params)

    def post(self, path: str, json: Optional[dict] = None, params: Optional[dict] = None) -> Any:
        return self._request("POST", path, json=json, params=params)

    def put(self, path: str, json: Optional[dict] = None) -> Any:
        return self._request("PUT", path, json=json)

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
