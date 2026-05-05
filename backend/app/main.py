from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

import asyncio
from contextlib import asynccontextmanager

import logging

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"

logging.basicConfig(
    level=logging.INFO,
    format=_LOG_FORMAT,
    datefmt=_LOG_DATEFMT,
)

# Override uvicorn's loggers so access logs get the same timestamp format.
# By default uvicorn.access uses its own formatter without timestamps.
for _uv_name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
    _uv_logger = logging.getLogger(_uv_name)
    for _handler in _uv_logger.handlers:
        _handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATEFMT))
    # If no handlers yet (uvicorn adds them at startup), set propagate so
    # messages bubble up to root which already has the timestamped formatter.
    _uv_logger.propagate = True

from app.routes import slices, resources, terminal, config, metrics, files, templates, vm_templates, projects, recipes, experiments, http_proxy, tunnels, ai_terminal, ai_chat, ai_agents, ai_rag, jupyter, artifacts, chameleon, trovi, schedule, composite, monitoring
from app.auth import router as auth_router, AuthMiddleware, is_auth_enabled
from app.tunnel_manager import get_tunnel_manager

logger = logging.getLogger(__name__)


def _startup_storage():
    """One-time storage setup on startup.

    1. Migrate user artifacts from old per-type dirs to my_artifacts/.
    2. Migrate .artifacts/ → my_artifacts/ (legacy layout).
    3. Re-key .artifact-originals/ from dir_name to UUID.
    """
    import json
    import shutil
    import logging
    logger = logging.getLogger("startup")

    storage = os.environ.get("FABRIC_STORAGE_DIR", "/home/fabric/work")

    # --- 1) Migrate artifacts from old per-type dirs to my_artifacts/ ---
    artifacts_dir = os.path.join(storage, "my_artifacts")
    os.makedirs(artifacts_dir, exist_ok=True)

    # Migrate from old work/my_artifacts/ layout
    old_work_artifacts = os.path.join(storage, "work", "my_artifacts")
    if os.path.isdir(old_work_artifacts):
        for entry in list(os.listdir(old_work_artifacts)):
            src = os.path.join(old_work_artifacts, entry)
            dst = os.path.join(artifacts_dir, entry)
            if os.path.isdir(src) and not os.path.exists(dst):
                shutil.move(src, dst)
                logger.info("Migrated work/my_artifacts/%s -> my_artifacts/%s", entry, entry)

    old_dirs = [".slice_templates", ".vm_templates", ".vm_recipes", ".experiments"]
    for old_sub in old_dirs:
        old_dir = os.path.join(storage, old_sub)
        if not os.path.isdir(old_dir):
            continue
        for entry in list(os.listdir(old_dir)):
            src = os.path.join(old_dir, entry)
            if not os.path.isdir(src):
                continue
            dst = os.path.join(artifacts_dir, entry)
            if not os.path.exists(dst):
                shutil.move(src, dst)
                logger.info("Migrated %s/%s -> my_artifacts/%s", old_sub, entry, entry)
            else:
                logger.warning("Skipped migration of %s/%s — name conflict in my_artifacts/", old_sub, entry)

    # --- Migrate work/my_slices/ → my_slices/ ---
    old_work_slices = os.path.join(storage, "work", "my_slices")
    slices_dir = os.path.join(storage, "my_slices")
    if os.path.isdir(old_work_slices):
        os.makedirs(slices_dir, exist_ok=True)
        for entry in list(os.listdir(old_work_slices)):
            src = os.path.join(old_work_slices, entry)
            dst = os.path.join(slices_dir, entry)
            if not os.path.exists(dst):
                shutil.move(src, dst)
                logger.info("Migrated work/my_slices/%s -> my_slices/%s", entry, entry)

    # --- 3) Migrate .artifacts/ → my_artifacts/ (legacy hidden dir) ---
    old_artifacts = os.path.join(storage, ".artifacts")
    if os.path.isdir(old_artifacts):
        for entry in list(os.listdir(old_artifacts)):
            src = os.path.join(old_artifacts, entry)
            if not os.path.isdir(src):
                continue
            dst = os.path.join(artifacts_dir, entry)
            if not os.path.exists(dst):
                shutil.move(src, dst)
                logger.info("Migrated .artifacts/%s -> my_artifacts/%s", entry, entry)
        # Remove old dir if empty
        try:
            os.rmdir(old_artifacts)
        except OSError:
            pass

    # Clean up legacy .artifacts symlinks
    for legacy_link in [
        os.path.join(storage, "work", ".artifacts"),
        os.path.join(storage, ".artifacts"),
    ]:
        if os.path.islink(legacy_link):
            try:
                os.unlink(legacy_link)
            except OSError:
                pass

    # --- 4) Migrate per-user data into the flat base directory ---
    users_dir = os.path.join(storage, "users")
    if os.path.isdir(users_dir):
        for user_uuid in list(os.listdir(users_dir)):
            udir = os.path.join(users_dir, user_uuid)
            if not os.path.isdir(udir):
                continue
            # Migrate per-user .artifact-originals/ → base .artifact-originals/
            old_originals = os.path.join(udir, ".artifact-originals")
            new_originals = os.path.join(storage, ".artifact-originals")
            if os.path.isdir(old_originals):
                os.makedirs(new_originals, exist_ok=True)
                for entry in list(os.listdir(old_originals)):
                    src = os.path.join(old_originals, entry)
                    dst = os.path.join(new_originals, entry)
                    if os.path.isdir(src) and not os.path.exists(dst):
                        shutil.move(src, dst)
                        logger.info("Migrated users/%s/.artifact-originals/%s -> .artifact-originals/%s", user_uuid, entry, entry)
            # Migrate per-user .boot_info/ → base .boot_info/
            old_boot = os.path.join(udir, ".boot_info")
            new_boot = os.path.join(storage, ".boot_info")
            if os.path.isdir(old_boot):
                os.makedirs(new_boot, exist_ok=True)
                for entry in list(os.listdir(old_boot)):
                    src = os.path.join(old_boot, entry)
                    dst = os.path.join(new_boot, entry)
                    if os.path.isfile(src) and not os.path.exists(dst):
                        shutil.move(src, dst)
                        logger.info("Migrated users/%s/.boot_info/%s -> .boot_info/%s", user_uuid, entry, entry)
            # Migrate per-user .slice-keys/ → base .slice-keys/
            old_keys = os.path.join(udir, ".slice-keys")
            new_keys = os.path.join(storage, ".slice-keys")
            if os.path.isdir(old_keys):
                os.makedirs(new_keys, exist_ok=True)
                for entry in list(os.listdir(old_keys)):
                    src = os.path.join(old_keys, entry)
                    dst = os.path.join(new_keys, entry)
                    if os.path.isfile(src) and not os.path.exists(dst):
                        shutil.move(src, dst)
                        logger.info("Migrated users/%s/.slice-keys/%s -> .slice-keys/%s", user_uuid, entry, entry)
            # Migrate per-user .monitoring/ → base .monitoring/
            old_mon = os.path.join(udir, ".monitoring")
            new_mon = os.path.join(storage, ".monitoring")
            if os.path.isdir(old_mon):
                os.makedirs(new_mon, exist_ok=True)
                for entry in list(os.listdir(old_mon)):
                    src = os.path.join(old_mon, entry)
                    dst = os.path.join(new_mon, entry)
                    if os.path.isfile(src) and not os.path.exists(dst):
                        shutil.move(src, dst)
                        logger.info("Migrated users/%s/.monitoring/%s -> .monitoring/%s", user_uuid, entry, entry)
            # Migrate per-user notebooks/ → base notebooks/
            for nb_sub in ["notebooks", os.path.join("work", "notebooks")]:
                old_nb = os.path.join(udir, nb_sub)
                new_nb = os.path.join(storage, "notebooks")
                if os.path.isdir(old_nb):
                    os.makedirs(new_nb, exist_ok=True)
                    for entry in list(os.listdir(old_nb)):
                        src = os.path.join(old_nb, entry)
                        dst = os.path.join(new_nb, entry)
                        if not os.path.exists(dst):
                            shutil.move(src, dst)
                            logger.info("Migrated users/%s/%s/%s -> notebooks/%s", user_uuid, nb_sub, entry, entry)
                    break  # only process first matching notebooks dir
            # Migrate per-user .drafts/ → base my_slices/
            old_drafts = os.path.join(udir, ".drafts")
            if os.path.isdir(old_drafts):
                slices_dir = os.path.join(storage, "my_slices")
                os.makedirs(slices_dir, exist_ok=True)
                for entry in list(os.listdir(old_drafts)):
                    src = os.path.join(old_drafts, entry)
                    dst = os.path.join(slices_dir, entry)
                    if os.path.isdir(src) and not os.path.exists(dst):
                        shutil.move(src, dst)
                        logger.info("Migrated users/%s/.drafts/%s -> my_slices/%s", user_uuid, entry, entry)
            # Migrate per-user .artifacts/ → base my_artifacts/
            old_art = os.path.join(udir, ".artifacts")
            if os.path.isdir(old_art):
                for entry in list(os.listdir(old_art)):
                    src = os.path.join(old_art, entry)
                    dst = os.path.join(artifacts_dir, entry)
                    if os.path.isdir(src) and not os.path.exists(dst):
                        shutil.move(src, dst)
                        logger.info("Migrated users/%s/.artifacts/%s -> my_artifacts/%s", user_uuid, entry, entry)

    # --- 5) Re-key .artifact-originals/ from dir_name to UUID ---
    originals_dir = os.path.join(storage, ".artifact-originals")
    if os.path.isdir(originals_dir):
        for entry in list(os.listdir(originals_dir)):
            src = os.path.join(originals_dir, entry)
            if not os.path.isdir(src):
                continue
            # Read metadata from the working copy to find artifact_uuid
            working_meta = os.path.join(artifacts_dir, entry, "weave.json")
            if not os.path.isfile(working_meta):
                continue
            try:
                with open(working_meta) as f:
                    meta = json.load(f)
                art_uuid = meta.get("artifact_uuid", "")
                if art_uuid and art_uuid != entry:
                    dst = os.path.join(originals_dir, art_uuid)
                    if not os.path.exists(dst):
                        os.rename(src, dst)
                        logger.info("Re-keyed original %s -> %s", entry, art_uuid)
            except Exception:
                pass


