"""Minimal async client for remote MCP servers (streamable HTTP transport).

LoomAI already depends on ``httpx`` for every outbound call, so this speaks the
small JSON-RPC subset we actually need — ``initialize``, ``tools/list`` and
``tools/call`` — instead of pulling in the MCP SDK. It is the mirror image of
``app.harness_mcp_server``, which serves LoomAI's own tools over stdio.

Design notes
------------
- **Sessions are cached per server.** ``initialize`` returns an
  ``mcp-session-id`` header that must be echoed on subsequent requests. Sessions
  are re-established automatically when the server drops them (HTTP 400/404).
- **Responses may be SSE.** Streamable-HTTP servers answer with
  ``text/event-stream``; :func:`_parse_response` handles both that and plain
  JSON.
- **tools/list is cached** for ``_TOOLS_TTL`` seconds so the Configure page and
  the chat handler don't re-probe on every request.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field, replace
from typing import Any

import httpx

from app.mcp_registry import MCPServer

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2024-11-05"
CLIENT_INFO = {"name": "loomai", "version": "1.0"}

_TOOLS_TTL = 300.0      # seconds to cache a server's tools/list
_SESSION_TTL = 600.0    # seconds before we proactively re-initialize
_REQUEST_TIMEOUT = 30.0
_CONNECT_TIMEOUT = 10.0


class MCPError(RuntimeError):
    """A remote MCP server returned an error or was unreachable."""


@dataclass
class _Session:
    session_id: str = ""
    created_at: float = 0.0
    server_info: dict[str, Any] = field(default_factory=dict)
    instructions: str = ""

    @property
    def expired(self) -> bool:
        return (time.time() - self.created_at) > _SESSION_TTL


@dataclass
class _ToolsCache:
    tools: list[dict[str, Any]] = field(default_factory=list)
    fetched_at: float = 0.0
    error: str = ""

    @property
    def fresh(self) -> bool:
        return bool(self.fetched_at) and (time.time() - self.fetched_at) < _TOOLS_TTL


_sessions: dict[str, _Session] = {}
_tools_cache: dict[str, _ToolsCache] = {}
_locks: dict[str, asyncio.Lock] = {}

# Lazily created so the module imports cleanly without a running loop.
_client: httpx.AsyncClient | None = None


def _lock_for(name: str) -> asyncio.Lock:
    lock = _locks.get(name)
    if lock is None:
        lock = asyncio.Lock()
        _locks[name] = lock
    return lock


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(_REQUEST_TIMEOUT, connect=_CONNECT_TIMEOUT),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            follow_redirects=True,
        )
    return _client


async def aclose() -> None:
    """Close the shared client — called from the FastAPI lifespan shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def reset_cache(name: str | None = None) -> None:
    """Drop cached sessions/tools, for one server or all of them."""
    if name is None:
        _sessions.clear()
        _tools_cache.clear()
        return
    _sessions.pop(name, None)
    for key in [k for k in _tools_cache if k.split(":", 1)[0] == name]:
        _tools_cache.pop(key, None)


# ---------------------------------------------------------------------------
# Wire protocol
# ---------------------------------------------------------------------------


def _parse_response(resp: httpx.Response) -> dict[str, Any]:
    """Extract the JSON-RPC payload from a JSON or SSE response body."""
    ctype = (resp.headers.get("content-type") or "").lower()
    text = resp.text
    if "text/event-stream" in ctype:
        for line in text.splitlines():
            if not line.startswith("data:"):
                continue
            chunk = line[len("data:"):].strip()
            if not chunk:
                continue
            try:
                payload = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            # Skip keep-alives / notifications; we want the response frame.
            if isinstance(payload, dict) and ("result" in payload or "error" in payload):
                return payload
        raise MCPError("no JSON-RPC frame in SSE response")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise MCPError(f"invalid JSON response: {e}") from e


def _auth_headers(server: MCPServer) -> dict[str, str]:
    if server.auth != "fabric_token":
        return {}
    try:
        from app.user_context import get_token_path

        with open(get_token_path()) as f:
            token = json.load(f).get("id_token")
    except Exception as e:
        raise MCPError(
            f"{server.name} requires a FABRIC token but none is available: {e}"
        ) from e
    if not token:
        raise MCPError(f"{server.name} requires a FABRIC token but none is available")
    return {"Authorization": f"Bearer {token}"}


