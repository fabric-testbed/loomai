"""Advanced tests for AI chat — model endpoints, tool dispatch, intent, context."""

import json
from unittest.mock import patch, MagicMock, AsyncMock

import pytest
from fastapi.params import Body as FieldInfo


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

    def test_custom_provider_discovery_honors_responses_endpoint_style(self, storage_dir):
        """Custom provider discovery should use a configured Responses probe."""
        from app import settings_manager
        from app.routes.ai_terminal import _fetch_all_models

        settings = settings_manager.load_settings()
        settings.setdefault("ai", {})["custom_providers"] = [{
            "name": "Local",
            "base_url": "https://provider.example/",
            "api_key": "provider-key",
            "endpoint_style": "responses",
        }]
        settings_manager.save_settings(settings)

        mock_resp = _mock_urllib_response({
            "data": [{"id": "resp-model", "context_length": 65536}],
        })

        with patch("app.routes.ai_terminal._get_ai_api_key", return_value=""), \
             patch("app.routes.ai_terminal._get_nrp_api_key", return_value=""), \
             patch("app.routes.ai_terminal._fetch_fabric_model_info", return_value=[]), \
             patch("app.routes.ai_terminal._fetch_models", return_value=[]), \
             patch("app.routes.ai_terminal._fetch_nrp_models", return_value=[]), \
             patch("urllib.request.urlopen", return_value=mock_resp), \
             patch("app.routes.ai_terminal._try_responses_api", return_value=True) as responses_probe, \
             patch("app.routes.ai_terminal._try_chat_completions") as chat_probe:
            data = _fetch_all_models()

        assert data["custom"]["Local"] == [{
            "id": "resp-model",
            "name": "resp-model",
            "healthy": True,
            "model_type": "responses",
            "endpoint_style": "responses",
            "context_length": 65536,
            "tier": "large",
            "supports_tools": True,
        }]
        responses_probe.assert_called_once()
        assert responses_probe.call_args.args[0] == "https://provider.example"
        assert responses_probe.call_args.args[2] == "resp-model"
        chat_probe.assert_not_called()


# ---------------------------------------------------------------------------
# GET /api/ai/models/{model}/capabilities
# ---------------------------------------------------------------------------

