"""LoomAI Hub — FastAPI application entry point.

Multi-user hub service that handles CILogon OIDC authentication,
FABRIC Core API authorization, Kubernetes pod spawning, and
configurable-http-proxy route management.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.culler.idle_culler import start_culler, stop_culler
from app.db.session import async_session_maker, init_db
from app.proxy.chp_client import add_route
from app.routes import admin, health, login, spawn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown tasks."""
    # --- Startup ---
    logger.info("LoomAI Hub starting up")

    # 1. Initialize database tables
    await init_db()

    # 2. Register the hub itself with the CHP proxy
    #    so that /hub/* requests are routed to this FastAPI service
    try:
        hub_target = settings.HUB_BASE_URL
        await add_route(f"{settings.HUB_PREFIX}/", hub_target)
        logger.info(
            "Registered hub route: %s/ -> %s",
            settings.HUB_PREFIX,
            hub_target,
        )
    except Exception as e:
        logger.warning(
            "Could not register hub route with proxy (proxy may not be running): %s",
            e,
        )

    # 3. Start idle culler background task
    culler_task = start_culler(async_session_maker)
    if culler_task:
        logger.info("Idle culler started")

    yield

    # --- Shutdown ---
    logger.info("LoomAI Hub shutting down")
    stop_culler()


app = FastAPI(
    title="LoomAI Hub",
    description="Multi-user hub for LoomAI on Kubernetes",
    version="0.1.0",
    lifespan=lifespan,
)

# Serve static assets (logos, images) — must be mounted before routers
_static_dir = Path(__file__).parent / "static"
app.mount("/hub/static", StaticFiles(directory=str(_static_dir)), name="static")

# Mount route modules
app.include_router(health.router)
app.include_router(login.router)
app.include_router(spawn.router)
app.include_router(admin.router)

# Root redirect → login
@app.get("/")
async def root_redirect():
    """Redirect root to hub login."""
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url=f"{settings.HUB_PREFIX}/login", status_code=302)
