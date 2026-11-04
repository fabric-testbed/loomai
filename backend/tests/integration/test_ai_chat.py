"""Tests for AI chat REST endpoints."""

import json
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

import pytest


def _set_assistant_flags(**flags):
    from app import settings_manager
    settings = settings_manager.load_settings()
    settings.setdefault("ai", {}).setdefault("assistant", {}).update(flags)
    settings_manager.save_settings(settings)


def _run_async(coro):
    result = asyncio.run(coro)
    asyncio.set_event_loop(asyncio.new_event_loop())
    return result


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

    def test_builtin_fabric_slice_operator_agent_present(self, client):
        import app.routes.ai_chat as ai_chat_mod
        ai_chat_mod._agents_cache = None

        resp = client.get("/api/ai/chat/agents")
        assert resp.status_code == 200
        agents = {agent["id"]: agent for agent in resp.json()}
        assert "fabric-slice-operator" in agents
        assert "slice creation" in agents["fabric-slice-operator"]["description"].lower()

        loaded = ai_chat_mod._load_agents()
        prompt = loaded["fabric-slice-operator"]["prompt"]
        assert "Prepare a FABRIC slice request for benchmark static validation only" in prompt
        assert "configure_networking(slice_name, verify=true)" in prompt

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


def _make_responses_llm_response(content="Hello!", tool_calls=None, reasoning_items=None):
    """Create a mock httpx Response for an OpenAI Responses API call."""
    resp = MagicMock()
    resp.status_code = 200
    output = []
    if content:
        output.append({
            "type": "message",
            "content": [{"type": "output_text", "text": content}],
        })
    output.extend(reasoning_items or [])
    for tool_call in tool_calls or []:
        item = {
            "type": "function_call",
            "call_id": tool_call.get("id", "call_1"),
            "name": tool_call["function"]["name"],
            "arguments": tool_call["function"].get("arguments", "{}"),
        }
        if tool_call.get("responses_id"):
            item["id"] = tool_call["responses_id"]
        if tool_call.get("status"):
            item["status"] = tool_call["status"]
        output.append(item)
    resp.json.return_value = {"output": output}
    return resp


