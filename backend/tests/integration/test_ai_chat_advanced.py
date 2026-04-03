"""Advanced tests for AI chat — model endpoints, tool dispatch, intent, context."""

import json
from unittest.mock import patch, MagicMock, AsyncMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_urllib_response(data: dict, status: int = 200):
    """Create a mock urllib response context manager."""
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.read.return_value = json.dumps(data).encode()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


# ---------------------------------------------------------------------------
# GET /api/ai/models
# ---------------------------------------------------------------------------

class TestListModels:
    def test_models_returns_dict(self, client):
        """GET /api/ai/models should return a dict with model info."""
        # Mock the _fetch_all_models function (called by call manager)
        mock_result = {
            "fabric_models": [
                {"id": "qwen3-coder-30b", "name": "qwen3-coder-30b", "healthy": True,
                 "context_length": 32768, "tier": "standard", "supports_tools": True},
            ],
            "nrp_models": [],
            "custom": {},
            "default": "qwen3-coder-30b",
            "fabric_error": "",
            "nrp_error": "",
        }

        with patch("app.routes.ai_terminal._fetch_all_models", return_value=mock_result):
            resp = client.get("/api/ai/models")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert "fabric_models" in data

    def test_models_with_fetch_error(self, client):
        """GET /api/ai/models should still return when model fetch fails."""
        mock_result = {
            "fabric_models": [],
            "nrp_models": [],
            "custom": {},
            "default": "",
            "fabric_error": "Connection refused",
            "nrp_error": "",
        }
        with patch("app.routes.ai_terminal._fetch_all_models", return_value=mock_result):
            resp = client.get("/api/ai/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["fabric_models"] == []


# ---------------------------------------------------------------------------
# GET /api/ai/models/default
# ---------------------------------------------------------------------------

class TestGetDefaultModel:
    def test_returns_persisted_default(self, client):
        """GET /api/ai/models/default should return the persisted default model."""
        with patch("app.settings_manager.get_default_model", return_value="qwen3-coder-30b"), \
             patch("app.settings_manager.get_default_model_source", return_value="fabric"):
            resp = client.get("/api/ai/models/default")
        assert resp.status_code == 200
        data = resp.json()
        assert data["default"] == "qwen3-coder-30b"
        assert data["source"] == "fabric"

    def test_returns_empty_when_no_default(self, client):
        """GET /api/ai/models/default should discover when no default is persisted."""
        mock_result = {"default": "some-model", "source": "fabric"}
        with patch("app.settings_manager.get_default_model", return_value=""), \
             patch("app.settings_manager.set_default_model"), \
             patch("app.routes.ai_terminal._find_first_healthy_model",
                    return_value=mock_result):
            resp = client.get("/api/ai/models/default")
        assert resp.status_code == 200
        data = resp.json()
        assert "default" in data


# ---------------------------------------------------------------------------
# PUT /api/ai/models/default
# ---------------------------------------------------------------------------

class TestSetDefaultModel:
    def test_set_default_success(self, client):
        """PUT /api/ai/models/default should set and return the model."""
        with patch("app.settings_manager.set_default_model"):
            resp = client.put("/api/ai/models/default",
                              json={"model": "qwen3-coder-30b", "source": "fabric"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["default"] == "qwen3-coder-30b"
        assert data["source"] == "fabric"

    def test_set_default_missing_model(self, client):
        """PUT /api/ai/models/default with empty model should return 400."""
        resp = client.put("/api/ai/models/default", json={"model": ""})
        assert resp.status_code == 400

    def test_set_default_auto_detects_nrp_source(self, client):
        """PUT /api/ai/models/default with nrp: prefix should auto-detect source."""
        with patch("app.settings_manager.set_default_model"):
            resp = client.put("/api/ai/models/default",
                              json={"model": "nrp:llama3-70b"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "nrp"
        assert data["default"] == "llama3-70b"


# ---------------------------------------------------------------------------
# POST /api/ai/models/test
# ---------------------------------------------------------------------------

class TestModelHealthCheck:
    def test_health_check_healthy(self, client):
        """POST /api/ai/models/test should return healthy when model responds."""
        mock_resp = _mock_urllib_response(
            {"choices": [{"message": {"content": "hi"}}]}, status=200
        )
        with patch("app.routes.ai_terminal._get_ai_api_key", return_value="fake-key"), \
             patch("urllib.request.urlopen", return_value=mock_resp):
            resp = client.post("/api/ai/models/test",
                               json={"model": "test-model", "source": "fabric"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["healthy"] is True
        assert data["model"] == "test-model"
        assert "latency_ms" in data

    def test_health_check_no_api_key(self, client):
        """POST /api/ai/models/test should return unhealthy without API key."""
        with patch("app.routes.ai_terminal._get_ai_api_key", return_value=""):
            resp = client.post("/api/ai/models/test",
                               json={"model": "test-model", "source": "fabric"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["healthy"] is False
        assert "API key" in data["error"]

    def test_health_check_missing_model(self, client):
        """POST /api/ai/models/test with empty model should return 400."""
        resp = client.post("/api/ai/models/test", json={"model": ""})
        assert resp.status_code == 400

    def test_health_check_connection_error(self, client):
        """POST /api/ai/models/test should handle connection errors."""
        with patch("app.routes.ai_terminal._get_ai_api_key", return_value="fake-key"), \
             patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
            resp = client.post("/api/ai/models/test",
                               json={"model": "bad-model", "source": "fabric"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["healthy"] is False
        assert "Connection refused" in data["error"]

    def test_health_check_nrp_source(self, client):
        """POST /api/ai/models/test with NRP source should use NRP server."""
        mock_resp = _mock_urllib_response(
            {"choices": [{"message": {"content": "hi"}}]}, status=200
        )
        with patch("app.routes.ai_terminal._get_nrp_api_key", return_value="nrp-key"), \
             patch("app.routes.ai_terminal._nrp_server_url", return_value="https://nrp.example.com"), \
             patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            resp = client.post("/api/ai/models/test",
                               json={"model": "nrp-model", "source": "nrp"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "nrp"


# ---------------------------------------------------------------------------
# POST /api/ai/models/refresh
# ---------------------------------------------------------------------------

class TestModelRefresh:
    def test_refresh_returns_model_data(self, client):
        """POST /api/ai/models/refresh should invalidate cache and return fresh data."""
        mock_result = {
            "fabric_models": [],
            "nrp_models": [],
            "custom": {},
            "default": "",
            "fabric_error": "",
            "nrp_error": "",
        }
        with patch("app.routes.ai_terminal._fetch_all_models", return_value=mock_result):
            resp = client.post("/api/ai/models/refresh")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert "fabric_models" in data


# ---------------------------------------------------------------------------
# Tool execution dispatch (unit-style tests via the execute_tool function)
# ---------------------------------------------------------------------------

class TestExecuteTool:
    """Test the execute_tool() function dispatches to correct handlers.

    The function uses inline imports (from app.routes.slices import list_slices)
    so we patch at the source module level.
    """

    @pytest.mark.asyncio
    async def test_execute_list_slices(self, storage_dir):
        """execute_tool('list_slices') should call list_slices and return JSON."""
        from app.routes.ai_chat import execute_tool

        mock_slices = [{"name": "test-slice", "state": "StableOK", "nodes": [], "lease_end": None}]
        with patch("app.routes.slices.list_slices", new_callable=AsyncMock, return_value=mock_slices):
            result = await execute_tool("list_slices", {})
        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert parsed[0]["name"] == "test-slice"

    @pytest.mark.asyncio
    async def test_execute_query_sites(self, storage_dir):
        """execute_tool('query_sites') should return site summaries."""
        from app.routes.ai_chat import execute_tool

        mock_sites = [
            {"name": "RENC", "cores_available": 100, "ram_available": 500,
             "disk_available": 1000, "state": "Active", "gpu_available": 2},
        ]
        with patch("app.routes.resources.list_sites", new_callable=AsyncMock, return_value=mock_sites):
            result = await execute_tool("query_sites", {})
        parsed = json.loads(result)
        assert parsed[0]["name"] == "RENC"
        assert parsed[0]["gpus"] == 2

    @pytest.mark.asyncio
    async def test_execute_write_file(self, storage_dir):
        """execute_tool('write_file') should create files in user storage."""
        from app.routes.ai_chat import execute_tool
        import os

        with patch("app.user_context.get_user_storage", return_value=str(storage_dir)):
            result = await execute_tool("write_file", {
                "path": "test_dir/hello.txt",
                "content": "Hello, world!",
            })
        parsed = json.loads(result)
        assert parsed["status"] == "written"
        assert os.path.isfile(os.path.join(str(storage_dir), "test_dir", "hello.txt"))

    @pytest.mark.asyncio
    async def test_execute_read_file(self, storage_dir):
        """execute_tool('read_file') should read files from user storage."""
        from app.routes.ai_chat import execute_tool
        import os

        # Create a test file
        test_file = os.path.join(str(storage_dir), "readme.txt")
        with open(test_file, "w") as f:
            f.write("test content")

        with patch("app.user_context.get_user_storage", return_value=str(storage_dir)):
            result = await execute_tool("read_file", {"path": "readme.txt"})
        parsed = json.loads(result)
        assert parsed["content"] == "test content"

    @pytest.mark.asyncio
    async def test_execute_list_directory(self, storage_dir):
        """execute_tool('list_directory') should list directory contents."""
        from app.routes.ai_chat import execute_tool

        with patch("app.user_context.get_user_storage", return_value=str(storage_dir)):
            result = await execute_tool("list_directory", {"path": ""})
        parsed = json.loads(result)
        assert "entries" in parsed
        names = [e["name"] for e in parsed["entries"]]
        assert "my_artifacts" in names
        assert "my_slices" in names

    @pytest.mark.asyncio
    async def test_execute_write_file_path_traversal_blocked(self, storage_dir):
        """execute_tool('write_file') should block path traversal."""
        from app.routes.ai_chat import execute_tool

        with patch("app.user_context.get_user_storage", return_value=str(storage_dir)):
            result = await execute_tool("write_file", {
                "path": "../../etc/passwd",
                "content": "malicious",
            })
        parsed = json.loads(result)
        assert "error" in parsed

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self, storage_dir):
        """execute_tool with unknown name should return error."""
        from app.routes.ai_chat import execute_tool
        result = await execute_tool("nonexistent_tool", {})
        parsed = json.loads(result)
        assert "error" in parsed or "Unknown" in result

    @pytest.mark.asyncio
    async def test_execute_create_directory(self, storage_dir):
        """execute_tool('create_directory') should create a directory."""
        from app.routes.ai_chat import execute_tool
        import os

        with patch("app.user_context.get_user_storage", return_value=str(storage_dir)):
            result = await execute_tool("create_directory", {"path": "new_dir/sub"})
        parsed = json.loads(result)
        assert parsed["status"] == "created"
        assert os.path.isdir(os.path.join(str(storage_dir), "new_dir", "sub"))

    @pytest.mark.asyncio
    async def test_execute_delete_path(self, storage_dir):
        """execute_tool('delete_path') should delete a file."""
        from app.routes.ai_chat import execute_tool
        import os

        # Create a file
        test_file = os.path.join(str(storage_dir), "to_delete.txt")
        with open(test_file, "w") as f:
            f.write("delete me")

        with patch("app.user_context.get_user_storage", return_value=str(storage_dir)):
            result = await execute_tool("delete_path", {"path": "to_delete.txt"})
        parsed = json.loads(result)
        assert parsed["status"] == "deleted"
        assert not os.path.exists(test_file)


# ---------------------------------------------------------------------------
# Intent detection — broader coverage than unit tests
# ---------------------------------------------------------------------------

class TestIntentDetectionIntegration:
    """Test intent detection patterns via the module function."""

    def test_refresh_slice_intent(self):
        from app.chat_intent import detect_intent
        tool, args, conf = detect_intent("refresh slice my-exp")
        assert tool == "refresh_slice"
        assert args["slice_name"] == "my-exp"

    def test_show_slice_with_quotes(self):
        from app.chat_intent import detect_intent
        tool, args, conf = detect_intent("show slice my-experiment")
        assert tool == "get_slice"

    def test_renew_slice_intent(self):
        from app.chat_intent import detect_intent
        tool, args, conf = detect_intent("renew slice my-exp")
        assert tool == "renew_slice"
        assert args["slice_name"] == "my-exp"
        assert args["days"] == 7

    def test_long_complex_message_low_conf(self):
        from app.chat_intent import detect_intent
        tool, args, conf = detect_intent(
            "I'm trying to understand the networking setup and need help "
            "configuring VLANs for my experiment across multiple sites"
        )
        assert conf == "low"

    def test_chameleon_leases_intent(self):
        from app.chat_intent import detect_intent
        tool, args, conf = detect_intent("list chameleon leases")
        assert tool == "list_chameleon_leases"
        assert conf == "high"

    def test_create_weave_intent(self):
        from app.chat_intent import detect_intent
        tool, args, conf = detect_intent("create a weave called my-test")
        assert tool == "create_weave"
        assert args["name"] == "my-test"

    def test_is_destructive(self):
        from app.chat_intent import is_destructive
        assert is_destructive("delete_slice")
        assert is_destructive("submit_slice")
        assert not is_destructive("list_slices")
        assert not is_destructive("query_sites")

    def test_record_intent_result(self):
        from app.chat_intent import record_intent_result, get_intent_stats
        record_intent_result("test-model", "list_slices", True)
        stats = get_intent_stats()
        assert "test-model" in stats
        assert stats["test-model"]["list_slices"]["success"] >= 1


# ---------------------------------------------------------------------------
# Chat context management
# ---------------------------------------------------------------------------

class TestChatContextIntegration:
    """Test chat context tier detection and token budgets."""

    def test_compact_tier_profile(self):
        from app.chat_context import get_model_profile
        profile = get_model_profile("qwen3-coder-8b")
        assert profile["tier"] == "compact"
        assert profile["context_window"] <= 16384
        assert profile["max_tools"] <= 12

    def test_standard_tier_profile(self):
        from app.chat_context import get_model_profile
        profile = get_model_profile("qwen3-coder-30b")
        assert profile["tier"] == "standard"
        assert profile["context_window"] <= 65536
        assert profile["supports_tools"] is True

    def test_large_tier_profile(self):
        from app.chat_context import get_model_profile
        profile = get_model_profile("claude-3-5-sonnet-20241022")
        assert profile["tier"] == "large"
        assert profile["context_window"] >= 128000

    def test_token_budget_respects_tier(self):
        from app.chat_context import get_model_profile
        compact = get_model_profile("tiny-model", context_length=4096)
        standard = get_model_profile("medium-model", context_length=32768)
        assert compact["summarize_at"] < standard["summarize_at"]

    def test_filter_tool_schemas_respects_max(self):
        from app.chat_context import filter_tool_schemas
        schemas = [{"function": {"name": f"tool_{i}"}} for i in range(30)]
        filtered = filter_tool_schemas(schemas, max_tools=10)
        assert len(filtered) == 10

    def test_trim_conversation_keeps_system(self):
        from app.chat_context import trim_conversation, PROFILE_TIERS
        msgs = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "x" * 2000},
            {"role": "assistant", "content": "y" * 2000},
        ] * 20  # Large conversation
        profile = dict(PROFILE_TIERS["compact"])
        result = trim_conversation(msgs, system_tokens=500, profile=profile)
        assert result.messages[0]["role"] == "system"