class TestModelCapabilities:
    def test_capabilities_warn_for_unhealthy_non_chat_custom_model(self, client, storage_dir):
        """Capability payloads should expose persisted health/tool warnings."""
        from app import settings_manager

        settings = settings_manager.load_settings()
        settings.setdefault("ai", {})["custom_providers"] = [{
            "name": "Local",
            "base_url": "https://provider.example",
            "api_key": "provider-key",
            "endpoint_style": "non-chat",
        }]
        settings["ai"]["discovered_models"] = {
            "fabric": [],
            "nrp": [],
            "custom": {
                "Local": [{
                    "id": "embed-model",
                    "name": "embed-model",
                    "healthy": False,
                    "model_type": "non-chat",
                    "endpoint_style": "non-chat",
                    "context_length": 8192,
                    "tier": "compact",
                    "supports_tools": False,
                }],
            },
        }
        settings_manager.save_settings(settings)

        resp = client.get("/api/ai/models/embed-model/capabilities?source=custom:Local")

        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "custom:Local"
        assert data["found"] is True
        assert data["healthy"] is False
        assert data["model_type"] == "non-chat"
        assert data["endpoint_style"] == "non-chat"
        assert data["supports_tools"] is False
        assert any("health check" in warning for warning in data["warnings"])
        assert any("does not support chat" in warning for warning in data["warnings"])


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

    def test_operational_tools_are_exposed_to_standard_filter(self):
        """Operational wrappers should be present after standard-tier filtering."""
        from app.chat_context import filter_tool_schemas
        from app.routes.ai_chat import TOOL_SCHEMAS

        expected = {
            "configure_networking",
            "list_recipes",
            "execute_recipe",
            "clone_slice",
            "create_tunnel",
            "run_python_script",
            "run_jupyter_notebook",
            "download_file_bulk",
        }
        all_names = {schema["function"]["name"] for schema in TOOL_SCHEMAS}
        assert expected <= all_names

        filtered_names = {
            schema["function"]["name"]
            for schema in filter_tool_schemas(TOOL_SCHEMAS, 46)
        }
        assert expected <= filtered_names

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
        """execute_tool('query_sites') should derive legacy GPU counts from components."""
        from app.routes.ai_chat import execute_tool

        mock_sites = [
            {"name": "RENC", "cores_available": 100, "ram_available": 500,
             "disk_available": 1000, "state": "Active",
             "components": {
                 "GPU_A30": {"available": 2},
                 "GPU_RTX6000": {"available": 0},
                 "NIC_Basic": {"available": 4},
             }},
        ]
        with patch("app.routes.resources.list_sites", new_callable=AsyncMock, return_value=mock_sites), \
             patch("app.settings_manager.is_compact_fabric_resource_tools_enabled", return_value=False):
            result = await execute_tool("query_sites", {})
        parsed = json.loads(result)
        assert parsed[0]["name"] == "RENC"
        assert parsed[0]["gpus"] == 2
        assert parsed[0]["gpu_components"] == {"GPU_A30": 2}
        assert parsed[0]["notable_components"] == {"GPU_A30": 2, "NIC_Basic": 4}

    @pytest.mark.asyncio
    async def test_execute_get_site_hosts_derives_gpu_counts(self, storage_dir):
        """execute_tool('get_site_hosts') should preserve host components and add GPU totals."""
        from app.routes.ai_chat import execute_tool

        mock_hosts = [
            {"name": "renc-w1", "cores_available": 32, "ram_available": 128,
             "disk_available": 500,
             "components": {
                 "GPU_A40": {"available": 1},
                 "GPU_RTX6000": {"available": 2},
             }},
            {"name": "renc-w2", "cores_available": 32, "ram_available": 128,
             "disk_available": 500, "components": {}},
        ]
        with patch("app.routes.resources.list_site_hosts", new_callable=AsyncMock, return_value=mock_hosts), \
             patch("app.settings_manager.is_compact_fabric_resource_tools_enabled", return_value=False):
            result = await execute_tool("get_site_hosts", {"site_name": "RENC"})
        parsed = json.loads(result)
        assert parsed[0]["name"] == "renc-w1"
        assert parsed[0]["gpus"] == 3
        assert parsed[0]["gpu_components"] == {"GPU_A40": 1, "GPU_RTX6000": 2}
        assert parsed[0]["components"]["GPU_A40"]["available"] == 1
        assert parsed[1]["gpus"] == 0

    @pytest.mark.asyncio
    async def test_execute_get_site_hosts_compact_derives_gpu_counts(self, storage_dir):
        """Compact get_site_hosts should expose GPU totals and component names."""
        from app.routes.ai_chat import execute_tool

        mock_hosts = [
            {"name": "renc-w1", "cores_available": 32, "ram_available": 128,
             "disk_available": 500,
             "components": {
                 "GPU_A40": {"available": 1},
                 "NIC_Basic": {"available": 2},
             }},
            {"name": "renc-w2", "cores_available": 32, "ram_available": 128,
             "disk_available": 500, "components": {}},
        ]
        with patch("app.routes.resources.list_site_hosts", new_callable=AsyncMock, return_value=mock_hosts), \
             patch("app.settings_manager.is_compact_fabric_resource_tools_enabled", return_value=True):
            result = await execute_tool("get_site_hosts", {"site_name": "RENC"})
        parsed = json.loads(result)
        assert parsed["summary"]["gpu_host_count"] == 1
        assert parsed["summary"]["gpu_total_available"] == 1
        assert parsed["rows"][0]["host"] == "renc-w1"
        assert parsed["rows"][0]["gpus"] == 1
        assert parsed["rows"][0]["gpu_components"] == {"GPU_A40": 1}
        assert parsed["rows"][0]["notable_components"] == {"GPU_A40": 1, "NIC_Basic": 2}
        assert parsed["rows"][1]["gpus"] == 0

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
    async def test_execute_submit_slice_passes_wait_for_stableok_flag(self, storage_dir):
        """submit_slice wait_for_stableok should reach the backend request model."""
        from app.routes.ai_chat import execute_tool

        captured = {}

        async def fake_submit(slice_name, body):
            captured["slice_name"] = slice_name
            captured["body"] = body
            return {"state": "StableOK"}

        with patch("app.routes.slices.submit_slice", new_callable=AsyncMock, side_effect=fake_submit):
            result = await execute_tool("submit_slice", {
                "slice_name": "bench-wait",
                "lease_hours": 6,
                "wait_for_stableok": True,
            })

        parsed = json.loads(result)
        assert captured["slice_name"] == "bench-wait"
        assert captured["body"].lease_hours == 6
        assert captured["body"].wait is True
        assert captured["body"].wait_for_stableok is True
        assert parsed["status"] == "submitted"
        assert parsed["state"] == "StableOK"
        assert parsed["name"] == "bench-wait"
        assert parsed["lease_hours"] == 6
        assert parsed["wait"] is True
        assert parsed["wait_for_stableok"] is True

    @pytest.mark.asyncio
    async def test_execute_submit_slice_background_returns_pollable_job(self, storage_dir):
        """submit_slice(background=true) should return a job id and get_job_status should poll it."""
        from app.assistant_jobs import _clear_jobs_for_tests
        from app.routes.ai_chat import execute_tool

        await _clear_jobs_for_tests()
        captured = {}

        async def fake_submit(slice_name, body):
            captured["slice_name"] = slice_name
            captured["body"] = body
            return {"name": slice_name, "state": "StableOK"}

        with patch("app.routes.slices.submit_slice", new_callable=AsyncMock, side_effect=fake_submit):
            started = await execute_tool("submit_slice", {
                "slice_name": "bench-bg",
                "lease_hours": 6,
                "wait_for_stableok": True,
                "background": True,
            })

            parsed_started = json.loads(started)
            assert parsed_started["status"] == "queued"
            assert parsed_started["job_id"].startswith("job-")
            assert parsed_started["background"] is True
            assert parsed_started["ready"] is False

            status = await execute_tool("get_job_status", {
                "job_id": parsed_started["job_id"],
                "wait_seconds": 1,
                "poll_interval": 0.01,
            })

        parsed_status = json.loads(status)
        await _clear_jobs_for_tests()
        assert captured["slice_name"] == "bench-bg"
        assert captured["body"].lease_hours == 6
        assert captured["body"].wait is True
        assert captured["body"].wait_for_stableok is True
        assert captured["body"].background is False
        assert parsed_status["status"] == "ready"
        assert parsed_status["ready"] is True
        assert parsed_status["done"] is True
        assert parsed_status["slice_name"] == "bench-bg"
        assert parsed_status["result"]["state"] == "StableOK"

    def test_ai_http_client_timeout_supports_long_submit_waits(self):
        """Shared AI HTTP client should allow long-running assistant streams."""
        from app.http_pool import ai_client

        assert ai_client.timeout.read == 1800.0
        assert ai_client.timeout.connect == 10.0

    @pytest.mark.asyncio
    async def test_execute_clone_slice_dispatches_to_route(self, storage_dir):
        """clone_slice tool should call the existing slice clone endpoint."""
        from app.routes.ai_chat import execute_tool

        async def fake_clone(slice_name, new_name):
            return {
                "name": new_name,
                "state": "Draft",
                "nodes": [{"name": "n1"}],
                "networks": [{"name": "net1"}],
            }

        with patch("app.routes.slices.clone_slice", new_callable=AsyncMock, side_effect=fake_clone) as mock_clone:
            result = await execute_tool("clone_slice", {
                "slice_name": "source-slice",
                "new_name": "copy-slice",
            })

        parsed = json.loads(result)
        mock_clone.assert_awaited_once_with("source-slice", "copy-slice")
        assert parsed["status"] == "cloned"
        assert parsed["source_slice"] == "source-slice"
        assert parsed["name"] == "copy-slice"
        assert parsed["state"] == "Draft"
        assert parsed["nodes"] == 1
        assert parsed["networks"] == 1

    @pytest.mark.asyncio
    async def test_execute_create_tunnel_dispatches_to_route(self, storage_dir):
        """create_tunnel tool should call the tunnel route with a request model."""
        from app.routes.ai_chat import execute_tool

        captured = {}

        def fake_create(req):
            captured["request"] = req
            return {
                "id": "tun1",
                "slice_name": req.slice_name,
                "node_name": req.node_name,
                "remote_port": req.port,
                "local_port": 9100,
                "status": "connecting",
                "protocol": req.protocol,
            }

        with patch("app.routes.tunnels.create_tunnel", side_effect=fake_create):
            result = await execute_tool("create_tunnel", {
                "slice_name": "web-slice",
                "node_name": "web",
                "port": 8080,
                "protocol": "http",
            })

        parsed = json.loads(result)
        assert captured["request"].slice_name == "web-slice"
        assert captured["request"].node_name == "web"
        assert captured["request"].port == 8080
        assert parsed["id"] == "tun1"
        assert parsed["remote_port"] == 8080

    @pytest.mark.asyncio
    async def test_execute_recipe_consumes_sse_route_response(self, storage_dir):
        """execute_recipe tool should convert recipe SSE progress to JSON."""
        from fastapi.responses import StreamingResponse

        from app.routes.ai_chat import execute_tool

        async def fake_execute_recipe(recipe_name, slice_name, node_name):
            async def stream():
                yield 'data: {"event":"step","message":"Connecting","status":"ok"}\n\n'
                yield 'data: {"event":"done","status":"ok","results":[{"type":"execute","status":"ok"}]}\n\n'

            return StreamingResponse(stream(), media_type="text/event-stream")

        with patch("app.routes.recipes.execute_recipe", new_callable=AsyncMock, side_effect=fake_execute_recipe) as mock_recipe:
            result = await execute_tool("execute_recipe", {
                "recipe_name": "install-docker",
                "slice_name": "svc-slice",
                "node_name": "web",
            })

        parsed = json.loads(result)
        mock_recipe.assert_awaited_once_with("install-docker", "svc-slice", "web")
        assert parsed["recipe_name"] == "install-docker"
        assert parsed["slice_name"] == "svc-slice"
        assert parsed["node_name"] == "web"
        assert parsed["status"] == "ok"
        assert parsed["results"] == [{"type": "execute", "status": "ok"}]
        assert parsed["events"][0]["event"] == "step"

    @pytest.mark.asyncio
    async def test_execute_run_python_script_runs_storage_script(self, storage_dir):
        """run_python_script should execute a .py script inside user storage."""
        from app.routes.ai_chat import execute_tool

        script = storage_dir / "analysis.py"
        script.write_text(
            "import pathlib\n"
            "import sys\n"
            "print('args=' + ','.join(sys.argv[1:]))\n"
            "pathlib.Path('analysis.out').write_text('done')\n"
        )

        result = await execute_tool("run_python_script", {
            "path": "analysis.py",
            "args": ["alpha", "beta"],
            "timeout": 5,
        })

        parsed = json.loads(result)
        assert parsed["status"] == "ok"
        assert parsed["exit_code"] == 0
        assert "args=alpha,beta" in parsed["stdout"]
        assert (storage_dir / "analysis.out").read_text() == "done"

    @pytest.mark.asyncio
    async def test_execute_run_python_script_blocks_path_escape(self, storage_dir):
        """run_python_script should reject paths outside user storage."""
        from app.routes.ai_chat import execute_tool

        result = await execute_tool("run_python_script", {"path": "../outside.py"})

        parsed = json.loads(result)
        assert "error" in parsed
        assert "outside user storage" in parsed["error"]

    @pytest.mark.asyncio
    async def test_execute_run_jupyter_notebook_runs_storage_notebook(self, storage_dir):
        """run_jupyter_notebook should execute an .ipynb inside user storage."""
        import sys
        import types
        from app.routes.ai_chat import execute_tool

        notebook = {
            "nbformat": 4,
            "nbformat_minor": 5,
            "metadata": {},
            "cells": [{
                "cell_type": "code",
                "source": "print('hello')",
                "metadata": {},
                "outputs": [],
                "execution_count": None,
            }],
        }
        (storage_dir / "analysis.ipynb").write_text(json.dumps(notebook))

        nbformat_mod = types.ModuleType("nbformat")

        def fake_read(handle, as_version=4):
            return json.load(handle)

        def fake_write(nb, handle):
            json.dump(nb, handle)

        nbformat_mod.read = fake_read
        nbformat_mod.write = fake_write

        nbclient_mod = types.ModuleType("nbclient")

        class FakeNotebookClient:
            def __init__(self, nb, timeout, kernel_name, resources):
                self.nb = nb
                self.timeout = timeout
                self.kernel_name = kernel_name
                self.resources = resources

            def execute(self):
                self.nb["cells"][0]["outputs"] = [{
                    "output_type": "stream",
                    "name": "stdout",
                    "text": "hello\n",
                }]
                self.nb["cells"][0]["execution_count"] = 1
                return self.nb

        nbclient_mod.NotebookClient = FakeNotebookClient

        with patch.dict(sys.modules, {"nbformat": nbformat_mod, "nbclient": nbclient_mod}):
            result = await execute_tool("run_jupyter_notebook", {
                "path": "analysis.ipynb",
                "output_path": "executed/analysis.ipynb",
                "timeout": 5,
            })

        parsed = json.loads(result)
        assert parsed["status"] == "ok"
        assert parsed["path"] == "analysis.ipynb"
        assert parsed["output_path"] == "executed/analysis.ipynb"
        assert parsed["code_cells"] == 1
        assert parsed["output_count"] == 1
        assert parsed["outputs"][0]["text"] == "hello\n"
        assert (storage_dir / "executed" / "analysis.ipynb").is_file()

    @pytest.mark.asyncio
    async def test_execute_run_jupyter_notebook_blocks_path_escape(self, storage_dir):
        """run_jupyter_notebook should reject paths outside user storage."""
        from app.routes.ai_chat import execute_tool

        result = await execute_tool("run_jupyter_notebook", {"path": "../outside.ipynb"})

        parsed = json.loads(result)
        assert "error" in parsed
        assert "outside user storage" in parsed["error"]

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

    @pytest.mark.asyncio
    async def test_execute_ssh_includes_command_context(self, storage_dir):
        """ssh_execute results should retain command context for final evidence."""
        from app.routes.ai_chat import execute_tool

        async def fake_execute_on_vm(slice_name, node_name, body):
            return {"stdout": "vm1\n", "stderr": ""}

        with patch("app.routes.files.execute_on_vm", new_callable=AsyncMock, side_effect=fake_execute_on_vm):
            result = await execute_tool("ssh_execute", {
                "slice_name": "bench",
                "node_name": "vm1",
                "command": "hostname",
            })

        parsed = json.loads(result)
        assert parsed["slice_name"] == "bench"
        assert parsed["node_name"] == "vm1"
        assert parsed["command"] == "hostname"
        assert parsed["stdout"] == "vm1\n"
        assert parsed["stdout_truncated"] is False

    @pytest.mark.asyncio
    async def test_execute_ssh_stdout_cap_is_32kb(self, storage_dir):
        """ssh_execute should retain up to 32KB of stdout with metadata."""
        from app.routes.ai_chat import execute_tool

        async def fake_execute_on_vm(slice_name, node_name, body):
            return {"stdout": "x" * 40000, "stderr": "e" * 9000}

        with patch("app.routes.files.execute_on_vm", new_callable=AsyncMock, side_effect=fake_execute_on_vm):
            result = await execute_tool("ssh_execute", {
                "slice_name": "bench",
                "node_name": "vm1",
                "command": "cat /tmp/result.log",
            })

        parsed = json.loads(result)
        assert len(parsed["stdout"]) == 32000
        assert len(parsed["stderr"]) == 8000
        assert parsed["stdout_truncated"] is True
        assert parsed["stderr_truncated"] is True

    @pytest.mark.asyncio
    async def test_execute_download_file_bulk_writes_to_user_storage(self, storage_dir):
        """download_file_bulk should download to storage and return a preview."""
        from app.routes.ai_chat import execute_tool

        captured = {}

        class FakeNode:
            def download_file(self, local_path, remote_path):
                captured["local_path"] = local_path
                captured["remote_path"] = remote_path
                with open(local_path, "w") as f:
                    f.write("abcdef\n" + ("z" * 20))

        with patch("app.routes.files._get_node", return_value=FakeNode()):
            result = await execute_tool("download_file_bulk", {
                "slice_name": "bench",
                "node_name": "vm1",
                "remote_path": "/tmp/result.log",
                "dest_dir": "analysis",
                "preview_bytes": 6,
            })

        parsed = json.loads(result)
        assert parsed["status"] == "downloaded"
        assert parsed["remote_path"] == "/tmp/result.log"
        assert parsed["local_path"] == "analysis/result.log"
        assert parsed["preview"] == "abcdef"
        assert parsed["preview_truncated"] is True
        assert (storage_dir / "analysis" / "result.log").is_file()
        assert captured["remote_path"] == "/tmp/result.log"


    @pytest.mark.asyncio
    async def test_execute_package_sphere_experiment(self, storage_dir):
        """execute_tool('package_sphere_experiment') dispatches to the SPHERE
        packager route with explicit kwargs (no Body(...) FieldInfo leaks)."""
        from app.routes.ai_chat import execute_tool

        captured = {}

        async def fake_package(**kwargs):
            captured.update(kwargs)
            return {"dir_name": kwargs["name"], "format": "sphere-experiment-v1", "files": ["weave.json"]}

        with patch("app.routes.sphere.sphere_package_experiment",
                   new=AsyncMock(side_effect=fake_package)):
            result = await execute_tool("package_sphere_experiment", {
                "experiment": "netsec1",
                "name": "netsec1-detector",
                "realization": "r0",
                "scripts": [{"name": "detector.py", "target": "gateway", "content": "print('x')"}],
                "notebook": [{"cell_type": "markdown", "source": "# Analysis"}],
            })
        parsed = json.loads(result)
        assert parsed["format"] == "sphere-experiment-v1"
        # AI-authored notebook is passed through to the packager.
        assert captured["notebook"] == [{"cell_type": "markdown", "source": "# Analysis"}]
        # Every param passed explicitly — defaulted Body params must be real values,
        # never FieldInfo sentinels.
        assert captured["experiment"] == "netsec1"
        assert captured["name"] == "netsec1-detector"
        assert captured["realization"] == "r0"
        assert captured["include_notebook"] is True
        assert captured["description_short"] == ""
        assert captured["scripts"][0]["name"] == "detector.py"
        for key in ("description", "description_short", "description_long", "dir_name",
                    "tags", "project"):
            assert not isinstance(captured[key], FieldInfo), f"{key} leaked a Body() sentinel"
    @pytest.mark.asyncio
    async def test_create_weave_default_script_honors_lease_policy_env(self, storage_dir):
        """The default create_weave script should submit with the runtime lease cap."""
        from app.routes.ai_chat import _create_weave_tool

        result = await _create_weave_tool({
            "name": "lease weave",
            "description": "lease guard test",
            "script_content": "",
            "num_nodes": 1,
            "include_notebooks": False,
        })

        parsed = json.loads(result)
        assert parsed["status"] == "created"
        script_path = storage_dir / "my_artifacts" / "lease_weave" / "lease_weave.py"
        script = script_path.read_text()
        assert "FABRIC_MAX_LEASE_HOURS" in script
        assert "lease_in_hours=max_lease_hours" in script
        assert "_submit_with_lease_policy(slice_obj)" in script


