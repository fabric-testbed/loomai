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
