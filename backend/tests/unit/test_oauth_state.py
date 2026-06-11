"""CSRF-state checks for the OAuth callback (non-breaking enforcement)."""
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.routes import config


def _req(cookie: str | None):
    r = MagicMock()
    r.cookies = {config._OAUTH_STATE_COOKIE: cookie} if cookie is not None else {}
    return r


def test_matching_state_ok():
    config._verify_oauth_state(_req("abc"), "abc")          # no raise


def test_mismatched_state_rejected():
    with pytest.raises(HTTPException) as exc:
        config._verify_oauth_state(_req("abc"), "evil")
    assert exc.value.status_code == 403


def test_no_cookie_proceeds():
    # Paste flow / direct callback — can't validate, must not block.
    config._verify_oauth_state(_req(None), "anything")


def test_cookie_but_no_echoed_state_proceeds():
    # CM didn't echo state — log + proceed (non-breaking).
    config._verify_oauth_state(_req("abc"), "")
