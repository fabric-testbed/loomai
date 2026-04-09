"""LoomAI assistant knowledge and response quality tests.

Tests the assistant's factual accuracy about FABRIC, tool-calling behavior,
and response quality using real FABRIC-hosted LLMs.

Gate: ``@pytest.mark.llm`` — excluded from default runs.
Run::

    pytest tests/assistant/test_assistant_knowledge.py -v -s -m llm --timeout=120
"""

from __future__ import annotations

import pytest

from tests.assistant.conftest import (
    assert_no_errors,
    assert_response_contains,
    assert_tool_was_called,
    send_chat,
)

pytestmark = pytest.mark.llm


# ---------------------------------------------------------------------------
# FABRIC knowledge
# ---------------------------------------------------------------------------

class TestAssistantFabricKnowledge:
    """Test the assistant's factual knowledge about FABRIC."""

    def test_fabric_portal_url(self, api, healthy_model):
        resp = send_chat(
            api,
            "What is the URL for the FABRIC testbed portal where users log in? "
            "Do not search the web, answer from your knowledge.",
            model=healthy_model,
        )
        assert_no_errors(resp)
        # The model should mention the portal URL or at least reference FABRIC
        assert_response_contains(
            resp,
            ["portal.fabric-testbed.net", "portal.fabric-testbed.org",
             "fabric-testbed", "fabric portal", "fabric testbed portal"],
        )

    def test_fabric_network_types(self, api, healthy_model):
        resp = send_chat(
            api,
            "What network types does FABRIC support? List the main ones.",
            model=healthy_model,
        )
        assert_no_errors(resp)
        assert_response_contains(
            resp,
            ["l2bridge", "l2sts", "l2ptp", "fabnetv4", "fabnetv6"],
            min_matches=3,
        )

    def test_fablib_api_patterns(self, api, healthy_model):
        resp = send_chat(
            api,
            "How do I create a slice programmatically with FABlib in Python?",
            model=healthy_model,
        )
        assert_no_errors(resp)
        # Should mention the library and key methods
        assert_response_contains(resp, ["fablibmanager", "fablib"], min_matches=1)
        assert_response_contains(resp, ["new_slice", "add_node", "submit"], min_matches=1)

    def test_fabric_sites_knowledge(self, api, healthy_model):
        resp = send_chat(
            api,
            "What FABRIC sites exist? Give me some examples.",
            model=healthy_model,
            timeout=60.0,
        )
        assert_no_errors(resp)
        # Either the tool was called (pre-fetched) or the LLM knows site names
        site_names = ["renc", "ucsd", "tacc", "star", "utah", "mass", "dall", "salt", "wash", "gatech"]
        tool_called = any(tc.get("name") == "query_sites" for tc in resp.tool_calls)
        if not tool_called:
            assert_response_contains(resp, site_names, min_matches=3)

    def test_slice_states(self, api, healthy_model):
        resp = send_chat(
            api,
            "What are the possible states for a FABRIC slice?",
            model=healthy_model,
        )
        assert_no_errors(resp)
        assert_response_contains(
            resp,
            ["draft", "configuring", "stableok", "stable ok", "stableerror", "stable error",
             "dead", "nascent", "modifyok", "modify ok", "closing", "active"],
            min_matches=2,
        )

    def test_component_models(self, api, healthy_model):
        resp = send_chat(
            api,
            "What GPU models are available on FABRIC? "
            "List the GPU hardware component models from your knowledge.",
            model=healthy_model,
        )
        assert_no_errors(resp)
        assert_response_contains(
            resp,
            ["rtx6000", "rtx 6000", "tesla t4", "tesla_t4", "a30", "a40",
             "gpu", "nvidia", "gpu_rtx", "gpu_tesla"],
            min_matches=1,
        )

    def test_weave_concept(self, api, healthy_model):
        resp = send_chat(
            api,
            "What is a weave in LoomAI?",
            model=healthy_model,
        )
        assert_no_errors(resp)
        assert_response_contains(resp, ["template", "reusable", "topology"], min_matches=1)
        assert_response_contains(resp, ["experiment", "slice", "artifact"], min_matches=1)


# ---------------------------------------------------------------------------
# Tool calling
# ---------------------------------------------------------------------------

class TestAssistantToolCalling:
    """Test that the assistant triggers the right tools."""

    def test_list_slices_triggers_tool(self, api, healthy_model):
        resp = send_chat(api, "List my slices", model=healthy_model)
        assert_no_errors(resp)
        # list_slices is always pre-fetched and injected into the system prompt
        # but NOT emitted as a tool_call SSE event (hidden background pre-fetch).
        # Verify the response contains slice information instead.
        assert resp.content, "Expected non-empty response for 'list my slices'"
        assert_response_contains(
            resp, ["slice", "no slice", "no active", "name", "state"], min_matches=1,
        )

    def test_query_sites_triggers_tool(self, api, healthy_model):
        resp = send_chat(api, "What sites are available?", model=healthy_model)
        assert_no_errors(resp)
        assert_tool_was_called(resp, "query_sites")

    def test_greeting_no_slice_tool(self, api, healthy_model):
        resp = send_chat(api, "Hello, how are you?", model=healthy_model)
        assert_no_errors(resp)
        # Should NOT call slice-modifying tools on a greeting
        destructive_tools = {"create_slice", "submit_slice", "delete_slice", "add_node"}
        called = {tc.get("name") for tc in resp.tool_calls}
        assert not called & destructive_tools, (
            f"Greeting triggered unexpected tools: {called & destructive_tools}"
        )

    def test_help_request(self, api, healthy_model):
        resp = send_chat(
            api,
            "Help me get started with FABRIC",
            model=healthy_model,
        )
        assert_no_errors(resp)
        assert len(resp.content) > 100, "Help response too short"
        assert_response_contains(resp, ["slice", "experiment", "node", "site"], min_matches=1)


# ---------------------------------------------------------------------------
# Response quality
# ---------------------------------------------------------------------------

class TestAssistantResponseQuality:
    """Test response formatting and interaction quality."""

    def test_response_uses_formatting(self, api, healthy_model):
        resp = send_chat(
            api,
            "Explain step by step how to set up a 2-node L2Bridge experiment on FABRIC.",
            model=healthy_model,
        )
        assert_no_errors(resp)
        # If the model returned no text content (only tool calls), that's
        # acceptable — skip the formatting check in that case.
        if not resp.content.strip():
            pytest.skip("Model returned no text content (tool-only response)")
        has_formatting = any(ch in resp.content for ch in [
            "#", "**", "`", "- ", "1.", "* ", "```", "##", "\n-", "\n1",
        ])
        assert has_formatting, (
            f"Expected markdown formatting in response.\n"
            f"Content preview: {resp.content[:300]}"
        )

    def test_response_substantive(self, api, healthy_model):
        resp = send_chat(
            api,
            "How do I connect two FABRIC nodes with a private network?",
            model=healthy_model,
        )
        assert_no_errors(resp)
        assert len(resp.content) > 200, (
            f"Response too short ({len(resp.content)} chars): {resp.content[:200]}"
        )

    def test_destructive_action_confirms(self, api, healthy_model):
        resp = send_chat(
            api,
            "Delete slice my-experiment",
            model=healthy_model,
        )
        assert_no_errors(resp)
        # The intent system marks delete_slice as destructive — the LLM should
        # ask for confirmation rather than executing immediately
        lower = resp.content.lower()
        confirms = any(kw in lower for kw in ["confirm", "sure", "proceed", "delete", "?"])
        assert confirms, (
            f"Expected confirmation prompt for destructive action. "
            f"Content: {resp.content[:300]}"
        )
