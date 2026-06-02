"""Auth check endpoint for singleuser pod nginx auth_request."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, Response

from app.auth.session import get_current_user
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/hub/api/auth/check")
async def auth_check(request: Request, user: str = Query(...)):
    """Validate session cookie and check user authorization.

    Called by singleuser pod nginx via auth_request.
    The ``user`` query parameter is the pod owner's username (FABRIC UUID).

    Returns:
        200 if the session user matches (or is admin).
        401 if not authenticated (no valid session cookie).
        403 if authenticated but accessing another user's pod.
    """
    session = get_current_user(request)
    if not session:
        logger.debug("Auth check: no valid session for user=%s", user)
        return Response(status_code=401)

    session_user = session.get("username", "")
    is_admin = session.get("admin", False)

    if session_user == user or is_admin:
        return Response(status_code=200)

    logger.warning(
        "Auth check: user %s tried to access pod of %s",
        session_user,
        user,
    )
    return HTMLResponse(
        status_code=403,
        content=f"""<!DOCTYPE html>
<html><head><title>403 — Access Denied</title>
<style>
body{{font-family:sans-serif;display:flex;align-items:center;justify-content:center;
min-height:100vh;margin:0;background:#f5f7fa;color:#1c2e4a}}
.card{{text-align:center;padding:40px;border-radius:12px;background:white;
box-shadow:0 2px 12px rgba(0,0,0,0.1);max-width:460px}}
h1{{font-size:48px;margin:0 0 8px;opacity:0.3}}h2{{margin:0 0 16px}}
p{{color:#666;line-height:1.5}}
a{{display:inline-block;margin-top:16px;padding:10px 24px;background:#27aae1;
color:white;text-decoration:none;border-radius:6px;font-weight:600}}
a:hover{{background:#1f6a8c}}
</style></head>
<body><div class="card">
<h1>403</h1>
<h2>Access Denied</h2>
<p>You do not have permission to access Server at <code>/user/{user}/</code></p>
<a href="/hub/spawn">Go to Your Server</a>
</div></body></html>""",
    )
