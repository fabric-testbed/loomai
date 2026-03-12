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

    # TODO: Test full SSE streaming with mocked LLM backend
    # TODO: Test tool-calling loop with mocked tool execution
