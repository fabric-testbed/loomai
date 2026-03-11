from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

import asyncio
from contextlib import asynccontextmanager

from app.routes import slices, resources, terminal, config, metrics, files, templates, vm_templates, projects, recipes, experiments, http_proxy, tunnels, ai_terminal, ai_chat, jupyter, artifacts
from app.tunnel_manager import get_tunnel_manager


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
            working_meta = os.path.join(artifacts_dir, entry, "metadata.json")
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
    _startup_settings()
    _startup_ai_tools()

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

    task = asyncio.create_task(_cleanup_loop())
    yield
    task.cancel()
    mgr.close_all()

    # Back up Claude Code config to persistent storage on shutdown
    try:
        from app.routes.ai_terminal import _backup_claude_config
        _backup_claude_config()
    except Exception:
        pass


app = FastAPI(title="FABRIC Web GUI API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(slices.router, prefix="/api")
app.include_router(resources.router, prefix="/api")
app.include_router(metrics.router, prefix="/api")
app.include_router(ai_terminal.router)
app.include_router(ai_chat.router)
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

# Serve frontend static files in production
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


@app.get("/api/health")
def health():
    from app.fablib_manager import is_configured
    return {"status": "ok", "configured": is_configured()}


# Fast 404 for /metrics — prevents Prometheus scraper from clogging the threadpool
@app.get("/metrics")
async def metrics_not_found():
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("Not Found", status_code=404)
