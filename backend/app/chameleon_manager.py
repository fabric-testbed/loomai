"""Chameleon Cloud manager — per-site Keystone sessions for Chameleon auth.

Thread-safe singleton pattern mirroring fablib_manager.py.
Uses urllib for Keystone auth (no SDK dependency for auth layer). Supports
application credentials and Chameleon's OIDC password flow.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from app.tracking_headers import add_tracking_headers

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_sessions: dict[str, "_ChameleonSession"] = {}
_OIDC_HEADERS = {"User-Agent": "LoomAI/ChameleonPasswordAuth"}

# GPS coordinates for Chameleon sites (for map display)
CHAMELEON_SITE_LOCATIONS = {
    "CHI@TACC": {"lat": 30.2672, "lon": -97.7431, "city": "Austin, TX"},
    "CHI@UC": {"lat": 41.7897, "lon": -87.5997, "city": "Chicago, IL"},
    "CHI@Edge": {"lat": 41.7897, "lon": -87.5997, "city": "Chicago, IL"},
    "KVM@TACC": {"lat": 30.2672, "lon": -97.7431, "city": "Austin, TX"},
}

CHAMELEON_OIDC_DEFAULTS = {
    "CHI@TACC": {
        "identity_provider": "chameleon",
        "protocol": "openid",
        "discovery_endpoint": "https://auth.chameleoncloud.org/auth/realms/chameleon/.well-known/openid-configuration",
        "client_id": "keystone-tacc-prod",
        "client_secret": "none",
        "access_token_type": "access_token",
        "openid_scope": "openid profile",
    },
    "CHI@UC": {
        "identity_provider": "chameleon",
        "protocol": "openid",
        "discovery_endpoint": "https://auth.chameleoncloud.org/auth/realms/chameleon/.well-known/openid-configuration",
        "client_id": "keystone-uc-prod",
        "client_secret": "none",
        "access_token_type": "access_token",
        "openid_scope": "openid profile",
    },
    "CHI@Edge": {
        "identity_provider": "chameleon",
        "protocol": "openid",
        "discovery_endpoint": "https://auth.chameleoncloud.org/auth/realms/chameleon/.well-known/openid-configuration",
        "client_id": "keystone-edge-prod",
        "client_secret": "none",
        "access_token_type": "access_token",
        "openid_scope": "openid profile",
    },
    "KVM@TACC": {
        "identity_provider": "chameleon",
        "protocol": "openid",
        "discovery_endpoint": "https://auth.chameleoncloud.org/auth/realms/chameleon/.well-known/openid-configuration",
        "client_id": "keystone-tacc-prod",
        "client_secret": "none",
        "access_token_type": "access_token",
        "openid_scope": "openid profile",
    },
}


def _contract_mode() -> bool:
    return os.environ.get("LOOMAI_CONTRACT_MODE", "").strip() == "1"


def _ensure_v3_auth_url(auth_url: str) -> str:
    """Return a Keystone v3 auth URL regardless of whether /v3 was supplied."""
    stripped = auth_url.rstrip("/")
    if stripped.endswith("/v3"):
        return stripped
    return f"{stripped}/v3"


class _ChameleonSession:
    """Authenticated session for a single Chameleon site."""

    def __init__(self, site: str, cfg: dict[str, Any], cache_key: str):
        self.site = site
        self.auth_url = _ensure_v3_auth_url(cfg.get("auth_url", ""))
        self.auth_type = cfg.get("auth_type", "application_credential")
        self.cred_id = cfg.get("app_credential_id", "")
        self.cred_secret = cfg.get("app_credential_secret", "")
        self.username = cfg.get("username", "")
        self.password = cfg.get("password", "")
        self.project_id = cfg.get("project_id", "")
        self.project_name = cfg.get("project_name", "")
        self.project_domain_name = cfg.get("project_domain_name", "")
        oidc_defaults = CHAMELEON_OIDC_DEFAULTS.get(site, {})
        self.identity_provider = cfg.get("identity_provider") or oidc_defaults.get("identity_provider", "chameleon")
        self.protocol = cfg.get("protocol") or oidc_defaults.get("protocol", "openid")
        self.discovery_endpoint = cfg.get("discovery_endpoint") or oidc_defaults.get("discovery_endpoint", "")
        self.client_id = cfg.get("client_id") or oidc_defaults.get("client_id", "")
        self.client_secret = cfg.get("client_secret")
        if self.client_secret is None:
            self.client_secret = oidc_defaults.get("client_secret", "none")
        self.access_token_type = cfg.get("access_token_type") or oidc_defaults.get("access_token_type", "access_token")
        self.openid_scope = cfg.get("openid_scope") or oidc_defaults.get("openid_scope", "openid profile")
        self._cache_key = cache_key
        self._token: Optional[str] = None
        self._token_expires: float = 0
        self._catalog: dict[str, str] = {}  # service_type → public endpoint URL
        self._lock = threading.Lock()

    def _authenticate(self) -> None:
        """Authenticate to Keystone and cache the token + service catalog."""
        if self.auth_type == "password":
            body = self._authenticate_oidc_password()
        else:
            body = self._authenticate_application_credential()

        self._load_auth_response(body)
        logger.info("Chameleon %s: authenticated (auth_type=%s, project=%s, services=%s)",
                    self.site, self.auth_type, self.project_id, list(self._catalog.keys()))

    def _authenticate_application_credential(self) -> dict[str, Any]:
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
            return json.loads(resp.read())

    def _authenticate_oidc_password(self) -> dict[str, Any]:
        """Authenticate using Chameleon's Keystone OIDC password flow."""
        if not self.project_id and not self.project_name:
            raise RuntimeError(f"Chameleon site {self.site} missing password auth project")
        unscoped_token = self._get_oidc_unscoped_token()

        scope: dict[str, Any]
        if self.project_id:
            scope = {"project": {"id": self.project_id}}
        else:
            project: dict[str, Any] = {"name": self.project_name}
            if self.project_domain_name:
                project["domain"] = {"name": self.project_domain_name}
            scope = {"project": project}

        rescope_body = json.dumps({
            "auth": {
                "identity": {
                    "methods": ["token"],
                    "token": {"id": unscoped_token},
                },
                "scope": scope,
            },
        }).encode()
        rescope_req = urllib.request.Request(
            f"{self.auth_url}/auth/tokens",
            data=rescope_body,
            headers={
                **_OIDC_HEADERS,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(rescope_req, timeout=15) as resp:
                self._token = resp.headers.get("X-Subject-Token")
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")[:500]
            logger.warning("Chameleon %s OIDC rescope failed: %s %s — %s", self.site, e.code, e.reason, err_body)
            raise RuntimeError(f"Chameleon API error {e.code}: {err_body}") from e

    def _get_oidc_unscoped_token(self) -> str:
        """Return an unscoped Keystone token from Chameleon's OIDC password flow."""
        if not self.username or not self.password:
            raise RuntimeError(f"Chameleon site {self.site} missing password auth username/password")
        if not self.discovery_endpoint:
            raise RuntimeError(f"Chameleon site {self.site} missing OIDC discovery endpoint")
        if not self.client_id:
            raise RuntimeError(f"Chameleon site {self.site} missing OIDC client ID")

        discovery_req = urllib.request.Request(
            self.discovery_endpoint,
            headers={**_OIDC_HEADERS, "Accept": "application/json"},
        )
        with urllib.request.urlopen(discovery_req, timeout=15) as resp:
            discovery = json.loads(resp.read())
        token_endpoint = discovery.get("token_endpoint")
        if not token_endpoint:
            raise RuntimeError(f"Chameleon site {self.site} OIDC discovery document has no token endpoint")

        payload = {
            "grant_type": "password",
            "username": self.username,
            "password": self.password,
            "scope": self.openid_scope,
        }
        headers = {
            **_OIDC_HEADERS,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
        if self.client_secret:
            basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
            headers["Authorization"] = f"Basic {basic}"
        else:
            payload["client_id"] = self.client_id

        token_req = urllib.request.Request(
            token_endpoint,
            data=urllib.parse.urlencode(payload).encode(),
            headers=headers,
        )
        with urllib.request.urlopen(token_req, timeout=15) as resp:
            oidc_body = json.loads(resp.read())
        access_token = oidc_body.get(self.access_token_type)
        if not access_token:
            raise RuntimeError(f"Chameleon site {self.site} OIDC response did not include {self.access_token_type}")

        fed_url = (
            f"{self.auth_url}/OS-FEDERATION/identity_providers/"
            f"{urllib.parse.quote(self.identity_provider, safe='')}/protocols/"
            f"{urllib.parse.quote(self.protocol, safe='')}/auth"
        )
        fed_req = urllib.request.Request(
            fed_url,
            data=b"",
            headers={
                **_OIDC_HEADERS,
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(fed_req, timeout=15) as resp:
            unscoped_token = resp.headers.get("X-Subject-Token")
            resp.read()

        if not unscoped_token:
            raise RuntimeError(f"Chameleon site {self.site} federated auth did not return a Keystone token")
        return unscoped_token

    def list_oidc_projects(self) -> list[dict[str, str]]:
        """List projects this password-auth user can scope to at this site."""
        unscoped_token = self._get_oidc_unscoped_token()
        paths = ("/OS-FEDERATION/projects", "/auth/projects")
        last_error: Exception | None = None
        for path in paths:
            req = urllib.request.Request(
                f"{self.auth_url}{path}",
                headers={
                    **_OIDC_HEADERS,
                    "X-Auth-Token": unscoped_token,
                    "Accept": "application/json",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    body = json.loads(resp.read())
                projects = []
                for project in body.get("projects", []):
                    project_id = project.get("id", "")
                    name = project.get("name", "")
                    if project_id and name:
                        projects.append({"id": project_id, "name": name})
                return projects
            except Exception as e:
                last_error = e
        raise RuntimeError(f"Failed to list Chameleon projects for {self.site}: {last_error}")

    def _load_auth_response(self, body: dict[str, Any]) -> None:
        token_body = body.get("token", {})
        actual_project_id = token_body.get("project", {}).get("id", "")
        if self.project_id:
            if not actual_project_id:
                raise RuntimeError(
                    f"Chameleon site {self.site} token is not scoped to configured project {self.project_id}"
                )
            if actual_project_id != self.project_id:
                raise RuntimeError(
                    f"Chameleon site {self.site} token is scoped to project {actual_project_id}, "
                    f"but settings specify {self.project_id}"
                )
        elif actual_project_id:
            self.project_id = actual_project_id

        # Parse token expiry (ISO format)
        expires_str = token_body.get("expires_at", "")
        if expires_str:
            from datetime import datetime, timezone
            try:
                dt = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
                self._token_expires = dt.timestamp() - 300  # Refresh 5 min before expiry
            except Exception:
                self._token_expires = time.time() + 3300  # Default: ~55 min

        # Extract service catalog
        self._catalog = {}
        for entry in token_body.get("catalog", []):
            stype = entry.get("type", "")
            for ep in entry.get("endpoints", []):
                if ep.get("interface") == "public":
                    self._catalog[stype] = ep["url"]
                    break

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
        return self.api_request(service_type, "GET", path)

    def api_post(self, service_type: str, path: str, body: dict) -> Any:
        """POST request to a Chameleon service API."""
        return self.api_request(service_type, "POST", path, body)

    def api_delete(self, service_type: str, path: str) -> None:
        """DELETE request to a Chameleon service API."""
        self.api_request(service_type, "DELETE", path)

    def api_put(self, service_type: str, path: str, body: dict) -> Any:
        """PUT request to a Chameleon service API."""
        return self.api_request(service_type, "PUT", path, body)

    def api_request(
        self,
        service_type: str,
        method: str,
        path: str,
        body: dict | None = None,
        timeout: int = 30,
    ) -> Any:
        """Issue an arbitrary request through this scoped Chameleon session."""
        endpoint = self.get_endpoint(service_type)
        if not path.startswith("/"):
            path = "/" + path
        url = f"{endpoint.rstrip('/')}{path}"
        data = json.dumps(body).encode() if body is not None else None
        headers = {
            "X-Auth-Token": self.get_token(),
            "Accept": "application/json",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            url,
            data=data,
            method=method.upper(),
            headers=add_tracking_headers(headers),
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                resp_body = resp.read()
                if not resp_body:
                    return {}
                return json.loads(resp_body)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")[:500]
            logger.warning(
                "Chameleon %s %s failed: %s %s — %s",
                method.upper(), path, e.code, e.reason, err_body,
            )
            raise RuntimeError(f"Chameleon API error {e.code}: {err_body}") from e


class _ContractChameleonSession:
    """Deterministic Chameleon session for backend contract tests."""

    def __init__(self, site: str = "CHI@TACC"):
        self.site = site
        self.auth_url = "https://chi.tacc.chameleoncloud.org:5000/v3"
        self.project_id = "contract-project"
        self.project_name = "Contract Project"
        self._token = "contract-chameleon-token"
        self._lease = {
            "id": "contract-lease-1",
            "name": "contract-lease",
            "status": "ACTIVE",
            "start_date": "2026-06-08 00:00",
            "end_date": "2026-06-08 04:00",
            "reservations": [
                {
                    "id": "contract-reservation-1",
                    "resource_type": "physical:host",
                    "resource_properties": json.dumps(["==", "$node_type", "compute_haswell"]),
                    "min": 1,
                    "max": 1,
                    "status": "active",
                }
            ],
            "events": [],
        }
        self._networks = [
            {
                "id": "sharednet1-id",
                "name": "sharednet1",
                "status": "ACTIVE",
                "shared": True,
                "router:external": False,
                "project_id": "service",
                "subnets": ["sharednet1-subnet"],
            },
            {
                "id": "public-id",
                "name": "public",
                "status": "ACTIVE",
                "shared": True,
                "router:external": True,
                "project_id": "service",
                "subnets": ["public-subnet"],
            },
        ]
        self._subnets = [
            {
                "id": "sharednet1-subnet",
                "name": "sharednet1-subnet",
                "network_id": "sharednet1-id",
                "cidr": "10.140.0.0/24",
            },
            {
                "id": "public-subnet",
                "name": "public-subnet",
                "network_id": "public-id",
                "cidr": "192.0.2.0/24",
            },
        ]
        self._floating_ips: list[dict[str, Any]] = []
        self._security_groups = [
            {
                "id": "default-sg",
                "name": "default",
                "description": "Contract default security group",
                "security_group_rules": [],
            }
        ]

    def get_token(self) -> str:
        return self._token

    def get_endpoint(self, service_type: str) -> str:
        return f"https://contract.chameleon.invalid/{service_type}"

    def api_get(self, service_type: str, path: str) -> Any:
        path_only, _, query = path.partition("?")
        if service_type == "reservation":
            if path_only == "/leases":
                return {"leases": [dict(self._lease)]}
            if path_only == "/leases/contract-lease-1":
                return {"lease": dict(self._lease)}
            if path_only == "/os-hosts":
                return {
                    "hosts": [
                        {
                            "id": "contract-host-1",
                            "hypervisor_hostname": "contract-host-1",
                            "node_type": "compute_haswell",
                            "reservable": True,
                            "cpu_arch": "x86_64",
                            "vcpus": 48,
                            "memory_mb": 196608,
                            "local_gb": 2000,
                        }
                    ]
                }
        if service_type == "compute":
            if path_only == "/servers/detail":
                return {"servers": []}
            if path_only == "/flavors/detail":
                return {
                    "flavors": [
                        {
                            "id": "compute_haswell",
                            "name": "compute_haswell",
                            "vcpus": 48,
                            "ram": 196608,
                            "disk": 2000,
                        }
                    ]
                }
        if service_type == "image" and path_only == "/v2/images":
            return {
                "images": [
                    {
                        "id": "cc-ubuntu-22",
                        "name": "CC-Ubuntu22.04",
                        "status": "active",
                        "visibility": "public",
                        "size": 4 * 1024 * 1024 * 1024,
                        "created_at": "2026-06-08T00:00:00Z",
                        "architecture": "x86_64",
                    }
                ]
            }
        if service_type == "network":
            if path_only == "/v2.0/networks":
                params = urllib.parse.parse_qs(query)
                networks = list(self._networks)
                if params.get("name"):
                    wanted = params["name"][0]
                    networks = [net for net in networks if net.get("name") == wanted]
                if params.get("router:external"):
                    wanted_external = params["router:external"][0].lower() == "true"
                    networks = [net for net in networks if bool(net.get("router:external")) == wanted_external]
                return {"networks": networks}
            if path_only == "/v2.0/subnets":
                return {"subnets": list(self._subnets)}
            if path_only == "/v2.0/routers":
                return {"routers": []}
            if path_only == "/v2.0/floatingips":
                return {"floatingips": list(self._floating_ips)}
            if path_only == "/v2.0/security-groups":
                return {"security_groups": list(self._security_groups)}
        return {}

    def api_post(self, service_type: str, path: str, body: dict) -> Any:
        path_only = path.split("?", 1)[0]
        if service_type == "network" and path_only == "/v2.0/networks":
            payload = body.get("network", body)
            network = {
                "id": f"contract-network-{len(self._networks) + 1}",
                "name": payload.get("name", f"contract-network-{len(self._networks) + 1}"),
                "status": "ACTIVE",
                "shared": False,
                "router:external": False,
                "project_id": self.project_id,
                "subnets": [],
            }
            self._networks.append(network)
            return {"network": network}
        if service_type == "network" and path_only == "/v2.0/subnets":
            payload = body.get("subnet", body)
            subnet = {
                "id": f"contract-subnet-{len(self._subnets) + 1}",
                "name": payload.get("name", f"contract-subnet-{len(self._subnets) + 1}"),
                "network_id": payload.get("network_id", ""),
                "cidr": payload.get("cidr", ""),
            }
            self._subnets.append(subnet)
            for network in self._networks:
                if network["id"] == subnet["network_id"]:
                    network.setdefault("subnets", []).append(subnet["id"])
            return {"subnet": subnet}
        if service_type == "network" and path_only == "/v2.0/routers":
            return {"router": {"id": "contract-router-1", **body.get("router", {})}}
        if service_type == "network" and path_only == "/v2.0/floatingips":
            fip = {
                "id": f"contract-fip-{len(self._floating_ips) + 1}",
                "floating_ip_address": f"198.51.100.{10 + len(self._floating_ips)}",
                "floating_network_id": body.get("floatingip", {}).get("floating_network_id", "public-id"),
                "port_id": None,
                "status": "DOWN",
            }
            self._floating_ips.append(fip)
            return {"floatingip": fip}
        if service_type == "network" and path_only == "/v2.0/security-groups":
            payload = body.get("security_group", body)
            sg = {
                "id": f"contract-sg-{len(self._security_groups) + 1}",
                "name": payload.get("name", "contract-sg"),
                "description": payload.get("description", ""),
                "security_group_rules": [],
            }
            self._security_groups.append(sg)
            return {"security_group": sg}
        if service_type == "network" and path_only == "/v2.0/security-group-rules":
            payload = body.get("security_group_rule", body)
            rule_count = sum(len(sg.get("security_group_rules", [])) for sg in self._security_groups)
            rule = {"id": f"contract-sg-rule-{rule_count + 1}", **payload}
            for sg in self._security_groups:
                if sg.get("id") == rule.get("security_group_id"):
                    sg.setdefault("security_group_rules", []).append(rule)
                    break
            return {"security_group_rule": rule}
        if service_type == "reservation" and path_only == "/leases":
            return {"lease": dict(self._lease)}
        return {}

    def api_put(self, service_type: str, path: str, body: dict) -> Any:
        path_only = path.split("?", 1)[0]
        if service_type == "network" and path_only.startswith("/v2.0/floatingips/"):
            fip_id = path_only.rsplit("/", 1)[-1]
            payload = body.get("floatingip", body)
            for fip in self._floating_ips:
                if fip.get("id") == fip_id:
                    fip.update(payload)
                    fip["status"] = "ACTIVE" if fip.get("port_id") else "DOWN"
                    return {"floatingip": fip}
        return {}

    def api_delete(self, service_type: str, path: str) -> None:
        path_only = path.split("?", 1)[0]
        if service_type == "network" and path_only.startswith("/v2.0/floatingips/"):
            fip_id = path_only.rsplit("/", 1)[-1]
            self._floating_ips = [fip for fip in self._floating_ips if fip.get("id") != fip_id]
            return None
        if service_type == "network" and path_only.startswith("/v2.0/security-group-rules/"):
            rule_id = path_only.rsplit("/", 1)[-1]
            for sg in self._security_groups:
                sg["security_group_rules"] = [
                    rule for rule in sg.get("security_group_rules", [])
                    if rule.get("id") != rule_id
                ]
            return None
        if service_type == "network" and path_only.startswith("/v2.0/security-groups/"):
            sg_id = path_only.rsplit("/", 1)[-1]
            self._security_groups = [
                sg for sg in self._security_groups
                if sg.get("id") != sg_id or sg.get("name") == "default"
            ]
            return None
        return None

    def api_request(
        self,
        service_type: str,
        method: str,
        path: str,
        body: dict | None = None,
        timeout: int = 30,
    ) -> Any:
        method = method.upper()
        if method == "GET":
            return self.api_get(service_type, path)
        if method == "POST":
            return self.api_post(service_type, path, body or {})
        if method == "PUT":
            return self.api_put(service_type, path, body or {})
        if method == "DELETE":
            return self.api_delete(service_type, path)
        return {}

    def list_oidc_projects(self) -> list[dict[str, str]]:
        return [{"id": self.project_id, "name": self.project_name}]


_contract_sessions: dict[str, _ContractChameleonSession] = {}


def get_session(site: str) -> _ChameleonSession:
    """Get or create an authenticated session for a Chameleon site.

    Raises RuntimeError if the site is not configured or Chameleon is disabled.
    """
    if _contract_mode():
        with _lock:
            if site not in _contract_sessions:
                _contract_sessions[site] = _ContractChameleonSession(site)
            return _contract_sessions[site]  # type: ignore[return-value]

    from app import settings_manager

    if not settings_manager.is_chameleon_enabled():
        raise RuntimeError("Chameleon integration is disabled")

    cfg = dict(settings_manager.get_chameleon_site_config(site))
    if not cfg:
        raise RuntimeError(f"Unknown Chameleon site: {site}")

    if cfg.get("auth_type") == "password":
        password_auth = settings_manager.get_chameleon_password_auth()
        cfg["username"] = password_auth.get("username") or cfg.get("username", "")
        cfg["password"] = password_auth.get("password") or cfg.get("password", "")
        cfg["project_id"] = cfg.get("project_id", "") or password_auth.get("project_id", "")

    if not settings_manager.is_chameleon_site_configured(site):
        raise RuntimeError(f"Chameleon site {site} not configured (missing credentials)")

    cache_key = json.dumps({
        key: cfg.get(key, "")
        for key in (
            "auth_type",
            "auth_url",
            "app_credential_id",
            "app_credential_secret",
            "username",
            "password",
            "project_id",
            "project_name",
            "project_domain_name",
            "identity_provider",
            "protocol",
            "discovery_endpoint",
            "client_id",
            "client_secret",
            "access_token_type",
            "openid_scope",
        )
    }, sort_keys=True)

    with _lock:
        session = _sessions.get(site)
        if session and session._cache_key == cache_key:
            return session

        # Create new session
        session = _ChameleonSession(site=site, cfg=cfg, cache_key=cache_key)
        _sessions[site] = session
        return session


def list_password_auth_projects(site: str, cfg: dict[str, Any], username: str, password: str) -> list[dict[str, str]]:
    """List password-auth projects available at a Chameleon site."""
    if _contract_mode():
        return [{"id": "contract-project", "name": "Contract Project"}]
    merged = dict(cfg)
    merged["auth_type"] = "password"
    merged["username"] = username
    merged["password"] = password
    session = _ChameleonSession(
        site=site,
        cfg=merged,
        cache_key=json.dumps({"site": site, "auth_type": "password", "username": username}, sort_keys=True),
    )
    return session.list_oidc_projects()


def get_configured_sites() -> list[str]:
    """Return list of site names that have credentials configured."""
    if _contract_mode():
        return ["CHI@TACC"]
    from app import settings_manager
    return [
        name for name in settings_manager.get_chameleon_sites()
        if settings_manager.is_chameleon_site_configured(name)
    ]


def reset_sessions() -> None:
    """Clear all cached sessions (call on settings change)."""
    with _lock:
        _sessions.clear()
        _contract_sessions.clear()
    logger.info("Chameleon sessions cleared")


def is_configured() -> bool:
    """Check if at least one Chameleon site has credentials."""
    if _contract_mode():
        return True
    from app import settings_manager
    if not settings_manager.is_chameleon_enabled():
        return False
    return len(get_configured_sites()) > 0
