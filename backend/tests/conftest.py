"""Shared test fixtures: TestClient, mock FABlib, isolated storage."""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

# Ensure backend app is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.fixtures.fablib_mocks import MockFablibManager, MockSlice
from tests.fixtures.site_data import default_sites


@pytest.fixture()
def storage_dir(tmp_path):
    """Create an isolated storage directory with minimal FABRIC config.

    Sets environment variables so the app uses this temp directory.
    """
    storage = tmp_path / "fabric_work"
    storage.mkdir()

    # Create config dir with minimal fabric_rc
    config_dir = storage / "fabric_config"
    config_dir.mkdir()
    (config_dir / "fabric_rc").write_text(
        'export FABRIC_ORCHESTRATOR_HOST=orchestrator.fabric-testbed.net\n'
        'export FABRIC_PROJECT_ID=test-project-id\n'
    )
    (config_dir / "id_token.json").write_text(json.dumps({
        "id_token": "fake-token",
        "created_at": 1700000000,
    }))

    # Create slice keys
    keys_dir = config_dir / "slice_keys" / "default"
    keys_dir.mkdir(parents=True)
    (keys_dir / "slice_key").write_text("fake-private-key")
    (keys_dir / "slice_key.pub").write_text("fake-public-key")

    # Create storage subdirectories
    (storage / "my_artifacts").mkdir()
    (storage / "my_slices").mkdir()

    # Set environment
    env_vars = {
        "FABRIC_STORAGE_DIR": str(storage),
        "FABRIC_CONFIG_DIR": str(config_dir),
        "FABRIC_TOKEN_FILE": str(config_dir / "id_token.json"),
        "FABRIC_PROJECT_ID": "test-project-id",
    }

    with patch.dict(os.environ, env_vars):
        # Reset the cached _BASE_STORAGE so user_context picks up the new env
        import app.user_context as uc
        old_base = uc._BASE_STORAGE
        uc._BASE_STORAGE = None

        # Reset settings_manager cache so it picks up the new env
        import app.settings_manager as sm
        old_settings = sm._cached_settings
        sm._cached_settings = None

        yield storage

        uc._BASE_STORAGE = old_base
        sm._cached_settings = old_settings


@pytest.fixture()
def mock_fablib(storage_dir):
    """Patch get_fablib() everywhere it's imported.

    Also patches is_configured() to return True.
    """
    mock_mgr = MockFablibManager()

    # Must patch get_fablib in every module that imports it directly
    with patch("app.fablib_manager.get_fablib", return_value=mock_mgr), \
         patch("app.fablib_manager.is_configured", return_value=True), \
         patch("app.routes.slices.get_fablib", return_value=mock_mgr), \
         patch("app.routes.resources.get_fablib", return_value=mock_mgr), \
         patch("app.routes.files.get_fablib", return_value=mock_mgr):
        yield mock_mgr


@pytest.fixture()
def client(mock_fablib, storage_dir):
    """Create a FastAPI TestClient with mocked FABlib and isolated storage.

    Uses a fresh app import to avoid lifespan side effects.
    """
    from fastapi.testclient import TestClient

    # Patch lifespan to be a no-op — we don't need startup migrations in tests
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _noop_lifespan(app):
        yield

    import app.main as main_module
    original_lifespan = main_module.app.router.lifespan_context
    main_module.app.router.lifespan_context = _noop_lifespan

    # Clear draft state between tests
    from app.routes import slices as slices_mod
    slices_mod._draft_slices.clear()
    slices_mod._draft_is_new.clear()
    slices_mod._draft_site_groups.clear()
    slices_mod._draft_ip_hints.clear()
    slices_mod._draft_l3_config.clear()
    slices_mod._draft_project_id.clear()

    # Pre-populate the resources cache so /api/sites doesn't call FABlib
    import time
    from app.routes import resources as res_mod
    sites_data = default_sites()
    res_mod._cache["sites"] = (time.time(), sites_data)

    # Also patch resources.get_cached_sites for routes that use it
    # and jupyter.ensure_slice_workdir which is called during slice creation
    with patch("app.routes.resources.get_cached_sites", return_value=sites_data), \
         patch("app.routes.resources.get_fresh_sites", return_value=sites_data), \
         patch("app.routes.jupyter.ensure_slice_workdir", return_value=None):
        with TestClient(main_module.app) as tc:
            yield tc

    # Clean up draft state after test
    slices_mod._draft_slices.clear()
    slices_mod._draft_is_new.clear()
    slices_mod._draft_site_groups.clear()
    slices_mod._draft_ip_hints.clear()
    slices_mod._draft_l3_config.clear()
    slices_mod._draft_project_id.clear()

    main_module.app.router.lifespan_context = original_lifespan


@pytest.fixture()
def mock_sites():
    """Return default mock site data."""
    return default_sites()