def _seed_default_artifacts():
    """Copy default artifacts (e.g. Hello_FABRIC) into my_artifacts/ if missing."""
    import shutil
    import logging
    logger = logging.getLogger("startup")

    storage = os.environ.get("FABRIC_STORAGE_DIR", "/home/fabric/work")
    artifacts_dir = os.path.join(storage, "my_artifacts")
    os.makedirs(artifacts_dir, exist_ok=True)

    # default_artifacts/ lives next to the app/ package
    defaults_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "default_artifacts")
    if not os.path.isdir(defaults_dir):
        return
    for entry in os.listdir(defaults_dir):
        src = os.path.join(defaults_dir, entry)
        dst = os.path.join(artifacts_dir, entry)
        if os.path.isdir(src) and not os.path.exists(dst):
            shutil.copytree(src, dst)
            logger.info("Seeded default artifact: %s", entry)


def _startup_ai_tools():
    """Seed AI tool configs into default locations (best-effort)."""
    import logging
    logger = logging.getLogger("startup")
    try:
        from app.tool_installer import clean_stale_locks, fixup_jupyter_kernel
        clean_stale_locks()
        fixup_jupyter_kernel()
    except Exception as e:
        logger.warning("AI tools startup fixup failed (non-fatal): %s", e)
    try:
        from app.routes.ai_terminal import seed_ai_tool_defaults
        seed_ai_tool_defaults()
    except Exception as e:
        logger.warning("AI tool seeding failed (non-fatal): %s", e)


