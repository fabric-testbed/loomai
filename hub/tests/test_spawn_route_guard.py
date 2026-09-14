"""The spawn paths must never send a user to a server with no proxy route.

A Server row stays "ready" across a proxy restart, but CHP's routing table does
not survive one. Redirecting on the database state alone is what produced the
2026-09-14 ERR_TOO_MANY_REDIRECTS outage.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import Server, User
from app.routes import spawn as S

USER = "f2b25790-b1b9-421f-a998-16fc443dc999"


class FakeRequest:
    """Minimal stand-in; spawn_page only passes it through to the template."""

    scope = {"type": "http"}


async def _spawn_page(db, ensure_ok: bool, rendered="SPAWN_PAGE"):
    with patch.object(S, "ensure_route", AsyncMock(return_value=ensure_ok)), \
         patch.object(S.templates, "TemplateResponse", lambda *a, **k: rendered):
        return await S.spawn_page(FakeRequest(), {"username": USER}, db)


class TestSpawnPage:
    async def test_redirects_when_the_route_is_healthy(self, db_maker, add_user):
        await add_user(USER, "ready")
        async with db_maker() as db:
            resp = await _spawn_page(db, ensure_ok=True)
        assert resp.status_code == 302
        assert resp.headers["location"] == f"/user/{USER}/"

    async def test_does_not_redirect_when_the_route_is_gone(self, db_maker, add_user):
        # The regression under test: without the guard this returned a 302 to
        # /user/<id>/ and the browser looped until Chrome gave up.
        await add_user(USER, "ready")
        async with db_maker() as db:
            resp = await _spawn_page(db, ensure_ok=False)
        assert resp == "SPAWN_PAGE"

    async def test_route_is_checked_for_the_session_user(self, db_maker, add_user):
        await add_user(USER, "ready")
        with patch.object(S, "ensure_route", AsyncMock(return_value=True)) as ensure:
            async with db_maker() as db:
                await S.spawn_page(FakeRequest(), {"username": USER}, db)
        ensure.assert_awaited_once_with(USER)

    async def test_stopped_server_renders_the_spawn_page(self, db_maker, add_user):
        await add_user(USER, "stopped")
        with patch.object(S, "ensure_route", AsyncMock()) as ensure, \
             patch.object(S.templates, "TemplateResponse", lambda *a, **k: "SPAWN_PAGE"):
            async with db_maker() as db:
                resp = await S.spawn_page(FakeRequest(), {"username": USER}, db)
        assert resp == "SPAWN_PAGE"
        # No point asking the proxy about a server that is not running.
        assert ensure.await_count == 0

    async def test_unknown_user_renders_the_spawn_page(self, db_maker):
        async with db_maker() as db:
            resp = await _spawn_page(db, ensure_ok=True)
        assert resp == "SPAWN_PAGE"


class TestSpawnProgressStream:
    """The SSE stream backing the spawn page carries the same trap."""

    async def _events(self, db, ensure_ok: bool):
        with patch.object(S, "ensure_route", AsyncMock(return_value=ensure_ok)), \
             patch.object(S, "ensure_user_pvc", AsyncMock(side_effect=RuntimeError("stop here"))):
            resp = await S.spawn_progress(USER, FakeRequest(), {"username": USER}, db)
            return [chunk async for chunk in resp.body_iterator]

    async def test_ready_is_announced_when_the_route_exists(self, db_maker, add_user):
        await add_user(USER, "ready")
        async with db_maker() as db:
            events = await self._events(db, ensure_ok=True)
        payload = json.loads(events[0].removeprefix("data: ").strip())
        assert payload == {"event": "ready", "url": f"/user/{USER}/"}

    async def test_missing_route_does_not_announce_ready(self, db_maker, add_user):
        # Otherwise the spawn page immediately bounces the browser back to the
        # unroutable URL and the loop resumes.
        await add_user(USER, "ready")
        async with db_maker() as db:
            events = await self._events(db, ensure_ok=False)
        first = json.loads(events[0].removeprefix("data: ").strip())
        assert first["event"] != "ready"
