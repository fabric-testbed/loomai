"""Tests for app.chat_context — model profiles, token estimation, trimming."""

import pytest

from app.chat_context import (
    estimate_tokens,
    estimate_message_tokens,
    estimate_conversation_tokens,
    get_model_profile,
    get_system_prompt,
    filter_tool_schemas,
    trim_conversation,
    PROFILE_TIERS,
    CORE_TOOLS,
)


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens("") == 1  # minimum 1

    def test_short_string(self):
        # "hello" = 5 chars → ~1 token
        assert estimate_tokens("hello") >= 1

    def test_longer_string(self):
        text = "a" * 400  # 400 chars → ~100 tokens
        assert 90 <= estimate_tokens(text) <= 110

    def test_message_tokens(self):
        msg = {"role": "user", "content": "Hello, how are you?"}
        tokens = estimate_message_tokens(msg)
        assert tokens > 0

    def test_conversation_tokens(self):
        msgs = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
        ]
        tokens = estimate_conversation_tokens(msgs)
        assert tokens > 0


# ---------------------------------------------------------------------------
# Model profiles
# ---------------------------------------------------------------------------

class TestGetModelProfile:
    def test_known_model(self):
        profile = get_model_profile("qwen3-coder-30b")
        assert profile["tier"] == "standard"
        assert profile["temperature"] == 0.3
        assert profile["tool_result_max"] == 6000

    def test_small_model(self):
        profile = get_model_profile("qwen3-coder-8b")
        assert profile["tier"] == "compact"
        assert profile["context_window"] == 8192

    def test_large_model(self):
        profile = get_model_profile("claude-3-5-sonnet-20241022")
        assert profile["tier"] == "large"
        assert profile["tool_result_max"] == 6000

    def test_unknown_model_defaults_standard(self):
        profile = get_model_profile("some-random-model")
        assert profile["tier"] == "standard"

    def test_glm5_is_reasoning_model(self):
        profile = get_model_profile("nrp:glm-5", context_length=32768)
        assert profile["tier"] == "standard"
        assert profile["is_reasoning"] is True

    @pytest.mark.parametrize(
        ("model_name", "context_length", "expected_max_output"),
        [
            ("qwen3-coder-30b", 262144, 12288),
            ("gpt-oss-20b", 131072, 6144),
            ("gemma-4-27b", 262144, 6144),
        ],
    )
    def test_fabric_floor_models_use_standard_tier(self, model_name, context_length, expected_max_output):
        profile = get_model_profile(model_name, context_length=context_length)

        assert profile["tier"] == "standard"
        assert profile["context_window"] == context_length
        assert profile["system_prompt"] == "standard"
        assert profile["tool_result_max"] == 6000
        assert profile["max_output"] == expected_max_output

    def test_fabric_floor_reasoning_model_profile(self):
        profile = get_model_profile("nemotron-nano-30b", context_length=262144)

        assert profile["tier"] == "standard"
        assert profile["context_window"] == 262144
        assert profile["system_prompt"] == "standard"
        assert profile["tool_result_max"] == 6000
        assert profile["is_reasoning"] is True
        assert profile["max_output"] == 15360

    def test_fabric_context_defaults_cover_floor_models(self):
        from app.routes.ai_terminal import _FABRIC_CONTEXT_DEFAULTS

        assert _FABRIC_CONTEXT_DEFAULTS["gpt-oss-20b"] == 131072
        assert _FABRIC_CONTEXT_DEFAULTS["qwen3-coder-30b"] == 262144
        assert _FABRIC_CONTEXT_DEFAULTS["nemotron-nano-30b"] == 262144
        assert _FABRIC_CONTEXT_DEFAULTS["gemma-4-27b"] == 262144

    def test_context_length_override(self):
        profile = get_model_profile("unknown-model", context_length=4096)
        assert profile["tier"] == "compact"
        assert profile["context_window"] == 4096

    def test_large_context_length(self):
        profile = get_model_profile("unknown-model", context_length=200000)
        assert profile["tier"] == "large"

    def test_profile_has_required_keys(self):
        profile = get_model_profile("test")
        for key in ["context_window", "max_output", "system_prompt",
                     "tool_result_max", "summarize_at", "max_tools",
                     "temperature", "supports_tools"]:
            assert key in profile, f"Missing key: {key}"

    def test_standard_prompt_keeps_weave_and_notebook_guidance(self):
        from app import chat_context

        chat_context._prompt_cache.clear()
        prompt = get_system_prompt("standard")

        assert "## Quick Weave Creation" in prompt
        assert "Minimal `weave.json`" in prompt
        assert "## Data Analysis with Jupyter" in prompt

        import inspect
        source = inspect.getsource(chat_context._build_standard_prompt)
        assert '"weave.json"' not in source
        assert '"Creating a notebook from scratch"' not in source

        compact_source = inspect.getsource(chat_context._build_compact_prompt)
        assert "code_block_lines <= 20" in compact_source


