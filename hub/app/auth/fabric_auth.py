"""FABRIC Core API and Credential Manager integration."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.config import settings
from app.tracking_headers import get_tracking_headers

logger = logging.getLogger(__name__)


def _tracked_headers(base: dict[str, str], username: str = "") -> dict[str, str]:
    """Merge tracking headers into a base headers dict."""
    return {**base, **get_tracking_headers(username)}


async def check_fabric_role(sub: str) -> tuple[bool, list[str], dict[str, Any]]:
    """Check if a CILogon subject has the required FABRIC role.

    Mirrors FabricAuthenticator.is_in_allowed_cou_core_api from JupyterHub config.

    Args:
        sub: CILogon subject identifier (e.g. "http://cilogon.org/serverA/users/12345").

    Returns:
        Tuple of (authorized, roles, user_info).
        authorized is True if the user holds the required role.
    """
    url = f"{settings.FABRIC_CORE_API_HOST}/people/services-auth"
    params = {"sub": sub}
    headers = _tracked_headers({
        "Authorization": f"Bearer {settings.FABRIC_CORE_API_BEARER_TOKEN}",
        "Accept": "application/json",
    })

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, params=params, headers=headers)
        if resp.status_code != 200:
            logger.error(
                "FABRIC Core API /people/services-auth failed: %s %s",
                resp.status_code,
                resp.text,
            )
            return False, [], {}

    data = resp.json()
    results = data.get("results", [])
    if not results:
        logger.warning("No FABRIC user found for sub=%s", sub)
        return False, [], {}

    user_info = results[0]
    roles = user_info.get("roles", [])
    role_names = [r.get("name", "") for r in roles] if isinstance(roles, list) else []

    required = settings.FABRIC_REQUIRED_ROLE
    authorized = any(required.lower() in rn.lower() for rn in role_names)

    if not authorized:
        logger.warning(
            "User sub=%s does not have required role '%s'. Roles: %s",
            sub,
            required,
            role_names,
        )

    return authorized, role_names, user_info


async def get_fabric_username(sub: str) -> str:
    """Get the FABRIC UUID to use as the hub username.

    Mirrors check_username_claim_core_api: uses the UUID from the Core API
    as the canonical username.

    Args:
        sub: CILogon subject identifier.

    Returns:
        FABRIC UUID string (used as hub username).

    Raises:
        ValueError: If user is not found in FABRIC.
    """
    url = f"{settings.FABRIC_CORE_API_HOST}/people/services-auth"
    params = {"sub": sub}
    headers = _tracked_headers({
        "Authorization": f"Bearer {settings.FABRIC_CORE_API_BEARER_TOKEN}",
        "Accept": "application/json",
    })

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, params=params, headers=headers)
        if resp.status_code != 200:
            raise ValueError(f"Core API lookup failed: {resp.status_code}")

    data = resp.json()
    results = data.get("results", [])
    if not results:
        raise ValueError(f"No FABRIC user found for sub={sub}")

    uuid = results[0].get("uuid", "")
    if not uuid:
        raise ValueError(f"FABRIC user has no UUID for sub={sub}")

    return uuid


async def provision_fabric_tokens(
    cilogon_id_token: str,
    cilogon_refresh_token: str,
    project_id: str = "",
) -> dict[str, Any]:
    """Call FABRIC Credential Manager to create FABRIC tokens.

    Args:
        cilogon_id_token: The CILogon ID token.
        cilogon_refresh_token: The CILogon refresh token.
        project_id: Optional FABRIC project ID to scope tokens.

    Returns:
        Dict with FABRIC token data (id_token, refresh_token, etc.).
    """
    cm_url = f"https://{settings.FABRIC_CM_HOST}/credmgr/tokens/create"
    params: dict[str, Any] = {
        "scope": settings.FABRIC_CM_SCOPE,
        "lifetime": settings.FABRIC_CM_TOKEN_LIFETIME,
    }
    if project_id:
        params["projectId"] = project_id

    headers = _tracked_headers({
        "Accept": "application/json",
        "Content-Type": "application/json",
    })

    # The CM authenticates via cookie with the CILogon ID token
    cookies = {"mod_auth_openidc_session": cilogon_id_token}

    # The refresh token is sent in the request body
    body = {
        "refresh_token": cilogon_refresh_token,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(cm_url, params=params, headers=headers, json=body, cookies=cookies)
        if resp.status_code not in (200, 201):
            logger.error(
                "FABRIC CM token create failed: %s %s", resp.status_code, resp.text
            )
            raise ValueError(f"FABRIC CM token create failed: {resp.status_code}")

    token_data = resp.json()
    logger.info("FABRIC tokens provisioned successfully")
    return token_data


async def refresh_fabric_tokens(refresh_token: str) -> dict[str, Any]:
    """Refresh FABRIC tokens using a refresh token.

    Args:
        refresh_token: The FABRIC refresh token.

    Returns:
        Dict with refreshed FABRIC token data.
    """
    cm_url = f"https://{settings.FABRIC_CM_HOST}/credmgr/tokens/refresh"
    headers = _tracked_headers({
        "Accept": "application/json",
        "Content-Type": "application/json",
    })
    body = {
        "refresh_token": refresh_token,
        "scope": settings.FABRIC_CM_SCOPE,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(cm_url, headers=headers, json=body)
        if resp.status_code not in (200, 201):
            logger.error(
                "FABRIC CM token refresh failed: %s %s", resp.status_code, resp.text
            )
            raise ValueError(f"FABRIC CM token refresh failed: {resp.status_code}")

    token_data = resp.json()
    logger.info("FABRIC tokens refreshed successfully")
    return token_data
