"""Tests for AI chat REST endpoints."""

import json
from unittest.mock import patch, MagicMock, AsyncMock


class TestListAgents:
    def test_agents_returns_list(self, client):
        # Clear the agent cache so it re-scans
        from app.routes.ai_chat import _load_agents
        import app.routes.ai_chat as ai_chat_mod
        ai_chat_mod._agents_cache = None

        resp = client.get("/api/ai/chat/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_agents_list_has_expected_fields(self, client, storage_dir):
        # Create a mock agents directory with a test agent
        import app.routes.ai_chat as ai_chat_mod
        ai_chat_mod._agents_cache = None

        import os
        agents_dir = ai_chat_mod._AGENTS_DIR
        os.makedirs(agents_dir, exist_ok=True)
        agent_file = os.path.join(agents_dir, "test-agent.md")
        with open(agent_file, "w") as f:
            f.write("name: Test Agent\ndescription: A test agent\n---\nYou are a test agent.")

        try:
            resp = client.get("/api/ai/chat/agents")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list)
            agent_ids = [a["id"] for a in data]
            assert "test-agent" in agent_ids
            agent = next(a for a in data if a["id"] == "test-agent")
            assert agent["name"] == "Test Agent"
            assert agent["description"] == "A test agent"
        finally:
            os.remove(agent_file)
            ai_chat_mod._agents_cache = None


class TestChatStop:
    def test_stop_nonexistent_request(self, client):
        resp = client.post("/api/ai/chat/stop",
                           json={"request_id": ""})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "not_found"

    def test_stop_active_request(self, client):
        from app.routes.ai_chat import _cancelled_requests

        try:
            resp = client.post("/api/ai/chat/stop",
                               json={"request_id": "test-req-123"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "stopped"
            assert "test-req-123" in _cancelled_requests
        finally:
            _cancelled_requests.discard("test-req-123")


def _make_llm_response(content="Hello!", tool_calls=None, finish_reason="stop"):
    """Create a mock httpx Response for an LLM chat/completions call.

    Uses MagicMock (not AsyncMock) because httpx Response.json() is synchronous.
    """
    resp = MagicMock()
    resp.status_code = 200
    msg = {"content": content, "role": "assistant"}
    if tool_calls:
        msg["tool_calls"] = tool_calls
        msg["content"] = None
    resp.json.return_value = {"choices": [{"message": msg, "finish_reason": finish_reason}]}
    return resp


def _make_stream_ctx(lines):
    """Create a mock async context manager for ai_client.stream().

    *lines* is a list of strings that will be yielded by aiter_lines().
    """
    async def mock_aiter_lines():
        for line in lines:
            yield line

    mock_stream_resp = MagicMock()
    mock_stream_resp.status_code = 200
    mock_stream_resp.aiter_lines = mock_aiter_lines

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_stream_resp)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx


class TestChatStream:
    """Tests for POST /api/ai/chat/stream.

    This endpoint returns an SSE stream. We test error paths and basic
    behavior; full multi-turn tool-calling tests are out of scope.
    """

    def test_stream_returns_error_when_no_api_key(self, client):
        with patch("app.routes.ai_chat._get_ai_api_key", return_value=""):
            resp = client.post("/api/ai/chat/stream",
                               json={"messages": [{"role": "user", "content": "hi"}]})
        assert resp.status_code == 200
        # SSE stream — read the first event
        lines = resp.text.strip().split("\n")
        data_lines = [l for l in lines if l.startswith("data: ")]
        assert len(data_lines) >= 1
        payload = json.loads(data_lines[0].replace("data: ", ""))
        assert "error" in payload
        assert "API key" in payload["error"]

    def test_stream_returns_sse_content_type(self, client):
        """POST /api/ai/chat/stream should return text/event-stream content type."""
        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, return_value='{"slices": []}'), \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock(return_value=_make_llm_response("Hello!"))
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"choices": [{"delta": {"content": "Hello!"}}]}',
                "data: [DONE]",
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{"role": "user", "content": "hello"}],
                "model": "test-model",
            })
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")

    def test_stream_emits_content_events(self, client):
        """POST /api/ai/chat/stream should emit SSE data events with content."""
        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, return_value='{"slices": []}'), \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock(return_value=_make_llm_response("Hi there!"))
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"choices": [{"delta": {"content": "Hi "}}]}',
                'data: {"choices": [{"delta": {"content": "there!"}}]}',
                "data: [DONE]",
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{"role": "user", "content": "hello"}],
                "model": "test-model",
            })
            assert resp.status_code == 200

            # Parse SSE events from response body
            lines = resp.text.strip().split("\n")
            data_lines = [l for l in lines if l.startswith("data: ") and l != "data: [DONE]"]
            # Should have at least one data event
            assert len(data_lines) >= 1

            # Check that we got content or usage events
            found_content = False
            found_usage = False
            for dl in data_lines:
                try:
                    payload = json.loads(dl[6:])  # strip "data: "
                    if "content" in payload:
                        found_content = True
                    if "usage" in payload:
                        found_usage = True
                except json.JSONDecodeError:
                    continue
            assert found_content or found_usage

    def test_stream_with_tool_call(self, client):
        """POST /api/ai/chat/stream should handle tool call round-trips."""
        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock) as mock_exec, \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_exec.return_value = '{"sites": [{"name": "RENC"}]}'

            # First call — tool call response; second call — text response
            tool_call_resp = _make_llm_response(
                tool_calls=[{
                    "id": "call_1",
                    "function": {"name": "query_sites", "arguments": "{}"},
                }],
                finish_reason="tool_calls",
            )
            text_resp = _make_llm_response("RENC is available.")
            mock_client.post = AsyncMock(side_effect=[tool_call_resp, text_resp])

            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"choices": [{"delta": {"content": "RENC is available."}}]}',
                "data: [DONE]",
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{"role": "user", "content": "what sites are available?"}],
                "model": "test-model",
            })
            assert resp.status_code == 200

            # Should have tool_call and/or tool_result and/or content events
            all_text = resp.text
            assert "tool_call" in all_text or "tool_result" in all_text or "content" in all_text

    def test_stream_empty_messages(self, client):
        """POST /api/ai/chat/stream with empty messages should return 200 SSE."""
        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, return_value='{"slices": []}'), \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock(return_value=_make_llm_response(""))
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                "data: [DONE]",
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [],
                "model": "test-model",
            })
            # Should return 200 (SSE stream, possibly with empty content)
            assert resp.status_code == 200
