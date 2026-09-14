"""Shared fixtures for the hub test suite."""

from __future__ import annotations

import os
import sys

import pytest

# HubSettings validates required secrets at import time, so the environment has
# to be populated before anything pulls in app.config. conftest is imported
# before any test module, which makes this the right place for it.
os.environ.setdefault("PROXY_AUTH_TOKEN", "test-proxy-token")
os.environ.setdefault("FABRIC_CORE_API_BEARER_TOKEN", "test-bearer")
os.environ.setdefault("SESSION_SECRET", "test-session-secret")
os.environ.setdefault("CILOGON_CLIENT_ID", "test-client")
os.environ.setdefault("CILOGON_CLIENT_SECRET", "test-secret")

# Ensure the hub app package is importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.db.models import Base, Server, User  # noqa: E402


@pytest.fixture
async def db_maker():
    """An in-memory SQLite database with the hub schema created."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def add_user(db_maker):
    """Return a helper that inserts a user plus their default server record."""
    counter = {"n": 0}

    async def _add(username: str, state: str = "ready") -> None:
        counter["n"] += 1
        n = counter["n"]
        async with db_maker() as db:
            db.add(User(id=n, username=username, sub=f"sub-{n}"))
            db.add(Server(user_id=n, name="", state=state))
            await db.commit()

    return _add