async def _post(
    server: MCPServer,
    payload: dict[str, Any],
    *,
    session_id: str = "",
    expect_response: bool = True,
) -> dict[str, Any] | None:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        **_auth_headers(server),
    }
    if session_id:
        headers["mcp-session-id"] = session_id

    try:
        resp = await _http().post(server.url, json=payload, headers=headers)
    except httpx.HTTPError as e:
        raise MCPError(f"{server.name} unreachable: {e}") from e

    _raise_if_headers_too_large(server, resp)
    if resp.status_code in (400, 404) and session_id:
        # Server forgot the session — caller retries with a fresh one.
        raise _SessionExpired(resp.status_code)
    if resp.status_code >= 400:
        raise MCPError(
            f"{server.name} returned HTTP {resp.status_code}: {resp.text[:200]}"
        )
    if not expect_response:
        return None

    frame = _parse_response(resp)
    if "error" in frame:
        err = frame["error"] or {}
        raise MCPError(f"{server.name}: {err.get('message') or err}")
    result = frame.get("result")
    return result if isinstance(result, dict) else {"result": result}


class MCPHeaderTooLargeError(MCPError):
    """The server's ingress rejected our request headers as oversized.

    FABRIC id_tokens are ~8.6 KB, which overflows an nginx default
    ``large_client_header_buffers`` of 8k. The fix is on the server side; we
    surface it verbatim so the operator knows what to change.
    """


def _raise_if_headers_too_large(server: MCPServer, resp: httpx.Response) -> None:
    if resp.status_code != 400:
        return
    body = (resp.text or "")[:400].lower()
    if "header or cookie too large" not in body and "header too large" not in body:
        return
    raise MCPHeaderTooLargeError(
        f"{server.name} rejected the request: the FABRIC bearer token is larger "
        f"than the server's request-header buffer. The server operator needs to "
        f"raise nginx `large_client_header_buffers` (e.g. `4 32k`) for "
        f"{server.url}."
    )


class _SessionExpired(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"session expired (HTTP {status})")
        self.status = status


async def _initialize(server: MCPServer) -> _Session:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        **_auth_headers(server),
    }
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": CLIENT_INFO,
        },
    }
    try:
        resp = await _http().post(server.url, json=payload, headers=headers)
    except httpx.HTTPError as e:
        raise MCPError(f"{server.name} unreachable: {e}") from e
    _raise_if_headers_too_large(server, resp)
    if resp.status_code >= 400:
        raise MCPError(
            f"{server.name} initialize failed with HTTP {resp.status_code}: "
            f"{resp.text[:200]}"
        )

    frame = _parse_response(resp)
    if "error" in frame:
        raise MCPError(f"{server.name} initialize error: {frame['error']}")
    result = frame.get("result") or {}
    session = _Session(
        session_id=resp.headers.get("mcp-session-id", ""),
        created_at=time.time(),
        server_info=result.get("serverInfo") or {},
        instructions=str(result.get("instructions") or ""),
    )

    # Best-effort notifications/initialized — some servers require it before
    # they will answer tools/list.
    try:
        await _post(
            server,
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            session_id=session.session_id,
            expect_response=False,
        )
    except Exception as e:
        logger.debug("MCP %s: initialized notification failed: %s", server.name, e)
    return session


async def _session_for(server: MCPServer) -> _Session:
    session = _sessions.get(server.name)
    if session is not None and not session.expired:
        return session
    session = await _initialize(server)
    _sessions[server.name] = session
    return session


async def _call(server: MCPServer, method: str, params: dict[str, Any]) -> dict[str, Any]:
    """Issue one JSON-RPC call, re-initializing once if the session lapsed."""
    for attempt in (1, 2):
        session = await _session_for(server)
        payload = {
            "jsonrpc": "2.0",
            "id": int(time.time() * 1000) % 1_000_000,
            "method": method,
            "params": params,
        }
        try:
            result = await _post(server, payload, session_id=session.session_id)
            return result or {}
        except _SessionExpired:
            _sessions.pop(server.name, None)
            if attempt == 2:
                raise MCPError(f"{server.name}: session could not be re-established")
    raise MCPError(f"{server.name}: call failed")  # unreachable, keeps mypy happy


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _tools_key(server: MCPServer) -> str:
    """Cache key for tools/list.

    Keyed by auth mode as well as name: :func:`health` retries discovery
    anonymously when the authenticated attempt fails, and that fallback must
    not overwrite (and so hide) the authenticated failure on the next call.
    """
    return f"{server.name}:{server.auth}"


