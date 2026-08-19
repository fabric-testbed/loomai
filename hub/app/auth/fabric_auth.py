"""FABRIC Core API and Credential Manager integration."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.config import settings
from app.tracking_headers import get_tracking_headers

logger = logging.getLogger(__name__)


class FabricAPIError(Exception):
    """The FABRIC Core API could not be reached or returned an error.

    Distinct from a user genuinely lacking the required role — callers must
    not report this as ineligibility."""


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

    Raises:
        FabricAPIError: If the Core API is unreachable or returns an error —
            i.e. eligibility could not be determined at all.
    """
    import re

    url = f"{settings.FABRIC_CORE_API_HOST}/people/services-auth"
    params = {"sub": sub}
    headers = _tracked_headers({
        "Authorization": f"Bearer {settings.FABRIC_CORE_API_BEARER_TOKEN}",
        "Accept": "application/json",
    })

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, params=params, headers=headers)
    except httpx.HTTPError as e:
        logger.error("FABRIC Core API /people/services-auth unreachable: %s", e)
        raise FabricAPIError(f"Core API unreachable: {e}") from e

    if resp.status_code != 200:
        logger.error(
            "FABRIC Core API /people/services-auth failed: %s %s",
            resp.status_code,
            resp.text,
        )
        raise FabricAPIError(f"Core API returned {resp.status_code}")

    try:
        data = resp.json()
    except ValueError as e:
        logger.error(
            "FABRIC Core API returned non-JSON body: %s", resp.text[:200]
        )
        raise FabricAPIError("Core API returned a malformed response") from e

    if not isinstance(data, dict) or not isinstance(data.get("results", []), list):
        logger.error("FABRIC Core API returned unexpected structure: %.200s", data)
        raise FabricAPIError("Core API returned a malformed response")

    results = data.get("results", [])
    if not results:
        logger.warning("No FABRIC user found for sub=%s", sub)
        return False, [], {}, []

    user_info = results[0]
    if not isinstance(user_info, dict):
        logger.error("FABRIC Core API returned non-dict user entry: %.200s", user_info)
        raise FabricAPIError("Core API returned a malformed response")

    roles = user_info.get("roles", [])
    if not isinstance(roles, list):
        # A user with no roles is "roles": [] — a non-list is a malformed
        # response, and treating it as "no roles" would misreport an
        # eligible user as unauthorized.
        logger.error("FABRIC Core API returned non-list roles: %.200s", roles)
        raise FabricAPIError("Core API returned a malformed response")

    # A malformed entry must not be skipped: if it were the one carrying the
    # required role, an eligible user would be misreported as unauthorized.
    role_names: list[str] = []
    for r in roles:
        if not isinstance(r, dict) or not isinstance(r.get("name"), str):
            logger.error("FABRIC Core API returned malformed role entry: %.200s", r)
            raise FabricAPIError("Core API returned a malformed response")
        role_names.append(r["name"])

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
    # A project appears as several roles ({uuid}-pm/po/pc/tk), possibly with
    # differing/malformed descriptions. Decide per project over ALL its role
    # entries so the outcome is order-independent (role entries are validated
    # above: dicts with a string name):
    #   - any readable description marks it SERVICE -> exclude
    #   - else at least one readable description    -> include
    #   - else (no readable description)            -> exclude; SERVICE cannot
    #     be ruled out. This only affects auto-selection, never eligibility.
    # A missing description key is as unreadable as a non-string one — it must
    # not default to "" or it would count as readable and vouch for the project.
    project_descs: dict[str, list] = {}
    for role in roles:
        m = uuid_pattern.match(role["name"])
        if not m:
            continue
        project_descs.setdefault(m.group(1), []).append(role.get("description"))

    service_re = re.compile(r'^SERVICE\s*[-\u2013\u2014]', re.IGNORECASE)
    projects: list[dict[str, str]] = []
    for project_uuid, descs in project_descs.items():
        readable = [d for d in descs if isinstance(d, str)]
        if any(service_re.match(d) for d in readable):
            continue
        if not readable:
            logger.warning(
                "Project %s has no readable description; excluding: %.200s",
                project_uuid, descs,
            )
            continue
        projects.append({"uuid": project_uuid, "name": readable[0]})

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
