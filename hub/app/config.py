"""Hub configuration via environment variables."""

from __future__ import annotations

import secrets
from typing import List

from pydantic_settings import BaseSettings


class HubSettings(BaseSettings):
    """LoomAI Hub settings, read from environment variables."""

    # ---------- Hub core ----------
    HUB_BASE_URL: str = "http://localhost:8081"
    HUB_PREFIX: str = "/hub"

    # ---------- CILogon OIDC ----------
    CILOGON_CLIENT_ID: str
    CILOGON_CLIENT_SECRET: str
    CILOGON_CALLBACK_URL: str = ""
    CILOGON_SCOPES: str = "openid email profile org.cilogon.userinfo"
    CILOGON_SKIN: str = "FABRIC"

    # ---------- FABRIC APIs ----------
    FABRIC_CORE_API_HOST: str = "https://uis.fabric-testbed.net"
    FABRIC_CORE_API_BEARER_TOKEN: str
    FABRIC_CM_HOST: str = "cm.fabric-testbed.net"
    FABRIC_CM_TOKEN_LIFETIME: int = 4
    FABRIC_CM_SCOPE: str = "all"
    FABRIC_REQUIRED_ROLE: str = "Jupyterhub"
    FABRIC_BASTION_HOST: str = "bastion.fabric-testbed.net"
    FABRIC_ORCHESTRATOR_HOST: str = "orchestrator.fabric-testbed.net"

    # ---------- Session / cookies ----------
    COOKIE_SECRET: str = ""
    COOKIE_MAX_AGE: int = 86400  # 24 h
    COOKIE_SECURE: bool = True  # Set to false for HTTP-only deployments

    # ---------- Configurable HTTP Proxy ----------
    PROXY_API_URL: str = "http://localhost:8001"
    PROXY_AUTH_TOKEN: str

    # ---------- Database ----------
    DATABASE_URL: str = "sqlite+aiosqlite:///./hub.db"

    # ---------- Single-user pod ----------
    SINGLEUSER_IMAGE: str = "fabrictestbed/loomai:latest"
    SINGLEUSER_CPU_LIMIT: str = "4"
    SINGLEUSER_MEM_LIMIT: str = "2G"
    SINGLEUSER_CPU_REQUEST: str = "50m"
    SINGLEUSER_MEM_REQUEST: str = "512M"
    SINGLEUSER_STORAGE_CAPACITY: str = "1Gi"
    SINGLEUSER_STORAGE_CLASS: str = ""
    SINGLEUSER_START_TIMEOUT: int = 300
    SINGLEUSER_ALLOW_PRIVILEGE_ESCALATION: bool = True

    # ---------- Kubernetes ----------
    K8S_NAMESPACE: str = "default"

    # ---------- Idle culler ----------
    CULL_ENABLED: bool = True
    CULL_TIMEOUT: int = 28800
    CULL_EVERY: int = 600
    CULL_MAX_AGE: int = 86400

    # ---------- Admin ----------
    ADMIN_USERS: str = ""

    # ------------------------------------------------------------------
    # Derived helpers
    # ------------------------------------------------------------------

    @property
    def cookie_secret_bytes(self) -> str:
        """Return cookie secret, auto-generating one if not set."""
        if self.COOKIE_SECRET:
            return self.COOKIE_SECRET
        return secrets.token_hex(32)

    @property
    def cilogon_callback_url(self) -> str:
        """Return callback URL, auto-derived from HUB_BASE_URL if empty."""
        if self.CILOGON_CALLBACK_URL:
            return self.CILOGON_CALLBACK_URL
        return f"{self.HUB_BASE_URL}{self.HUB_PREFIX}/oauth_callback"

    @property
    def admin_user_list(self) -> List[str]:
        """Return list of admin usernames."""
        if not self.ADMIN_USERS:
            return []
        return [u.strip() for u in self.ADMIN_USERS.split(",") if u.strip()]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


# Singleton — imported elsewhere as `from app.config import settings`
settings = HubSettings()  # type: ignore[call-arg]