async def list_tools(server: MCPServer, *, force: bool = False) -> list[dict[str, Any]]:
    """Return the server's tool definitions, cached for ``_TOOLS_TTL``."""
    if server.transport != "http" or not server.url:
        return []
    key = _tools_key(server)
    cached = _tools_cache.get(key)
    if cached is not None and cached.fresh and not force:
        if cached.error:
            raise MCPError(cached.error)
        return cached.tools

    async with _lock_for(key):
        cached = _tools_cache.get(key)
        if cached is not None and cached.fresh and not force:
            if cached.error:
                raise MCPError(cached.error)
            return cached.tools
        try:
            result = await _call(server, "tools/list", {})
        except MCPError as e:
            _tools_cache[key] = _ToolsCache(fetched_at=time.time(), error=str(e))
            raise
        tools = [t for t in (result.get("tools") or []) if isinstance(t, dict)]
        _tools_cache[key] = _ToolsCache(tools=tools, fetched_at=time.time())
        return tools


async def call_tool(
    server: MCPServer, tool: str, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Invoke one tool. Returns the raw MCP ``tools/call`` result."""
    if server.transport != "http" or not server.url:
        raise MCPError(f"{server.name} is not an HTTP MCP server")
    return await _call(
        server, "tools/call", {"name": tool, "arguments": arguments or {}}
    )


def result_to_text(result: dict[str, Any]) -> str:
    """Flatten an MCP ``tools/call`` result into text for the LLM.

    Prefers ``structuredContent`` when present (it round-trips as JSON), then
    falls back to concatenating the ``content`` blocks.
    """
    if result.get("isError"):
        parts = _content_text(result.get("content"))
        return json.dumps({"error": parts or "MCP tool reported an error"})

    structured = result.get("structuredContent")
    if structured is not None:
        return json.dumps(structured, default=str)

    text = _content_text(result.get("content"))
    if text:
        return text
    return json.dumps(result, default=str)


def _content_text(content: Any) -> str:
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and block.get("text"):
            parts.append(str(block["text"]))
        elif block.get("type") == "resource":
            res = block.get("resource") or {}
            if res.get("text"):
                parts.append(str(res["text"]))
    return "\n".join(parts)


async def health(server: MCPServer, *, force: bool = False) -> dict[str, Any]:
    """Probe one server and report reachability plus tool count."""
    info: dict[str, Any] = {
        "name": server.name,
        "reachable": False,
        "tool_count": 0,
        "tools": [],
        "error": "",
        "server_info": {},
        "instructions": "",
        "latency_ms": None,
        "auth_warning": "",
    }
    if server.transport != "http" or not server.url:
        # Local stdio servers are always available inside the container.
        info["reachable"] = True
        info["local"] = True
        return info

    started = time.perf_counter()
    auth_warning = ""
    try:
        tools = await list_tools(server, force=force)
    except MCPError as e:
        # Discovery is open on some servers even when tool calls need a token.
        # Retry unauthenticated so the page can still list the tool surface,
        # and keep the original failure as a warning.
        tools, auth_warning = [], str(e)
        if server.auth != "none":
            try:
                tools = await list_tools(replace(server, auth="none"), force=force)
            except Exception:
                info["error"] = auth_warning
                return info
        else:
            info["error"] = auth_warning
            return info
    except Exception as e:  # defensive: never let the page 500
        info["error"] = f"{type(e).__name__}: {e}"
        return info

    session = _sessions.get(server.name)
    info.update(
        reachable=True,
        tool_count=len(tools),
        tools=[
            {
                "name": t.get("name", ""),
                "description": (t.get("description") or "").strip(),
                "input_schema": t.get("inputSchema") or {},
            }
            for t in tools
        ],
        server_info=session.server_info if session else {},
        instructions=session.instructions if session else "",
        latency_ms=round((time.perf_counter() - started) * 1000, 1),
        auth_warning=auth_warning,
    )
    return info
