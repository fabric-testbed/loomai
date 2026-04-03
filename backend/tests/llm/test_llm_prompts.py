"""End-to-end LLM tests — verify prompts, tool calling, and context management.

These tests make REAL API calls to FABRIC AI and NRP servers.
Only run with: pytest tests/llm/ -v --llm-tests

Requires API keys in environment or .env file:
  FABRIC_LLM_KEY — FABRIC AI server key
  NRP_LLM_KEY — NRP server key (optional)
"""

from __future__ import annotations

import json
import os
import time

import pytest
import httpx

# Load .env if present
_env_file = os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env")
if os.path.isfile(_env_file):
    with open(_env_file) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))

FABRIC_KEY = os.environ.get("FABRIC_LLM_KEY", "")
NRP_KEY = os.environ.get("NRP_LLM_KEY", "")
FABRIC_URL = "https://ai.fabric-testbed.net"
NRP_URL = "https://ellm.nrp-nautilus.io"

# Skip unless explicitly requested with --llm-tests or -m llm
pytestmark = [
    pytest.mark.llm,
    pytest.mark.skipif(not FABRIC_KEY, reason="FABRIC_LLM_KEY not set"),
]


def _chat(server_url: str, api_key: str, model: str, messages: list[dict],
           tools: list[dict] | None = None, max_tokens: int = 256,
           timeout: float = 60.0) -> dict:
    """Make a single chat completion call and return the response."""
    body: dict = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }
    if tools:
        body["tools"] = tools

    resp = httpx.post(
        f"{server_url}/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=body,
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def _get_healthy_model(server_url: str, api_key: str) -> str | None:
    """Find the first healthy model on a server."""
    try:
        resp = httpx.get(
            f"{server_url}/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        models = [m["id"] for m in resp.json().get("data", [])]
    except Exception:
        return None

    # Try preferred models first
    preferred = ["qwen3-coder-30b", "qwen3-coder", "gpt-oss-20b", "qwen3"]
    for pref in preferred:
        for m in models:
            if pref in m.lower():
                try:
                    _chat(server_url, api_key, m,
                           [{"role": "user", "content": "hi"}], max_tokens=1, timeout=15)
                    return m
                except Exception:
                    continue

    # Try any model
    for m in models:
        try:
            _chat(server_url, api_key, m,
                   [{"role": "user", "content": "hi"}], max_tokens=1, timeout=15)
            return m
        except Exception:
            continue
    return None


# Fixture: find a working model once per test session
@pytest.fixture(scope="session")
def healthy_model():
    model = _get_healthy_model(FABRIC_URL, FABRIC_KEY)
    if not model:
        pytest.skip("No healthy FABRIC model available")
    return model


# Simple tool schema for testing
SIMPLE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_slices",
            "description": "List all FABRIC slices.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_sites",
            "description": "Query FABRIC sites and resources.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


# ---------------------------------------------------------------------------
# Common request tests
# ---------------------------------------------------------------------------

class TestCommonRequests:
    """Verify the model can handle common user requests."""

    def test_list_slices_request(self, healthy_model):
        """'list my slices' should trigger list_slices tool call."""
        result = _chat(FABRIC_URL, FABRIC_KEY, healthy_model,
                        [{"role": "user", "content": "list my slices"}],
                        tools=SIMPLE_TOOLS)
        msg = result["choices"][0]["message"]
        # Should either call list_slices or mention slices in text
        tool_calls = msg.get("tool_calls", [])
        content = msg.get("content") or ""
        has_tool_call = any(tc["function"]["name"] == "list_slices" for tc in tool_calls)
        mentions_slices = "slice" in content.lower()
        assert has_tool_call or mentions_slices, f"Expected list_slices call or slice mention, got: {msg}"

    def test_find_sites_request(self, healthy_model):
        """'what sites are available' should trigger query_sites."""
        result = _chat(FABRIC_URL, FABRIC_KEY, healthy_model,
                        [{"role": "user", "content": "what sites are available?"}],
                        tools=SIMPLE_TOOLS)
        msg = result["choices"][0]["message"]
        tool_calls = msg.get("tool_calls", [])
        content = msg.get("content") or ""
        has_tool_call = any(tc["function"]["name"] == "query_sites" for tc in tool_calls)
        mentions_sites = "site" in content.lower()
        assert has_tool_call or mentions_sites

    def test_simple_greeting(self, healthy_model):
        """A simple greeting should produce a text response (no tool calls)."""
        result = _chat(FABRIC_URL, FABRIC_KEY, healthy_model,
                        [{"role": "user", "content": "hello"}])
        msg = result["choices"][0]["message"]
        assert msg.get("content"), "Expected text response to greeting"

    def test_help_request(self, healthy_model):
        """'help' should produce a helpful text response."""
        result = _chat(FABRIC_URL, FABRIC_KEY, healthy_model,
                        [{"role": "user", "content": "help me with FABRIC"}])
        msg = result["choices"][0]["message"]
        content = msg.get("content") or ""
        assert len(content) > 20, "Expected substantive help response"


# ---------------------------------------------------------------------------
# Context window tests
# ---------------------------------------------------------------------------

class TestContextWindow:
    """Verify context management works correctly."""

    def test_compact_prompt_fits(self, healthy_model):
        """Compact system prompt + user message should fit in any model."""
        from app.chat_context import get_system_prompt, estimate_tokens
        compact = get_system_prompt("compact")
        tokens = estimate_tokens(compact)
        # Compact should be under 4K tokens
        assert tokens < 4000, f"Compact prompt too large: {tokens} tokens"

    def test_standard_prompt_fits(self, healthy_model):
        """Standard prompt should fit in 32K+ models."""
        from app.chat_context import get_system_prompt, estimate_tokens
        standard = get_system_prompt("standard")
        tokens = estimate_tokens(standard)
        assert tokens < 10000, f"Standard prompt too large: {tokens} tokens"

    def test_model_profile_exists(self, healthy_model):
        """The healthy model should get a valid profile."""
        from app.chat_context import get_model_profile
        profile = get_model_profile(healthy_model)
        assert profile["context_window"] > 0
        assert profile["system_prompt"] in ("compact", "standard", "full")

    def test_conversation_with_tool_results(self, healthy_model):
        """Multi-turn conversation with tool results should not exceed context."""
        from app.chat_context import get_model_profile, get_system_prompt, trim_conversation, estimate_tokens

        profile = get_model_profile(healthy_model)
        prompt = get_system_prompt(profile["system_prompt"])
        sys_tokens = estimate_tokens(prompt)

        # Build a conversation with multiple tool results
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": "list my slices"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "1", "function": {"name": "list_slices", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "1", "content": '{"slices": [' + '"slice",' * 100 + ']}'},
            {"role": "assistant", "content": "Here are your slices."},
            {"role": "user", "content": "show me slice details"},
        ]

        result = trim_conversation(messages, sys_tokens, profile)
        assert len(result.messages) >= 3  # At least system + some recent


# ---------------------------------------------------------------------------
# Tool calling tests
# ---------------------------------------------------------------------------

class TestToolCalling:
    """Verify the model can make function calls."""

    def test_tool_call_format(self, healthy_model):
        """Model should return properly formatted tool calls."""
        result = _chat(FABRIC_URL, FABRIC_KEY, healthy_model,
                        [{"role": "system", "content": "You are a FABRIC assistant. Use tools when asked."},
                         {"role": "user", "content": "list all slices"}],
                        tools=SIMPLE_TOOLS)
        msg = result["choices"][0]["message"]
        tool_calls = msg.get("tool_calls", [])
        if tool_calls:
            tc = tool_calls[0]
            assert "function" in tc
            assert "name" in tc["function"]
            assert tc["function"]["name"] in ("list_slices", "query_sites")


# ---------------------------------------------------------------------------
# Timeout and error tests
# ---------------------------------------------------------------------------

class TestTimeoutAndErrors:
    """Verify error handling."""

    def test_invalid_model_returns_error(self):
        """Requesting a nonexistent model should return an error."""
        with pytest.raises(httpx.HTTPStatusError):
            _chat(FABRIC_URL, FABRIC_KEY, "nonexistent-model-xyz",
                   [{"role": "user", "content": "hi"}], timeout=10)

    def test_empty_message_handled(self, healthy_model):
        """Empty message should not crash."""
        result = _chat(FABRIC_URL, FABRIC_KEY, healthy_model,
                        [{"role": "user", "content": ""}])
        # Should return something (even if it's an error in content)
        assert "choices" in result


# ---------------------------------------------------------------------------
# Round-trip tests
# ---------------------------------------------------------------------------

class TestLLMRoundTrip:
    """Basic round-trip tests with real LLM API."""

    def test_model_list_returns_models(self):
        """GET /v1/models should return at least one model."""
        resp = httpx.get(
            f"{FABRIC_URL}/v1/models",
            headers={"Authorization": f"Bearer {FABRIC_KEY}"},
            timeout=10,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data.get("data", [])) > 0

    def test_simple_completion_round_trip(self, healthy_model):
        """Send a simple message and verify we get a non-empty text response."""
        result = _chat(FABRIC_URL, FABRIC_KEY, healthy_model,
                       [{"role": "user", "content": "Say the word 'pong' and nothing else."}],
                       max_tokens=32)
        msg = result["choices"][0]["message"]
        content = msg.get("content") or ""
        assert len(content) > 0, "Expected non-empty response"

    def test_system_message_respected(self, healthy_model):
        """Verify the model follows a system message instruction."""
        result = _chat(FABRIC_URL, FABRIC_KEY, healthy_model, [
            {"role": "system", "content": "You must start every reply with the word BANANA."},
            {"role": "user", "content": "Hi there."},
        ], max_tokens=64)
        content = (result["choices"][0]["message"].get("content") or "").strip()
        assert content.upper().startswith("BANANA"), f"Expected BANANA prefix, got: {content[:40]}"

    def test_multi_turn_conversation(self, healthy_model):
        """Verify the model can track context across turns."""
        result = _chat(FABRIC_URL, FABRIC_KEY, healthy_model, [
            {"role": "user", "content": "My secret number is 42. Remember it."},
            {"role": "assistant", "content": "Got it, your secret number is 42."},
            {"role": "user", "content": "What is my secret number?"},
        ], max_tokens=64)
        content = (result["choices"][0]["message"].get("content") or "")
        assert "42" in content, f"Expected model to recall 42, got: {content[:60]}"
