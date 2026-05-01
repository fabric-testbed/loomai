"""REST client for configurable-http-proxy (CHP)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def add_route(
    route_spec: str,
    target: str,
    auth_token: str | None = None,
) -> None:
    """Add a route to the CHP proxy.

    Args:
        route_spec: The route path (e.g. "/user/abc123/").
        target: The target URL (e.g. "http://loomai-abc123:8000").
        auth_token: CHP API auth token. Defaults to settings.
    """
    auth_token = auth_token or settings.PROXY_AUTH_TOKEN
    url = f"{settings.PROXY_API_URL}/api/routes{route_spec}"
    headers = {"Authorization": f"token {auth_token}"}
    body = {"target": target}

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, headers=headers, json=body)
        if resp.status_code not in (200, 201):
            logger.error(
                "Failed to add proxy route %s -> %s: %s %s",
                route_spec,
                target,
                resp.status_code,
                resp.text,
            )
            raise RuntimeError(f"CHP add_route failed: {resp.status_code}")

    logger.info("Proxy route added: %s -> %s", route_spec, target)


async def delete_route(
    route_spec: str,
    auth_token: str | None = None,
) -> None:
    """Delete a route from the CHP proxy.

    Args:
        route_spec: The route path to remove.
        auth_token: CHP API auth token. Defaults to settings.
    """
    auth_token = auth_token or settings.PROXY_AUTH_TOKEN
    url = f"{settings.PROXY_API_URL}/api/routes{route_spec}"
    headers = {"Authorization": f"token {auth_token}"}

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.delete(url, headers=headers)
        if resp.status_code not in (200, 204, 404):
            logger.error(
                "Failed to delete proxy route %s: %s %s",
                route_spec,
                resp.status_code,
                resp.text,
            )
            raise RuntimeError(f"CHP delete_route failed: {resp.status_code}")

    logger.info("Proxy route deleted: %s", route_spec)


async def get_routes(auth_token: str | None = None) -> dict[str, Any]:
    """Get all routes from the CHP proxy.

    Args:
        auth_token: CHP API auth token. Defaults to settings.

    Returns:
        Dict mapping route specs to their target info.
    """
    auth_token = auth_token or settings.PROXY_AUTH_TOKEN
    url = f"{settings.PROXY_API_URL}/api/routes"
    headers = {"Authorization": f"token {auth_token}"}

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            logger.error("Failed to get proxy routes: %s %s", resp.status_code, resp.text)
            raise RuntimeError(f"CHP get_routes failed: {resp.status_code}")

    return resp.json()
