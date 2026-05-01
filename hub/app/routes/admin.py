"""Admin routes for managing users and servers."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.session import get_current_user
from app.config import settings
from app.db.models import Server, User
from app.db.session import get_db
from app.proxy.chp_client import delete_route
from app.spawner.kubespawner import stop_user_pod
from app.spawner.pod_template import sanitize_username
from app.templates import templates

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_admin(request: Request) -> dict[str, Any]:
    """Dependency: require an authenticated admin user."""
    session = get_current_user(request)
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not session.get("admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return session


@router.get("/hub/admin")
async def admin_dashboard(
    request: Request,
    session: dict = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin dashboard showing all users and their server states."""
    stmt = select(User).order_by(User.last_login.desc())
    result = await db.execute(stmt)
    users = result.scalars().all()

    # Build user data with server info
    user_data = []
    for user in users:
        stmt = select(Server).where(Server.user_id == user.id).where(Server.name == "")
        result = await db.execute(stmt)
        server = result.scalar_one_or_none()

        user_data.append({
            "username": user.username,
            "email": user.email or "",
            "admin": user.admin,
            "last_login": user.last_login.isoformat() if user.last_login else "never",
            "server_state": server.state if server else "stopped",
            "pod_name": server.pod_name if server else "",
            "started_at": server.started_at.isoformat() if server and server.started_at else "",
            "last_activity": server.last_activity.isoformat() if server and server.last_activity else "",
        })

    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "hub_prefix": settings.HUB_PREFIX,
            "users": user_data,
            "admin_username": session["username"],
        },
    )


@router.post("/hub/admin/users/{username}/stop")
async def admin_stop_server(
    username: str,
    request: Request,
    session: dict = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin action: stop a user's server."""
    logger.info("Admin %s stopping server for user %s", session["username"], username)

    # Stop the pod
    try:
        await stop_user_pod(username)
    except Exception as e:
        logger.error("Error stopping pod for %s: %s", username, e)

    # Remove proxy route
    safe_name = sanitize_username(username)
    try:
        await delete_route(f"/user/{safe_name}/")
    except Exception:
        pass

    # Update DB
    stmt = select(User).where(User.username == username)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if user:
        await db.execute(
            update(Server)
            .where(Server.user_id == user.id)
            .where(Server.name == "")
            .values(state="stopped")
        )
        await db.commit()

    return RedirectResponse(url=f"{settings.HUB_PREFIX}/admin", status_code=303)
