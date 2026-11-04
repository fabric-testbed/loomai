"""Who initiated the current request: a person or an AI agent.

The slice lease cap (``fabric.slice_policy.max_lease_hours``) only applies to
agent-initiated actions, so a person working in the UI gets FABRIC's normal
lease limits while an agent that forgets a slice can't hold resources for days.

Agent surfaces mark themselves:

- LoomAI chat tools run inside :func:`agent_actor` (see ``ai_chat.execute_tool``).
- The ``loomai-harness`` MCP server always sends ``X-LoomAI-Actor: agent``.
- The ``loomai`` CLI sends the header when ``LOOMAI_ACTOR=agent`` is set, which
  the AI-tool launchers in ``ai_terminal`` do. A person's own terminal does not.

This is a guardrail, not a security boundary: the marker is self-declared and
an agent calling FABlib directly is not covered.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Iterator

ACTOR_HEADER = "X-LoomAI-Actor"
ACTOR_ENV = "LOOMAI_ACTOR"
AGENT = "agent"
USER = "user"

_actor: contextvars.ContextVar[str] = contextvars.ContextVar("loomai_actor", default=USER)


def is_agent_request() -> bool:
    """Return True when the current request or tool call came from an AI agent."""
    return _actor.get() == AGENT


@contextmanager
def agent_actor() -> Iterator[None]:
    """Mark everything run inside the block as agent-initiated."""
    token = _actor.set(AGENT)
    try:
        yield
    finally:
        _actor.reset(token)


class ActorMiddleware:
    """ASGI middleware that sets the actor from the ``X-LoomAI-Actor`` header."""

    _header = ACTOR_HEADER.lower().encode()

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        value = b""
        for name, raw in scope.get("headers") or []:
            if name == self._header:
                value = raw
                break
        actor = AGENT if value.strip().lower() == AGENT.encode() else USER
        token = _actor.set(actor)
        try:
            await self.app(scope, receive, send)
        finally:
            _actor.reset(token)
