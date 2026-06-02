"""Health check and error page routes."""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, update, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Server, User
from app.db.session import get_db, async_session_maker
from app.proxy.chp_client import delete_route
from app.spawner.kubespawner import get_pod_status

logger = logging.getLogger(__name__)
router = APIRouter()

# Pattern to extract username from CHP error URLs like /user/{username}/...
_USER_URL_RE = re.compile(r"^/user/([^/]+)")


@router.get("/hub/health")
async def health():
    """Basic liveness probe."""
    return {"status": "ok"}


async def _cleanup_dead_server(safe_name: str) -> bool:
    """Check if a user's pod is gone and clean up stale proxy route + DB state.

    Returns True if the pod was dead and cleanup was performed.
    """
    status = await get_pod_status(safe_name)
    phase = status["phase"]

    if phase in ("Running", "Pending", "ContainerCreating"):
        # Pod is alive or starting — don't clean up
        return False

    logger.info(
        "Pod for %s is %s — cleaning up stale route and DB state",
        safe_name, phase,
    )

    # Remove the CHP proxy route so future requests don't loop
    try:
        await delete_route(f"/user/{safe_name}/")
    except Exception:
        logger.warning("Failed to delete proxy route for %s", safe_name, exc_info=True)

    # Mark the server as stopped in the DB
    try:
        async with async_session_maker() as db:
            result = await db.execute(
                select(User).where(User.username == safe_name)
            )
            user = result.scalar_one_or_none()
            if user:
                await db.execute(
                    update(Server)
                    .where(Server.user_id == user.id, Server.state != "stopped")
                    .values(state="stopped")
                )
                await db.commit()
    except Exception:
        logger.warning("Failed to update DB state for %s", safe_name, exc_info=True)

    return True


@router.get("/hub/error/{code}", response_class=HTMLResponse)
async def error_page(code: int, url: str = ""):
    """Error page shown by CHP when a target is unreachable."""

    # For 503 errors on user URLs, check if the pod is actually dead.
    # If so, clean up the stale proxy route and redirect to home/login
    # instead of looping on the 503 page forever.
    if code == 503 and url:
        m = _USER_URL_RE.match(url)
        if m:
            safe_name = m.group(1)
            logger.info("503 handler: checking pod for user %s (url=%s)", safe_name, url)
            try:
                pod_dead = await _cleanup_dead_server(safe_name)
                if pod_dead:
                    logger.info("503 handler: pod dead, redirecting %s to /hub/home", safe_name)
                    return RedirectResponse(url="/hub/login", status_code=302)
                else:
                    logger.info("503 handler: pod still alive for %s, showing 503 page", safe_name)
            except Exception:
                logger.warning(
                    "Error checking pod status for %s during 503 handler",
                    safe_name, exc_info=True,
                )

    messages = {
        503: "Your server is starting up or has stopped. Please wait a moment and try again.",
        500: "An internal error occurred. Please try again.",
        404: "The requested page was not found.",
    }
    msg = messages.get(code, f"An error occurred (HTTP {code}).")
    retry_url = url or "/hub/spawn"
    return f"""<!DOCTYPE html>
<html><head><title>LoomAI - {code}</title>
<style>body{{font-family:sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;background:#f5f7fa;color:#1c2e4a}}
.card{{text-align:center;padding:40px;border-radius:12px;background:white;box-shadow:0 2px 12px rgba(0,0,0,0.1);max-width:420px}}
h1{{font-size:48px;margin:0 0 8px;opacity:0.3}}h2{{margin:0 0 16px}}p{{color:#666;line-height:1.5}}
a{{display:inline-block;margin-top:16px;padding:10px 24px;background:#27aae1;color:white;text-decoration:none;border-radius:6px;font-weight:600}}
a:hover{{background:#1f6a8c}}</style>
{('<meta http-equiv="refresh" content="5;url=' + retry_url + '">') if code == 503 else ''}
</head><body><div class="card"><h1>{code}</h1><h2>{'Server Starting...' if code == 503 else 'Error'}</h2>
<p>{msg}</p><a href="{retry_url}">{'Retry' if code != 503 else 'Go to Spawn Page'}</a>
{'<p style="font-size:12px;color:#999;margin-top:12px">This page will auto-refresh in 5 seconds...</p>' if code == 503 else ''}
</div></body></html>"""


@router.get("/hub/ready")
async def ready(db: AsyncSession = Depends(get_db)):
    """Readiness probe — verifies DB connectivity."""
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        logger.error("Readiness check failed: %s", e)
        return {"status": "error", "database": str(e)}