# ---------------------------------------------------------------------------
# Tool filtering
# ---------------------------------------------------------------------------

class TestFilterToolSchemas:
    def _make_schemas(self, names):
        return [{"function": {"name": n}} for n in names]

    def test_no_filtering_when_under_limit(self):
        schemas = self._make_schemas(["a", "b", "c"])
        result = filter_tool_schemas(schemas, max_tools=10)
        assert len(result) == 3

    def test_filters_to_max(self):
        names = [f"tool_{i}" for i in range(20)]
        schemas = self._make_schemas(names)
        result = filter_tool_schemas(schemas, max_tools=10)
        assert len(result) == 10

    def test_core_tools_prioritized(self):
        names = ["list_slices", "obscure_tool_1", "get_slice", "obscure_tool_2", "create_slice"]
        schemas = self._make_schemas(names)
        result = filter_tool_schemas(schemas, max_tools=3)
        result_names = {s["function"]["name"] for s in result}
        assert "list_slices" in result_names
        assert "get_slice" in result_names
        assert "create_slice" in result_names

    def test_all_tools_returned_when_limit_is_high(self):
        schemas = self._make_schemas(list(CORE_TOOLS))
        result = filter_tool_schemas(schemas, max_tools=100)
        assert len(result) == len(CORE_TOOLS)


# ---------------------------------------------------------------------------
# Conversation trimming
# ---------------------------------------------------------------------------

