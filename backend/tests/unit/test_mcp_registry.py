"""Tests for the MCP server registry and the remote-MCP client."""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest

from app import mcp_client
from app.mcp_registry import (
    BUILTIN_SERVERS,
    FABRIC_METRICS,
    METRICS_TOOL_PREFIX,
    MCPServer,
    all_servers,
    get_server,
    harness_servers,
    harness_targets,
    loomai_servers,
    metrics_server,
    remote_harness_servers,
)


@pytest.fixture(autouse=True)
def _clear_mcp_caches():
    mcp_client.reset_cache()
    yield
    mcp_client.reset_cache()


def _no_custom_settings():
    return patch("app.settings_manager.load_settings", return_value={})


class TestRegistry:
    def test_builtins_are_registered(self):
        with _no_custom_settings():
            names = {s.name for s in all_servers()}
        assert names == {"fabric-metrics", "fabric-reports", "loomai-harness"}

    def test_metrics_server_is_the_loomai_proxy_target(self):
        with _no_custom_settings():
            assert [s.name for s in loomai_servers()] == ["fabric-metrics"]
            assert metrics_server() is not None
            assert metrics_server().name == "fabric-metrics"

    def test_metrics_server_url_and_auth(self):
        assert FABRIC_METRICS.url == (
            "https://infrastructure-metrics-mcp.fabric-testbed.net/mcp"
        )
        # tools/list is open, but tools/call needs a FABRIC bearer token.
        assert FABRIC_METRICS.auth == "fabric_token"
        assert FABRIC_METRICS.requires_staff is False

    def test_remote_harness_servers_excludes_local_stdio(self):
        with _no_custom_settings():
            names = {s.name for s in remote_harness_servers()}
        assert names == {"fabric-metrics", "fabric-reports"}

    def test_harness_targets_by_transport(self):
        assert harness_targets(FABRIC_METRICS) == ["opencode", "claude"]
        local = next(s for s in BUILTIN_SERVERS if s.transport == "stdio")
        assert harness_targets(local) == ["opencode", "claude", "pi"]

    def test_harness_targets_empty_when_not_wired(self):
        srv = MCPServer(name="x", label="X", description="", harness=False)
        assert harness_targets(srv) == []

    def test_custom_server_from_settings(self):
        settings = {
            "ai": {
                "mcp_servers": [
                    {"name": "my-mcp", "url": "https://example.test/mcp", "label": "Mine"}
                ]
            }
        }
        with patch("app.settings_manager.load_settings", return_value=settings):
            srv = get_server("my-mcp")
        assert srv is not None
        assert srv.url == "https://example.test/mcp"
        assert srv.builtin is False
        # Custom servers never get the LoomAI chat proxy — no hand-written
        # tool schema exists for them.
        assert srv.loomai is False

    def test_custom_entry_without_url_is_ignored(self):
        settings = {"ai": {"mcp_servers": [{"name": "broken"}]}}
        with patch("app.settings_manager.load_settings", return_value=settings):
            assert get_server("broken") is None

    def test_disabled_server_is_hidden(self):
        settings = {"ai": {"mcp_disabled": ["fabric-reports"]}}
        with patch("app.settings_manager.load_settings", return_value=settings):
            names = {s.name for s in all_servers(include_disabled=False)}
            assert "fabric-reports" not in names
            assert get_server("fabric-reports") is None

    def test_custom_override_keeps_builtin_loomai_wiring(self):
        settings = {
            "ai": {
                "mcp_servers": [
                    {"name": "fabric-metrics", "url": "https://staging.test/mcp"}
                ]
            }
        }
        with patch("app.settings_manager.load_settings", return_value=settings):
            srv = get_server("fabric-metrics")
        assert srv.url == "https://staging.test/mcp"
        assert srv.loomai is True

    def test_settings_failure_falls_back_to_builtins(self):
        with patch("app.settings_manager.load_settings", side_effect=OSError("boom")):
            names = {s.name for s in harness_servers()}
        assert names == {"fabric-metrics", "fabric-reports", "loomai-harness"}


class TestParseResponse:
    def _resp(self, body: str, ctype: str) -> httpx.Response:
        return httpx.Response(
            200,
            text=body,
            headers={"content-type": ctype},
            request=httpx.Request("POST", "https://x.test/mcp"),
        )

    def test_plain_json(self):
        frame = mcp_client._parse_response(
            self._resp(json.dumps({"result": {"ok": True}}), "application/json")
        )
        assert frame["result"]["ok"] is True

    def test_sse_frame(self):
        body = 'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"tools":[]}}\n\n'
        frame = mcp_client._parse_response(self._resp(body, "text/event-stream"))
        assert frame["result"] == {"tools": []}

    def test_sse_skips_keepalives_and_notifications(self):
        body = (
            ": ping\n"
            'data: {"jsonrpc":"2.0","method":"notifications/message"}\n'
            'data: {"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"t"}]}}\n'
        )
        frame = mcp_client._parse_response(self._resp(body, "text/event-stream"))
        assert frame["result"]["tools"][0]["name"] == "t"

    def test_sse_without_a_frame_raises(self):
        with pytest.raises(mcp_client.MCPError):
            mcp_client._parse_response(self._resp("data: nonsense\n", "text/event-stream"))

    def test_invalid_json_raises(self):
        with pytest.raises(mcp_client.MCPError):
            mcp_client._parse_response(self._resp("<html>", "application/json"))


