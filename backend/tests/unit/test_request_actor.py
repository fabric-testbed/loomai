"""Tests for agent/user request attribution used by the agent lease cap."""

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import request_actor
from app.fablib_executor import run_in_fablib_pool


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(request_actor.ActorMiddleware)

    @app.get("/actor")
    async def actor():
        # Read in the FABlib pool as well, where most route work runs.
        in_pool = await run_in_fablib_pool(request_actor.is_agent_request)
        return {"agent": request_actor.is_agent_request(), "in_pool": in_pool}

    return app


def test_requests_default_to_user():
    resp = TestClient(_app()).get("/actor")
    assert resp.json() == {"agent": False, "in_pool": False}


def test_agent_header_marks_request_and_reaches_fablib_pool():
    resp = TestClient(_app()).get("/actor", headers={request_actor.ACTOR_HEADER: "Agent"})
    assert resp.json() == {"agent": True, "in_pool": True}


def test_unknown_header_value_is_user():
    resp = TestClient(_app()).get("/actor", headers={request_actor.ACTOR_HEADER: "admin"})
    assert resp.json()["agent"] is False


def test_agent_actor_is_scoped_to_block():
    assert not request_actor.is_agent_request()
    with request_actor.agent_actor():
        assert request_actor.is_agent_request()
        assert asyncio.run(run_in_fablib_pool(request_actor.is_agent_request))
    assert not request_actor.is_agent_request()


def test_cap_only_returned_for_agents(monkeypatch):
    from app import settings_manager

    monkeypatch.setattr(settings_manager, "get_max_slice_lease_hours", lambda: 6)
    assert settings_manager.get_request_lease_cap_hours() is None
    with request_actor.agent_actor():
        assert settings_manager.get_request_lease_cap_hours() == 6