class TestTrimConversation:
    def _make_conversation(self, n_messages, content_size=100):
        msgs = [{"role": "system", "content": "System prompt " + "x" * 200}]
        for i in range(n_messages):
            role = "user" if i % 2 == 0 else "assistant"
            msgs.append({"role": role, "content": f"Message {i} " + "y" * content_size})
        return msgs

    def test_short_conversation_unchanged(self):
        msgs = self._make_conversation(4, content_size=50)
        profile = dict(PROFILE_TIERS["standard"])
        result = trim_conversation(msgs, system_tokens=500, profile=profile)
        assert len(result.messages) == len(msgs)
        assert not result.was_trimmed

    def test_long_conversation_trimmed(self):
        # 100 messages with 1000 chars each → ~25K tokens, exceeds standard budget
        msgs = self._make_conversation(100, content_size=1000)
        profile = dict(PROFILE_TIERS["compact"])
        result = trim_conversation(msgs, system_tokens=2000, profile=profile)
        assert len(result.messages) < len(msgs)
        assert result.was_trimmed
        assert result.messages[0]["role"] == "system"

    def test_system_message_always_kept(self):
        msgs = self._make_conversation(50, content_size=500)
        profile = dict(PROFILE_TIERS["compact"])
        result = trim_conversation(msgs, system_tokens=2000, profile=profile)
        assert result.messages[0]["role"] == "system"

    def test_recent_messages_kept(self):
        msgs = self._make_conversation(20, content_size=500)
        profile = dict(PROFILE_TIERS["compact"])
        result = trim_conversation(msgs, system_tokens=2000, profile=profile)
        assert msgs[-1]["content"] in [m["content"] for m in result.messages]

    def test_tool_results_truncated(self):
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "tool", "content": "x" * 5000, "tool_call_id": "1"},
            {"role": "user", "content": "thanks"},
        ]
        profile = dict(PROFILE_TIERS["compact"])
        result = trim_conversation(msgs, system_tokens=500, profile=profile)
        assert len(result.messages) >= 2

    def test_near_full_flag(self):
        msgs = self._make_conversation(50, content_size=500)
        profile = dict(PROFILE_TIERS["compact"])
        result = trim_conversation(msgs, system_tokens=3000, profile=profile)
        # With 3K system tokens in 8K context, should be near full after trimming
        assert result.near_full or result.was_trimmed

    def test_negative_budget_preserves_latest_user_turn(self):
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "Which hosts have at least 64 GB RAM?"},
            {"role": "assistant", "content": None, "tool_calls": []},
            {"role": "tool", "content": '{"rows": []}', "tool_call_id": "1"},
        ]
        profile = dict(PROFILE_TIERS["standard"])
        profile["context_window"] = 32768
        profile["max_output"] = 32768
        result = trim_conversation(msgs, system_tokens=1000, profile=profile)

        assert result.was_trimmed
        assert any(
            m.get("role") == "user" and "64 GB RAM" in m.get("content", "")
            for m in result.messages
        )

    def test_state_preserving_compaction_keeps_state_and_recent_tool_exchange(self):
        msgs = [{"role": "system", "content": "sys\n\n## CURRENT SESSION STATE\nbench-a StableOK"}]
        for i in range(12):
            msgs.append({"role": "user", "content": f"old user turn {i}"})
            msgs.append({"role": "assistant", "content": f"old assistant turn {i}"})
        msgs.extend([
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "get_slice", "arguments": '{"slice_name":"bench-a"}'},
                }],
            },
            {
                "role": "tool",
                "tool_call_id": "call-1",
                "content": '{"name":"bench-a","state":"StableOK","nodes":[{"name":"vm1"},{"name":"vm2"}]}',
            },
            {"role": "user", "content": "Continue and verify ping now."},
        ])
        profile = dict(PROFILE_TIERS["standard"])
        profile.update({
            "context_compaction_enabled": True,
            "context_compaction_trigger_messages": 10,
            "context_compaction_trigger_tokens": 0,
            "context_compaction_keep_last_messages": 4,
            "context_compaction_preserve_last_tool_outputs": 1,
        })

        result = trim_conversation(msgs, system_tokens=50, profile=profile)

        assert result.was_compacted is True
        assert result.compacted_from_tokens > result.compacted_to_tokens
        assert result.messages[0]["role"] == "system"
        assert "CURRENT SESSION STATE" in result.messages[0]["content"]
        assert any(
            m.get("role") == "user" and "Compacted prior progress" in m.get("content", "")
            for m in result.messages
        )
        assert any(m.get("role") == "tool" and "StableOK" in m.get("content", "") for m in result.messages)
        assert any(
            m.get("role") == "assistant" and m.get("tool_calls")
            for m in result.messages
        )
        assert result.messages[-1]["content"] == "Continue and verify ping now."


# ---------------------------------------------------------------------------
# 30/50/20 budget: tool schemas count, prompt fitting, paired trimming
# ---------------------------------------------------------------------------

from app.chat_context import (  # noqa: E402
    estimate_tool_schema_tokens,
    system_prompt_budget,
    fit_system_parts,
    _recent_paired_messages,
)


