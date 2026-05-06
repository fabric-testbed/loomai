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


async def check_fabric_role(sub: str) -> tuple[bool, list[str], dict[str, Any], list[dict[str, str]]]:
    """Check if a CILogon subject has the required FABRIC role.

    Mirrors FabricAuthenticator.is_in_allowed_cou_core_api from JupyterHub config.
    Also extracts project UUIDs from role names (pattern: ``{uuid}-{suffix}``).

    Args:
        sub: CILogon subject identifier (e.g. "http://cilogon.org/serverA/users/12345").

    Returns:
        Tuple of (authorized, roles, user_info, projects).
        authorized is True if the user holds the required role.
        projects is a list of {uuid, name} dicts for non-SERVICE projects.
    """
    import re

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
            return False, [], {}, []

    data = resp.json()
    results = data.get("results", [])
    if not results:
        logger.warning("No FABRIC user found for sub=%s", sub)
        return False, [], {}, []

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

    # Extract projects from role names: {uuid}-{suffix} where suffix is pm/po/pc/tk
    uuid_pattern = re.compile(
        r'^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})-(?:pm|po|pc|tk)$'
    )
    seen_uuids: set[str] = set()
    projects: list[dict[str, str]] = []
    for role in (roles if isinstance(roles, list) else []):
        name = role.get("name", "")
        desc = role.get("description", "")
        m = uuid_pattern.match(name)
        if not m:
            continue
        project_uuid = m.group(1)
        if project_uuid in seen_uuids:
            continue
        seen_uuids.add(project_uuid)
        # Skip SERVICE projects
        if re.match(r'^SERVICE\s*[-\u2013\u2014]', desc, re.IGNORECASE):
            continue
        projects.append({"uuid": project_uuid, "name": desc})

    logger.info("Extracted %d projects from roles for sub=%s", len(projects), sub)

    return authorized, role_names, user_info, projects


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
