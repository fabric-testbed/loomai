"""Tests for app.chat_context — model profiles, token estimation, trimming."""

import pytest

from app.chat_context import (
    estimate_tokens,
    estimate_message_tokens,
    estimate_conversation_tokens,
    get_model_profile,
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

    def test_small_model(self):
        profile = get_model_profile("qwen3-coder-8b")
        assert profile["tier"] == "compact"
        assert profile["context_window"] == 8192

    def test_large_model(self):
        profile = get_model_profile("claude-3-5-sonnet-20241022")
        assert profile["tier"] == "large"

    def test_unknown_model_defaults_standard(self):
        profile = get_model_profile("some-random-model")
        assert profile["tier"] == "standard"

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