def _startup_settings():
    """Load or migrate settings, regenerate derived files, apply env vars."""
    import logging
    logger = logging.getLogger("startup")
    from app import settings_manager
    from app.user_context import register_user_changed_callback

    # Register settings cache invalidation on user switch
    register_user_changed_callback(settings_manager.invalidate_settings_cache)

    # Verify active user directory exists if registry is present
    from app import user_registry
    active_uuid = user_registry.get_active_user_uuid()
    if active_uuid:
        user_dir = user_registry.get_user_storage_dir(active_uuid)
        if user_dir and not os.path.isdir(user_dir):
            logger.warning("Active user dir %s missing — creating it", user_dir)
            user_registry.ensure_user_dir(active_uuid)
        # Ensure top-level symlinks point to the active user's directories
        from app.routes.config import _ensure_user_symlinks
        _ensure_user_symlinks(active_uuid)

    if not os.path.isfile(settings_manager.get_settings_path()):
        logger.info("No settings.json found — migrating from legacy config")
        settings_manager.migrate_from_legacy()
    else:
        settings_manager.load_settings()

    settings = settings_manager.load_settings()
    settings_manager.apply_env_vars(settings)

    # Only regenerate fabric_rc if the config dir exists and we have
    # meaningful settings (bastion_username or project_id set)
    if settings["fabric"].get("bastion_username") or settings["fabric"].get("project_id"):
        try:
            settings_manager.generate_fabric_rc(settings)
            settings_manager.generate_ssh_config(settings)
        except Exception as e:
            logger.warning("Failed to regenerate derived config files: %s", e)

    # Seed tool configs from Docker image defaults (only if not already present)
    try:
        settings_manager.seed_tool_configs()
    except Exception as e:
        logger.warning("Tool config seeding failed (non-fatal): %s", e)

    logger.info("Settings loaded from %s", settings_manager.get_settings_path())


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle: periodic tunnel cleanup + shutdown."""
    _startup_storage()
    _seed_default_artifacts()
    _startup_settings()
    _startup_ai_tools()

    # Load persisted Chameleon slices
    try:
        from app.routes.chameleon import load_chameleon_slices
        load_chameleon_slices()
    except Exception:
        logger.warning("Chameleon slice loading failed (non-fatal)", exc_info=True)

    # Load persisted composite slices
    try:
        from app.routes.composite import load_composite_slices
        load_composite_slices()
    except Exception:
        logger.warning("Composite slice loading failed (non-fatal)", exc_info=True)

    # Mark stale runs from previous container lifecycle
    try:
        from app.run_manager import recover_stale_runs
        recover_stale_runs()
    except Exception:
        pass

    mgr = get_tunnel_manager()

    async def _cleanup_loop():
        while True:
            await asyncio.sleep(60)
            mgr.cleanup_idle()

    # Periodically warm the site resource cache in background (every 4 min)
    # so users never hit a cold cache stall
    async def _site_cache_warmer():
        from app.fabric_call_manager import get_call_manager
        from app.routes.resources import _fetch_sites_locked
        # Initial delay — let the app finish starting before first refresh
        await asyncio.sleep(30)
        while True:
            mgr = get_call_manager()
            try:
                await mgr.get("sites", fetcher=_fetch_sites_locked, max_age=0)
            except Exception:
                logger.warning("Background site cache warm failed", exc_info=True)
            await asyncio.sleep(240)  # 4 minutes

    # Periodically back up Claude Code config so credentials survive
    # container force-kills (docker compose down may not wait for shutdown)
    async def _claude_config_backup_loop():
        from app.routes.ai_terminal import _backup_claude_config
        await asyncio.sleep(120)  # Wait 2 min before first backup
        while True:
            try:
                _backup_claude_config()
                logger.debug("Periodic Claude Code config backup complete")
            except Exception as e:
                logger.warning("Periodic Claude config backup failed: %s", e)
            await asyncio.sleep(300)  # Every 5 minutes

    # Background reservation checker — auto-submit slices when scheduled time arrives
    async def _reservation_checker():
        await asyncio.sleep(15)  # Let the server finish starting
        while True:
            try:
                from app.reservation_manager import check_and_execute_reservations
                executed = check_and_execute_reservations()
                if executed:
                    logger.info("Reservation checker processed %d reservation(s)", len(executed))
            except Exception as e:
                logger.warning("Reservation checker failed (non-fatal): %s", e)
            await asyncio.sleep(60)

    # Background model discovery — find first healthy LLM and persist as default
    async def _model_discovery():
        await asyncio.sleep(5)  # Let the server finish starting
        try:
            from app.routes.ai_terminal import discover_and_persist_default_model
            from app.fablib_executor import run_in_fablib_pool
            result = await run_in_fablib_pool(discover_and_persist_default_model)
            if result.get("default"):
                logger.info("Background model discovery: %s (%s)",
                            result["default"], result.get("source"))
            else:
                logger.warning("Background model discovery: no healthy models found")
        except Exception as e:
            logger.warning("Background model discovery failed (non-fatal): %s", e)

    # Background RAG index build — happens after model discovery so the
    # embedder probe sees the configured providers. Runs off-loop via
    # asyncio.to_thread to avoid blocking other startup tasks.
    async def _rag_index_build():
        await asyncio.sleep(10)  # Let settings load and model discovery warm up
        try:
            from app.rag import startup_build_index
            await startup_build_index()
        except Exception as e:
            logger.warning("RAG index build failed (non-fatal): %s", e, exc_info=True)

    task = asyncio.create_task(_cleanup_loop())
    cache_task = asyncio.create_task(_site_cache_warmer())
    backup_task = asyncio.create_task(_claude_config_backup_loop())
    reservation_task = asyncio.create_task(_reservation_checker())
    model_task = asyncio.create_task(_model_discovery())
    rag_task = asyncio.create_task(_rag_index_build())
    yield
    task.cancel()
    cache_task.cancel()
    backup_task.cancel()
    reservation_task.cancel()
    model_task.cancel()
    rag_task.cancel()
    mgr.close_all()

    # Close shared httpx connection pools
    try:
        from app.http_pool import fabric_client, ai_client, metrics_client
        await fabric_client.aclose()
        await ai_client.aclose()
        await metrics_client.aclose()
    except Exception:
        pass

    # Back up Claude Code config to persistent storage on shutdown
    try:
        from app.routes.ai_terminal import _backup_claude_config
        _backup_claude_config()
        logger.info("Claude Code config backed up on shutdown")
    except Exception as e:
        logger.warning("Claude Code config backup failed on shutdown: %s", e)


# Disable Swagger/ReDoc in production unless explicitly enabled
_enable_docs = os.environ.get("LOOMAI_ENABLE_DOCS", "").strip() == "1"
_docs_kwargs = {} if _enable_docs else {"docs_url": None, "redoc_url": None, "openapi_url": None}

app = FastAPI(title="LoomAI API", version="0.4.0", lifespan=lifespan, **_docs_kwargs)

from app.error_handler import install_error_handlers
install_error_handlers(app)

_DEFAULT_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "https://cm.fabric-testbed.net",
]
_cors_env = os.environ.get("CORS_ORIGINS", "")
_cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()] if _cors_env else _DEFAULT_ORIGINS

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth middleware — added after CORS so preflight requests pass through first
app.add_middleware(AuthMiddleware)

app.include_router(auth_router)
app.include_router(slices.router, prefix="/api")
app.include_router(resources.router, prefix="/api")
app.include_router(metrics.router, prefix="/api")
app.include_router(ai_terminal.router)
app.include_router(ai_chat.router)
app.include_router(ai_agents.router)
app.include_router(ai_rag.router)
app.include_router(terminal.router)
app.include_router(config.router)
app.include_router(files.router)
app.include_router(templates.router)
app.include_router(vm_templates.router)
app.include_router(projects.router)
app.include_router(recipes.router)
app.include_router(experiments.router)
app.include_router(http_proxy.router)
app.include_router(tunnels.router)
app.include_router(jupyter.router)
app.include_router(artifacts.router)
app.include_router(chameleon.router)
app.include_router(trovi.router)
app.include_router(schedule.router, prefix="/api")
app.include_router(composite.router)
app.include_router(monitoring.router)

# Serve frontend static files in production
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


import time as _time
_APP_START_TIME = _time.time()


@app.get("/api/health")
def health():
    from app.fablib_manager import is_configured
    return {"status": "ok", "configured": is_configured()}


@app.get("/api/health/detailed")
async def health_detailed():
    """Extended health check with subsystem status, resource info, and uptime."""
    import shutil
    from app.fablib_manager import is_configured
    from app.routes.config import CURRENT_VERSION

    checks: dict = {}

    # 1. FABlib check
    try:
        configured = is_configured()
        checks["fablib"] = {
            "ok": configured,
            "message": "Connected" if configured else "Not configured",
        }
    except Exception as e:
        checks["fablib"] = {"ok": False, "message": str(e)}

    # 2. Storage check
    storage_dir = os.environ.get("FABRIC_STORAGE_DIR", "/home/fabric/work")
    try:
        exists = os.path.exists(storage_dir)
        if exists:
            usage = shutil.disk_usage(storage_dir)
            free_gb = round(usage.free / (1024 ** 3), 1)
            checks["storage"] = {
                "ok": True,
                "message": f"{storage_dir} exists, {free_gb}GB free",
            }
        else:
            checks["storage"] = {
                "ok": False,
                "message": f"{storage_dir} does not exist",
            }
    except Exception as e:
        checks["storage"] = {"ok": False, "message": str(e)}

    # 3. AI server check
    try:
        from app import settings_manager
        settings = settings_manager.load_settings()
        ai_url = settings.get("ai", {}).get("ai_server_url", "")
        if ai_url:
            import httpx
            t0 = _time.time()
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{ai_url}/v1/models")
            latency_ms = round((_time.time() - t0) * 1000)
            checks["ai_server"] = {
                "ok": resp.status_code == 200,
                "latency_ms": latency_ms,
            }
        else:
            checks["ai_server"] = {"ok": False, "message": "No AI server URL configured"}
    except Exception as e:
        checks["ai_server"] = {"ok": False, "message": str(e)}

    # 4. Chameleon check
    try:
        from app import settings_manager
        settings = settings_manager.load_settings()
        cham_sites = settings.get("chameleon", {}).get("sites", {})
        configured_count = sum(
            1 for s in cham_sites.values()
            if isinstance(s, dict) and s.get("enabled")
        )
        checks["chameleon"] = {
            "ok": configured_count > 0,
            "sites_configured": configured_count,
        }
    except Exception as e:
        checks["chameleon"] = {"ok": False, "message": str(e)}

    # 5. Jupyter check
    try:
        import httpx
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get("http://localhost:8889/api/status")
        checks["jupyter"] = {
            "ok": resp.status_code == 200,
            "port": 8889,
        }
    except Exception:
        checks["jupyter"] = {"ok": False, "port": 8889}

    # Slice counts
    slices_info: dict = {"active": 0, "total": 0}
    try:
        if is_configured():
            from app.fablib_executor import run_in_fablib_pool
            from app.fablib_manager import get_fablib

            def _count_slices():
                fablib = get_fablib()
                # Use lightweight list_slices with graph_format=NONE to
                # avoid per-slice topology/sliver fetches.
                mgr = fablib.get_manager()
                dtos = mgr.list_slices(
                    exclude_states=["Dead", "Closing"],
                    graph_format="NONE",
                    as_self=True,
                    limit=200,
                    return_fmt="dto",
                )
                active = sum(
                    1 for d in dtos
                    if (d.state or "") in {"StableOK", "StableError", "ModifyOK", "Configuring"}
                )
                return {"active": active, "total": len(dtos)}

            slices_info = await run_in_fablib_pool(_count_slices)
    except Exception:
        pass

    # Memory usage
    memory_mb: float | None = None
    try:
        import psutil
        proc = psutil.Process()
        memory_mb = round(proc.memory_info().rss / (1024 * 1024), 1)
    except ImportError:
        pass
    except Exception:
        pass

    # Disk free
    disk_free_gb: float | None = None
    try:
        if os.path.exists(storage_dir):
            usage = shutil.disk_usage(storage_dir)
            disk_free_gb = round(usage.free / (1024 ** 3), 1)
    except Exception:
        pass

    uptime = round(_time.time() - _APP_START_TIME, 1)
    overall_ok = all(c.get("ok", False) for c in checks.values())

    result: dict = {
        "status": "healthy" if overall_ok else "degraded",
        "uptime_seconds": uptime,
        "version": CURRENT_VERSION,
        "checks": checks,
        "slices": slices_info,
    }
    if memory_mb is not None:
        result["memory_mb"] = memory_mb
    if disk_free_gb is not None:
        result["disk_free_gb"] = disk_free_gb

    return result


# Fast 404 for /metrics — prevents Prometheus scraper from clogging the threadpool
@app.get("/metrics")
async def metrics_not_found():
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("Not Found", status_code=404)
