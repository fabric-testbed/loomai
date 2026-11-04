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


@pytest.fixture(autouse=True)
def _no_real_package_installs():
    """No test may shell out to a real package install.

    app.tool_installer spawns processes through exactly two primitives, and
    both are blocked here:

      * asyncio.create_subprocess_exec -- reached only via _run_install_cmd(),
        which is where _install_pip / _install_npm / _install_shell /
        _install_archive_binary all end up (pip, npm, curl, tar).
      * subprocess.run -- used directly by _ensure_venv() and
        fixup_jupyter_kernel(). _install_pip() calls _ensure_venv() FIRST, and
        that creates a real virtualenv and then runs `pip install --upgrade
        pip` against the network. Guarding only _run_install_cmd lets that
        bootstrap through and fires afterwards, once the damage is done.

    Guard the primitives, not the installers: enumerating install functions is
    how the archive path and then the venv bootstrap were each missed in turn.

    Nothing in the app guarantees a test cannot reach these. Until the
    storage_dir fixture redirected tool_installer's paths, the only thing
    stopping it was os.makedirs('/home/fabric') failing -- an accident of the
    environment, not a safeguard. Make the property explicit so a future
    change fails loudly here instead of quietly downloading hundreds of MB.

    Tests that legitimately drive these paths patch _run_install_cmd (or the
    calling function) themselves; an inner ``with patch(...)`` takes
    precedence over this fixture.
    """
    import subprocess as _subprocess

    import app.tool_installer as ti

    async def _forbid_async(cmd, *args, **kwargs):
        raise AssertionError(
            "test attempted a real package install via _run_install_cmd("
            f"{cmd!r}); patch app.tool_installer._run_install_cmd in the test "
            "if this code path is intended"
        )

    class _GuardedSubprocess:
        """Stand-in for tool_installer's `subprocess`; only .run is blocked."""

        def __getattr__(self, name):
            return getattr(_subprocess, name)

        def run(self, cmd, *args, **kwargs):
            raise AssertionError(
                f"test attempted a real subprocess install via subprocess.run({cmd!r}); "
                "patch the calling function in the test if this path is intended"
            )

    with patch.object(ti, "_run_install_cmd", _forbid_async), \
         patch.object(ti, "subprocess", _GuardedSubprocess()):
        yield


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path_factory, monkeypatch):
    """No test may see the real HOME directory.

    The app manages AI-tool dotfiles in the home dir (~/.claude, ~/.codex,
    ~/.crush, ...): ``config._ensure_user_symlinks`` MOVES them into per-user
    storage and ``ai_terminal.restore_ai_tool_configs`` rmtree's them. A test
    that reaches those paths with the real HOME destroys the developer's
    dotfiles — this happened: a relocation test moved a real ~/.claude into
    pytest's tmp_path, which was later pruned. Tests that need a specific
    home layout can still monkeypatch HOME themselves (it overrides this).
    """
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))


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
        "HOME": str(storage),
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

        # tool_installer resolves its paths from FABRIC_STORAGE_DIR at MODULE
        # IMPORT time, so setting the env var above is too late: the constants
        # still point at the production default /home/fabric/work. A test that
        # reaches the install path then calls os.makedirs on the real path --
        # which fails on a bare CI runner (PermissionError: '/home/fabric')
        # and would write outside tmp_path anywhere it succeeds. Redirect the
        # constants into this test's storage, like the caches above.
        import app.tool_installer as ti
        ai_tools = storage / ".ai-tools"
        old_ti = {name: getattr(ti, name) for name in (
            "_STORAGE_DIR", "AI_TOOLS_DIR", "_VENV_DIR", "_NPM_DIR",
            "_MANIFEST_PATH", "_LOCK_DIR",
        )}
        ti._STORAGE_DIR = str(storage)
        ti.AI_TOOLS_DIR = str(ai_tools)
        ti._VENV_DIR = str(ai_tools / "venv")
        ti._NPM_DIR = str(ai_tools / "npm")
        ti._MANIFEST_PATH = str(ai_tools / ".installed.json")
        ti._LOCK_DIR = str(ai_tools / ".locks")

        yield storage

        for name, value in old_ti.items():
            setattr(ti, name, value)
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

    # Reset the call manager singleton so cached data doesn't leak between tests
    from app.fabric_call_manager import reset_call_manager
    reset_call_manager()

    # Clear draft state between tests
    from app.routes import slices as slices_mod
    slices_mod._draft_slices.clear()
    slices_mod._draft_is_new.clear()
    slices_mod._draft_site_groups.clear()
    slices_mod._draft_ip_hints.clear()
    slices_mod._draft_l3_config.clear()
    slices_mod._draft_project_id.clear()

    # Pre-populate the call manager's sites cache so /api/sites doesn't call FABlib
    import time
    from app.fabric_call_manager import get_call_manager, CacheEntry
    sites_data = default_sites()
    mgr = get_call_manager()
    mgr._cache["sites"] = CacheEntry(data=sites_data, timestamp=time.time())

    # Also patch resources.get_cached_sites for routes that use it
    with patch("app.routes.resources.get_cached_sites", return_value=sites_data), \
         patch("app.routes.resources.get_fresh_sites", return_value=sites_data):
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
def browse_root(storage_dir):
    """The base the user-facing file routes browse from.

    Today's file manager browses one level *above* the storage root (so the UI
    shows the whole home dir, not just ``work/``) — see ``files._browse_dir()``.
    Tests that create files for the ``/api/files*`` endpoints must place them
    here, relative to this base.
    """
    return storage_dir.parent


@pytest.fixture()
def mock_sites():
    """Return default mock site data."""
    return default_sites()
