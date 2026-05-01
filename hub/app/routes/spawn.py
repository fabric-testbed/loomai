"""Spawn routes for starting/stopping single-user servers."""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.session import get_current_user
from app.config import settings
from app.db.models import Server, TokenStore, User
from app.db.session import get_db
from app.proxy.chp_client import add_route, delete_route
from app.spawner.kubespawner import (
    create_token_secret,
    get_pod_status,
    spawn_user_pod,
    stop_user_pod,
    wait_for_pod_ready,
)
from app.spawner.pvc import ensure_user_pvc
from app.spawner.pod_template import sanitize_username
from app.templates import templates

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_user(request: Request) -> dict[str, Any]:
    """Dependency: require an authenticated user session."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


async def _get_or_create_server(db: AsyncSession, user: User) -> Server:
    """Get the default server for a user, creating one if needed."""
    stmt = select(Server).where(Server.user_id == user.id).where(Server.name == "")
    result = await db.execute(stmt)
    server = result.scalar_one_or_none()

    if server is None:
        server = Server(user_id=user.id, name="", state="stopped")
        db.add(server)
        await db.flush()

    return server


async def _do_spawn(username: str, db: AsyncSession) -> str:
    """Execute the full spawn sequence.

    Returns:
        The pod name on success.

    Raises:
        RuntimeError: If spawn fails.
    """
    # Look up user and tokens
    stmt = select(User).where(User.username == username)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise RuntimeError(f"User {username} not found")

    stmt = select(TokenStore).where(TokenStore.user_id == user.id)
    result = await db.execute(stmt)
    token_store = result.scalar_one_or_none()

    # Prepare token data for K8s secret
    token_data = {}
    if token_store and token_store.fabric_tokens_json:
        token_data = json.loads(token_store.fabric_tokens_json)
    if token_store and token_store.id_token:
        token_data["cilogon_id_token"] = token_store.id_token
    if token_store and token_store.refresh_token:
        token_data["cilogon_refresh_token"] = token_store.refresh_token

    # Get or create server record
    server = await _get_or_create_server(db, user)
    server.state = "pending"
    server.started_at = datetime.datetime.utcnow()
    server.last_activity = datetime.datetime.utcnow()
    await db.commit()

    try:
        # 1. Ensure PVC
        pvc_name = await ensure_user_pvc(username)

        # 2. Create token secret
        secret_name = await create_token_secret(username, token_data)

        # 3. Spawn pod
        pod_name = await spawn_user_pod(
            username=username,
            token_secret_name=secret_name,
            config={"pvc_name": pvc_name},
        )

        server.pod_name = pod_name
        await db.commit()

        # 4. Wait for pod readiness
        ready = await wait_for_pod_ready(username)
        if not ready:
            raise RuntimeError(f"Pod for {username} did not become ready in time")

        # 5. Add proxy route
        safe_name = sanitize_username(username)
        route_spec = f"/user/{safe_name}/"
        target = f"http://loomai-{safe_name}:3000"
        await add_route(route_spec, target)

        # 6. Update server state
        server.state = "ready"
        await db.commit()

        logger.info("Spawn complete for user %s (pod=%s)", username, pod_name)
        return pod_name

    except Exception as e:
        logger.error("Spawn failed for user %s: %s", username, e)
        server.state = "stopped"
        await db.commit()
        raise


@router.get("/hub/spawn")
async def spawn_page(
    request: Request,
    session: dict = Depends(_require_user),
    db: AsyncSession = Depends(get_db),
):
    """Spawn page: redirect to running server or show spawn progress."""
    username = session["username"]
    safe_name = sanitize_username(username)

    # Check if user already has a running server
    stmt = select(User).where(User.username == username)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user:
        stmt = select(Server).where(Server.user_id == user.id).where(Server.name == "")
        result = await db.execute(stmt)
        server = result.scalar_one_or_none()

        if server and server.state == "ready":
            return RedirectResponse(url=f"/user/{safe_name}/", status_code=302)

    # Render spawn progress page
    return templates.TemplateResponse(
        request,
        "spawn.html",
        {
            "hub_prefix": settings.HUB_PREFIX,
            "username": username,
            "safe_name": safe_name,
        },
    )


@router.post("/hub/api/users/{username}/server")
async def start_server(
    username: str,
    request: Request,
    session: dict = Depends(_require_user),
    db: AsyncSession = Depends(get_db),
):
    """API endpoint to start a user's server."""
    # Authorization: user can only start their own server (or admin)
    if session["username"] != username and not session.get("admin"):
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        pod_name = await _do_spawn(username, db)
        safe_name = sanitize_username(username)
        return {
            "status": "ready",
            "pod_name": pod_name,
            "url": f"/user/{safe_name}/",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/hub/api/users/{username}/server")
async def stop_server(
    username: str,
    request: Request,
    session: dict = Depends(_require_user),
    db: AsyncSession = Depends(get_db),
):
    """API endpoint to stop a user's server."""
    if session["username"] != username and not session.get("admin"):
        raise HTTPException(status_code=403, detail="Forbidden")

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

    # Update server state
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

    return {"status": "stopped"}


@router.get("/hub/api/users/{username}/server/progress")
async def spawn_progress(
    username: str,
    request: Request,
    session: dict = Depends(_require_user),
    db: AsyncSession = Depends(get_db),
):
    """SSE endpoint for spawn progress updates."""
    if session["username"] != username and not session.get("admin"):
        raise HTTPException(status_code=403, detail="Forbidden")

    async def event_stream():
        # Check current server state
        stmt = select(User).where(User.username == username)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            yield f"data: {json.dumps({'event': 'error', 'message': 'User not found'})}\n\n"
            return

        stmt = select(Server).where(Server.user_id == user.id).where(Server.name == "")
        result = await db.execute(stmt)
        server = result.scalar_one_or_none()

        if server and server.state == "ready":
            safe_name = sanitize_username(username)
            yield f"data: {json.dumps({'event': 'ready', 'url': f'/user/{safe_name}/'})}\n\n"
            return

        # Start the spawn process in the background
        yield f"data: {json.dumps({'event': 'progress', 'message': 'Starting server...'})}\n\n"

        try:
            # Spawn steps with progress
            yield f"data: {json.dumps({'event': 'progress', 'message': 'Creating storage volume...'})}\n\n"
            pvc_name = await ensure_user_pvc(username)

            yield f"data: {json.dumps({'event': 'progress', 'message': 'Preparing credentials...'})}\n\n"

            # Get token data
            token_data = {}
            if user:
                stmt2 = select(TokenStore).where(TokenStore.user_id == user.id)
                result2 = await db.execute(stmt2)
                ts = result2.scalar_one_or_none()
                if ts and ts.fabric_tokens_json:
                    token_data = json.loads(ts.fabric_tokens_json)
                if ts and ts.id_token:
                    token_data["cilogon_id_token"] = ts.id_token
                if ts and ts.refresh_token:
                    token_data["cilogon_refresh_token"] = ts.refresh_token

            secret_name = await create_token_secret(username, token_data)

            yield f"data: {json.dumps({'event': 'progress', 'message': 'Launching pod...'})}\n\n"

            # Update server state
            if not server:
                server = Server(user_id=user.id, name="", state="pending")
                db.add(server)
                await db.flush()
            server.state = "pending"
            server.started_at = datetime.datetime.utcnow()
            server.last_activity = datetime.datetime.utcnow()
            await db.commit()

            pod_name = await spawn_user_pod(
                username=username,
                token_secret_name=secret_name,
                config={"pvc_name": pvc_name},
            )
            server.pod_name = pod_name
            await db.commit()

            yield f"data: {json.dumps({'event': 'progress', 'message': 'Waiting for pod to be ready...'})}\n\n"

            # Poll pod status
            timeout = settings.SINGLEUSER_START_TIMEOUT
            elapsed = 0
            interval = 3
            while elapsed < timeout:
                status = await get_pod_status(username)
                phase = status["phase"]
                yield f"data: {json.dumps({'event': 'progress', 'message': f'Pod status: {phase}', 'phase': phase})}\n\n"

                if status["ready"]:
                    break
                if status["phase"] in ("Failed", "Unknown"):
                    msg = status["message"]
                    yield f"data: {json.dumps({'event': 'error', 'message': f'Pod failed: {msg}'})}\n\n"
                    server.state = "stopped"
                    await db.commit()
                    return

                await asyncio.sleep(interval)
                elapsed += interval

            if elapsed >= timeout:
                yield f"data: {json.dumps({'event': 'error', 'message': 'Pod startup timed out'})}\n\n"
                server.state = "stopped"
                await db.commit()
                return

            # Add proxy route
            safe_name = sanitize_username(username)
            route_spec = f"/user/{safe_name}/"
            target = f"http://loomai-{safe_name}:3000"
            await add_route(route_spec, target)

            server.state = "ready"
            await db.commit()

            yield f"data: {json.dumps({'event': 'ready', 'url': f'/user/{safe_name}/'})}\n\n"

        except Exception as e:
            logger.exception("Spawn SSE error for %s", username)
            yield f"data: {json.dumps({'event': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
