"""CSRF-state checks for the OAuth callback (fail-closed)."""
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


def test_no_cookie_rejected():
    # A crafted link opened cold (no login started in this browser) must not
    # be able to install a token. The paste flow has its own endpoint.
    with pytest.raises(HTTPException) as exc:
        config._verify_oauth_state(_req(None), "anything")
    assert exc.value.status_code == 403


def test_cookie_but_no_echoed_state_rejected():
    # The state is part of the redirect_uri, so a real CM redirect always
    # carries it; its absence means the delivery did not come from our login.
    with pytest.raises(HTTPException) as exc:
        config._verify_oauth_state(_req("abc"), "")
    assert exc.value.status_code == 403


def test_empty_cookie_and_state_rejected():
    with pytest.raises(HTTPException):
        config._verify_oauth_state(_req(""), "")
