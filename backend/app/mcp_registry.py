"""Central registry of MCP servers LoomAI and its harnesses talk to.

This module is the single source of truth for "which MCP servers exist".
Everything else reads from here:

- ``harness_config.py`` / ``routes/ai_terminal.py`` generate the per-harness
  MCP wiring (OpenCode ``opencode.json``, Claude Code ``.mcp.json``, Pi
  ``agent/mcp.json``, ...) from :func:`harness_servers`.
- ``routes/ai_chat.py`` proxies LoomAI assistant tool calls to the servers
  returned by :func:`loomai_servers`.
- ``routes/ai_mcp.py`` serves the Configure -> MCP Servers page.

Built-in servers are declared in :data:`BUILTIN_SERVERS`. Operators can add
their own via the ``ai.mcp_servers`` settings key without a code change.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import Any, Literal

logger = logging.getLogger(__name__)

Transport = Literal["http", "stdio"]
AuthMode = Literal["none", "fabric_token"]


@dataclass(frozen=True)
class MCPServer:
    """One MCP server LoomAI knows about."""

    name: str
    label: str
    description: str
    transport: Transport = "http"
    url: str = ""
    auth: AuthMode = "none"
    # Wire this server into the generated external-harness configs
    # (OpenCode, Claude Code, Pi, Crush, ...).
    harness: bool = True
    # Expose this server's tools to the LoomAI assistant chat panel.
    # Only servers with a hand-written proxy in ai_chat.py set this.
    loomai: bool = False
    # Requires FABRIC staff/admin privileges to return data.
    requires_staff: bool = False
    # Purely informational, shown on the Configure -> MCP Servers page.
    docs_url: str = ""
    topics: tuple[str, ...] = field(default_factory=tuple)
    builtin: bool = True
    # stdio only
    command: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "transport": self.transport,
            "url": self.url,
            "auth": self.auth,
            "harness": self.harness,
            "loomai": self.loomai,
            "requires_staff": self.requires_staff,
            "docs_url": self.docs_url,
            "topics": list(self.topics),
            "builtin": self.builtin,
            "command": list(self.command),
        }


# ---------------------------------------------------------------------------
# Built-in servers
# ---------------------------------------------------------------------------

FABRIC_METRICS = MCPServer(
    name="fabric-metrics",
    label="FABRIC Infrastructure Metrics",
    description=(
        "Live FABRIC testbed infrastructure metrics — node CPU, memory, disk, "
        "filesystem, network, sockets, netstat, system, time and temperature, "
        "plus switch link status, rack-to-rack link traffic and per-port "
        "traffic. Runs the fixed PromQL queries authored in FABRIC's Grafana "
        "dashboards; callers pick a topic tool plus a variant instead of "
        "writing PromQL. Discovery (tools/list) is open; tool calls need a "
        "FABRIC bearer token."
    ),
    url="https://infrastructure-metrics-mcp.fabric-testbed.net/mcp",
    auth="fabric_token",
    harness=True,
    loomai=True,
    requires_staff=False,
    docs_url="https://public-metrics.fabric-testbed.net/grafana",
    topics=(
        "cpu",
        "memory",
        "memory_internals",
        "disk",
        "filesystem",
        "network",
        "sockets",
        "netstat",
        "system",
        "time",
        "temperature",
        "link_status",
        "link_traffic",
        "port_traffic",
    ),
)

FABRIC_REPORTS = MCPServer(
    name="fabric-reports",
    label="FABRIC Reports",
    description=(
        "FABRIC usage statistics, project membership and resource "
        "utilization reports. Requires a FABRIC bearer token AND "
        "staff/admin privileges — regular users get empty or denied results."
    ),
    url="https://reports.fabric-testbed.net/mcp",
    auth="fabric_token",
    harness=True,
    loomai=False,
    requires_staff=True,
    docs_url="https://reports.fabric-testbed.net/reports",
)

LOOMAI_HARNESS = MCPServer(
    name="loomai-harness",
    label="LoomAI Harness (local)",
    description=(
        "LoomAI's own REST API exposed over stdio MCP so in-container "
        "harnesses (OpenCode, Claude Code, Pi, Crush) can drive slices, "
        "weaves, recipes and SSH without leaving the container."
    ),
    transport="stdio",
    url="",
    auth="none",
    harness=True,
    loomai=False,
    command=("python3", "-m", "app.harness_mcp_server"),
)

BUILTIN_SERVERS: tuple[MCPServer, ...] = (
    FABRIC_METRICS,
    FABRIC_REPORTS,
    LOOMAI_HARNESS,
)

# The metrics server is the one the LoomAI assistant proxies directly.
METRICS_SERVER_NAME = FABRIC_METRICS.name
METRICS_TOOL_PREFIX = "fabric_metrics_"

# Which generated harness configs each transport lands in. Remote servers are
# reached with `npx mcp-remote`, which only OpenCode and Claude Code are wired
# for; the local stdio harness is additionally launched directly by Pi.
HTTP_HARNESSES: tuple[str, ...] = ("opencode", "claude")
STDIO_HARNESSES: tuple[str, ...] = ("opencode", "claude", "pi")


def harness_targets(server: "MCPServer") -> list[str]:
    """Names of the generated harness configs that reference ``server``."""
    if not server.harness:
        return []
    return list(STDIO_HARNESSES if server.transport == "stdio" else HTTP_HARNESSES)


# ---------------------------------------------------------------------------
# Registry access
# ---------------------------------------------------------------------------


def _ai_settings() -> dict[str, Any]:
    """The ``ai`` settings block, or ``{}`` when settings are unavailable.

    Read once per :func:`all_servers` call — it hits disk, and the registry is
    consulted on every proxied assistant tool call.
    """
    try:
        from app.settings_manager import load_settings

        return load_settings().get("ai") or {}
    except Exception as e:  # settings unavailable (tests, early startup)
        logger.debug("MCP registry: could not read settings: %s", e)
        return {}


def _custom_servers(ai: dict[str, Any]) -> list[MCPServer]:
    """Build operator-defined servers from ``ai.mcp_servers``."""
    raw = ai.get("mcp_servers") or []

    servers: list[MCPServer] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        url = str(entry.get("url") or "").strip()
        if not name or not url:
            continue
        servers.append(
            MCPServer(
                name=name,
                label=str(entry.get("label") or name),
                description=str(entry.get("description") or ""),
                transport="http",
                url=url,
                auth="fabric_token" if entry.get("auth") == "fabric_token" else "none",
                harness=bool(entry.get("harness", True)),
                loomai=False,  # no hand-written proxy exists for custom servers
                requires_staff=bool(entry.get("requires_staff", False)),
                docs_url=str(entry.get("docs_url") or ""),
                builtin=False,
            )
        )
    return servers


def all_servers(include_disabled: bool = True) -> list[MCPServer]:
    """Every known server: built-ins first, then operator-defined ones."""
    ai = _ai_settings()
    disabled: set[str] = set()
    if not include_disabled:
        disabled = {str(n) for n in (ai.get("mcp_disabled") or []) if n}

    by_name: dict[str, MCPServer] = {}
    for srv in BUILTIN_SERVERS:
        by_name[srv.name] = srv
    for srv in _custom_servers(ai):
        # A custom entry with a built-in name overrides that built-in's
        # url/auth but keeps the built-in's loomai proxy wiring.
        existing = by_name.get(srv.name)
        if existing is not None and existing.builtin:
            by_name[srv.name] = replace(
                existing, url=srv.url or existing.url, auth=srv.auth, harness=srv.harness
            )
        else:
            by_name[srv.name] = srv
    return [s for s in by_name.values() if s.name not in disabled]


def get_server(name: str) -> MCPServer | None:
    """Look up one server by name, or ``None`` if unknown/disabled."""
    for srv in all_servers(include_disabled=False):
        if srv.name == name:
            return srv
    return None


def harness_servers() -> list[MCPServer]:
    """Servers that should be wired into generated harness configs."""
    return [s for s in all_servers(include_disabled=False) if s.harness]


def managed_server_names() -> set[str]:
    """Every server name LoomAI generates config for — enabled or not.

    Config reconciliation needs this: a server that was disabled or dropped
    from ``ai.mcp_servers`` must have its stale harness entry removed, while a
    server the user added to ``opencode.json`` or ``.mcp.json`` by hand must be
    left alone. Names here are LoomAI's to manage; everything else is the
    user's.
    """
    return {s.name for s in all_servers(include_disabled=True)}


def remote_harness_servers() -> list[MCPServer]:
    """HTTP servers for harness configs (excludes the local stdio harness)."""
    return [s for s in harness_servers() if s.transport == "http" and s.url]


def loomai_servers() -> list[MCPServer]:
    """Servers whose tools the LoomAI assistant chat panel can call."""
    return [s for s in all_servers(include_disabled=False) if s.loomai]


def metrics_server() -> MCPServer | None:
    """The FABRIC infrastructure-metrics server, if enabled."""
    return get_server(METRICS_SERVER_NAME)
