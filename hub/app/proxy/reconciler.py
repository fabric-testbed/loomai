"""Background reconciler that keeps CHP proxy routes in sync with running pods.

CHP (configurable-http-proxy) holds its routing table in memory only. When the
proxy restarts, every per-user route is lost, while the hub database still
records those servers as ``ready``. The hub would then redirect users to
``/user/<name>/``, CHP would fall through to the hub default target, and the
hub's ``/user/*`` catch-all would bounce them back to login — an endless
redirect loop that only ends in ``ERR_TOO_MANY_REDIRECTS``.

This module closes that gap from both sides:

* :func:`ensure_route` — an on-demand check used before redirecting a user to
  their server, restoring the route if the pod is alive but unrouted.
* :func:`start_reconciler` — a periodic sweep that re-adds routes for every
  ``ready`` server, so a proxy restart self-heals without user interaction.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.db.models import Server, User
from app.proxy.chp_client import add_route, get_routes
from app.spawner.kubespawner import get_pod_status
from app.spawner.pod_template import sanitize_username

logger = logging.getLogger(__name__)

_reconciler_task: asyncio.Task | None = None

# Pod phases that mean the pod is alive (or on its way) and worth routing to.
_LIVE_PHASES = ("Running", "Pending", "ContainerCreating")


def route_spec_for(username: str) -> str:
    """Return the CHP route spec for a user's server."""
    return f"/user/{sanitize_username(username)}/"


def target_for(username: str) -> str:
    """Return the in-cluster target URL for a user's server."""
    return f"http://loomai-{sanitize_username(username)}:3000"


def _normalize(route_spec: str) -> str:
    """Normalize a route spec for comparison.

    The hub registers routes with a trailing slash (``/user/abc/``) but CHP
    reports them without one (``/user/abc``). Comparing the raw strings would
    make every route look missing and re-add it on every pass.
    """
    return "/" + route_spec.strip("/")


async def _current_route_specs() -> set[str]:
    """Return the set of normalized route specs currently known to CHP."""
    routes = await get_routes()
    return {_normalize(spec) for spec in routes}


async def ensure_route(
    username: str,
    known_routes: set[str] | None = None,
) -> bool:
    """Ensure a proxy route exists for a user whose server should be running.

    Args:
        username: Hub username.
        known_routes: Pre-fetched set of normalized route specs, to avoid
            re-querying CHP once per user during a bulk sweep.

    Returns:
        True if the route is present (or was successfully restored), False if
        it is missing and could not be restored — e.g. the pod is gone, or the
        proxy is unreachable. A False result means the caller must NOT redirect
        the user to ``/user/<name>/``, since that would start a redirect loop.
    """
    route_spec = route_spec_for(username)

    try:
        if known_routes is None:
            known_routes = await _current_route_specs()
    except Exception:
        logger.warning(
            "Could not read proxy routes while checking %s", username, exc_info=True
        )
        return False

    if _normalize(route_spec) in known_routes:
        return True

    # Route is missing. Only re-add it if the pod is actually there to serve it.
    try:
        status = await get_pod_status(username)
    except Exception:
        logger.warning(
            "Could not read pod status while recovering route for %s",
            username,
            exc_info=True,
        )
        return False

    if status.get("phase") not in _LIVE_PHASES:
        logger.info(
            "Not restoring route %s: pod is %s", route_spec, status.get("phase")
        )
        return False

    if not status.get("ready"):
        # Pod exists but is not serving yet; let the spawn flow wait on it
        # rather than routing traffic into a pod that will 503.
        logger.info("Not restoring route %s yet: pod not ready", route_spec)
        return False

    try:
        await add_route(route_spec, target_for(username))
    except Exception:
        logger.warning("Failed to restore proxy route %s", route_spec, exc_info=True)
        return False

    logger.info(
        "Recovered missing proxy route %s (pod was running but unrouted)", route_spec
    )
    return True


async def _reconcile_once(session_maker: async_sessionmaker) -> int:
    """Run one reconciliation pass over all servers marked ready.

    Returns:
        The number of routes restored during this pass.
    """
    async with session_maker() as db:
        stmt = (
            select(User.username)
            .join(Server, Server.user_id == User.id)
            .where(Server.name == "")
            .where(Server.state == "ready")
        )
        result = await db.execute(stmt)
        usernames = [row[0] for row in result.all()]

    if not usernames:
        return 0

    try:
        known_routes = await _current_route_specs()
    except Exception:
        logger.warning("Proxy unreachable during route reconcile", exc_info=True)
        return 0

    missing = [
        u for u in usernames if _normalize(route_spec_for(u)) not in known_routes
    ]
    if not missing:
        return 0

    logger.info(
        "Route reconcile: %d of %d ready server(s) have no proxy route",
        len(missing),
        len(usernames),
    )

    restored = 0
    for username in missing:
        try:
            if await ensure_route(username, known_routes=known_routes):
                restored += 1
        except Exception:
            logger.exception("Error reconciling route for user %s", username)

    if restored:
        logger.info("Route reconcile: restored %d route(s)", restored)

    return restored


async def _reconciler_loop(session_maker: async_sessionmaker) -> None:
    """Run the route reconciler in a loop."""
    logger.info(
        "Proxy route reconciler started (every=%ds)",
        settings.ROUTE_RECONCILE_EVERY,
    )
    # Run once promptly at startup: if the hub and proxy restarted together,
    # users should not have to wait a full interval to get their routes back.
    while True:
        try:
            await _reconcile_once(session_maker)
            await asyncio.sleep(settings.ROUTE_RECONCILE_EVERY)
        except asyncio.CancelledError:
            logger.info("Proxy route reconciler cancelled")
            break
        except Exception:
            logger.exception("Error in proxy route reconciler loop")
            await asyncio.sleep(settings.ROUTE_RECONCILE_EVERY)


def start_reconciler(session_maker: async_sessionmaker) -> asyncio.Task | None:
    """Start the route reconciler background task.

    Args:
        session_maker: Async session factory for DB access.

    Returns:
        The asyncio Task, or None if reconciliation is disabled.
    """
    global _reconciler_task

    if not settings.ROUTE_RECONCILE_ENABLED:
        logger.info("Proxy route reconciler is disabled")
        return None

    _reconciler_task = asyncio.create_task(_reconciler_loop(session_maker))
    return _reconciler_task


def stop_reconciler() -> None:
    """Cancel the reconciler task if running."""
    global _reconciler_task
    if _reconciler_task and not _reconciler_task.done():
        _reconciler_task.cancel()
        _reconciler_task = None