class TestHeaderTooLarge:
    """FABRIC id_tokens are ~8.6 KB and overflow an 8k nginx header buffer."""

    def _resp(self) -> httpx.Response:
        return httpx.Response(
            400,
            text="<html><title>400 Request Header Or Cookie Too Large</title></html>",
            request=httpx.Request("POST", FABRIC_METRICS.url),
        )

    def test_raises_actionable_error(self):
        with pytest.raises(mcp_client.MCPHeaderTooLargeError) as exc:
            mcp_client._raise_if_headers_too_large(FABRIC_METRICS, self._resp())
        assert "large_client_header_buffers" in str(exc.value)

    def test_is_an_mcp_error(self):
        assert issubclass(mcp_client.MCPHeaderTooLargeError, mcp_client.MCPError)

    def test_ignores_other_400s(self):
        resp = httpx.Response(
            400, text="bad request", request=httpx.Request("POST", FABRIC_METRICS.url)
        )
        mcp_client._raise_if_headers_too_large(FABRIC_METRICS, resp)  # no raise


class TestResultToText:
    def test_prefers_structured_content(self):
        text = mcp_client.result_to_text({"structuredContent": {"load1": 1.5}})
        assert json.loads(text) == {"load1": 1.5}

    def test_falls_back_to_text_blocks(self):
        result = {"content": [{"type": "text", "text": "line one"}, {"type": "text", "text": "line two"}]}
        assert mcp_client.result_to_text(result) == "line one\nline two"

    def test_embedded_resource_text(self):
        result = {"content": [{"type": "resource", "resource": {"text": "payload"}}]}
        assert mcp_client.result_to_text(result) == "payload"

    def test_error_result_becomes_error_json(self):
        result = {"isError": True, "content": [{"type": "text", "text": "nope"}]}
        assert json.loads(mcp_client.result_to_text(result)) == {"error": "nope"}


class TestTopicNormalization:
    def test_bare_topic_gets_the_prefix(self):
        from app.routes.ai_chat import _metrics_topic_tool

        assert _metrics_topic_tool("cpu") == f"{METRICS_TOOL_PREFIX}cpu"

    def test_already_prefixed_topic_is_left_alone(self):
        from app.routes.ai_chat import _metrics_topic_tool

        full = f"{METRICS_TOOL_PREFIX}link_traffic"
        assert _metrics_topic_tool(full) == full

    def test_leading_underscores_are_stripped(self):
        from app.routes.ai_chat import _metrics_topic_tool

        assert _metrics_topic_tool("_cpu") == f"{METRICS_TOOL_PREFIX}cpu"

    def test_empty_topic(self):
        from app.routes.ai_chat import _metrics_topic_tool

        assert _metrics_topic_tool("  ") == ""


class TestHarnessWiring:
    """Generated harness configs must come from the registry, not hardcoded lists."""

    def test_opencode_mcp_block_covers_every_registered_server(self, tmp_path):
        from app.harness_config import _opencode_mcp

        with _no_custom_settings():
            cfg = _opencode_mcp(tmp_path)
        assert set(cfg) == {"fabric-metrics", "fabric-reports", "loomai-harness"}
        assert cfg["loomai-harness"]["command"] == ["python3", "-m", "app.harness_mcp_server"]
        for name in ("fabric-metrics", "fabric-reports"):
            assert cfg[name]["command"][0] == "bash"
            assert cfg[name]["enabled"] is True

    def test_opencode_writes_an_executable_wrapper_per_remote_server(self, tmp_path):
        from app.harness_config import _opencode_mcp

        with _no_custom_settings():
            _opencode_mcp(tmp_path)
        script = tmp_path / ".opencode" / "mcp-scripts" / "fabric-metrics.sh"
        assert script.exists()
        assert script.stat().st_mode & 0o111
        body = script.read_text()
        assert FABRIC_METRICS.url in body
        assert "Authorization: Bearer" in body

    def test_claude_mcp_servers_cover_every_registered_server(self, tmp_path):
        from app.harness_config import claude_mcp_servers

        with _no_custom_settings():
            servers = claude_mcp_servers(tmp_path)
        assert set(servers) == {"fabric-metrics", "fabric-reports", "loomai-harness"}
        assert servers["loomai-harness"]["command"] == "python3"
        assert servers["fabric-metrics"]["command"] == "bash"

    def test_claude_and_opencode_share_one_wrapper_script(self, tmp_path):
        """Token resolution must live in exactly one place."""
        from app.harness_config import claude_mcp_servers, _opencode_mcp

        with _no_custom_settings():
            claude = claude_mcp_servers(tmp_path)
            opencode = _opencode_mcp(tmp_path)
        assert claude["fabric-metrics"]["args"][0] == opencode["fabric-metrics"]["command"][1]

    def test_unauthenticated_server_gets_no_token_plumbing(self):
        from app.harness_config import _mcp_remote_script

        srv = MCPServer(
            name="open-mcp", label="Open", description="", url="https://open.test/mcp", auth="none"
        )
        script = _mcp_remote_script(srv)
        assert "Authorization" not in script
        assert "https://open.test/mcp" in script

    def test_wrapper_follows_the_canonical_token_resolution_order(self):
        """Must match settings_manager.get_token_path(), not a shortcut."""
        from app.harness_config import _mcp_remote_script

        script = _mcp_remote_script(FABRIC_METRICS)
        # Exact path first (honours the settings paths.token_file override)...
        assert "get_token_path" in script
        # ...then the documented fallback chain.
        assert "FABRIC_TOKEN_FILE" in script
        assert "$HOME/.tokens.json" in script
        assert "FABRIC_CONFIG_DIR" in script