# ---------------------------------------------------------------------------
# Operational final-answer verification evidence
# ---------------------------------------------------------------------------

class TestVerificationEvidenceGuard:
    def test_prepends_configure_networking_stdout_before_success_claim(self):
        from app.routes.ai_chat import _apply_verification_evidence_guard

        tool_result = json.dumps({
            "status": "ok",
            "pings": [{
                "ok": True,
                "source_node": "vm1",
                "target_node": "vm2",
                "target_ip": "192.168.100.2",
                "network": "lan",
                "command": "ping -c 3 -W 2 192.168.100.2",
                "stdout": "3 packets transmitted, 3 received, 0% packet loss\n__loomai_ping_rc=0\n",
                "stderr": "",
            }],
        })

        guarded, guard_applied, evidence_appended = _apply_verification_evidence_guard(
            "The slice is working and verification passed.",
            [("configure_networking", tool_result)],
        )

        assert guard_applied is True
        assert evidence_appended is True
        assert guarded.startswith("Verification evidence:")
        assert "ping -c 3 -W 2 192.168.100.2" in guarded
        assert "0% packet loss" in guarded
        assert guarded.index("Verification evidence:") < guarded.index("The slice is working")

    def test_does_not_append_evidence_without_success_claim(self):
        from app.routes.ai_chat import _apply_verification_evidence_guard

        tool_result = json.dumps({
            "stdout": "vm1\n",
            "stderr": "",
            "node_name": "vm1",
            "command": "hostname",
        })

        guarded, guard_applied, evidence_appended = _apply_verification_evidence_guard(
            "I ran the hostname command and captured output.",
            [("ssh_execute", tool_result)],
        )

        assert guarded == "I ran the hostname command and captured output."
        assert guard_applied is False
        assert evidence_appended is False

    def test_uses_background_run_output_as_weave_evidence(self):
        from app.routes.ai_chat import _apply_verification_evidence_guard

        tool_result = json.dumps({
            "run_id": "run-iperf",
            "status": "done",
            "output": "[SUM] 0.00-10.00 sec 14.8 GBytes 12.7 Gbits/sec\n",
            "offset": 128,
        })

        guarded, guard_applied, evidence_appended = _apply_verification_evidence_guard(
            "The weave run completed successfully.",
            [("get_background_run_output", tool_result)],
        )

        assert guard_applied is True
        assert evidence_appended is True
        assert "run-iperf" in guarded
        assert "12.7 Gbits/sec" in guarded


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
