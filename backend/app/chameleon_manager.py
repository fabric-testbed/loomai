"""Chameleon Cloud manager — per-site Keystone sessions via application credentials.

Thread-safe singleton pattern mirroring fablib_manager.py.
Uses urllib for Keystone auth (no SDK dependency for auth layer).
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.request
from typing import Any, Optional

from app.tracking_headers import add_tracking_headers

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_sessions: dict[str, "_ChameleonSession"] = {}

# GPS coordinates for Chameleon sites (for map display)
CHAMELEON_SITE_LOCATIONS = {
    "CHI@TACC": {"lat": 30.2672, "lon": -97.7431, "city": "Austin, TX"},
    "CHI@UC": {"lat": 41.7897, "lon": -87.5997, "city": "Chicago, IL"},
    "CHI@Edge": {"lat": 41.7897, "lon": -87.5997, "city": "Chicago, IL"},
    "KVM@TACC": {"lat": 30.2672, "lon": -97.7431, "city": "Austin, TX"},
}


class _ChameleonSession:
    """Authenticated session for a single Chameleon site."""

    def __init__(self, site: str, auth_url: str, cred_id: str, cred_secret: str, project_id: str):
        self.site = site
        self.auth_url = auth_url
        self.cred_id = cred_id
        self.cred_secret = cred_secret
        self.project_id = project_id
        self._token: Optional[str] = None
        self._token_expires: float = 0
        self._catalog: dict[str, str] = {}  # service_type → public endpoint URL
        self._lock = threading.Lock()

    def _authenticate(self) -> None:
        """Authenticate to Keystone and cache the token + service catalog."""
        auth_body = json.dumps({
            "auth": {
                "identity": {
                    "methods": ["application_credential"],
                    "application_credential": {
                        "id": self.cred_id,
                        "secret": self.cred_secret,
                    },
                },
            },
        }).encode()

        req = urllib.request.Request(
            f"{self.auth_url}/auth/tokens",
            data=auth_body,
            headers=add_tracking_headers({"Content-Type": "application/json"}),
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            self._token = resp.headers.get("X-Subject-Token")
            body = json.loads(resp.read())

        # Parse token expiry (ISO format)
        expires_str = body.get("token", {}).get("expires_at", "")
        if expires_str:
            from datetime import datetime, timezone
            try:
                dt = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
                self._token_expires = dt.timestamp() - 300  # Refresh 5 min before expiry
            except Exception:
                self._token_expires = time.time() + 3300  # Default: ~55 min

        # Extract service catalog
        self._catalog = {}
        for entry in body.get("token", {}).get("catalog", []):
            stype = entry.get("type", "")
            for ep in entry.get("endpoints", []):
                if ep.get("interface") == "public":
                    self._catalog[stype] = ep["url"]
                    break

        logger.info("Chameleon %s: authenticated (project=%s, services=%s)",
                    self.site, self.project_id, list(self._catalog.keys()))

    def get_token(self) -> str:
        """Return a valid auth token, refreshing if expired."""
        with self._lock:
            if not self._token or time.time() >= self._token_expires:
                self._authenticate()
            return self._token  # type: ignore[return-value]

    def get_endpoint(self, service_type: str) -> str:
        """Return the public endpoint URL for a service type.

        Common types: 'compute' (Nova), 'reservation' (Blazar),
        'network' (Neutron), 'image' (Glance), 'identity' (Keystone).
        """
        if not self._catalog:
            self.get_token()  # Force auth to populate catalog
        url = self._catalog.get(service_type)
        if not url:
            raise ValueError(f"Service '{service_type}' not found in catalog for {self.site}")
        return url

    def api_get(self, service_type: str, path: str) -> Any:
        """GET request to a Chameleon service API."""
        endpoint = self.get_endpoint(service_type)
        url = f"{endpoint}{path}"
        req = urllib.request.Request(url, headers=add_tracking_headers({
            "X-Auth-Token": self.get_token(),
            "Accept": "application/json",
        }))
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())

    def api_post(self, service_type: str, path: str, body: dict) -> Any:
        """POST request to a Chameleon service API."""
        endpoint = self.get_endpoint(service_type)
        url = f"{endpoint}{path}"
        data = json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, headers=add_tracking_headers({
            "X-Auth-Token": self.get_token(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }))
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp_body = resp.read()
                if not resp_body:
                    return {}  # Nova server actions return 202 with empty body
                return json.loads(resp_body)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")[:500]
            logger.warning("Chameleon POST %s failed: %s %s — %s", path, e.code, e.reason, err_body)
            raise RuntimeError(f"Chameleon API error {e.code}: {err_body}") from e

    def api_delete(self, service_type: str, path: str) -> None:
        """DELETE request to a Chameleon service API."""
        endpoint = self.get_endpoint(service_type)
        url = f"{endpoint}{path}"
        req = urllib.request.Request(url, method="DELETE", headers=add_tracking_headers({
            "X-Auth-Token": self.get_token(),
        }))
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp.read()
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")[:500]
            logger.warning("Chameleon DELETE %s failed: %s — %s", path, e.code, err_body)
            raise RuntimeError(f"Chameleon API error {e.code}: {err_body}") from e

    def api_put(self, service_type: str, path: str, body: dict) -> Any:
        """PUT request to a Chameleon service API."""
        endpoint = self.get_endpoint(service_type)
        url = f"{endpoint}{path}"
        data = json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, method="PUT", headers=add_tracking_headers({
            "X-Auth-Token": self.get_token(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }))
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")[:500]
            logger.warning("Chameleon PUT %s failed: %s — %s", path, e.code, err_body)
            raise RuntimeError(f"Chameleon API error {e.code}: {err_body}") from e


def get_session(site: str) -> _ChameleonSession:
    """Get or create an authenticated session for a Chameleon site.

    Raises RuntimeError if the site is not configured or Chameleon is disabled.
    """
    from app import settings_manager

    if not settings_manager.is_chameleon_enabled():
        raise RuntimeError("Chameleon integration is disabled")

    cfg = settings_manager.get_chameleon_site_config(site)
    if not cfg:
        raise RuntimeError(f"Unknown Chameleon site: {site}")

    cred_id = cfg.get("app_credential_id", "")
    cred_secret = cfg.get("app_credential_secret", "")
    if not cred_id or not cred_secret:
        raise RuntimeError(f"Chameleon site {site} not configured (missing credentials)")

    with _lock:
        session = _sessions.get(site)
        if session and session.cred_id == cred_id:
            return session

        # Create new session
        session = _ChameleonSession(
            site=site,
            auth_url=cfg.get("auth_url", ""),
            cred_id=cred_id,
            cred_secret=cred_secret,
            project_id=cfg.get("project_id", ""),
        )
        _sessions[site] = session
        return session


def get_configured_sites() -> list[str]:
    """Return list of site names that have credentials configured."""
    from app import settings_manager
    return [
        name for name in settings_manager.get_chameleon_sites()
        if settings_manager.is_chameleon_site_configured(name)
    ]


def reset_sessions() -> None:
    """Clear all cached sessions (call on settings change)."""
    with _lock:
        _sessions.clear()
    logger.info("Chameleon sessions cleared")


def is_configured() -> bool:
    """Check if at least one Chameleon site has credentials."""
    from app import settings_manager
    if not settings_manager.is_chameleon_enabled():
        return False
    return len(get_configured_sites()) > 0
