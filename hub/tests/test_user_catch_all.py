"""The /user/* catch-all is the last line of defence against the redirect loop.

CHP sends any request with no matching route to the hub's default target, so
this handler sees exactly the traffic that would otherwise loop.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from app import main as M

USER = "f2b25790-b1b9-421f-a998-16fc443dc999"


class FakeRequest:
    def __init__(self, path: str, query: dict | None = None):
        self.url = type("URL", (), {"path": path})()
        self.query_params = query or {}


def _login_url() -> str:
    return f"{M.settings.HUB_PREFIX}/login"


class TestUserCatchAll:
    async def test_recoverable_route_retries_the_original_url(self):
        with patch.object(M, "ensure_route", AsyncMock(return_value=True)):
            resp = await M.user_catch_all(
                f"{USER}/lab", FakeRequest(f"/user/{USER}/lab")
            )
        # Once the route is back, the retry is served by CHP and never reaches
        # the hub again.
        assert resp.headers["location"] == f"/user/{USER}/lab?route_retry=1"

    async def test_recovery_targets_the_user_from_the_url(self):
        with patch.object(M, "ensure_route", AsyncMock(return_value=True)) as ensure:
            await M.user_catch_all(f"{USER}/lab/tree", FakeRequest(f"/user/{USER}/lab/tree"))
        ensure.assert_awaited_once_with(USER)

    async def test_unrecoverable_route_falls_back_to_login(self):
        with patch.object(M, "ensure_route", AsyncMock(return_value=False)):
            resp = await M.user_catch_all(f"{USER}/", FakeRequest(f"/user/{USER}/"))
        assert resp.headers["location"] == _login_url()

    async def test_a_second_arrival_does_not_retry_again(self):
        # If the retry comes back here the recovery did not take effect;
        # retrying again would be the loop we are fixing.
        with patch.object(M, "ensure_route", AsyncMock(return_value=True)) as ensure:
            resp = await M.user_catch_all(
                f"{USER}/", FakeRequest(f"/user/{USER}/", {"route_retry": "1"})
            )
        assert resp.headers["location"] == _login_url()
        assert ensure.await_count == 0

    async def test_recovery_errors_do_not_surface_as_500s(self):
        with patch.object(M, "ensure_route", AsyncMock(side_effect=RuntimeError("boom"))):
            resp = await M.user_catch_all(f"{USER}/", FakeRequest(f"/user/{USER}/"))
        assert resp.headers["location"] == _login_url()

    async def test_empty_path_is_handled(self):
        with patch.object(M, "ensure_route", AsyncMock(return_value=True)) as ensure:
            resp = await M.user_catch_all("", FakeRequest("/user/"))
        assert resp.headers["location"] == _login_url()
        assert ensure.await_count == 0
