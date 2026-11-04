"""Path-containment tests for the file manager's _safe_path."""
import os

import pytest
from fastapi import HTTPException

from app.routes import files


@pytest.fixture()
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "_storage_dir", lambda: str(tmp_path))
    (tmp_path / "sub").mkdir()
    (tmp_path / ".loomai").mkdir()
    (tmp_path / ".loomai" / "session_secret").write_text("x")
    return str(tmp_path)


def test_relative_under_base_ok(base):
    assert files._safe_path(base, "sub") == os.path.realpath(os.path.join(base, "sub"))


def test_absolute_under_base_ok(base):
    p = os.path.join(base, "sub")
    assert files._safe_path(base, p) == os.path.realpath(p)


def test_absolute_outside_blocked(base):
    with pytest.raises(HTTPException):
        files._safe_path(base, "/etc/passwd")          # the old bug returned this


def test_relative_traversal_blocked(base):
    with pytest.raises(HTTPException):
        files._safe_path(base, "../../../../etc/passwd")


def test_loomai_secrets_denied(base):
    # Internal secrets dir is denied even though it's under the storage root.
    with pytest.raises(HTTPException):
        files._safe_path(base, ".loomai/session_secret")
    with pytest.raises(HTTPException):
        files._safe_path(base, os.path.join(base, ".loomai", "password_hash"))


def test_app_root_allowed(base):
    # Bundled artifacts/scripts under the backend install dir stay reachable.
    da = os.path.join(files._APP_ROOT, "default_artifacts")
    resolved = files._safe_path(base, da)
    assert resolved.startswith(os.path.realpath(files._APP_ROOT))


def test_app_root_never_writable(base):
    # The in-browser editor must not be able to rewrite app/*.py.
    target = os.path.join(files._APP_ROOT, "app", "main.py")
    files._safe_path(base, target)  # read is fine
    with pytest.raises(HTTPException):
        files._safe_path(base, target, writable=True)
    with pytest.raises(HTTPException):
        files._safe_path(base, os.path.join(files._APP_ROOT, "default_artifacts"), writable=True)


def test_storage_writable(base):
    assert files._safe_path(base, "sub", writable=True) == os.path.realpath(os.path.join(base, "sub"))


@pytest.fixture()
def multi_user(tmp_path, monkeypatch):
    """Multi-user layout: root/.loomai holds secrets, the registry and every
    user's storage; the caller's storage is root/.loomai/users/me."""
    from app import settings_manager

    root = tmp_path / "work"
    mine = root / ".loomai" / "users" / "me"
    other = root / ".loomai" / "users" / "other"
    for d in (mine / "my_artifacts", mine / ".loomai", other / "fabric_config"):
        d.mkdir(parents=True)
    (root / ".loomai" / "session_secret").write_text("s")
    (other / "fabric_config" / "id_token.json").write_text("{}")
    monkeypatch.setattr(settings_manager, "get_root_storage_dir", lambda: str(root))
    monkeypatch.setattr(files, "_storage_dir", lambda: str(mine))
    return str(root.parent), root, mine, other


def test_root_loomai_secrets_denied_in_multi_user(multi_user):
    base, root, _mine, other = multi_user
    with pytest.raises(HTTPException):
        files._safe_path(base, str(root / ".loomai" / "session_secret"))
    with pytest.raises(HTTPException):
        files._safe_path(base, "work/.loomai/user_registry.json")
    # Another user's storage lives under root/.loomai too.
    with pytest.raises(HTTPException):
        files._safe_path(base, str(other / "fabric_config" / "id_token.json"))


def test_own_storage_under_root_loomai_allowed(multi_user):
    base, _root, mine, _other = multi_user
    p = str(mine / "my_artifacts")
    assert files._safe_path(base, p) == os.path.realpath(p)
    assert files._safe_path(base, p, writable=True) == os.path.realpath(p)
    # ...but the user's own .loomai (settings.json) is still off limits.
    with pytest.raises(HTTPException):
        files._safe_path(base, str(mine / ".loomai" / "settings.json"))
