"""HTTP API for the MCP servers LoomAI and its harnesses talk to.

Backs the Configure -> MCP Servers page: which servers are registered, whether
they are reachable right now, and what tools each exposes.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import mcp_client
from app.mcp_registry import all_servers, get_server, harness_targets

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai/mcp", tags=["mcp"])


class MCPCallRequest(BaseModel):
    tool: str
    arguments: dict[str, Any] = {}


@router.get("/servers")
async def list_mcp_servers(probe: bool = True) -> dict[str, Any]:
    """List every registered MCP server, optionally probing each for health."""
    servers = all_servers(include_disabled=False)
    entries = [dict(s.to_dict(), harnesses=harness_targets(s)) for s in servers]

    if not probe:
        return {"servers": entries}

    results = await asyncio.gather(
        *(mcp_client.health(s) for s in servers), return_exceptions=True
    )
    for entry, result in zip(entries, results):
        if isinstance(result, BaseException):
            entry["status"] = {
                "reachable": False,
                "error": f"{type(result).__name__}: {result}",
                "tool_count": 0,
            }
            continue
        # The tool list itself is only returned by the per-server detail
        # endpoint; the overview stays small.
        status = {k: v for k, v in result.items() if k != "tools"}
        entry["status"] = status
    return {"servers": entries}


@router.get("/servers/{name}")
async def get_mcp_server(name: str, force: bool = False) -> dict[str, Any]:
    """One server with its full tool list and input schemas."""
    srv = get_server(name)
    if srv is None:
        raise HTTPException(status_code=404, detail=f"Unknown MCP server: {name}")
    status = await mcp_client.health(srv, force=force)
    return dict(srv.to_dict(), harnesses=harness_targets(srv), status=status)


@router.post("/servers/{name}/probe")
async def probe_mcp_server(name: str) -> dict[str, Any]:
    """Force a fresh connection and tools/list, bypassing the cache."""
    srv = get_server(name)
    if srv is None:
        raise HTTPException(status_code=404, detail=f"Unknown MCP server: {name}")
    mcp_client.reset_cache(name)
    return await mcp_client.health(srv, force=True)


@router.post("/servers/{name}/call")
async def call_mcp_tool(name: str, req: MCPCallRequest) -> dict[str, Any]:
    """Invoke one tool on a registered server — used by the page's try-it panel."""
    srv = get_server(name)
    if srv is None:
        raise HTTPException(status_code=404, detail=f"Unknown MCP server: {name}")
    try:
        result = await mcp_client.call_tool(srv, req.tool, req.arguments)
    except mcp_client.MCPError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"tool": req.tool, "text": mcp_client.result_to_text(result), "raw": result}
