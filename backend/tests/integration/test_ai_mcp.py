"""Tests for the MCP servers API and the LoomAI metrics tool proxy."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from app import mcp_client
from app.mcp_registry import FABRIC_METRICS


def _run_async(coro):
    result = asyncio.run(coro)
    asyncio.set_event_loop(asyncio.new_event_loop())
    return result


def _healthy(tool_count=2, **overrides):
    status = {
        "name": "fabric-metrics",
        "reachable": True,
        "tool_count": tool_count,
        "tools": [
            {"name": "fabric_metrics_cpu", "description": "CPU", "input_schema": {}},
            {"name": "fabric_metrics_list_topics", "description": "Topics", "input_schema": {}},
        ],
        "error": "",
        "auth_warning": "",
        "server_info": {"name": "fabric-metrics-mcp", "version": "1.0.0"},
        "instructions": "",
        "latency_ms": 12.3,
    }
    status.update(overrides)
    return status


class TestListServers:
    def test_lists_registered_servers(self, client):
        with patch("app.mcp_client.health", new=AsyncMock(return_value=_healthy())):
            resp = client.get("/api/ai/mcp/servers")
        assert resp.status_code == 200
        servers = {s["name"]: s for s in resp.json()["servers"]}
        assert {"fabric-metrics", "fabric-reports", "loomai-harness"} <= set(servers)

    def test_metrics_server_is_flagged_for_the_assistant(self, client):
        with patch("app.mcp_client.health", new=AsyncMock(return_value=_healthy())):
            resp = client.get("/api/ai/mcp/servers")
        metrics = next(s for s in resp.json()["servers"] if s["name"] == "fabric-metrics")
        assert metrics["loomai"] is True
        assert metrics["url"].endswith("infrastructure-metrics-mcp.fabric-testbed.net/mcp")
        assert metrics["harnesses"] == ["opencode", "claude"]

    def test_overview_omits_the_tool_list(self, client):
        with patch("app.mcp_client.health", new=AsyncMock(return_value=_healthy())):
            resp = client.get("/api/ai/mcp/servers")
        metrics = next(s for s in resp.json()["servers"] if s["name"] == "fabric-metrics")
        assert metrics["status"]["tool_count"] == 2
        assert "tools" not in metrics["status"]

    def test_probe_false_skips_the_network(self, client):
        health = AsyncMock(return_value=_healthy())
        with patch("app.mcp_client.health", new=health):
            resp = client.get("/api/ai/mcp/servers?probe=false")
        assert resp.status_code == 200
        health.assert_not_awaited()
        assert all("status" not in s for s in resp.json()["servers"])

    def test_probe_failure_does_not_500(self, client):
        with patch("app.mcp_client.health", new=AsyncMock(side_effect=RuntimeError("boom"))):
            resp = client.get("/api/ai/mcp/servers")
        assert resp.status_code == 200
        metrics = next(s for s in resp.json()["servers"] if s["name"] == "fabric-metrics")
        assert metrics["status"]["reachable"] is False
        assert "boom" in metrics["status"]["error"]


class TestServerDetail:
    def test_detail_includes_tools(self, client):
        with patch("app.mcp_client.health", new=AsyncMock(return_value=_healthy())):
            resp = client.get("/api/ai/mcp/servers/fabric-metrics")
        assert resp.status_code == 200
        assert [t["name"] for t in resp.json()["status"]["tools"]] == [
            "fabric_metrics_cpu",
            "fabric_metrics_list_topics",
        ]

    def test_unknown_server_is_404(self, client):
        assert client.get("/api/ai/mcp/servers/nope").status_code == 404

    def test_probe_endpoint_resets_the_cache(self, client):
        with patch("app.mcp_client.health", new=AsyncMock(return_value=_healthy())) as h:
            resp = client.post("/api/ai/mcp/servers/fabric-metrics/probe")
        assert resp.status_code == 200
        assert h.await_args.kwargs["force"] is True

    def test_probe_unknown_server_is_404(self, client):
        assert client.post("/api/ai/mcp/servers/nope/probe").status_code == 404


class TestCallEndpoint:
    def test_call_returns_flattened_text(self, client):
        result = {"structuredContent": {"load1": 0.4}}
        with patch("app.mcp_client.call_tool", new=AsyncMock(return_value=result)):
            resp = client.post(
                "/api/ai/mcp/servers/fabric-metrics/call",
                json={"tool": "fabric_metrics_cpu", "arguments": {"variant": "load_average", "node": "ncsa"}},
            )
        assert resp.status_code == 200
        assert json.loads(resp.json()["text"]) == {"load1": 0.4}

    def test_call_error_is_502(self, client):
        with patch(
            "app.mcp_client.call_tool",
            new=AsyncMock(side_effect=mcp_client.MCPError("unreachable")),
        ):
            resp = client.post(
                "/api/ai/mcp/servers/fabric-metrics/call",
                json={"tool": "fabric_metrics_cpu", "arguments": {}},
            )
        assert resp.status_code == 502
        assert "unreachable" in resp.json()["detail"]


class TestAssistantMetricsTools:
    """The three routing tools the LoomAI chat panel exposes."""

    def test_tool_schemas_are_registered(self):
        from app.routes.ai_chat import TOOL_SCHEMAS

        names = {t["function"]["name"] for t in TOOL_SCHEMAS}
        assert {
            "list_metric_topics",
            "list_metric_param_options",
            "query_infrastructure_metrics",
        } <= names

    def test_metrics_tools_survive_tool_filtering(self):
        """Non-core tools get dropped for standard-tier models — these must not."""
        from app.chat_context import PROFILE_TIERS, filter_tool_schemas
        from app.routes.ai_chat import TOOL_SCHEMAS

        kept = filter_tool_schemas(TOOL_SCHEMAS, PROFILE_TIERS["standard"]["max_tools"])
        names = {t["function"]["name"] for t in kept}
        assert {
            "list_metric_topics",
            "list_metric_param_options",
            "query_infrastructure_metrics",
        } <= names

    def test_core_tools_and_max_tools_stay_in_sync(self):
        from app.chat_context import CORE_TOOLS, PROFILE_TIERS

        assert len(CORE_TOOLS) == PROFILE_TIERS["standard"]["max_tools"]
        assert len(CORE_TOOLS) == PROFILE_TIERS["large"]["max_tools"]

    def test_list_topics_calls_the_server(self):
        from app.routes.ai_chat import execute_tool

        call = AsyncMock(return_value={"structuredContent": {"topics": ["cpu"]}})
        with patch("app.mcp_client.call_tool", new=call):
            out = _run_async(execute_tool("list_metric_topics", {}))
        assert json.loads(out) == {"topics": ["cpu"]}
        assert call.await_args.args[1] == "fabric_metrics_list_topics"

    def test_query_builds_the_topic_tool_name_and_args(self):
        from app.routes.ai_chat import execute_tool

        call = AsyncMock(return_value={"structuredContent": {"ok": True}})
        with patch("app.mcp_client.call_tool", new=call):
            _run_async(execute_tool(
                "query_infrastructure_metrics",
                {"topic": "cpu", "variant": "load_average", "args": {"node": "ncsa"}},
            ))
        assert call.await_args.args[1] == "fabric_metrics_cpu"
        assert call.await_args.args[2] == {"node": "ncsa", "variant": "load_average"}

    def test_query_accepts_hoisted_top_level_params(self):
        """Models often put node/src_rack at the top level instead of in args."""
        from app.routes.ai_chat import execute_tool

        call = AsyncMock(return_value={"structuredContent": {}})
        with patch("app.mcp_client.call_tool", new=call):
            _run_async(execute_tool(
                "query_infrastructure_metrics",
                {"topic": "link_traffic", "variant": "throughput", "src_rack": "ncsa", "dst_rack": "cern"},
            ))
        assert call.await_args.args[2] == {
            "src_rack": "ncsa",
            "dst_rack": "cern",
            "variant": "throughput",
        }

    def test_query_drops_empty_optionals(self):
        from app.routes.ai_chat import execute_tool

        call = AsyncMock(return_value={"structuredContent": {}})
        with patch("app.mcp_client.call_tool", new=call):
            _run_async(execute_tool(
                "query_infrastructure_metrics",
                {"topic": "cpu", "variant": "load_average", "args": {"node": "ncsa", "start": None, "step": ""}},
            ))
        assert call.await_args.args[2] == {"node": "ncsa", "variant": "load_average"}

    def test_list_sites_needs_no_variant(self):
        from app.routes.ai_chat import execute_tool

        call = AsyncMock(return_value={"structuredContent": {"sites": ["ncsa"]}})
        with patch("app.mcp_client.call_tool", new=call):
            _run_async(execute_tool("query_infrastructure_metrics", {"topic": "list_sites"}))
        assert call.await_args.args[1] == "fabric_metrics_list_sites"
        assert call.await_args.args[2] == {}

    def test_missing_topic_returns_a_routing_hint(self):
        from app.routes.ai_chat import execute_tool

        out = json.loads(_run_async(execute_tool("query_infrastructure_metrics", {})))
        assert "list_metric_topics" in out["error"]

    def test_mcp_error_is_returned_as_json_not_raised(self):
        from app.routes.ai_chat import execute_tool

        with patch(
            "app.mcp_client.call_tool",
            new=AsyncMock(side_effect=mcp_client.MCPError("server down")),
        ):
            out = json.loads(_run_async(execute_tool("query_infrastructure_metrics", {"topic": "cpu"})))
        assert out["error"] == "server down"
        assert out["tool"] == "fabric_metrics_cpu"

    def test_oversized_result_is_truncated(self):
        from app.routes.ai_chat import execute_tool

        big = {"content": [{"type": "text", "text": "x" * 20000}]}
        with patch("app.mcp_client.call_tool", new=AsyncMock(return_value=big)):
            out = _run_async(execute_tool("query_infrastructure_metrics", {"topic": "cpu", "variant": "v"}))
        assert len(out) < 7000
        assert out.endswith("[truncated — narrow the query]")

    def test_disabled_metrics_server_is_reported(self):
        from app.routes.ai_chat import execute_tool

        with patch("app.mcp_registry.metrics_server", return_value=None):
            out = json.loads(_run_async(execute_tool("list_metric_topics", {})))
        assert "not enabled" in out["error"]


class TestAnonymousDiscoveryFallback:
    """Discovery may succeed unauthenticated while tool calls still fail.

    The metrics server's ingress rejects the ~8.6 KB FABRIC token, so LoomAI
    falls back to an anonymous probe to keep the tool list visible. That
    fallback must not overwrite the authenticated failure — otherwise the page
    reports a healthy server while every call errors.
    """

    def setup_method(self):
        mcp_client.reset_cache()

    def teardown_method(self):
        mcp_client.reset_cache()

    async def _auth_fails_anon_works(self, server, method, params):
        if server.auth == "fabric_token":
            raise mcp_client.MCPHeaderTooLargeError("token exceeds the header buffer")
        return {"tools": [{"name": "fabric_metrics_cpu", "description": "CPU"}]}

    def test_first_probe_reports_tools_and_the_auth_warning(self):
        with patch("app.mcp_client._call", new=self._auth_fails_anon_works):
            health = _run_async(mcp_client.health(FABRIC_METRICS))
        assert health["reachable"] is True
        assert health["tool_count"] == 1
        assert "header buffer" in health["auth_warning"]

    def test_auth_warning_survives_the_cached_second_probe(self):
        with patch("app.mcp_client._call", new=self._auth_fails_anon_works):
            _run_async(mcp_client.health(FABRIC_METRICS))
            second = _run_async(mcp_client.health(FABRIC_METRICS))
        assert second["tool_count"] == 1
        assert "header buffer" in second["auth_warning"], (
            "anonymous discovery must not be cached over the authenticated failure"
        )

    def test_auth_and_anonymous_results_are_cached_separately(self):
        with patch("app.mcp_client._call", new=self._auth_fails_anon_works):
            _run_async(mcp_client.health(FABRIC_METRICS))
        assert set(mcp_client._tools_cache) == {
            "fabric-metrics:fabric_token",
            "fabric-metrics:none",
        }

    def test_reset_cache_clears_every_auth_variant(self):
        with patch("app.mcp_client._call", new=self._auth_fails_anon_works):
            _run_async(mcp_client.health(FABRIC_METRICS))
        mcp_client.reset_cache("fabric-metrics")
        assert mcp_client._tools_cache == {}

    def test_a_fully_unreachable_server_reports_an_error(self):
        async def always_fails(server, method, params):
            raise mcp_client.MCPError("connection refused")

        with patch("app.mcp_client._call", new=always_fails):
            health = _run_async(mcp_client.health(FABRIC_METRICS))
        assert health["reachable"] is False
        assert "connection refused" in health["error"]
