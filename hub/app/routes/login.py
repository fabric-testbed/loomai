"""Login, OAuth callback, and logout routes."""

from __future__ import annotations

import json
import logging
import secrets
import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.cilogon import exchange_code, get_authorize_url, get_userinfo
from app.auth.fabric_auth import (
    check_fabric_role,
    get_fabric_username,
    provision_fabric_tokens,
)
from app.auth.session import COOKIE_NAME, create_session_cookie, get_current_user
from app.config import settings
from app.db.models import Server, TokenStore, User
from app.db.session import get_db
from app.proxy.chp_client import delete_route
from app.spawner.kubespawner import stop_user_pod
from app.spawner.pod_template import sanitize_username
from app.templates import templates

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/hub/login")
async def login(request: Request):
    """Show login page or redirect to CILogon."""
    # If user already has a valid session, redirect to spawn
    user = get_current_user(request)
    if user:
        return RedirectResponse(url=f"{settings.HUB_PREFIX}/spawn", status_code=302)

    # Render the login page
    return templates.TemplateResponse(
        request,
        "login.html",
        {"hub_prefix": settings.HUB_PREFIX},
    )


@router.get("/hub/login/start")
async def login_start():
    """Redirect to CILogon authorization endpoint."""
    state = secrets.token_urlsafe(32)
    authorize_url = get_authorize_url(state)
    return RedirectResponse(url=authorize_url, status_code=302)


@router.get("/hub/oauth_callback")
async def oauth_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    db: AsyncSession = Depends(get_db),
):
    """Handle CILogon OAuth callback.

    Flow:
    1. Exchange code for tokens
    2. Get userinfo from CILogon
    3. Check FABRIC role authorization
    4. Get FABRIC UUID as username
    5. Provision FABRIC tokens
    6. Create/update user in DB
    7. Set session cookie and redirect to spawn
    """
    if error:
        logger.error("OAuth callback error: %s", error)
        raise HTTPException(status_code=403, detail=f"OAuth error: {error}")

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state parameter")

    # Step 1: Exchange code for tokens
    try:
        tokens = await exchange_code(code, state)
    except ValueError as e:
        logger.error("Token exchange failed: %s", e)
        raise HTTPException(status_code=403, detail=str(e))

    id_token = tokens.get("id_token", "")
    access_token = tokens.get("access_token", "")
    refresh_token = tokens.get("refresh_token", "")

    # Step 2: Get userinfo
    try:
        userinfo = await get_userinfo(access_token)
    except ValueError as e:
        logger.error("Userinfo fetch failed: %s", e)
        raise HTTPException(status_code=403, detail=str(e))

    sub = userinfo.get("sub", "")
    email = userinfo.get("email", "")

    if not sub:
        raise HTTPException(status_code=403, detail="No 'sub' claim in userinfo")

    # Step 3: Check FABRIC role
    authorized, roles, fabric_user_info = await check_fabric_role(sub)
    if not authorized:
        raise HTTPException(
            status_code=403,
            detail=f"You do not have the required FABRIC role ({settings.FABRIC_REQUIRED_ROLE}). "
            "Please contact FABRIC support.",
        )

    # Step 4: Get FABRIC UUID as username
    try:
        fabric_uuid = await get_fabric_username(sub)
    except ValueError as e:
        logger.error("FABRIC username lookup failed: %s", e)
        raise HTTPException(status_code=403, detail=str(e))

    username = fabric_uuid

    # Step 5: Provision FABRIC tokens
    fabric_tokens = {}
    try:
        fabric_tokens = await provision_fabric_tokens(id_token, refresh_token)
    except Exception as e:
        logger.warning("FABRIC token provisioning failed (non-fatal): %s", e)
        # Non-fatal — user can still log in, tokens will be provisioned later

    # Step 6: Create or update user in DB
    stmt = select(User).where(User.sub == sub)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    is_admin = username in settings.admin_user_list or email in settings.admin_user_list

    if user is None:
        user = User(
            username=username,
            email=email,
            sub=sub,
            fabric_uuid=fabric_uuid,
            roles_json=json.dumps(roles),
            admin=is_admin,
        )
        db.add(user)
        await db.flush()
        logger.info("Created new user: %s (email=%s)", username, email)
    else:
        user.email = email
        user.fabric_uuid = fabric_uuid
        user.roles_json = json.dumps(roles)
        user.admin = is_admin
        user.last_login = datetime.datetime.utcnow()
        logger.info("Updated existing user: %s", username)

    # Store tokens
    stmt = select(TokenStore).where(TokenStore.user_id == user.id)
    result = await db.execute(stmt)
    token_store = result.scalar_one_or_none()

    if token_store is None:
        token_store = TokenStore(
            user_id=user.id,
            id_token=id_token,
            refresh_token=refresh_token,
            fabric_tokens_json=json.dumps(fabric_tokens) if fabric_tokens else None,
        )
        db.add(token_store)
    else:
        token_store.id_token = id_token
        token_store.refresh_token = refresh_token
        if fabric_tokens:
            token_store.fabric_tokens_json = json.dumps(fabric_tokens)
        token_store.updated_at = datetime.datetime.utcnow()

    await db.commit()

    # Step 7: Create session cookie and redirect
    cookie_value = create_session_cookie(username, extra={"email": email, "admin": is_admin})

    response = RedirectResponse(url=f"{settings.HUB_PREFIX}/spawn", status_code=302)
    response.set_cookie(
        key=COOKIE_NAME,
        value=cookie_value,
        max_age=settings.COOKIE_MAX_AGE,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        path="/",
    )

    return response


@router.get("/hub/logout")
async def logout(request: Request, db: AsyncSession = Depends(get_db)):
    """Stop user's server, clear session, and redirect to login."""
    user_session = get_current_user(request)
    if user_session:
        username = user_session["username"]
        safe_name = sanitize_username(username)

        # Stop the pod
        try:
            await stop_user_pod(username)
        except Exception as e:
            logger.warning("Error stopping pod on logout for %s: %s", username, e)

        # Remove proxy route
        try:
            await delete_route(f"/user/{safe_name}/")
        except Exception:
            pass

        # Update server state in DB
        try:
            stmt = select(User).where(User.username == username)
            result = await db.execute(stmt)
            user = result.scalar_one_or_none()
            if user:
                stmt2 = select(Server).where(Server.user_id == user.id).where(Server.name == "")
                result2 = await db.execute(stmt2)
                server = result2.scalar_one_or_none()
                if server and server.state != "stopped":
                    server.state = "stopped"
                    await db.commit()
        except Exception as e:
            logger.warning("Error updating server state on logout for %s: %s", username, e)

    response = RedirectResponse(url=f"{settings.HUB_PREFIX}/login", status_code=302)
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return response