def _make_llm_error(status_code=400, text="provider error"):
    """Create a mock httpx Response for an LLM error."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
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


def _sse_content_text(response_text):
    """Concatenate SSE content events from a test response body."""
    parts = []
    for line in response_text.splitlines():
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        try:
            payload = json.loads(line[6:])
        except json.JSONDecodeError:
            continue
        if "content" in payload:
            parts.append(payload["content"])
    return "".join(parts)


class TestChatStream:
    """Tests for POST /api/ai/chat/stream.

    This endpoint returns an SSE stream. We test error paths and basic
    behavior; full multi-turn tool-calling tests are out of scope.
    """

    def test_create_slice_schema_marks_draft_only(self):
        from app.routes.ai_chat import TOOL_SCHEMAS

        create_schema = next(
            schema for schema in TOOL_SCHEMAS
            if schema["function"]["name"] == "create_slice"
        )
        description = create_schema["function"]["description"]
        props = create_schema["function"]["parameters"]["properties"]

        assert "DRAFT ONLY" in description
        assert "submit_slice()" in description
        assert "confirm_new_slice" in props

    def test_chat_create_slice_tool_creates_draft_through_real_dispatch(self, client, mock_fablib):
        """Exercise the real chat tool dispatch path into the slice route."""
        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock(side_effect=[
                _make_llm_response(
                    tool_calls=[{
                        "id": "call_create",
                        "function": {
                            "name": "create_slice",
                            "arguments": json.dumps({
                                "name": "bench-real-dispatch",
                                "lease_hours": 0,
                                "confirm_new_slice": True,
                            }),
                        },
                    }],
                    finish_reason="tool_calls",
                ),
                _make_llm_response("Created draft bench-real-dispatch."),
            ])
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"choices": [{"delta": {"content": "Created draft bench-real-dispatch."}}]}',
                "data: [DONE]",
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{
                    "role": "user",
                    "content": "Create a slice named bench-real-dispatch.",
                }],
                "model": "test-model",
            })

        assert resp.status_code == 200
        assert "'str' object has no attribute 'name'" not in resp.text
        created = mock_fablib.get_slice(name="bench-real-dispatch")
        assert created.get_name() == "bench-real-dispatch"
        assert created.get_state() == "Draft"
        assert '"duplicate_slice_guard_triggered": 0' in resp.text

    def test_submit_background_and_job_status_tools_are_exposed(self):
        from app.routes.ai_chat import TOOL_SCHEMAS

        schemas = {
            schema["function"]["name"]: schema["function"]
            for schema in TOOL_SCHEMAS
        }

        submit_props = schemas["submit_slice"]["parameters"]["properties"]
        assert "background" in submit_props
        assert "get_job_status" in schemas
        assert "wait_seconds" in schemas["get_job_status"]["parameters"]["properties"]

    def test_fabric_python_code_request_injects_fablib_reference(self, client):
        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, return_value="[]"), \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock(return_value=_make_llm_response("Here is the script."))
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"choices": [{"delta": {"content": "Here is the script."}}]}',
                "data: [DONE]",
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{
                    "role": "user",
                    "content": "Write a Python script for FABRIC that lists available GPU sites.",
                }],
                "model": "test-model",
            })

        assert resp.status_code == 200
        sent_body = mock_client.post.call_args.kwargs["json"]
        system_prompt = sent_body["messages"][0]["content"]
        assert "FABlib Ground Truth" in system_prompt
        assert "Real Method Names" in system_prompt

    def test_weak_model_state_block_and_compaction_metadata(self, client):
        _set_assistant_flags(
            weak_model_context_management=True,
            capability_profiles_enabled=True,
        )

        messages = [
            {"role": "user", "content": "Create slice bench-c2 with two nodes."},
            {"role": "assistant", "content": "Created draft bench-c2 and submitted it."},
        ]
        for i in range(10):
            messages.append({"role": "user", "content": f"status turn {i}"})
            messages.append({"role": "assistant", "content": f"still working turn {i}"})
        messages.append({
            "role": "user",
            "content": "Continue from that slice and verify vm1 to vm2 ping.",
        })

        async def fake_execute_tool(name, arguments, request=None):
            if name == "list_slices":
                return json.dumps([{
                    "name": "bench-c2",
                    "state": "StableOK",
                    "nodes": 2,
                    "lease_end": "2026-07-10T06:00:00+00:00",
                }])
            if name == "get_slice":
                return json.dumps({
                    "name": "bench-c2",
                    "state": "StableOK",
                    "lease_end": "2026-07-10T06:00:00+00:00",
                    "node_count": 2,
                    "nodes": [
                        {"name": "vm1", "site": "DALL", "reservation_state": "Active"},
                        {"name": "vm2", "site": "DALL", "reservation_state": "Active"},
                    ],
                    "network_count": 1,
                    "networks": [{"name": "net1", "type": "L2Bridge"}],
                })
            return "[]"

        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, side_effect=fake_execute_tool), \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock(return_value=_make_llm_response("Continuing from bench-c2."))
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"choices": [{"delta": {"content": "Continuing from bench-c2."}}]}',
                "data: [DONE]",
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": messages,
                "model": "qwen3-coder-30b",
            })

        assert resp.status_code == 200
        sent_body = mock_client.post.await_args.kwargs["json"]
        system_prompt = sent_body["messages"][0]["content"]
        assert "## CURRENT SESSION STATE" in system_prompt
        assert "bench-c2: StableOK" in system_prompt
        assert "Do NOT create a new slice" in system_prompt
        assert len(sent_body["messages"]) < len(messages) + 1
        assert any(
            msg.get("role") == "user"
            and "Compacted prior progress" in msg.get("content", "")
            for msg in sent_body["messages"]
        )
        assert '"session_state_injected": true' in resp.text
        assert '"created_slices_count": 1' in resp.text
        assert '"context_compacted": true' in resp.text

    def test_nrp_builtin_weak_profiles_inject_session_state_without_runtime_file(self, client, storage_dir):
        _set_assistant_flags(
            weak_model_context_management=True,
            capability_profiles_enabled=True,
            capability_profile_path=str(storage_dir / "missing-model-capabilities.json"),
        )

        messages = [
            {"role": "user", "content": "Create the bench-nrp slice."},
            {"role": "assistant", "content": "Created draft bench-nrp."},
            {"role": "user", "content": "Continue with that same slice."},
        ]

        async def fake_execute_tool(name, arguments, request=None):
            if name == "list_slices":
                return json.dumps([{
                    "name": "bench-nrp",
                    "state": "StableOK",
                    "nodes": 2,
                }])
            if name == "get_slice":
                return json.dumps({
                    "name": "bench-nrp",
                    "state": "StableOK",
                    "node_count": 2,
                    "nodes": [
                        {"name": "vm1", "site": "DALL", "reservation_state": "Active"},
                        {"name": "vm2", "site": "DALL", "reservation_state": "Active"},
                    ],
                    "network_count": 1,
                    "networks": [{"name": "net1", "type": "L2Bridge"}],
                })
            return "[]"

        for model in ("nrp:qwen3", "nrp:minimax-m2"):
            with patch("app.routes.ai_chat._get_nrp_api_key", return_value="fake-nrp-key"), \
                 patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, side_effect=fake_execute_tool), \
                 patch("app.routes.ai_chat.ai_client") as mock_client:

                mock_client.post = AsyncMock(return_value=_make_llm_response("Continuing from bench-nrp."))
                mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                    'data: {"choices": [{"delta": {"content": "Continuing from bench-nrp."}}]}',
                    "data: [DONE]",
                ]))

                resp = client.post("/api/ai/chat/stream", json={
                    "messages": messages,
                    "model": model,
                })

            assert resp.status_code == 200
            sent_body = mock_client.post.await_args.kwargs["json"]
            system_prompt = sent_body["messages"][0]["content"]
            assert "## CURRENT SESSION STATE" in system_prompt
            assert "bench-nrp: StableOK" in system_prompt
            assert '"session_state_injected": true' in resp.text

    def test_created_slice_extraction_reads_marker_and_backtick_names(self):
        from app.routes.ai_chat import _extract_conversation_created_slices

        names = _extract_conversation_created_slices([
            {
                "role": "assistant",
                "content": (
                    "Created draft `bench-backtick`.\n"
                    "[SESSION-STATE] created-slices: `bench-marker`, \"bench-quoted\""
                ),
            },
        ])

        assert names == {"bench-backtick", "bench-marker", "bench-quoted"}

    def test_weak_model_appends_session_state_marker_on_guard_after_create(self, client):
        """A guard final message should carry tool-created slice names forward."""
        _set_assistant_flags(
            weak_model_context_management=True,
            capability_profiles_enabled=True,
            tool_loop={"no_progress_limit": 3},
        )

        async def fake_execute(name, arguments, request=None):
            if name == "create_slice":
                return json.dumps({
                    "status": "created",
                    "name": arguments["name"],
                    "state": "Draft",
                })
            return "{}"

        tool_call_resp = _make_llm_response(
            tool_calls=[{
                "id": "call_create",
                "function": {
                    "name": "create_slice",
                    "arguments": json.dumps({"name": "bench-bridge"}),
                },
            }],
            finish_reason="tool_calls",
        )

        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, side_effect=fake_execute), \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock(side_effect=[
                tool_call_resp,
                tool_call_resp,
                tool_call_resp,
            ])
            mock_client.stream = MagicMock()

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{
                    "role": "user",
                    "content": "Create a slice named bench-bridge.",
                }],
                "model": "qwen3-coder-30b",
                "agent": "fabric-slice-operator",
            })

        assert resp.status_code == 200
        content = _sse_content_text(resp.text)
        assert "Stopped the tool loop" in content
        assert "bench-bridge" not in content.split("[SESSION-STATE]")[0]
        assert "[SESSION-STATE] created-slices: bench-bridge" in content
        assert '"session_state_marker_appended": true' in resp.text
        assert '"created_slices_count": 1' in resp.text
        assert not mock_client.stream.called

    def test_weak_model_followup_injects_state_from_session_marker(self, client):
        """The next stateless turn should rebuild CURRENT SESSION STATE from the marker."""
        _set_assistant_flags(
            weak_model_context_management=True,
            capability_profiles_enabled=True,
        )

        async def fake_execute(name, arguments, request=None):
            if name == "list_slices":
                return json.dumps([{
                    "name": "bench-bridge",
                    "state": "StableOK",
                    "nodes": 2,
                    "lease_end": "2026-07-10T06:00:00+00:00",
                }])
            if name == "get_slice":
                return json.dumps({
                    "name": "bench-bridge",
                    "state": "StableOK",
                    "node_count": 2,
                    "nodes": [
                        {"name": "vm1", "site": "DALL"},
                        {"name": "vm2", "site": "DALL"},
                    ],
                    "networks": [{"name": "net1", "type": "L2Bridge"}],
                })
            return "[]"

        marker_text = (
            "\n\n[Stopped the tool loop because the model repeated "
            "`create_slice` with the same arguments 3 times.]\n\n"
            "[SESSION-STATE] created-slices: bench-bridge"
        )

        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, side_effect=fake_execute), \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock(return_value=_make_llm_response("Continuing from bench-bridge."))
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"choices": [{"delta": {"content": "Continuing from bench-bridge."}}]}',
                "data: [DONE]",
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [
                    {"role": "user", "content": "Create a slice named bench-bridge."},
                    {"role": "assistant", "content": marker_text},
                    {"role": "user", "content": "Continue and verify vm1 to vm2 ping."},
                ],
                "model": "qwen3-coder-30b",
            })

        assert resp.status_code == 200
        sent_body = mock_client.post.await_args.kwargs["json"]
        system_prompt = sent_body["messages"][0]["content"]
        assert "## CURRENT SESSION STATE" in system_prompt
        assert "bench-bridge: StableOK" in system_prompt
        assert "Do NOT create a new slice" in system_prompt
        assert '"session_state_injected": true' in resp.text
        assert '"session_state_marker_appended": false' in resp.text

    def test_weak_model_duplicate_slice_guard_blocks_new_name(self, client):
        _set_assistant_flags(
            weak_model_context_management=True,
            capability_profiles_enabled=True,
        )

        async def fake_execute(name, arguments, request=None):
            if name == "list_slices":
                return json.dumps([{"name": "bench-old", "state": "StableOK", "nodes": 1}])
            if name == "get_slice":
                return json.dumps({
                    "name": "bench-old",
                    "state": "StableOK",
                    "node_count": 1,
                    "nodes": [{"name": "vm1", "site": "RENC"}],
                    "networks": [],
                })
            if name == "create_slice":
                return json.dumps({"status": "created", "name": arguments["name"]})
            return "{}"

        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, side_effect=fake_execute) as mock_exec, \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock(side_effect=[
                _make_llm_response(
                    tool_calls=[{
                        "id": "call_create",
                        "function": {
                            "name": "create_slice",
                            "arguments": json.dumps({"name": "bench-new"}),
                        },
                    }],
                    finish_reason="tool_calls",
                ),
                _make_llm_response("Continuing with bench-old."),
            ])
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"choices": [{"delta": {"content": "Continuing with bench-old."}}]}',
                "data: [DONE]",
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [
                    {"role": "user", "content": "Create slice bench-old."},
                    {"role": "assistant", "content": "Created draft bench-old."},
                    {"role": "user", "content": "Continue and verify it."},
                ],
                "model": "qwen3-coder-30b",
            })

        assert resp.status_code == 200
        assert "DUPLICATE_SLICE_GUARD" in resp.text
        assert "duplicate-slice-guard" in resp.text
        assert '"duplicate_slice_guard_triggered": 1' in resp.text
        assert not any(call.args[0] == "create_slice" for call in mock_exec.await_args_list)

    def test_weak_model_duplicate_slice_guard_allows_confirmed_new_slice(self, client):
        _set_assistant_flags(
            weak_model_context_management=True,
            capability_profiles_enabled=True,
        )

        async def fake_execute(name, arguments, request=None):
            if name == "list_slices":
                return json.dumps([{"name": "bench-old", "state": "StableOK", "nodes": 1}])
            if name == "get_slice":
                return json.dumps({"name": "bench-old", "state": "StableOK", "nodes": []})
            if name == "create_slice":
                return json.dumps({
                    "status": "created",
                    "name": arguments["name"],
                    "state": "Draft",
                })
            return "{}"

        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, side_effect=fake_execute) as mock_exec, \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock(side_effect=[
                _make_llm_response(
                    tool_calls=[{
                        "id": "call_create",
                        "function": {
                            "name": "create_slice",
                            "arguments": json.dumps({
                                "name": "bench-new",
                                "confirm_new_slice": True,
                            }),
                        },
                    }],
                    finish_reason="tool_calls",
                ),
                _make_llm_response("Created the additional slice."),
            ])
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"choices": [{"delta": {"content": "Created the additional slice."}}]}',
                "data: [DONE]",
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [
                    {"role": "user", "content": "Create slice bench-old."},
                    {"role": "assistant", "content": "Created draft bench-old."},
                    {"role": "user", "content": "Create an additional slice named bench-new."},
                ],
                "model": "qwen3-coder-30b",
            })

        assert resp.status_code == 200
        assert "DUPLICATE_SLICE_GUARD" not in resp.text
        assert '"duplicate_slice_guard_triggered": 0' in resp.text
        create_calls = [call for call in mock_exec.await_args_list if call.args[0] == "create_slice"]
        assert create_calls
        assert create_calls[-1].args[1]["name"] == "bench-new"

    def test_duplicate_slice_guard_is_weak_model_only(self, client):
        async def fake_execute(name, arguments, request=None):
            if name == "list_slices":
                return "[]"
            if name == "get_slice":
                return json.dumps({"name": "bench-old", "state": "StableOK"})
            if name == "create_slice":
                return json.dumps({
                    "status": "created",
                    "name": arguments["name"],
                    "state": "Draft",
                })
            return "{}"

        def run_case(model, weak_flag):
            _set_assistant_flags(
                weak_model_context_management=weak_flag,
                capability_profiles_enabled=True,
            )
            with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
                 patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, side_effect=fake_execute) as mock_exec, \
                 patch("app.routes.ai_chat.ai_client") as mock_client:

                mock_client.post = AsyncMock(side_effect=[
                    _make_llm_response(
                        tool_calls=[{
                            "id": "call_create",
                            "function": {
                                "name": "create_slice",
                                "arguments": json.dumps({"name": "bench-new"}),
                            },
                        }],
                        finish_reason="tool_calls",
                    ),
                    _make_llm_response("Created bench-new."),
                ])
                mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                    'data: {"choices": [{"delta": {"content": "Created bench-new."}}]}',
                    "data: [DONE]",
                ]))

                resp = client.post("/api/ai/chat/stream", json={
                    "messages": [
                        {"role": "user", "content": "Create slice bench-old."},
                        {"role": "assistant", "content": "Created draft bench-old."},
                        {"role": "user", "content": "Continue."},
                    ],
                    "model": model,
                })
                return resp, mock_exec.await_args_list

        strong_resp, strong_calls = run_case("test-model", True)
        flag_off_resp, flag_off_calls = run_case("qwen3-coder-30b", False)

        for resp, calls in ((strong_resp, strong_calls), (flag_off_resp, flag_off_calls)):
            assert resp.status_code == 200
            assert "DUPLICATE_SLICE_GUARD" not in resp.text
            assert '"duplicate_slice_guard_triggered": 0' in resp.text
            assert any(call.args[0] == "create_slice" for call in calls)

    def test_duplicate_slice_guard_points_dead_slice_to_diagnosis(self, client):
        _set_assistant_flags(
            weak_model_context_management=True,
            capability_profiles_enabled=True,
        )

        async def fake_execute(name, arguments, request=None):
            if name == "list_slices":
                return json.dumps([{"name": "bench-old", "state": "Dead", "nodes": 0}])
            if name == "get_slice":
                return json.dumps({
                    "name": "bench-old",
                    "state": "Dead",
                    "error_messages": [{"message": "reservation failed"}],
                })
            return "{}"

        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, side_effect=fake_execute), \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock(side_effect=[
                _make_llm_response(
                    tool_calls=[{
                        "id": "call_create",
                        "function": {
                            "name": "create_slice",
                            "arguments": json.dumps({"name": "bench-new"}),
                        },
                    }],
                    finish_reason="tool_calls",
                ),
                _make_llm_response("Diagnosing bench-old."),
            ])
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"choices": [{"delta": {"content": "Diagnosing bench-old."}}]}',
                "data: [DONE]",
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [
                    {"role": "user", "content": "Create slice bench-old."},
                    {"role": "assistant", "content": "Created draft bench-old."},
                    {"role": "user", "content": "Continue."},
                ],
                "model": "qwen3-coder-30b",
            })

        assert resp.status_code == 200
        assert "DUPLICATE_SLICE_GUARD" in resp.text
        assert "currently Dead" in resp.text
        assert "Diagnose or repair THAT slice" in resp.text

    def test_session_state_marker_is_gated_to_weak_context_management(self, client):
        """Flag-off qwen and flag-on strong profiles should not append the marker."""
        async def fake_execute(name, arguments, request=None):
            if name == "create_slice":
                return json.dumps({
                    "status": "created",
                    "name": arguments["name"],
                    "state": "Draft",
                })
            return "{}"

        def run_case(model, weak_flag):
            _set_assistant_flags(
                weak_model_context_management=weak_flag,
                capability_profiles_enabled=True,
                tool_loop={"no_progress_limit": 3},
            )
            tool_call_resp = _make_llm_response(
                tool_calls=[{
                    "id": "call_create",
                    "function": {
                        "name": "create_slice",
                        "arguments": json.dumps({"name": "bench-no-marker"}),
                    },
                }],
                finish_reason="tool_calls",
            )
            with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
                 patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, side_effect=fake_execute), \
                 patch("app.routes.ai_chat.ai_client") as mock_client:

                mock_client.post = AsyncMock(side_effect=[
                    tool_call_resp,
                    tool_call_resp,
                    tool_call_resp,
                ])
                mock_client.stream = MagicMock()

                return client.post("/api/ai/chat/stream", json={
                    "messages": [{
                        "role": "user",
                        "content": "Create a slice named bench-no-marker.",
                    }],
                    "model": model,
                    "agent": "fabric-slice-operator",
                })

        flag_off = run_case("qwen3-coder-30b", False)
        strong_profile = run_case("test-model", True)

        for resp in (flag_off, strong_profile):
            assert resp.status_code == 200
            assert "[SESSION-STATE] created-slices:" not in _sse_content_text(resp.text)
            assert '"session_state_marker_appended": false' in resp.text

    def test_stream_returns_error_when_no_api_key(self, client):
        with patch("app.routes.ai_chat._get_ai_api_key", return_value=""):
            resp = client.post("/api/ai/chat/stream",
                               json={"messages": [{"role": "user", "content": "hi"}]})
        assert resp.status_code == 503
        payload = resp.json()["detail"]
        assert payload["error"] == "AI_API_KEY_NOT_CONFIGURED"
        assert "API key" in payload["message"]

    def test_stream_returns_non_200_when_nrp_key_missing(self, client):
        with patch("app.routes.ai_chat._get_nrp_api_key", return_value=""):
            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{"role": "user", "content": "hi"}],
                "model": "nrp:qwen3",
            })
        assert resp.status_code == 503
        payload = resp.json()["detail"]
        assert payload["error"] == "NRP_API_KEY_NOT_CONFIGURED"
        assert payload["provider"] == "nrp"

    def test_stream_returns_non_200_when_custom_provider_key_missing(self, client, storage_dir):
        from app import settings_manager

        settings = settings_manager.load_settings()
        settings["ai"]["custom_providers"] = [{
            "name": "Local",
            "base_url": "https://provider.example",
            "api_key": "",
            "endpoint_style": "chat",
        }]
        settings_manager.save_settings(settings)

        resp = client.post("/api/ai/chat/stream", json={
            "messages": [{"role": "user", "content": "hi"}],
            "model": "Local:test-model",
        })

        assert resp.status_code == 503
        payload = resp.json()["detail"]
        assert payload["error"] == "CUSTOM_PROVIDER_API_KEY_NOT_CONFIGURED"
        assert payload["provider"] == "custom:Local"

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

    def test_custom_provider_404_does_not_fallback_to_fabric_default(self, client, storage_dir):
        """A missing custom-provider model should not silently switch providers."""
        from app import settings_manager

        settings = settings_manager.load_settings()
        settings.setdefault("ai", {})["fabric_api_key"] = ""
        settings["ai"]["default_model"] = "fabric-default"
        settings["ai"]["default_model_source"] = "fabric"
        settings["ai"]["custom_providers"] = [{
            "name": "Local",
            "base_url": "https://provider.example",
            "api_key": "custom-key",
            "endpoint_style": "chat",
        }]
        settings_manager.save_settings(settings)

        with patch("app.routes.ai_chat._get_ai_api_key", return_value=""), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, return_value="{}"), \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock(return_value=_make_llm_error(404, "model not found"))
            mock_client.stream = MagicMock()

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{"role": "user", "content": "hello"}],
                "model": "Local:missing-model",
            })

        assert resp.status_code == 200
        assert mock_client.post.await_count == 1
        assert not mock_client.stream.called
        assert "switching to fabric-default" not in resp.text
        assert "model not found" in resp.text
        sent_body = mock_client.post.await_args.kwargs["json"]
        assert sent_body["model"] == "missing-model"

    def test_custom_non_chat_model_returns_clear_error(self, client, storage_dir):
        """Known non-chat custom models should not be sent to chat completions."""
        from app import settings_manager

        settings = settings_manager.load_settings()
        settings.setdefault("ai", {})["fabric_api_key"] = ""
        settings["ai"]["custom_providers"] = [{
            "name": "Local",
            "base_url": "https://provider.example",
            "api_key": "custom-key",
            "endpoint_style": "non-chat",
        }]
        settings_manager.save_settings(settings)

        with patch("app.routes.ai_chat._get_ai_api_key", return_value=""), \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock()
            mock_client.stream = MagicMock()

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{"role": "user", "content": "hello"}],
                "model": "Local:embed-model",
            })

        assert resp.status_code == 200
        assert mock_client.post.await_count == 0
        assert not mock_client.stream.called
        assert "does not support chat" in resp.text

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
            text_resp = _make_llm_response("FINAL ANSWER\nRENC is available.")
            mock_client.post = AsyncMock(side_effect=[tool_call_resp, text_resp])

            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"choices": [{"delta": {"content": "FINAL ANSWER\\nRENC is available."}}]}',
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

    def test_tool_round_backstop_is_high_emergency_cap(self):
        """The fixed round cap should be a high backstop, not normal control flow."""
        from app.routes.ai_chat import _MAX_TOOL_ROUNDS

        assert _MAX_TOOL_ROUNDS == 100

    def test_stream_stops_when_turn_token_budget_would_be_exceeded(self, client):
        """Configured per-turn token budgets should stop before another provider call."""
        _set_assistant_flags(turn_budget={
            "default": {
                "max_tokens": 1,
                "max_cost_usd": 0,
                "cost_per_1k_tokens_usd": 0,
            },
        })

        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock()
            mock_client.stream = MagicMock()

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{"role": "user", "content": "hello"}],
                "model": "test-model",
                "agent": "fabric-slice-operator",
            })

        assert resp.status_code == 200
        assert mock_client.post.await_count == 0
        assert not mock_client.stream.called
        assert '"tool_loop_stopped"' in resp.text
        assert '"reason": "turn_token_budget_exceeded"' in resp.text
        assert '"tool_loop_stop_reason": "turn_token_budget_exceeded"' in resp.text

    def test_stream_stops_repeated_identical_tool_calls(self, client):
        """Same tool+args with unchanged result should stop after the no-progress limit."""
        async def fake_execute(name, arguments, request=None):
            if name == "query_sites":
                return json.dumps({
                    "sites": [{"name": "RENC", "state": "Active"}],
                    "summary": {"count": 1},
                })
            return "{}"

        tool_call_resp = _make_llm_response(
            tool_calls=[{
                "id": "call_sites",
                "function": {"name": "query_sites", "arguments": "{}"},
            }],
            finish_reason="tool_calls",
        )

        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, side_effect=fake_execute) as mock_exec, \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock(side_effect=[
                tool_call_resp,
                tool_call_resp,
                tool_call_resp,
                _make_llm_response("should not be reached"),
            ])
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"choices": [{"delta": {"content": "should not stream"}}]}',
                "data: [DONE]",
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{"role": "user", "content": "repeat the same inventory check"}],
                "model": "test-model",
                "agent": "fabric-slice-operator",
            })

        query_calls = [
            call for call in mock_exec.await_args_list
            if call.args and call.args[0] == "query_sites"
        ]
        assert resp.status_code == 200
        assert len(query_calls) == 3
        assert mock_client.post.await_count == 3
        assert not mock_client.stream.called
        assert '"tool_loop_stopped"' in resp.text
        assert '"reason": "no_progress"' in resp.text
        assert '"tool": "query_sites"' in resp.text
        assert '"repeat_count": 3' in resp.text
        assert "result did not change" in resp.text

    def test_stream_prepends_verification_output_before_success_claim(self, client):
        """Operational success answers should include real command output evidence."""
        async def fake_execute(name, arguments, request=None):
            if name == "list_slices":
                return "[]"
            if name == "configure_networking":
                return json.dumps({
                    "status": "ok",
                    "pings": [{
                        "ok": True,
                        "source_node": "vm1",
                        "target_node": "vm2",
                        "target_ip": "192.168.100.2",
                        "network": "lan",
                        "command": "ping -c 3 -W 2 192.168.100.2",
                        "stdout": (
                            "3 packets transmitted, 3 received, "
                            "0% packet loss\n__loomai_ping_rc=0\n"
                        ),
                        "stderr": "",
                    }],
                })
            return "{}"

        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, side_effect=fake_execute), \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            tool_call_resp = _make_llm_response(
                tool_calls=[{
                    "id": "call_net",
                    "function": {
                        "name": "configure_networking",
                        "arguments": json.dumps({"slice_name": "bench-l2", "verify": True}),
                    },
                }],
                finish_reason="tool_calls",
            )
            final_resp = _make_llm_response("The slice is working and verification passed.")
            mock_client.post = AsyncMock(side_effect=[tool_call_resp, final_resp])
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"choices": [{"delta": {"content": "different success text"}}]}',
                "data: [DONE]",
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{"role": "user", "content": "Configure bench-l2 networking and prove ping works."}],
                "model": "test-model",
            })

        assert resp.status_code == 200
        assert "Verification evidence:" in resp.text
        assert "ping -c 3 -W 2 192.168.100.2" in resp.text
        assert "0% packet loss" in resp.text
        assert resp.text.index("Verification evidence:") < resp.text.index("The slice is working")
        assert "different success text" not in resp.text
        assert not mock_client.stream.called
        assert '"verification_evidence_guard_applied": true' in resp.text
        assert '"verification_evidence_appended": true' in resp.text

    def test_stream_retries_empty_final_after_tool_execution(self, client):
        """Empty visible final answers after tool calls should retry once."""
        async def fake_execute(name, arguments, request=None):
            if name == "list_slices":
                return "[]"
            if name == "get_background_run_output":
                return json.dumps({
                    "run_id": arguments["run_id"],
                    "status": "done",
                    "output": "[SUM] 0.00-10.00 sec 14.8 GBytes 12.7 Gbits/sec\n",
                    "offset": 128,
                })
            return "{}"

        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, side_effect=fake_execute), \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            tool_call_resp = _make_llm_response(
                tool_calls=[{
                    "id": "call_run_output",
                    "function": {
                        "name": "get_background_run_output",
                        "arguments": json.dumps({"run_id": "run-iperf", "offset": 0}),
                    },
                }],
                finish_reason="tool_calls",
            )
            empty_final_resp = _make_llm_response("")
            recovered_final_resp = _make_llm_response("The weave completed successfully.")
            mock_client.post = AsyncMock(side_effect=[
                tool_call_resp,
                empty_final_resp,
                recovered_final_resp,
            ])
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"choices": [{"delta": {"content": "different streamed answer"}}]}',
                "data: [DONE]",
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{"role": "user", "content": "Run the iperf weave and show the result."}],
                "model": "test-model",
            })

        assert resp.status_code == 200
        assert mock_client.post.await_count == 3
        assert not mock_client.stream.called
        assert "12.7 Gbits/sec" in resp.text
        assert '"empty_visible_final_retry_count": 1' in resp.text
        assert '"empty_tool_call_placeholder_count": 1' in resp.text
        assert '"verification_evidence_guard_applied": true' in resp.text

        second_body = mock_client.post.await_args_list[1].kwargs["json"]
        assert any(
            msg.get("content") == "I am running the requested tools and will answer using their results."
            for msg in second_body["messages"]
            if msg.get("role") == "assistant"
        )

        third_body = mock_client.post.await_args_list[2].kwargs["json"]
        assert "tools" not in third_body
        assert "previous response had no visible final answer" in third_body["messages"][-1]["content"]

    def test_submit_slice_uses_conversation_level_authorization(self, client):
        """A prior create-and-verify goal should authorize later submit of that draft."""
        async def fake_execute(name, arguments, request=None):
            if name == "list_slices":
                return "[]"
            if name == "submit_slice":
                return json.dumps({"status": "submitted", "state": "Configuring"})
            return "{}"

        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, side_effect=fake_execute) as mock_exec, \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            tool_call_resp = _make_llm_response(
                tool_calls=[{
                    "id": "call_submit",
                    "function": {
                        "name": "submit_slice",
                        "arguments": json.dumps({
                            "slice_name": "bench-l2",
                            "lease_hours": 6,
                        }),
                    },
                }],
                finish_reason="tool_calls",
            )
            final_resp = _make_llm_response("FINAL ANSWER\nSubmitted bench-l2.")
            mock_client.post = AsyncMock(side_effect=[tool_call_resp, final_resp])
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"choices": [{"delta": {"content": "FINAL ANSWER\\nSubmitted bench-l2."}}]}',
                "data: [DONE]",
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Create a two-node slice named bench-l2 with a "
                            "6-hour lease and demonstrate inter-node ping."
                        ),
                    },
                    {"role": "assistant", "content": "Created draft 'bench-l2'."},
                    {"role": "user", "content": "continue"},
                ],
                "model": "test-model",
            })

        assert resp.status_code == 200
        assert "DESTRUCTIVE_ACTION_BLOCKED" not in resp.text
        assert any(call.args[0] == "submit_slice" for call in mock_exec.await_args_list)

    def test_authorized_creation_retries_draft_only_answer_to_submit_wait(self, client):
        """Authorized create-and-verify flows should not stop at draft-only answers."""
        async def fake_execute(name, arguments, request=None):
            if name == "list_slices":
                return "[]"
            if name == "create_slice":
                return json.dumps({
                    "status": "created",
                    "name": arguments["name"],
                    "state": "Draft",
                    "lease_hours": arguments.get("lease_hours"),
                })
            if name == "add_node":
                return json.dumps({"status": "added", "node": arguments["node_name"]})
            if name == "submit_slice":
                return json.dumps({
                    "status": "submitted",
                    "name": arguments["slice_name"],
                    "state": "StableOK",
                    "lease_hours": arguments.get("lease_hours"),
                    "wait": bool(arguments.get("wait") or arguments.get("wait_for_stableok")),
                    "wait_for_stableok": bool(arguments.get("wait_for_stableok")),
                })
            return "{}"

        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, side_effect=fake_execute) as mock_exec, \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            create_tool_resp = _make_llm_response(
                tool_calls=[
                    {
                        "id": "call_create",
                        "function": {
                            "name": "create_slice",
                            "arguments": json.dumps({
                                "name": "bench-web",
                                "lease_hours": 6,
                            }),
                        },
                    },
                    {
                        "id": "call_node",
                        "function": {
                            "name": "add_node",
                            "arguments": json.dumps({
                                "slice_name": "bench-web",
                                "node_name": "vm1",
                                "site": "RENC",
                            }),
                        },
                    },
                ],
                finish_reason="tool_calls",
            )
            draft_only_resp = _make_llm_response("Draft bench-web is ready.")
            submit_tool_resp = _make_llm_response(
                tool_calls=[{
                    "id": "call_submit",
                    "function": {
                        "name": "submit_slice",
                        "arguments": json.dumps({
                            "slice_name": "bench-web",
                            "lease_hours": 6,
                            "wait_for_stableok": True,
                        }),
                    },
                }],
                finish_reason="tool_calls",
            )
            final_resp = _make_llm_response("bench-web reached StableOK.")
            mock_client.post = AsyncMock(side_effect=[
                create_tool_resp,
                draft_only_resp,
                submit_tool_resp,
                final_resp,
            ])
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"choices": [{"delta": {"content": "bench-web reached StableOK."}}]}',
                "data: [DONE]",
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{
                    "role": "user",
                    "content": (
                        "Create a single VM slice named bench-web with a "
                        "6-hour lease and demonstrate SSH works."
                    ),
                }],
                "model": "test-model",
            })

        assert resp.status_code == 200
        assert mock_client.post.await_count == 4
        assert "Draft bench-web is ready" not in resp.text
        assert "bench-web reached StableOK" in resp.text
        assert '"draft_submission_retry_count": 1' in resp.text

        post_create_body = mock_client.post.await_args_list[1].kwargs["json"]
        post_create_contents = [
            message.get("content", "")
            for message in post_create_body.get("messages", [])
            if isinstance(message, dict)
        ]
        assert any(
            "`create_slice` creates a DRAFT ONLY" in content
            for content in post_create_contents
        )
        assert any(
            "submit_slice(slice_name=\"bench-web\", wait_for_stableok=true, background=true)" in content
            for content in post_create_contents
        )
        assert any("lease_hours=6" in content for content in post_create_contents)

        retry_prompts = []
        for posted in mock_client.post.await_args_list:
            body = posted.kwargs["json"]
            for message in body.get("messages", []):
                content = message.get("content", "")
                if "has not submitted it yet" in content:
                    retry_prompts.append(content)
        assert retry_prompts
        retry_prompt = retry_prompts[-1]
        assert "wait_for_stableok=true" in retry_prompt
        assert "background=true" in retry_prompt
        assert "lease_hours=6" in retry_prompt

        submit_calls = [
            call for call in mock_exec.await_args_list
            if call.args[0] == "submit_slice"
        ]
        assert submit_calls
        assert submit_calls[-1].args[1]["wait_for_stableok"] is True
        assert submit_calls[-1].args[1]["lease_hours"] == 6

    def test_submit_slice_without_conversation_authorization_is_blocked(self, client):
        """Cold submit attempts still need explicit authorization."""
        async def fake_execute(name, arguments, request=None):
            if name == "list_slices":
                return "[]"
            return "{}"

        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, side_effect=fake_execute) as mock_exec, \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            tool_call_resp = _make_llm_response(
                tool_calls=[{
                    "id": "call_submit",
                    "function": {
                        "name": "submit_slice",
                        "arguments": json.dumps({
                            "slice_name": "bench-l2",
                            "lease_hours": 6,
                        }),
                    },
                }],
                finish_reason="tool_calls",
            )
            final_resp = _make_llm_response("FINAL ANSWER\nI need confirmation.")
            mock_client.post = AsyncMock(side_effect=[tool_call_resp, final_resp])
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"choices": [{"delta": {"content": "FINAL ANSWER\\nI need confirmation."}}]}',
                "data: [DONE]",
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{"role": "user", "content": "continue"}],
                "model": "test-model",
            })

        assert resp.status_code == 200
        assert "DESTRUCTIVE_ACTION_BLOCKED" in resp.text
        assert not any(call.args[0] == "submit_slice" for call in mock_exec.await_args_list)

    def test_authorized_over_cap_submit_reaches_backend_for_clamp(self, client):
        """Lease policy clamps in the backend; authorization should not block over-cap intent."""
        async def fake_execute(name, arguments, request=None):
            if name == "list_slices":
                return "[]"
            if name == "submit_slice":
                return json.dumps({
                    "status": "submitted",
                    "state": "Configuring",
                    "warnings": [{
                        "code": "LEASE_CLAMPED_TO_POLICY",
                        "requested_lease_hours": arguments.get("lease_hours"),
                        "effective_lease_hours": 6,
                    }],
                })
            return "{}"

        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch(
                 "app.routes.ai_chat.execute_tool",
                 new_callable=AsyncMock,
                 side_effect=fake_execute,
             ) as mock_exec, \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            tool_call_resp = _make_llm_response(
                tool_calls=[{
                    "id": "call_submit",
                    "function": {
                        "name": "submit_slice",
                        "arguments": json.dumps({
                            "slice_name": "bench-clamp",
                            "lease_hours": 30,
                        }),
                    },
                }],
                finish_reason="tool_calls",
            )
            final_resp = _make_llm_response("FINAL ANSWER\nSubmitted bench-clamp with lease clamp.")
            mock_client.post = AsyncMock(side_effect=[tool_call_resp, final_resp])
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"choices": [{"delta": {"content": "FINAL ANSWER\\nSubmitted bench-clamp."}}]}',
                "data: [DONE]",
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Create and submit a slice named bench-clamp with "
                            "a 30-hour lease, clamped if policy requires it."
                        ),
                    },
                    {"role": "assistant", "content": "Created draft 'bench-clamp'."},
                    {"role": "user", "content": "continue"},
                ],
                "model": "test-model",
            })

        assert resp.status_code == 200
        assert "DESTRUCTIVE_ACTION_BLOCKED" not in resp.text
        submit_calls = [
            call for call in mock_exec.await_args_list
            if call.args[0] == "submit_slice"
        ]
        assert submit_calls
        assert submit_calls[-1].args[1]["lease_hours"] == 30

    def test_delete_slice_without_scoped_confirmation_is_blocked(self, client):
        """Delete remains confirmation-gated for the named slice."""
        async def fake_execute(name, arguments, request=None):
            if name == "list_slices":
                return "[]"
            return "{}"

        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, side_effect=fake_execute) as mock_exec, \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            tool_call_resp = _make_llm_response(
                tool_calls=[{
                    "id": "call_delete",
                    "function": {
                        "name": "delete_slice",
                        "arguments": json.dumps({"slice_name": "old-slice"}),
                    },
                }],
                finish_reason="tool_calls",
            )
            final_resp = _make_llm_response("FINAL ANSWER\nPlease confirm deletion.")
            mock_client.post = AsyncMock(side_effect=[tool_call_resp, final_resp])
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"choices": [{"delta": {"content": "FINAL ANSWER\\nPlease confirm deletion."}}]}',
                "data: [DONE]",
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{"role": "user", "content": "delete slice old-slice"}],
                "model": "test-model",
            })

        assert resp.status_code == 200
        assert "DESTRUCTIVE_ACTION_BLOCKED" in resp.text
        assert not any(call.args[0] == "delete_slice" for call in mock_exec.await_args_list)

    def test_explicit_custom_agent_is_authoritative(self, client, storage_dir):
        """A selected custom agent should outrank automatic query context."""
        import app.routes.ai_chat as ai_chat_mod

        custom_dir = storage_dir / ".loomai" / "agents"
        custom_dir.mkdir(parents=True)
        (custom_dir / "bare-json.md").write_text(
            "---\n"
            "name: Bare JSON\n"
            "description: Return only JSON\n"
            "---\n"
            "Return exactly one bare JSON object. Do not use FINAL ANSWER, "
            "markdown, tools-used text, or prose."
        )
        ai_chat_mod._agents_cache = None
        _set_assistant_flags(
            strict_fabric_query_contract=True,
            compact_fabric_resource_tools=True,
        )

        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock) as mock_exec, \
             patch("app.routes.ai_chat.ai_client") as mock_client, \
             patch("app.rag.refresh_index_if_stale", new_callable=AsyncMock):

            mock_client.post = AsyncMock(return_value=_make_llm_response('{"ok": true}'))
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"choices": [{"delta": {"content": "{\\"ok\\": true}"}}]}',
                "data: [DONE]",
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{"role": "user", "content": "list all available sites"}],
                "model": "test-model",
                "agent": "bare-json",
            })

        assert resp.status_code == 200
        mock_exec.assert_not_called()
        sent_body = mock_client.post.call_args.kwargs["json"]
        system_prompt = sent_body["messages"][0]["content"]
        assert system_prompt.startswith("## Selected Agent: Bare JSON")
        assert "Return exactly one bare JSON object" in system_prompt
        assert "## Current Data" not in system_prompt
        assert "## Tool Use" not in system_prompt
        assert "fabric-query-reporter" not in system_prompt
        assert "FABRIC Slice Operator" not in system_prompt

    def test_slice_creation_intent_auto_routes_to_operator_agent(self, client):
        """Slice lifecycle intents should use the built-in operator by default."""
        async def fake_execute(name, arguments, request=None):
            if name == "list_slices":
                return "[]"
            if name == "create_slice":
                return json.dumps({
                    "status": "created",
                    "name": arguments["name"],
                    "state": "Draft",
                })
            return "{}"

        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, side_effect=fake_execute), \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock(return_value=_make_llm_response("Draft created."))
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"choices": [{"delta": {"content": "Draft created."}}]}',
                "data: [DONE]",
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{"role": "user", "content": "create a new slice named bench-op"}],
                "model": "test-model",
            })

        assert resp.status_code == 200
        sent_body = mock_client.post.call_args.kwargs["json"]
        system_prompt = sent_body["messages"][0]["content"]
        assert "## Active Agent: FABRIC Slice Operator" in system_prompt
        assert "carry out live FABRIC" in system_prompt

    def test_query_sites_tool_returns_compact_envelope(self, client):
        """query_sites should return bounded compact rows plus raw evidence ref."""
        from app.routes.ai_chat import execute_tool

        _set_assistant_flags(compact_fabric_resource_tools=True)
        payload = json.loads(_run_async(execute_tool("query_sites", {})))

        assert payload["source"] == "resources.list_sites"
        assert "summary" in payload
        assert "rows" in payload
        assert "raw_evidence_ref" in payload
        assert payload["raw_evidence_ref"].startswith("cache://fabric-resource-query/")
        if payload["rows"]:
            first = payload["rows"][0]
            assert "site" in first
            assert "cores_available" in first
            assert "ram_available_gb" in first
            assert "disk_available_gb" in first
            assert "gpus" in first
            assert "gpu_components" in first

    def test_compact_query_sites_derives_gpu_counts_from_host_details(self, client):
        """Compact query_sites should surface GPUs even when site aggregates are zero."""
        from app.routes.ai_chat import execute_tool

        mock_sites = [{
            "name": "RENC",
            "state": "Active",
            "cores_available": 100,
            "ram_available": 512,
            "disk_available": 2000,
            "components": {
                "GPU_A30": {"available": 0},
                "GPU_A40": {"available": 1},
                "NIC_Basic": {"available": 4},
            },
            "hosts_detail": [
                {"name": "renc-w1", "components": {"GPU_A30": {"available": 2}}},
                {"name": "renc-w2", "components": {
                    "GPU_A40": {"available": 1},
                    "GPU_RTX6000": {"available": 1},
                }},
            ],
        }]

        _set_assistant_flags(compact_fabric_resource_tools=True)
        with patch("app.routes.resources.list_sites", new_callable=AsyncMock, return_value=mock_sites):
            payload = json.loads(_run_async(execute_tool("query_sites", {})))

        row = payload["rows"][0]
        assert row["site"] == "RENC"
        assert row["gpus"] == 4
        assert row["gpu_components"] == {"GPU_A30": 2, "GPU_A40": 1, "GPU_RTX6000": 1}
        assert row["has_available_gpus"] is True
        assert row["notable_components"]["NIC_Basic"] == 4
        assert payload["summary"]["gpu_site_count"] == 1
        assert payload["summary"]["gpu_total_available"] == 4
        assert payload["gpu_sites"] == ["RENC"]

    def test_fabric_query_final_answer_retry(self, client):
        """Incomplete FABRIC query final answers should retry once without tools."""
        _set_assistant_flags(final_answer_retry=True)
        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, return_value='{"slices": []}') as mock_exec, \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock(side_effect=[
                _make_llm_response("I'll check one more site."),
                _make_llm_response(
                    "FINAL ANSWER\n"
                    "Request: checked NOT_A_FABRIC_SITE.\n"
                    "Result: NOT_A_FABRIC_SITE is invalid and not found."
                ),
            ])
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                "data: [DONE]",
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{"role": "user", "content": "Is NOT_A_FABRIC_SITE a valid FABRIC site?"}],
                "model": "test-model",
                "agent": "fabric-query-reporter",
            })
            assert resp.status_code == 200
            assert "NOT_A_FABRIC_SITE is invalid" in resp.text
            assert '"final_answer_retry_count": 1' in resp.text
            assert mock_client.post.await_count == 2
            # list_slices prefetch may run, but the retry itself must not execute tools again.
            assert mock_exec.await_count <= 1

    def test_empty_strict_answer_retries_without_contract(self, client):
        """Empty strict-query answers should retry once as marked best-effort."""
        _set_assistant_flags(
            strict_fabric_query_contract=True,
            final_answer_retry=True,
            final_answer_retry_scope="all",
        )
        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, return_value='[{"name": "RENC"}]'), \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock(side_effect=[
                _make_llm_response(""),
                _make_llm_response(
                    "RENC has available GPU resources. Tools used: query_sites."
                ),
            ])
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"choices": [{"delta": {"content": "should not stream"}}]}',
                "data: [DONE]",
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{"role": "user", "content": "Which FABRIC sites have GPUs available?"}],
                "model": "test-model",
            })

        assert resp.status_code == 200
        assert "RENC has available GPU resources" in resp.text
        assert '"final_answer_retry_count": 1' in resp.text
        assert '"final_answer_best_effort": true' in resp.text
        assert '"incomplete_response_after_retry": false' in resp.text
        assert not mock_client.stream.called

        retry_body = mock_client.post.await_args_list[1].kwargs["json"]
        retry_prompt = retry_body["messages"][-1]["content"]
        assert "Do not use the strict FINAL ANSWER contract" in retry_prompt
        assert "return only the FINAL ANSWER" not in retry_prompt

    def test_final_answer_retry_warning_stays_out_of_content(self, client):
        """Incomplete-after-retry state should be metadata, not answer text."""
        _set_assistant_flags(final_answer_retry=True)
        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, return_value='{"slices": []}'), \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock(side_effect=[
                _make_llm_response("I'll check one more site."),
                _make_llm_response("FINAL ANSWER\nI cannot tell."),
            ])
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                "data: [DONE]",
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{"role": "user", "content": "Is NOT_A_FABRIC_SITE a valid FABRIC site?"}],
                "model": "test-model",
                "agent": "fabric-query-reporter",
            })

        assert resp.status_code == 200
        assert "FINAL ANSWER" in resp.text
        assert "LoomAI warning: final answer may still be incomplete" not in resp.text
        assert '"final_answer_retry_count": 1' in resp.text
        assert '"incomplete_response_after_retry": true' in resp.text

    def test_host_threshold_retry_appends_collected_hosts(self, client):
        """Threshold queries should not rely on weak models to enumerate every host."""
        _set_assistant_flags(
            strict_fabric_query_contract=True,
            final_answer_retry=True,
            final_answer_retry_scope="all",
            compact_fabric_resource_tools=True,
        )
        mock_sites = [{
            "name": "TACC",
            "state": "Active",
            "hosts_detail": [
                {"name": "host-a", "cores_available": 32, "ram_available": 128, "disk_available": 500},
                {"name": "host-b", "cores_available": 32, "ram_available": 96, "disk_available": 500},
                {"name": "host-c", "cores_available": 32, "ram_available": 32, "disk_available": 500},
            ],
        }]

        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.resources.list_sites", new_callable=AsyncMock, return_value=mock_sites), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, return_value='[]'), \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock(side_effect=[
                _make_llm_response("FINAL ANSWER\nhost-a has enough RAM."),
                _make_llm_response("FINAL ANSWER\nhost-a has enough RAM."),
            ])
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                "data: [DONE]",
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{"role": "user", "content": "Which hosts have at least 64 GB RAM available? Limit 2 hosts."}],
                "model": "test-model",
            })

        assert resp.status_code == 200
        assert "host-a" in resp.text
        assert "host-b" in resp.text
        assert "LoomAI completed host-threshold enumeration" in resp.text
        assert '"host_threshold_completion_applied": true' in resp.text
        assert '"incomplete_response_after_retry": false' in resp.text

        retry_body = mock_client.post.await_args_list[1].kwargs["json"]
        retry_prompt = retry_body["messages"][-1]["content"]
        assert "missing benchmark-visible host(s): host-b" in retry_prompt
        assert "Host rows that must be enumerated exactly" in retry_prompt
        assert "host-b at TACC" in retry_prompt

    def test_valid_fabric_query_answer_is_not_regenerated_for_streaming(self, client):
        """The emitted answer should be the non-streaming answer that passed validation."""
        _set_assistant_flags(
            strict_fabric_query_contract=True,
            final_answer_retry=True,
            final_answer_retry_scope="all",
        )
        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, return_value='[{"name": "RENC", "cores_available": 10}]'), \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock(return_value=_make_llm_response(
                "FINAL ANSWER\nRENC has available resources."
            ))
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"choices": [{"delta": {"content": "different answer"}}]}',
                "data: [DONE]",
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{"role": "user", "content": "what sites are available?"}],
                "model": "test-model",
            })

        assert resp.status_code == 200
        assert "RENC has available resources" in resp.text
        assert "different answer" not in resp.text
        assert not mock_client.stream.called

    def test_stream_forwards_generation_controls(self, client):
        """POST /api/ai/chat/stream should forward generation controls."""
        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, return_value='{"slices": []}'), \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock(return_value=_make_llm_response("Hi there!"))
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"choices": [{"delta": {"content": "Hi"}}]}',
                "data: [DONE]",
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{"role": "user", "content": "hello"}],
                "model": "test-model",
                "temperature": 0.0,
                "top_p": 0.9,
                "max_output_tokens": 4096,
            })
            assert resp.status_code == 200

            sent_body = mock_client.post.call_args.kwargs["json"]
            assert sent_body["temperature"] == 0.0
            assert sent_body["top_p"] == 0.9
            assert sent_body["max_tokens"] == 4096
            assert "generation_config_applied" in resp.text

    def test_stream_applies_resource_query_generation_defaults(self, client):
        """Configured D3 defaults should apply to resource queries and metadata."""
        _set_assistant_flags(
            resource_query_generation_defaults=True,
            resource_query_generation={
                "default": {
                    "temperature": 0.1,
                    "top_p": 0.95,
                    "max_output_tokens": 4096,
                },
                "models": {
                    "test-model": {
                        "temperature": 0.0,
                        "max_output_tokens": 8192,
                    },
                },
            },
        )
        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, return_value='{"sites": []}'), \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock(return_value=_make_llm_response("FINAL ANSWER\nNo sites found."))
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"choices": [{"delta": {"content": "FINAL ANSWER\\nNo sites found."}}]}',
                "data: [DONE]",
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{"role": "user", "content": "what FABRIC sites have RAM available?"}],
                "model": "test-model",
            })
            assert resp.status_code == 200

            sent_body = mock_client.post.call_args.kwargs["json"]
            assert sent_body["temperature"] == 0.0
            assert sent_body["top_p"] == 0.95
            assert sent_body["max_tokens"] == 8192
            assert '"generation_config_defaults_applied"' in resp.text
            assert '"max_output_tokens": 8192' in resp.text

    def test_responses_model_uses_responses_payload_shape(self, client):
        """Known Responses-only model names should use input/max_output_tokens."""
        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, return_value='{"slices": []}'), \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock(return_value=_make_responses_llm_response("Hi"))
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"type": "response.output_text.delta", "delta": "Hi"}',
                'data: {"type": "response.completed"}',
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{"role": "user", "content": "hello"}],
                "model": "gpt-5.5",
                "temperature": 0.0,
                "top_p": 0.9,
                "max_output_tokens": 2048,
            })
            assert resp.status_code == 200

            endpoint = mock_client.post.call_args.args[0]
            sent_body = mock_client.post.call_args.kwargs["json"]
            assert endpoint.endswith("/v1/responses")
            assert "input" in sent_body
            assert "messages" not in sent_body
            assert "temperature" not in sent_body
            assert sent_body["top_p"] == 0.9
            assert sent_body["max_output_tokens"] == 2048
            assert '"strip_temperature": true' in resp.text

    def test_responses_input_drops_orphan_function_outputs(self):
        """Responses API replay must not send tool outputs without prior calls."""
        from app.routes.ai_chat import _build_responses_input

        conversation = [
            {"role": "system", "content": "sys"},
            {"type": "function_call_output", "call_id": "call_missing", "output": "{}"},
            {"type": "function_call", "id": "fc_ok", "call_id": "call_ok",
             "name": "query_sites", "arguments": "{}", "status": "completed"},
            {"type": "function_call_output", "call_id": "call_ok", "output": "[]"},
        ]

        _instructions, input_items = _build_responses_input(conversation)

        assert not any(
            item.get("type") == "function_call_output" and item.get("call_id") == "call_missing"
            for item in input_items
        )
        function_call = next(item for item in input_items if item.get("type") == "function_call")
        assert function_call["id"] == "fc_ok"
        assert function_call["call_id"] == "call_ok"
        assert function_call["status"] == "completed"
        assert any(
            item.get("type") == "function_call_output" and item.get("call_id") == "call_ok"
            for item in input_items
        )

    def test_prompt_lease_duration_applies_to_lifecycle_tools(self):
        """Lifecycle tools should inherit explicit short lease requests."""
        from app.routes.ai_chat import _apply_prompt_lease_duration

        prompt = "Create and submit a benchmark slice with a 6-hour lease."

        create_args = _apply_prompt_lease_duration("create_slice", {"name": "bench"}, prompt)
        submit_args = _apply_prompt_lease_duration(
            "submit_slice",
            {"slice_name": "bench", "end_date": "2099-01-01T00:00:00Z"},
            prompt,
        )
        renew_args = _apply_prompt_lease_duration(
            "renew_slice",
            {"slice_name": "bench", "days": 7, "lease_end": "2099-01-01T00:00:00Z"},
            prompt,
        )

        assert create_args["lease_hours"] == 6
        assert submit_args["lease_hours"] == 6
        assert "end_date" not in submit_args
        assert renew_args["hours"] == 6
        assert "days" not in renew_args
        assert "lease_end" not in renew_args

        equals_args = _apply_prompt_lease_duration("submit_slice", {"slice_name": "bench"}, "--lease-hours=6")
        word_args = _apply_prompt_lease_duration("submit_slice", {"slice_name": "bench"}, "Use a six hour lease")

        assert equals_args["lease_hours"] == 6
        assert word_args["lease_hours"] == 6

    def test_responses_input_preserves_reasoning_items(self):
        """Responses API replay must keep provider reasoning items in order."""
        from app.routes.ai_chat import _build_responses_input

        reasoning_item = {
            "type": "reasoning",
            "id": "rs_ok",
            "summary": [{"type": "summary_text", "text": "Use the site query tool."}],
            "status": "completed",
        }
        conversation = [
            {"role": "system", "content": "sys"},
            reasoning_item,
            {"type": "function_call", "id": "fc_ok", "call_id": "call_ok",
             "name": "query_sites", "arguments": "{}", "status": "completed"},
            {"type": "function_call_output", "call_id": "call_ok", "output": "[]"},
        ]

        _instructions, input_items = _build_responses_input(conversation)

        assert input_items[0] == reasoning_item
        assert input_items[1]["type"] == "function_call"
        assert input_items[1]["id"] == "fc_ok"
        assert input_items[2]["type"] == "function_call_output"

    def test_responses_tool_continuation_preserves_provider_call_item(self, client):
        """Responses tool loops should replay provider function_call id/status."""
        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, return_value='[{"name": "RENC"}]'), \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock(side_effect=[
                _make_responses_llm_response("", tool_calls=[{
                    "id": "call_resp_1",
                    "responses_id": "fc_resp_1",
                    "status": "completed",
                    "function": {"name": "query_sites", "arguments": "{}"},
                }]),
                _make_responses_llm_response("FINAL ANSWER\nRENC is available."),
            ])
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"type": "response.output_text.delta", "delta": "FINAL ANSWER\\nRENC is available."}',
                'data: {"type": "response.completed"}',
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{"role": "user", "content": "please use a tool and report back"}],
                "model": "gpt-5.5",
            })

        assert resp.status_code == 200
        assert mock_client.post.await_count == 2
        second_body = mock_client.post.await_args_list[1].kwargs["json"]
        input_items = second_body["input"]
        function_call = next(item for item in input_items if item.get("type") == "function_call")
        assert function_call["id"] == "fc_resp_1"
        assert function_call["call_id"] == "call_resp_1"
        assert function_call["status"] == "completed"
        assert any(
            item.get("type") == "function_call_output" and item.get("call_id") == "call_resp_1"
            for item in input_items
        )

    def test_responses_tool_continuation_replays_reasoning_before_call(self, client):
        """Responses tool loops should replay reasoning items before linked calls."""
        reasoning_item = {
            "type": "reasoning",
            "id": "rs_resp_1",
            "summary": [{"type": "summary_text", "text": "Need resource data."}],
            "status": "completed",
        }
        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, return_value='[{"name": "RENC"}]'), \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock(side_effect=[
                _make_responses_llm_response("", reasoning_items=[reasoning_item], tool_calls=[{
                    "id": "call_resp_1",
                    "responses_id": "fc_resp_1",
                    "status": "completed",
                    "function": {"name": "query_sites", "arguments": "{}"},
                }]),
                _make_responses_llm_response("FINAL ANSWER\nRENC is available."),
            ])
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"type": "response.output_text.delta", "delta": "FINAL ANSWER\\nRENC is available."}',
                'data: {"type": "response.completed"}',
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{"role": "user", "content": "please use a tool and report back"}],
                "model": "gpt-5.5",
            })

        assert resp.status_code == 200
        assert mock_client.post.await_count == 2
        second_body = mock_client.post.await_args_list[1].kwargs["json"]
        input_items = second_body["input"]
        reasoning_index = next(
            i for i, item in enumerate(input_items)
            if item.get("type") == "reasoning" and item.get("id") == "rs_resp_1"
        )
        function_index = next(
            i for i, item in enumerate(input_items)
            if item.get("type") == "function_call" and item.get("id") == "fc_resp_1"
        )
        output_index = next(
            i for i, item in enumerate(input_items)
            if item.get("type") == "function_call_output" and item.get("call_id") == "call_resp_1"
        )
        assert reasoning_index < function_index < output_index
        assert input_items[reasoning_index] == reasoning_item

    def test_stream_applies_capability_profile(self, client, storage_dir):
        """P6 capability profiles should tune endpoint style and defaults."""
        profile_path = storage_dir / "model_capabilities.json"
        profile_path.write_text(json.dumps({
            "schema_version": 1,
            "profiles": [{
                "model_key": "profile-model",
                "provider": "fabric",
                "capabilities": {
                    "endpoint_style": "responses",
                    "context_window_tokens": {"value": 65536, "source": "probe"},
                    "interaction_features": {
                        "tool_calling": {"supported": False, "source": "probe"},
                    },
                },
                "recommended_configuration": {
                    "config_id": "profile-model-test",
                    "context_window_tokens": 65536,
                    "max_output_tokens": 3072,
                    "temperature": 0.0,
                    "top_p": 0.8,
                },
            }],
        }))
        _set_assistant_flags(
            capability_profiles_enabled=True,
            capability_profile_path=str(profile_path),
        )
        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, return_value='{"slices": []}'), \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock(return_value=_make_responses_llm_response("Hi"))
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"type": "response.output_text.delta", "delta": "Hi"}',
                'data: {"type": "response.completed"}',
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{"role": "user", "content": "hello"}],
                "model": "profile-model",
            })
            assert resp.status_code == 200

            endpoint = mock_client.post.call_args.args[0]
            sent_body = mock_client.post.call_args.kwargs["json"]
            assert endpoint.endswith("/v1/responses")
            assert sent_body["temperature"] == 0.0
            assert sent_body["top_p"] == 0.8
            assert sent_body["max_output_tokens"] == 3072
            assert "tools" not in sent_body
            assert '"context_window_tokens": 65536' in resp.text
            assert '"config_id": "profile-model-test"' in resp.text

    def test_stream_adjusts_implausible_capability_profile_budget(self, client, storage_dir):
        """32K profiles must not reserve the whole context for output."""
        profile_path = storage_dir / "bad_model_capabilities.json"
        profile_path.write_text(json.dumps({
            "schema_version": 1,
            "profiles": [{
                "model_key": "nrp:qwen3",
                "provider": "nrp",
                "capabilities": {
                    "endpoint_style": "chat-completions",
                    "context_window_tokens": {"value": 32768, "source": "derived"},
                    "max_input_tokens": {"value": 1024, "source": "derived"},
                    "max_output_tokens": {"value": 32768, "source": "probe"},
                },
                "recommended_configuration": {
                    "context_window_tokens": 32768,
                    "max_input_tokens": 1024,
                    "max_output_tokens": 32768,
                    "temperature": 0.0,
                    "top_p": 0.9,
                },
            }],
        }))
        _set_assistant_flags(
            capability_profiles_enabled=True,
            capability_profile_path=str(profile_path),
        )
        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat._get_nrp_api_key", return_value="fake-nrp-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, return_value='[]'), \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock(return_value=_make_llm_response("Hi"))
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"choices": [{"delta": {"content": "Hi"}}]}',
                "data: [DONE]",
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{"role": "user", "content": "hello"}],
                "model": "nrp:qwen3",
            })
            assert resp.status_code == 200

            sent_body = mock_client.post.call_args.kwargs["json"]
            assert sent_body["max_tokens"] == 8192
            assert '"field": "max_input_tokens"' in resp.text
            assert '"field": "max_output_tokens"' in resp.text
            assert '"applied_value": 8192' in resp.text

    def test_stream_rebalances_reasoning_model_budget(self, client, storage_dir):
        """Reasoning models need output headroom for thinking plus visible text."""
        profile_path = storage_dir / "glm_model_capabilities.json"
        profile_path.write_text(json.dumps({
            "schema_version": 1,
            "profiles": [{
                "model_key": "nrp:glm-5",
                "provider": "nrp",
                "capabilities": {
                    "endpoint_style": "chat-completions",
                    "context_window_tokens": {"value": 32768, "source": "probe"},
                    "reasoning_model": {"supported": True, "source": "probe"},
                },
                "recommended_configuration": {
                    "context_window_tokens": 32768,
                    "max_input_tokens": 24576,
                    "max_output_tokens": 8192,
                    "temperature": 0.0,
                    "top_p": 0.9,
                },
            }],
        }))
        _set_assistant_flags(
            capability_profiles_enabled=True,
            capability_profile_path=str(profile_path),
        )
        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat._get_nrp_api_key", return_value="fake-nrp-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, return_value='[]'), \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock(return_value=_make_llm_response("FINAL ANSWER\nHi"))
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"choices": [{"delta": {"content": "FINAL ANSWER\\nHi"}}]}',
                "data: [DONE]",
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{"role": "user", "content": "hello"}],
                "model": "nrp:glm-5",
            })
            assert resp.status_code == 200

            sent_body = mock_client.post.call_args.kwargs["json"]
            assert sent_body["max_tokens"] == 24576
            assert sent_body["reasoning_effort"] == "high"
            assert '"reasoning_budget_mode": "output_preferred"' in resp.text
            assert '"reasoning_effort": "high"' in resp.text
            assert '"field": "reasoning_effort"' in resp.text
            assert '"profile_value": 8192' in resp.text
            assert '"applied_value": 24576' in resp.text
            assert '"profile_value": 24576' in resp.text
            assert '"applied_value": 8192' in resp.text

    def test_stream_retries_zero_visible_reasoning_output_with_minimal_effort(self, client):
        """Zero visible output from GLM-5 should retry with reduced reasoning."""
        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat._get_nrp_api_key", return_value="fake-nrp-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, return_value='[]'), \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock(side_effect=[
                _make_llm_response(""),
                _make_llm_response("FINAL ANSWER\nHi"),
            ])
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"choices": [{"delta": {"content": "FINAL ANSWER\\nHi"}}]}',
                "data: [DONE]",
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{"role": "user", "content": "hello"}],
                "model": "nrp:glm-5",
            })
            assert resp.status_code == 200

            first_body = mock_client.post.await_args_list[0].kwargs["json"]
            second_body = mock_client.post.await_args_list[1].kwargs["json"]
            assert first_body["reasoning_effort"] == "high"
            assert second_body["reasoning_effort"] == "minimal"
            assert mock_client.post.await_count == 2
            assert '"zero_visible_output_retry_count": 1' in resp.text
            assert '"source": "zero_visible_output_retry"' in resp.text
            assert '"reasoning_effort": "minimal"' in resp.text

    def test_stream_drops_unsupported_reasoning_effort(self, client, storage_dir):
        """If a provider rejects reasoning_effort, retry without it."""
        error_resp = MagicMock()
        error_resp.status_code = 400
        error_resp.text = "Unsupported parameter: reasoning_effort"

        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat._get_nrp_api_key", return_value="fake-nrp-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, return_value='[]'), \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock(side_effect=[
                error_resp,
                _make_llm_response("FINAL ANSWER\nHi"),
            ])
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"choices": [{"delta": {"content": "FINAL ANSWER\\nHi"}}]}',
                "data: [DONE]",
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{"role": "user", "content": "hello"}],
                "model": "nrp:glm-5",
            })
            assert resp.status_code == 200

            first_body = mock_client.post.await_args_list[0].kwargs["json"]
            second_body = mock_client.post.await_args_list[1].kwargs["json"]
            assert first_body["reasoning_effort"] == "high"
            assert "reasoning_effort" not in second_body
            assert '"reasoning_controls_disabled": true' in resp.text

    def test_stream_retries_transient_provider_5xx(self, client):
        """Transient provider 5xx responses should retry before failing."""
        error_resp = MagicMock()
        error_resp.status_code = 503
        error_resp.text = "gateway temporarily unavailable"

        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat._get_nrp_api_key", return_value=""), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, return_value="[]"), \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock(side_effect=[
                error_resp,
                _make_llm_response("FINAL ANSWER\nRecovered."),
            ])
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"choices": [{"delta": {"content": "FINAL ANSWER\\nRecovered."}}]}',
                "data: [DONE]",
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{"role": "user", "content": "hello"}],
                "model": "test-model",
            })

        assert resp.status_code == 200
        assert mock_client.post.await_count == 2
        assert '"provider_retry_count": 1' in resp.text
        assert "FINAL ANSWER" in resp.text

    def test_stream_tags_transient_provider_error_after_retries(self, client):
        """A persistent provider 5xx should be tagged as transient in SSE."""
        error_resp = MagicMock()
        error_resp.status_code = 503
        error_resp.text = "gateway temporarily unavailable"

        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat._get_nrp_api_key", return_value=""), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, return_value="[]"), \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock(side_effect=[error_resp, error_resp, error_resp])
            mock_client.stream = MagicMock()

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{"role": "user", "content": "hello"}],
                "model": "test-model",
            })

        assert resp.status_code == 200
        assert mock_client.post.await_count == 3
        assert '"error_type": "transient"' in resp.text
        assert '"retryable": true' in resp.text
        assert '"provider_retry_count": 2' in resp.text
        assert "LLM error 503" in resp.text

    def test_stream_emits_token_expired_event_for_tool_result(self, client):
        """FABRIC token-expiry tool errors should stop with TOKEN_EXPIRED SSE."""
        async def fake_execute(name, arguments, request=None):
            if name == "list_slices":
                return "[]"
            return json.dumps({
                "error": "401 Unauthorized: token expired",
                "status_code": 401,
            })

        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, side_effect=fake_execute), \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock(return_value=_make_llm_response(
                tool_calls=[{
                    "id": "call_slice",
                    "function": {
                        "name": "get_slice",
                        "arguments": json.dumps({"slice_name": "expired-token-slice"}),
                    },
                }],
                finish_reason="tool_calls",
            ))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{"role": "user", "content": "Inspect expired-token-slice with get_slice."}],
                "model": "test-model",
            })

        assert resp.status_code == 200
        assert '"event": "TOKEN_EXPIRED"' in resp.text
        assert '"error_code": "TOKEN_EXPIRED"' in resp.text
        assert '"tool": "get_slice"' in resp.text

    def test_stream_emits_ready_event_for_completed_background_job(self, client):
        """A ready get_job_status result should emit a compact ready SSE event."""
        async def fake_execute(name, arguments, request=None):
            if name == "list_slices":
                return "[]"
            if name == "get_job_status":
                return json.dumps({
                    "job_id": arguments["job_id"],
                    "kind": "submit_slice",
                    "slice_name": "bench-ready",
                    "status": "ready",
                    "ready": True,
                    "done": True,
                    "slice_state": "StableOK",
                    "result": {"name": "bench-ready", "state": "StableOK"},
                })
            return "{}"

        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, side_effect=fake_execute), \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock(side_effect=[
                _make_llm_response(
                    tool_calls=[{
                        "id": "call_job",
                        "function": {
                            "name": "get_job_status",
                            "arguments": json.dumps({"job_id": "job-ready"}),
                        },
                    }],
                    finish_reason="tool_calls",
                ),
                _make_llm_response("bench-ready is StableOK."),
            ])
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"choices": [{"delta": {"content": "bench-ready is StableOK."}}]}',
                "data: [DONE]",
            ]))

            resp = client.post("/api/ai/chat/stream", json={
                "messages": [{"role": "user", "content": "Check job-ready."}],
                "model": "test-model",
            })

        assert resp.status_code == 200
        assert '"ready": {' in resp.text
        assert '"job_id": "job-ready"' in resp.text
        assert '"slice_name": "bench-ready"' in resp.text
        assert '"slice_state": "StableOK"' in resp.text

    def test_chat_session_persists_hidden_tool_context_for_continue(self, client, storage_dir):
        """Server-side chat sessions should replay hidden tool results on later turns."""
        from app.chat_sessions import delete_chat_session, load_chat_session

        session_id = "conv-c2-persist"
        delete_chat_session(session_id)

        async def fake_execute(name, arguments, request=None):
            if name == "list_slices":
                return "[]"
            if name == "get_slice":
                return json.dumps({"name": "bench-c2", "state": "StableOK"})
            return "{}"

        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, side_effect=fake_execute), \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock(side_effect=[
                _make_llm_response(
                    tool_calls=[{
                        "id": "call_slice",
                        "function": {
                            "name": "get_slice",
                            "arguments": json.dumps({"slice_name": "bench-c2"}),
                        },
                    }],
                    finish_reason="tool_calls",
                ),
                _make_llm_response("bench-c2 is StableOK."),
            ])
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"choices": [{"delta": {"content": "bench-c2 is StableOK."}}]}',
                "data: [DONE]",
            ]))

            first = client.post("/api/ai/chat/stream", json={
                "conversation_id": session_id,
                "messages": [{"role": "user", "content": "Inspect bench-c2."}],
                "model": "test-model",
            })

        assert first.status_code == 200
        stored = load_chat_session(session_id)
        assert stored is not None
        assert any(
            msg.get("role") == "tool" and "StableOK" in msg.get("content", "")
            for msg in stored["messages"]
        )

        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, side_effect=fake_execute), \
             patch("app.routes.ai_chat.ai_client") as mock_client:

            mock_client.post = AsyncMock(return_value=_make_llm_response("The stored state was StableOK."))
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"choices": [{"delta": {"content": "The stored state was StableOK."}}]}',
                "data: [DONE]",
            ]))

            second = client.post("/api/ai/chat/stream", json={
                "conversation_id": session_id,
                "messages": [
                    {"role": "user", "content": "Inspect bench-c2."},
                    {"role": "assistant", "content": "bench-c2 is StableOK."},
                    {"role": "user", "content": "Continue from that result. What state was it?"},
                ],
                "model": "test-model",
            })

        assert second.status_code == 200
        posted_messages = mock_client.post.await_args.kwargs["json"]["messages"]
        assert any(
            msg.get("role") == "tool" and "StableOK" in msg.get("content", "")
            for msg in posted_messages
        )
        assert posted_messages[-1]["role"] == "user"
        assert "What state was it?" in posted_messages[-1]["content"]
        delete_chat_session(session_id)

    def test_fabric_query_validation_requires_threshold_hosts(self):
        from app.routes.ai_chat import _validate_fabric_query_final_answer

        tool_outputs = [("get_site_hosts", json.dumps({
            "rows": [
                {"host": "host-a", "site": "TACC", "ram_available_gb": 128},
                {"host": "host-b", "site": "TACC", "ram_available_gb": 96},
                {"host": "host-c", "site": "TACC", "ram_available_gb": 32},
            ]
        }))]

        reasons = _validate_fabric_query_final_answer(
            "FINAL ANSWER\nhost-a has enough RAM.",
            "Which hosts have at least 64 GB RAM? Limit 2 hosts.",
            ["get_site_hosts"],
            tool_outputs,
        )

        assert any("host-b" in reason for reason in reasons)

    def test_threshold_host_terms_accept_legacy_resource_fields(self):
        from app.routes.ai_chat import _expected_host_terms

        tool_outputs = [("get_site_hosts", json.dumps([
            {"name": "legacy-a", "site": "TACC", "ram_available": 128},
            {"name": "legacy-b", "site": "TACC", "ram_available": 96},
            {"name": "legacy-c", "site": "TACC", "ram_available": 32},
        ]))]

        terms = _expected_host_terms(
            tool_outputs,
            "Which hosts have at least 64 GB RAM? Limit 2 hosts.",
        )

        assert terms == ["legacy-a", "legacy-b"]

    def test_fabric_query_validation_requires_slice_names(self):
        from app.routes.ai_chat import _validate_fabric_query_final_answer

        tool_outputs = [("list_slices", json.dumps([
            {"name": "slice-one", "state": "StableOK"},
            {"name": "slice-two", "state": "Configuring"},
        ]))]

        reasons = _validate_fabric_query_final_answer(
            "FINAL ANSWER\nslice-one is StableOK.",
            "What slices do I have?",
            ["list_slices"],
            tool_outputs,
        )

        assert any("slice-two" in reason for reason in reasons)

    def test_stream_rejects_missing_user_message(self, client):
        """POST /api/ai/chat/stream should reject bodies with no user turn."""
        invalid_bodies = [
            {"messages": [], "model": "test-model"},
            {"message": "hello", "model": "test-model"},
            {"messages": [{"role": "assistant", "content": "hello"}], "model": "test-model"},
            {"messages": [{"role": "user", "content": "   "}], "model": "test-model"},
        ]

        for body in invalid_bodies:
            resp = client.post("/api/ai/chat/stream", json=body)
            assert resp.status_code == 422
            assert "messages" in resp.json()["detail"]


class TestConsentRules:
    """Word-boundary matching, latest-turn confirmation, pending action."""

    @pytest.fixture(autouse=True)
    def _clear_pending(self):
        from app import assistant_consent
        assistant_consent._pending.clear()
        yield
        assistant_consent._pending.clear()

    def _run(self, client, messages, tool_name, tool_args, conversation_id=None):
        async def fake_execute(name, arguments, request=None):
            if name == "list_slices":
                return "[]"
            return json.dumps({"status": "ok", "tool": name})

        with patch("app.routes.ai_chat._get_ai_api_key", return_value="fake-key"), \
             patch("app.routes.ai_chat.execute_tool", new_callable=AsyncMock, side_effect=fake_execute) as mock_exec, \
             patch("app.routes.ai_chat.ai_client") as mock_client:
            tool_call_resp = _make_llm_response(
                tool_calls=[{
                    "id": "call_1",
                    "function": {"name": tool_name, "arguments": json.dumps(tool_args)},
                }],
                finish_reason="tool_calls",
            )
            final_resp = _make_llm_response("FINAL ANSWER\nDone.")
            mock_client.post = AsyncMock(side_effect=[tool_call_resp, final_resp])
            mock_client.stream = MagicMock(return_value=_make_stream_ctx([
                'data: {"choices": [{"delta": {"content": "FINAL ANSWER\\nDone."}}]}',
                "data: [DONE]",
            ]))
            body = {"messages": messages, "model": "test-model"}
            if conversation_id:
                body["conversation_id"] = conversation_id
            resp = client.post("/api/ai/chat/stream", json=body)
        assert resp.status_code == 200
        executed = any(call.args[0] == tool_name for call in mock_exec.await_args_list)
        return resp.text, executed

    def test_testbed_wording_does_not_authorize_submit(self, client):
        # "testbed" used to satisfy the "test" proof term via substring match.
        text, executed = self._run(
            client,
            [{"role": "user", "content": "Set up a slice named bench on the FABRIC testbed with two nodes"}],
            "submit_slice", {"slice_name": "bench"},
        )
        assert "DESTRUCTIVE_ACTION_BLOCKED" in text
        assert not executed

    def test_look_at_slice_does_not_confirm_delete(self, client):
        # "look" used to satisfy the "ok" confirmation term via substring match.
        text, executed = self._run(
            client,
            [{"role": "user", "content": "look at slice old-slice and remove it"}],
            "delete_slice", {"slice_name": "old-slice"},
        )
        assert "DESTRUCTIVE_ACTION_BLOCKED" in text
        assert not executed

    def test_bare_yes_after_block_authorizes_the_pending_delete(self, client):
        first = [{"role": "user", "content": "delete slice old-slice"}]
        text, executed = self._run(client, first, "delete_slice", {"slice_name": "old-slice"},
                                   conversation_id="consent-flow")
        assert "DESTRUCTIVE_ACTION_BLOCKED" in text and not executed
        assert "reply 'yes'" in text

        second = first + [
            {"role": "assistant", "content": "This will delete old-slice. Reply 'yes' to confirm."},
            {"role": "user", "content": "yes"},
        ]
        text, executed = self._run(client, second, "delete_slice", {"slice_name": "old-slice"},
                                   conversation_id="consent-flow")
        assert "DESTRUCTIVE_ACTION_BLOCKED" not in text
        assert executed

    def test_bare_yes_in_another_conversation_does_not_authorize(self, client):
        first = [{"role": "user", "content": "delete slice old-slice"}]
        self._run(client, first, "delete_slice", {"slice_name": "old-slice"},
                  conversation_id="consent-a")
        second = first + [{"role": "user", "content": "yes"}]
        text, executed = self._run(client, second, "delete_slice", {"slice_name": "old-slice"},
                                   conversation_id="consent-b")
        assert "DESTRUCTIVE_ACTION_BLOCKED" in text and not executed

    def test_old_yes_does_not_confirm_later_delete(self, client):
        messages = [
            {"role": "user", "content": "yes, delete slice foo"},
            {"role": "assistant", "content": "Deleted foo."},
            {"role": "user", "content": "now also get rid of old-slice"},
        ]
        text, executed = self._run(client, messages, "delete_slice", {"slice_name": "old-slice"})
        assert "DESTRUCTIVE_ACTION_BLOCKED" in text and not executed
