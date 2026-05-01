"""Background idle culler for inactive single-user pods."""

from __future__ import annotations

import asyncio
import datetime
import logging
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.db.models import Server, User
from app.proxy.chp_client import delete_route
from app.spawner.kubespawner import stop_user_pod
from app.spawner.pod_template import sanitize_username

logger = logging.getLogger(__name__)

_culler_task: asyncio.Task | None = None


async def _cull_once(session_maker: async_sessionmaker) -> None:
    """Run one culling pass over all running servers."""
    now = datetime.datetime.utcnow()

    async with session_maker() as db:
        stmt = (
            select(Server, User)
            .join(User, Server.user_id == User.id)
            .where(Server.state.in_(["ready", "pending"]))
        )
        result = await db.execute(stmt)
        rows = result.all()

    for server, user in rows:
        should_cull = False
        reason = ""

        # Check max age
        if server.started_at:
            age = (now - server.started_at).total_seconds()
            if age > settings.CULL_MAX_AGE:
                should_cull = True
                reason = f"max age exceeded ({age:.0f}s > {settings.CULL_MAX_AGE}s)"

        # Check idle timeout
        if not should_cull and server.last_activity:
            idle = (now - server.last_activity).total_seconds()
            if idle > settings.CULL_TIMEOUT:
                should_cull = True
                reason = f"idle timeout ({idle:.0f}s > {settings.CULL_TIMEOUT}s)"

        # If no last_activity recorded, use started_at as fallback
        if not should_cull and not server.last_activity and server.started_at:
            idle = (now - server.started_at).total_seconds()
            if idle > settings.CULL_TIMEOUT:
                should_cull = True
                reason = f"no activity since start ({idle:.0f}s > {settings.CULL_TIMEOUT}s)"

        if should_cull:
            logger.info(
                "Culling server for user %s (pod=%s): %s",
                user.username,
                server.pod_name,
                reason,
            )
            try:
                # Stop the pod
                await stop_user_pod(user.username)

                # Remove proxy route
                safe = sanitize_username(user.username)
                try:
                    await delete_route(f"/user/{safe}/")
                except Exception:
                    logger.warning("Failed to remove proxy route for %s", user.username)

                # Update server state
                async with session_maker() as db:
                    await db.execute(
                        update(Server)
                        .where(Server.id == server.id)
                        .values(state="stopped")
                    )
                    await db.commit()

                logger.info("Successfully culled server for user %s", user.username)

            except Exception:
                logger.exception("Error culling server for user %s", user.username)


async def _culler_loop(session_maker: async_sessionmaker) -> None:
    """Run the culler in a loop."""
    logger.info(
        "Idle culler started (every=%ds, timeout=%ds, max_age=%ds)",
        settings.CULL_EVERY,
        settings.CULL_TIMEOUT,
        settings.CULL_MAX_AGE,
    )
    while True:
        try:
            await asyncio.sleep(settings.CULL_EVERY)
            await _cull_once(session_maker)
        except asyncio.CancelledError:
            logger.info("Idle culler cancelled")
            break
        except Exception:
            logger.exception("Error in idle culler loop")


def start_culler(session_maker: async_sessionmaker) -> asyncio.Task | None:
    """Start the idle culler background task.

    Args:
        session_maker: Async session factory for DB access.

    Returns:
        The asyncio Task, or None if culling is disabled.
    """
    global _culler_task

    if not settings.CULL_ENABLED:
        logger.info("Idle culler is disabled")
        return None

    _culler_task = asyncio.create_task(_culler_loop(session_maker))
    return _culler_task


def stop_culler() -> None:
    """Cancel the culler task if running."""
    global _culler_task
    if _culler_task and not _culler_task.done():
        _culler_task.cancel()
        _culler_task = None