class TestToolTokensInBudget:
    def _conv(self, n, size):
        msgs = [{"role": "system", "content": "sys"}]
        for i in range(n):
            msgs.append({"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i} " + "x" * size})
        return msgs

    def test_tool_schema_tokens_are_estimated(self):
        schemas = [{"type": "function", "function": {"name": f"t{i}", "parameters": {"x": "y" * 200}}} for i in range(20)]
        assert estimate_tool_schema_tokens(schemas) > 1000
        assert estimate_tool_schema_tokens([]) == 0
        assert estimate_tool_schema_tokens(None) == 0

    def test_tool_tokens_shrink_the_conversation_budget(self):
        profile = dict(PROFILE_TIERS["compact"])  # 8192 window, summarize_at 0.4 → 3276 threshold
        msgs = self._conv(6, 300)                  # ~500 tokens of conversation
        assert not trim_conversation(msgs, system_tokens=500, profile=profile).was_trimmed
        # The same conversation with 2000 tokens of tool schemas no longer fits.
        result = trim_conversation(msgs, system_tokens=500, profile=profile, tool_tokens=2000)
        assert result.was_trimmed and result.near_full

    def test_system_prompt_budget_is_30_percent_with_core_floor(self):
        assert system_prompt_budget({"context_window": 10000}) == 3000
        assert system_prompt_budget({"context_window": 10000}, core_tokens=1200) == 3000
        # A compact model's core prompt alone exceeds 30%; it is never cut below
        # it, and it gets headroom for the session-state block and markers.
        assert system_prompt_budget({"context_window": 8192}, core_tokens=3011) == 3411


class TestFitSystemParts:
    def test_truncates_largest_unprotected_part_first(self):
        core = "core prompt " * 50            # ~150 tokens, protected
        prefetch = "## Current Data\n" + "d" * 8000   # ~2000 tokens
        rag = "## Context\n" + "r" * 2000             # ~500 tokens
        state = "## CURRENT SESSION STATE\nbench-a StableOK"
        parts, truncated = fit_system_parts([core, prefetch, rag, state], max_tokens=1200, protected={0, 3})
        assert truncated == [1]
        assert parts[0] == core and parts[3] == state and parts[2] == rag
        assert "trimmed to fit" in parts[1]
        assert sum(estimate_tokens(p) for p in parts) <= 1200

    def test_protected_parts_only_as_last_resort(self):
        core = "c" * 4000
        state = "s" * 4000
        parts, truncated = fit_system_parts([core, state], max_tokens=500, protected={0, 1})
        assert truncated  # had to cut something
        assert sum(estimate_tokens(p) for p in parts) <= 520

    def test_nothing_to_do_when_it_fits(self):
        parts, truncated = fit_system_parts(["a", "b"], max_tokens=100)
        assert parts == ["a", "b"] and truncated == []


class TestPairedTrimming:
    def _tool_turn(self, i):
        return [
            {"role": "user", "content": f"q{i}"},
            {"role": "assistant", "content": None,
             "tool_calls": [{"id": f"c{i}", "type": "function", "function": {"name": "get_slice", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": f"c{i}", "name": "get_slice", "content": "r" * 300},
            {"role": "assistant", "content": f"a{i}"},
        ]

    def test_recent_window_keeps_tool_call_with_its_output(self):
        msgs = [{"role": "system", "content": "sys"}]
        for i in range(5):
            msgs += self._tool_turn(i)
        # Last 4 messages end with [assistant(tool_calls c4), tool c4, assistant a4]; make
        # the window start at the tool output so the pairing logic has to add the call.
        recent = _recent_paired_messages(msgs, keep_last=2)
        roles = [(m["role"], m.get("tool_call_id") or (m.get("tool_calls") or [{}])[0].get("id")) for m in recent]
        assert ("tool", "c4") in roles
        assert ("assistant", "c4") in roles      # the matching tool_calls message was pulled in
        assert recent == sorted(recent, key=lambda m: msgs.index(m))

    def test_legacy_trim_never_orphans_a_tool_message(self):
        msgs = [{"role": "system", "content": "sys"}]
        for i in range(30):
            msgs += self._tool_turn(i)
        profile = dict(PROFILE_TIERS["compact"])
        profile["context_compaction_enabled"] = False
        result = trim_conversation(msgs, system_tokens=500, profile=profile)
        assert result.was_trimmed
        kept = result.messages
        for idx, m in enumerate(kept):
            if m.get("role") == "tool":
                prior_ids = {c["id"] for p in kept[:idx] for c in (p.get("tool_calls") or [])}
                assert m["tool_call_id"] in prior_ids, "tool output without its tool_calls message"
        assert kept[-1]["content"] == "a29"
