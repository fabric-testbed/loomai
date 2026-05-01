"""Health check and error page routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/hub/health")
async def health():
    """Basic liveness probe."""
    return {"status": "ok"}


@router.get("/hub/error/{code}", response_class=HTMLResponse)
async def error_page(code: int, url: str = ""):
    """Error page shown by CHP when a target is unreachable."""
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