class TestHarnessReconciliation:
    """A registry change must reach configs that already exist on disk."""

    def _generate(self, workspace, settings):
        from app.harness_config import (
            claude_mcp_servers,
            _merge_json_file,
            _opencode_mcp,
            prune_stale_mcp_entries,
        )

        with patch("app.settings_manager.load_settings", return_value=settings):
            _merge_json_file(workspace / ".mcp.json", {"mcpServers": claude_mcp_servers(workspace)})
            prune_stale_mcp_entries(workspace / ".mcp.json", "mcpServers")
            _merge_json_file(workspace / "opencode.json", {"mcp": _opencode_mcp(workspace)})
            prune_stale_mcp_entries(workspace / "opencode.json", "mcp")

    def _names(self, path, key):
        return set(json.loads(path.read_text())[key])

    def test_disabling_a_server_removes_its_config_entries(self, tmp_path):
        self._generate(tmp_path, {})
        assert "fabric-metrics" in self._names(tmp_path / ".mcp.json", "mcpServers")

        self._generate(tmp_path, {"ai": {"mcp_disabled": ["fabric-metrics"]}})
        assert "fabric-metrics" not in self._names(tmp_path / ".mcp.json", "mcpServers")
        assert "fabric-metrics" not in self._names(tmp_path / "opencode.json", "mcp")

    def test_disabling_a_server_removes_its_wrapper_script(self, tmp_path):
        self._generate(tmp_path, {})
        script = tmp_path / ".opencode" / "mcp-scripts" / "fabric-metrics.sh"
        assert script.is_file()

        self._generate(tmp_path, {"ai": {"mcp_disabled": ["fabric-metrics"]}})
        assert not script.exists()

    def test_pruning_never_touches_a_user_added_server(self, tmp_path):
        self._generate(tmp_path, {})
        cfg = json.loads((tmp_path / ".mcp.json").read_text())
        cfg["mcpServers"]["my-own"] = {"command": "whatever"}
        (tmp_path / ".mcp.json").write_text(json.dumps(cfg))

        self._generate(tmp_path, {"ai": {"mcp_disabled": ["fabric-metrics"]}})
        names = self._names(tmp_path / ".mcp.json", "mcpServers")
        assert "my-own" in names
        assert "fabric-metrics" not in names

    def test_url_override_regenerates_the_wrapper(self, tmp_path):
        from app.harness_config import _opencode_mcp

        with _no_custom_settings():
            _opencode_mcp(tmp_path)
        script = tmp_path / ".opencode" / "mcp-scripts" / "fabric-reports.sh"
        assert "reports.fabric-testbed.net" in script.read_text()

        override = {"ai": {"mcp_servers": [
            {"name": "fabric-reports", "url": "https://staging.test/mcp"}]}}
        with patch("app.settings_manager.load_settings", return_value=override):
            _opencode_mcp(tmp_path)
        body = script.read_text()
        assert "https://staging.test/mcp" in body
        assert "reports.fabric-testbed.net" not in body

    def test_a_user_edited_wrapper_is_preserved(self, tmp_path):
        from app.harness_config import _opencode_mcp

        with _no_custom_settings():
            _opencode_mcp(tmp_path)
        script = tmp_path / ".opencode" / "mcp-scripts" / "fabric-metrics.sh"
        script.write_text("#!/usr/bin/env bash\necho MINE\n")

        with _no_custom_settings():
            _opencode_mcp(tmp_path)
        assert "echo MINE" in script.read_text()

