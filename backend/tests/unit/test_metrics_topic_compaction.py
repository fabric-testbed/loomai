"""Topic-catalogue compaction for the metrics routing tools.

fabric_metrics_list_topics returns ~13k chars — more than twice any tier's
tool_result_max. Before compaction the tier truncator cut it mid-JSON and
appended "narrow the query", advice that means nothing for a listing call, so
the model re-issued the identical call until the repeated-tool guard killed the
turn. These pin the payload small enough that it never reaches the truncator.
"""

import json

import pytest

from app.chat_context import PROFILE_TIERS
from app.routes.ai_chat import _compact_metrics_topics


class _FakeServer:
    name = "fabric-metrics"
    auth = "fabric_token"


def _patch_mcp(monkeypatch, payload):
    """Stub the MCP boundary. _call_metrics_mcp imports these inside the
    function body, so patch the source modules, not ai_chat's namespace."""
    from app import mcp_client, mcp_registry

    async def _call_tool(*_a, **_kw):
        return {"content": [{"type": "text", "text": payload}]}

    monkeypatch.setattr(mcp_registry, "metrics_server", lambda: _FakeServer())
    monkeypatch.setattr(mcp_client, "call_tool", _call_tool)
    monkeypatch.setattr(mcp_client, "result_to_text",
                        lambda r: r["content"][0]["text"])

# Mirrors the real server's shape: long variant prose and dashboard metadata
# are the bulk, and none of it is needed to pick a (topic, variant) pair.
_VARIANT_PROSE = (
    "Per-link bit rate (selected in/out/total metric) for links touching the "
    "selected rack, as authored in the FABRIC Grafana dashboard."
)


def _fake_catalogue(topics=14, variants=6):
    return json.dumps({
        f"fabric_metrics_topic{i}": {
            "topic": f"topic{i}",
            "description": f"Description for topic {i} covering several metrics",
            "dashboard": f"Some Dashboard {i}",
            "domain": "switch" if i % 2 else "node",
            "variants": {f"variant_{v}": _VARIANT_PROSE for v in range(variants)},
            "params": ["rack", "inouttotal", "ruler", "xlimit"],
        }
        for i in range(topics)
    })


def _smallest_tool_capable_cap():
    """Tightest tool_result_max among tiers that actually get tools."""
    caps = [p["tool_result_max"] for p in PROFILE_TIERS.values()
            if p.get("max_tools", 0) > 0 and p["tool_result_max"] >= 1000]
    return min(caps)


class TestCompaction:
    def test_fits_under_the_tier_truncation_cap(self):
        """The regression that broke the tool loop in prod."""
        raw = _fake_catalogue()
        assert len(raw) > 6000, "fixture must reproduce an oversized catalogue"
        out = _compact_metrics_topics(raw)
        assert len(out) < _smallest_tool_capable_cap()

    def test_keeps_every_topic(self):
        out = json.loads(_compact_metrics_topics(_fake_catalogue()))
        assert len(out) == 14
        assert "topic0" in out and "topic13" in out

    def test_keeps_variant_names_so_routing_still_works(self):
        """Names are what query_infrastructure_metrics needs; prose is not."""
        out = json.loads(_compact_metrics_topics(_fake_catalogue()))
        entry = out["topic0"]
        assert entry["variants"] == [f"variant_{v}" for v in range(6)]
        assert entry["params"] == ["rack", "inouttotal", "ruler", "xlimit"]
        assert _VARIANT_PROSE not in json.dumps(out)

    def test_is_keyed_by_topic_not_tool_name(self):
        """query_infrastructure_metrics takes a topic; the prefix is added later."""
        out = json.loads(_compact_metrics_topics(_fake_catalogue()))
        assert not any(k.startswith("fabric_metrics_") for k in out)


class TestDegradesSafely:
    def test_non_json_passes_through(self):
        assert _compact_metrics_topics("not json at all") == "not json at all"

    def test_error_payload_passes_through(self):
        """An {"error": ...} body must reach the model intact, not be eaten."""
        err = json.dumps({"error": "Unknown tool: 'x'"})
        assert json.loads(_compact_metrics_topics(err)) == {"error": "Unknown tool: 'x'"}

    def test_unexpected_shape_passes_through(self):
        arr = json.dumps([1, 2, 3])
        assert _compact_metrics_topics(arr) == arr

    def test_entry_without_variants_survives(self):
        raw = json.dumps({"fabric_metrics_x": {"topic": "x", "description": "d"}})
        out = json.loads(_compact_metrics_topics(raw))
        assert out == {"x": {"description": "d"}}


class TestThroughTheRealCallPath:
    """Compaction must happen BEFORE _METRICS_RESULT_MAX truncation.

    Compacting the *returned* value is a no-op: _call_metrics_mcp has already
    cut the JSON mid-structure, so json.loads fails and the oversized fragment
    passes straight through. These drive the actual dispatch path, which the
    isolated compactor tests do not.
    """

    @pytest.mark.asyncio
    async def test_list_metric_topics_returns_parseable_json_under_the_cap(self, monkeypatch):
        from app.routes import ai_chat

        oversized = _fake_catalogue()
        assert len(oversized) > ai_chat._METRICS_RESULT_MAX

        _patch_mcp(monkeypatch, oversized)

        out = await ai_chat.execute_tool("list_metric_topics", {})

        assert "[truncated" not in out, "compaction ran too late — cap already fired"
        parsed = json.loads(out)          # would raise on a mid-JSON cut
        assert len(parsed) == 14
        assert len(out) < ai_chat._METRICS_RESULT_MAX

    @pytest.mark.asyncio
    async def test_the_topic_the_model_picks_is_actually_callable(self, monkeypatch):
        """A compacted key must round-trip back to a real server tool name."""
        from app.routes import ai_chat

        _patch_mcp(monkeypatch, _fake_catalogue())

        topics = json.loads(await ai_chat.execute_tool("list_metric_topics", {}))
        for topic in topics:
            assert ai_chat._metrics_topic_tool(topic) == f"fabric_metrics_{topic}"
