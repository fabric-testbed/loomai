"""Route-level tests for today's config endpoints: settings-secret masking and
multi-user switching.

The masking/restore helpers and the per-user AI-home swap are unit-tested in
``unit/test_settings_secrets.py`` and ``unit/test_multiuser_ai_mount.py``. These
tests close the gap by exercising the behavior *through the HTTP routes*
(``GET/PUT /api/settings``, ``GET /api/users``, ``POST /api/users/switch``) so a
regression in the wiring — not just the helpers — is caught.

A minimal app with only ``config.router`` is built (no full-app lifespan), and
``HOME``/``FABRIC_STORAGE_DIR`` are redirected to a tmp dir so nothing touches
the real user environment.
"""
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    storage = tmp_path / "storage"
    home = tmp_path / "home"
    storage.mkdir()
    home.mkdir()
    monkeypatch.setenv("FABRIC_STORAGE_DIR", str(storage))
    monkeypatch.setenv("HOME", str(home))
    # multiuser_enabled() is gated off inside Kubernetes (LOOMAI_BASE_PATH set).
    monkeypatch.delenv("LOOMAI_BASE_PATH", raising=False)

    # PUT /api/settings kicks off a background AI-config propagation; stub it so
    # the test doesn't crawl tool workspaces.
    import app.routes.ai_terminal as ai_terminal
    monkeypatch.setattr(ai_terminal, "propagate_ai_configs", lambda *a, **k: None)

    # Settings are cached in a module global; isolate it to this test.
    import app.settings_manager as sm
    sm.invalidate_settings_cache()

    # _do_user_switch / put_settings call apply_env_vars(), which writes to
    # os.environ directly. Snapshot + restore so it can't leak into other tests.
    env_snapshot = dict(os.environ)

    from app.routes import config
    app = FastAPI()
    app.include_router(config.router)
    try:
        with TestClient(app) as c:
            yield c
    finally:
        sm.invalidate_settings_cache()
        os.environ.clear()
        os.environ.update(env_snapshot)


# ---------------------------------------------------------------------------
# Secret masking through GET/PUT /api/settings
# ---------------------------------------------------------------------------

MASK = "********"


def _full_settings_with_secrets():
    """A complete settings blob (PUT regenerates fabric_rc/ssh_config, so it
    needs the real ``paths``/``fabric`` sections) seeded with secret values."""
    import app.settings_manager as sm
    s = sm.load_settings()
    ai = s.setdefault("ai", {})
    ai["fabric_api_key"] = "fabric-api-key-fixture"
    ai["nrp_api_key"] = ""
    ai["custom_providers"] = [{"name": "p1", "base_url": "http://x", "api_key": "custom-provider-key-fixture"}]
    chm = s.setdefault("chameleon", {})
    chm["password_auth"] = {"username": "u", "password": "chameleon-password-fixture"}
    chm.setdefault("sites", {})["CHI@TACC"] = {"app_credential_secret": "app-credential-fixture", "password": ""}
    return s


def test_get_settings_masks_nonempty_secrets(client):
    assert client.put("/api/settings", json=_full_settings_with_secrets()).status_code == 200

    masked = client.get("/api/settings").json()
    assert masked["ai"]["fabric_api_key"] == MASK
    assert masked["ai"]["nrp_api_key"] == ""                       # empty stays empty
    assert masked["ai"]["custom_providers"][0]["api_key"] == MASK
    assert masked["chameleon"]["password_auth"]["password"] == MASK
    assert masked["chameleon"]["sites"]["CHI@TACC"]["app_credential_secret"] == MASK
    # Non-secret fields are untouched.
    assert masked["chameleon"]["password_auth"]["username"] == "u"


def test_put_settings_preserves_masked_and_applies_changes(client):
    """A round-trip where the client returns the masked blob (with one real
    edit) must keep the stored secrets it never saw, and apply the one it did."""
    import app.settings_manager as sm

    assert client.put("/api/settings", json=_full_settings_with_secrets()).status_code == 200
    masked = client.get("/api/settings").json()

    # The user changes only the FABRIC key; everything else comes back masked.
    masked["ai"]["fabric_api_key"] = "fabric-api-key-updated-fixture"
    assert client.put("/api/settings", json=masked).status_code == 200

    sm.invalidate_settings_cache()
    raw = sm.load_settings()
    assert raw["ai"]["fabric_api_key"] == "fabric-api-key-updated-fixture"         # edited
    assert raw["ai"]["custom_providers"][0]["api_key"] == "custom-provider-key-fixture"       # preserved
    assert raw["chameleon"]["password_auth"]["password"] == "chameleon-password-fixture"      # preserved
    assert raw["chameleon"]["sites"]["CHI@TACC"]["app_credential_secret"] == "app-credential-fixture"


def test_put_settings_allows_clearing_a_secret(client):
    import app.settings_manager as sm
    assert client.put("/api/settings", json=_full_settings_with_secrets()).status_code == 200
    masked = client.get("/api/settings").json()
    masked["ai"]["fabric_api_key"] = ""                       # user cleared it
    assert client.put("/api/settings", json=masked).status_code == 200
    sm.invalidate_settings_cache()
    assert sm.load_settings()["ai"]["fabric_api_key"] == ""


# ---------------------------------------------------------------------------
# Multi-user listing + switching (and the AI-home swap side effect)
# ---------------------------------------------------------------------------

A = "aaaaaaaa-1111-1111-1111-111111111111"
B = "bbbbbbbb-2222-2222-2222-222222222222"


def _seed_two_users(storage: Path):
    from app import user_registry
    user_registry.add_user(A, "Alice", "a@x")
    user_registry.add_user(B, "Bob", "b@x")
    # Give each a distinct stored Claude credential in their per-user folder.
    for uuid, val in ((A, "A-CRED"), (B, "B-CRED")):
        d = storage / ".loomai" / "users" / uuid / ".claude"
        d.mkdir(parents=True, exist_ok=True)
        (d / "creds").write_text(val)


def test_list_users_empty_then_reflects_registry(client, tmp_path):
    empty = client.get("/api/users").json()
    assert empty == {"active_user": None, "users": [], "multiuser": False} \
        or (empty["multiuser"] is True and empty["users"] == [])

    _seed_two_users(tmp_path / "storage")
    listed = client.get("/api/users").json()
    assert listed["multiuser"] is True
    uuids = {u["uuid"] for u in listed["users"]}
    assert uuids == {A, B}
    # Exactly one user is marked active.
    assert sum(1 for u in listed["users"] if u["is_active"]) == 1


def test_switch_user_changes_active_and_swaps_ai_home(client, tmp_path):
    storage = tmp_path / "storage"
    home = tmp_path / "home"
    _seed_two_users(storage)

    assert client.post("/api/users/switch", json={"uuid": A}).json()["active_user"] == A
    assert (home / ".claude" / "creds").read_text() == "A-CRED"

    assert client.post("/api/users/switch", json={"uuid": B}).status_code == 200
    assert (home / ".claude" / "creds").read_text() == "B-CRED"      # swapped

    listed = client.get("/api/users").json()
    assert listed["active_user"] == B
    active = [u for u in listed["users"] if u["is_active"]]
    assert len(active) == 1 and active[0]["uuid"] == B


def test_switch_unknown_user_404(client, tmp_path):
    _seed_two_users(tmp_path / "storage")
    assert client.post("/api/users/switch", json={"uuid": "no-such-uuid"}).status_code == 404
