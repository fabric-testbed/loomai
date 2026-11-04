"""Tests for productized external-harness default generation."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from app.harness_config import cleanup_harness_uninstall, reset_harness_defaults, sync_harness_defaults


def _shared_assets(root: Path) -> Path:
    shared = root / "ai-tools" / "shared"
    (shared / "agents").mkdir(parents=True)
    (shared / "skills").mkdir()
    (shared / "FABRIC_AI.md").write_text(
        "# FABRIC AI\n"
        "list_slices\n\n"
        "## Network-service hard limits\n"
        "FABNet services are per-site; use one FABNet service per site for multi-site L3.\n",
        encoding="utf-8",
    )
    (shared / "agents" / "fabric-slice-operator.md").write_text(
        "---\nid: fabric-slice-operator\ndescription: Slice ops\n---\nUse tools.\n",
        encoding="utf-8",
    )
    (shared / "skills" / "create-slice.md").write_text(
        "---\nid: create-slice\ndescription: Create slices\n---\nCreate a slice.\n",
        encoding="utf-8",
    )
    return shared


def test_sync_harness_defaults_renders_fresh_workspace(tmp_path: Path) -> None:
    shared = _shared_assets(tmp_path)
    workspace = tmp_path / "work"
    home = tmp_path / "home"

    with patch("app.harness_config._runtime_ai_settings", return_value={}):
        result = sync_harness_defaults(shared, workspace, home)

    assert result["providers"] == ["ai-renci", "fabric", "nrp"]
    assert "pi" in result["harnesses"]
    agents_md = (workspace / "AGENTS.md").read_text(encoding="utf-8")
    assert "lease" in agents_md
    assert "6-hour" in agents_md
    assert "Never use FABRIC sites EDC or EDUKY" in agents_md
    assert "LoomAI-generated defaults" in agents_md
    assert "loomai tools sync" in agents_md
    assert ".loomai/harness-defaults/MAPPING.md" in agents_md
    assert "POST /api/artifacts/validate" in agents_md
    assert "validate_artifact" in agents_md

    opencode = json.loads((workspace / "opencode.json").read_text(encoding="utf-8"))
    assert set(opencode["provider"]) >= {"ai-renci", "fabric", "nrp"}
    assert opencode["provider"]["ai-renci"]["options"]["apiKey"] == "{env:LOOMAI_CUSTOM_PROVIDER_AI_RENCI_API_KEY}"
    assert "Kimi-K2.6" in opencode["provider"]["ai-renci"]["models"]
    assert opencode["provider"]["ai-renci"]["models"]["Kimi-K2.6"]["name"] == "Kimi-K2.6"
    gpt55 = opencode["provider"]["ai-renci"]["models"]["gpt-5.5"]
    assert gpt55["endpoint_style"] == "responses"
    assert gpt55["strip_temperature"] is True
    assert gpt55["reasoning_effort"] == "medium"
    qwen = opencode["provider"]["fabric"]["models"]["qwen3-coder-30b"]
    assert qwen["temperature"] == 0.3
    assert qwen["context_window"] == 262144
    gemma = opencode["provider"]["fabric"]["models"]["gemma-4-27b"]
    assert gemma["context_window"] == 262144
    glm = opencode["provider"]["nrp"]["models"]["glm-5"]
    assert glm["reasoning_budget_mode"] == "output_preferred"
    assert glm["reasoning_effort"] == "high"
    nrp_gemma = opencode["provider"]["nrp"]["models"]["gemma-small-e4b"]
    assert nrp_gemma["omit_tool_choice"] is True
    assert "fabric-slice-operator" in opencode["agent"]
    assert "create-slice" in opencode["command"]
    assert "fabric-reports" in opencode["mcp"]
    assert "loomai-harness" in opencode["mcp"]
    assert opencode["permission"]["edit"] == "deny"
    mapping = (workspace / ".loomai" / "harness-defaults" / "MAPPING.md").read_text(encoding="utf-8")
    assert "python3 -m app.harness_mcp_server" in mapping
    assert "pi-mcp-adapter" in mapping
    assert "~/.pi/agent/*" in mapping
    assert "~/.local/bin/pi-fabric" in mapping
    assert "loomai-harness" in mapping
    assert "Responses API path" in mapping
    assert "loomai tools sync" in mapping
    assert "verify_harness_lifecycle.py --execute" in mapping
    assert "remove-config uninstall" in mapping
    assert "Network-service hard limits" in mapping

    assert (workspace / ".opencode" / "skills" / "create-slice" / "SKILL.md").is_file()
    assert (workspace / "pi" / "AGENTS.md").is_file()
    pi_agents_md = (workspace / "pi" / "AGENTS.md").read_text(encoding="utf-8")
    assert "Network-service hard limits" in pi_agents_md
    assert "FABNet services are per-site" in pi_agents_md
    assert (workspace / "pi" / "agent" / "skills" / "create-slice" / "SKILL.md").is_file()
    pi_models = json.loads((workspace / "pi" / "agent" / "models.json").read_text(encoding="utf-8"))
    pi_providers = pi_models["providers"]
    assert pi_providers["ai-renci"]["api"] == "openai-responses"
    assert pi_providers["ai-renci"]["apiKey"] == "$LOOMAI_CUSTOM_PROVIDER_AI_RENCI_API_KEY"
    assert pi_providers["ai-renci"]["models"][0]["id"] == "gpt-5.5"
    assert pi_providers["ai-renci"]["models"][0]["reasoning"] is True
    assert pi_providers["ai-renci-chat"]["models"][0]["id"] == "Kimi-K2.6"
    assert pi_providers["fabric"]["models"][0]["contextWindow"] > 0
    assert pi_providers["nrp"]["api"] == "openai-completions"
    pi_settings = json.loads((workspace / "pi" / "agent" / "settings.json").read_text(encoding="utf-8"))
    assert pi_settings["defaultProvider"] == "ai-renci"
    assert pi_settings["defaultModel"] == "gpt-5.5"
    assert pi_settings["sessionDir"] == str(workspace / ".loomai" / "harness-defaults" / "pi" / "sessions")
    assert "extensions/pi-mcp-adapter/index.ts" in pi_settings["extensions"]
    assert "extensions/@gotgenes/pi-permission-system/src/index.ts" in pi_settings["extensions"]
    assert "extensions/pi-subagents/src/extension/index.ts" in pi_settings["extensions"]
    assert "extensions/pi-web-access/index.ts" in pi_settings["extensions"]
    assert "extensions/@lebronj/pi-lsp/dist/index.js" in pi_settings["extensions"]
    assert "permission" not in pi_settings
    pi_permission = json.loads(
        (workspace / "pi" / "agent" / "extensions" / "pi-permission-system" / "config.json").read_text(encoding="utf-8")
    )
    project_pi_permission = json.loads(
        (workspace / ".pi" / "extensions" / "pi-permission-system" / "config.json").read_text(encoding="utf-8")
    )
    for permission_config in (pi_permission, project_pi_permission):
        policy = permission_config["permission"]
        assert policy["read"] == "allow"
        assert policy["write"] == "allow"
        assert policy["edit"] == "allow"
        assert policy["loomai_harness_*"] == "allow"
        assert policy["loomai_harness_delete_*"] == "ask"
        assert policy["bash"]["*"] == "allow"
        assert policy["bash"]["rm -rf *"] == "ask"
        assert policy["bash"]["git push --force*"] == "ask"
        assert policy["mcp"]["loomai_harness_*"] == "allow"
        assert policy["mcp"]["loomai_harness_delete_*"] == "ask"
        assert policy["path"]["~/.ssh/*"] == "ask"
        assert policy["path"]["*.env"] == "ask"
    pi_mcp = json.loads((workspace / "pi" / "agent" / "mcp.json").read_text(encoding="utf-8"))
    assert pi_mcp["mcpServers"]["loomai-harness"]["command"] == "python3"
    assert pi_mcp["mcpServers"]["loomai-harness"]["args"] == ["-m", "app.harness_mcp_server"]
    assert pi_mcp["mcpServers"]["loomai-harness"]["env"]["PYTHONPATH"] == "/app"
    assert pi_mcp["mcpServers"]["loomai-harness"]["env"]["LOOMAI_URL"] == "http://127.0.0.1:8000"
    assert pi_mcp["mcpServers"]["loomai-harness"]["lifecycle"] == "eager"
    assert pi_mcp["mcpServers"]["loomai-harness"]["requestTimeoutMs"] == 3600000
    assert pi_mcp["mcpServers"]["loomai-harness"]["idleTimeout"] == 10
    assert pi_mcp["settings"]["requestTimeoutMs"] == 3600000
    assert pi_mcp["settings"]["idleTimeout"] == 10
    assert pi_mcp["settings"]["outputGuard"] is True
    assert pi_mcp["settings"]["directTools"] is True
    home_pi_models = json.loads((home / ".pi" / "agent" / "models.json").read_text(encoding="utf-8"))
    home_pi_mcp = json.loads((home / ".pi" / "agent" / "mcp.json").read_text(encoding="utf-8"))
    home_pi_permission = json.loads(
        (home / ".pi" / "agent" / "extensions" / "pi-permission-system" / "config.json").read_text(encoding="utf-8")
    )
    assert home_pi_models["providers"]["ai-renci"]["apiKey"] == "$LOOMAI_CUSTOM_PROVIDER_AI_RENCI_API_KEY"
    assert home_pi_mcp["mcpServers"]["loomai-harness"]["env"]["PYTHONPATH"] == "/app"
    assert home_pi_mcp["mcpServers"]["loomai-harness"]["env"]["LOOMAI_URL"] == "http://127.0.0.1:8000"
    assert home_pi_mcp["mcpServers"]["loomai-harness"]["lifecycle"] == "eager"
    assert home_pi_mcp["mcpServers"]["loomai-harness"]["requestTimeoutMs"] == 3600000
    assert home_pi_mcp["mcpServers"]["loomai-harness"]["idleTimeout"] == 10
    assert home_pi_mcp["settings"]["outputGuard"] is True
    assert home_pi_mcp["settings"]["directTools"] is True
    assert home_pi_permission["permission"]["loomai_harness_delete_*"] == "ask"
    assert home_pi_permission["permission"]["path"]["*.env"] == "ask"
    assert (home / ".pi" / "agent" / "skills" / "create-slice" / "SKILL.md").is_file()
    home_pi_launcher = home / ".local" / "bin" / "pi-fabric"
    assert home_pi_launcher.is_file()
    assert home_pi_launcher.stat().st_mode & 0o111
    assert "get_storage_dir" in home_pi_launcher.read_text(encoding="utf-8")
    pi_lsp = json.loads((workspace / "pi" / "agent" / "lsp.json").read_text(encoding="utf-8"))
    assert pi_lsp["servers"]["python"]["command"] == "pyright-langserver"
    assert ".py" in pi_lsp["servers"]["python"]["fileTypes"]
    pi_web = json.loads((workspace / "pi" / "agent" / "web-search.json").read_text(encoding="utf-8"))
    assert pi_web["webSearch"]["enabled"] is True
    pi_guard = (workspace / "pi" / "agent" / "extensions" / "loomai-surface-guard.ts").read_text(encoding="utf-8")
    assert "/home/fabric/work/.loomai" in pi_guard
    assert "write/edit" in pi_guard
    assert "fablib" in pi_guard
    pi_launcher = workspace / "pi" / "pi-fabric"
    assert pi_launcher.is_file()
    assert pi_launcher.stat().st_mode & 0o111
    pi_launcher_text = pi_launcher.read_text(encoding="utf-8")
    assert "PI_CODING_AGENT_DIR" in pi_launcher_text
    assert "Install it from Settings > AI Tools" in pi_launcher_text
    assert "pi-mcp-adapter" in pi_launcher_text
    assert "@gotgenes/pi-permission-system" in pi_launcher_text
    assert "pi-subagents" in pi_launcher_text
    assert "pi-web-access" in pi_launcher_text
    assert "@lebronj/pi-lsp" in pi_launcher_text
    assert "mcp.json" in pi_launcher_text
    assert "lsp.json" in pi_launcher_text
    assert 'PI_MODE="${PI_MODE:-json}"' in pi_launcher_text
    assert "--extension" in pi_launcher_text
    pi_readme = (workspace / "pi" / "README.md").read_text(encoding="utf-8")
    assert '"yoloMode": true' in pi_readme
    assert '"permission": {"*": "allow"}' in pi_readme
    codex_toml = (home / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert "model_provider = \"ai-renci\"" in codex_toml
    assert 'env_key = "LOOMAI_CUSTOM_PROVIDER_AI_RENCI_API_KEY"' in codex_toml
    assert "<!--" not in codex_toml
    aider_yaml = (workspace / ".aider.conf.yml").read_text(encoding="utf-8")
    assert "openai-api-key: \"{env:LOOMAI_CUSTOM_PROVIDER_AI_RENCI_API_KEY}\"" in aider_yaml
    assert (workspace / ".claude" / "commands" / "create-slice.md").is_file()
    assert (workspace / ".claude" / "agents" / "fabric-slice-operator.md").is_file()
    goose_yaml = (workspace / ".config" / "goose" / "config.yaml").read_text(encoding="utf-8")
    assert "qwen3-coder-30b:" in goose_yaml
    assert "temperature: 0.3" in goose_yaml
    assert "reasoning_budget_mode: \"output_preferred\"" in goose_yaml
    assert "loomai-harness:" in goose_yaml
    assert (workspace / ".goose" / "skills" / "create-slice" / "SKILL.md").is_file()
    assert (workspace / ".goose" / "agents" / "fabric-slice-operator.md").is_file()
    claude_mcp = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
    assert claude_mcp["mcpServers"]["loomai-harness"]["command"] == "python3"
    assert (home / ".config" / "crush" / "crush.json").is_file()


def test_sync_harness_defaults_includes_custom_provider_models(tmp_path: Path) -> None:
    shared = _shared_assets(tmp_path)
    workspace = tmp_path / "work"
    home = tmp_path / "home"
    ai_settings = {
        "ai_server_url": "https://fabric.example",
        "nrp_server_url": "https://nrp.example",
        "custom_providers": [{
            "name": "Local Lab",
            "base_url": "https://provider.example",
            "api_key": "provider-key",
            "endpoint_style": "responses",
        }],
        "discovered_models": {
            "fabric": [{"id": "qwen3-coder-30b", "context_length": 262144}],
            "nrp": [{"id": "glm-5", "context_length": 32768, "model_type": "chat"}],
            "custom": {
                "Local Lab": [{
                    "id": "local-model",
                    "context_length": 65536,
                    "endpoint_style": "responses",
                    "supports_tools": True,
                }],
            },
        },
    }

    with patch("app.harness_config._runtime_ai_settings", return_value=ai_settings):
        result = sync_harness_defaults(shared, workspace, home)

    assert "custom-local-lab" in result["providers"]
    opencode = json.loads((workspace / "opencode.json").read_text(encoding="utf-8"))
    custom = opencode["provider"]["custom-local-lab"]
    assert custom["options"]["baseURL"] == "https://provider.example/v1"
    assert custom["options"]["apiKey"] == "{env:LOOMAI_CUSTOM_PROVIDER_LOCAL_LAB_API_KEY}"
    assert custom["models"]["local-model"]["context_window"] == 65536
    assert custom["models"]["local-model"]["endpoint_style"] == "responses"

    pi_models = json.loads((workspace / "pi" / "agent" / "models.json").read_text(encoding="utf-8"))
    assert pi_models["providers"]["custom-local-lab"]["api"] == "openai-responses"
    assert pi_models["providers"]["custom-local-lab"]["apiKey"] == "$LOOMAI_CUSTOM_PROVIDER_LOCAL_LAB_API_KEY"
    assert pi_models["providers"]["custom-local-lab"]["models"][0]["id"] == "local-model"

    goose_yaml = (workspace / ".config" / "goose" / "config.yaml").read_text(encoding="utf-8")
    assert "custom-local-lab:" in goose_yaml
    assert "api_key_env: \"LOOMAI_CUSTOM_PROVIDER_LOCAL_LAB_API_KEY\"" in goose_yaml
    codex_toml = (home / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert "[model_providers.custom-local-lab]" in codex_toml
    assert 'wire_api = "responses"' in codex_toml


def test_loomai_harness_mcp_lists_tools() -> None:
    from app.harness_mcp_server import MCPServer

    with patch("app.harness_mcp_server._mcp_metatools_enabled", return_value=False):
        response = MCPServer().handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    assert response is not None
    tools = response["result"]["tools"]
    by_name = {tool["name"]: tool for tool in tools}
    names = set(by_name)
    assert {
        "list_slices",
        "validate_slice",
        "validate_artifact",
        "submit_slice",
        "delete_slice",
        "configure_networking",
        "get_job_status",
    } <= names
    validate_tool = by_name["validate_slice"]
    assert validate_tool["annotations"]["readOnlyHint"] is True
    assert validate_tool["annotations"]["destructiveHint"] is False
    validate_description = validate_tool["description"].lower()
    assert "before submit_slice" in validate_description
    assert "fix reported issues" in validate_description
    assert "fabnet per-site" in validate_description
    artifact_tool = by_name["validate_artifact"]
    assert artifact_tool["annotations"]["readOnlyHint"] is True
    assert artifact_tool["annotations"]["destructiveHint"] is False
    artifact_description = artifact_tool["description"].lower()
    assert "before run_weave" in artifact_description
    assert "publish_artifact" in artifact_description
    assert "results/" in artifact_description
    assert artifact_tool["inputSchema"]["required"] == []
    delete_tool = by_name["delete_slice"]
    assert delete_tool["annotations"]["readOnlyHint"] is False
    assert delete_tool["annotations"]["destructiveHint"] is True
    delete_description = delete_tool["description"].lower()
    assert "explicit user authorization" in delete_description
    assert "wrong" in delete_description
    assert "over-policy lease" in delete_description
    submit_description = by_name["submit_slice"]["description"].lower()
    assert "validate_slice first" in submit_description
    assert "do not submit" in submit_description
    assert "default wait_for_stableok=false" in submit_description
    assert "poll get_job_status" in submit_description
    assert "capped at 240 seconds" in submit_description
    assert "one site" in submit_description
    assert "one fabnet service per site" in submit_description
    configure_description = by_name["configure_networking"]["description"].lower()
    assert "post-stableok" in configure_description
    assert "cannot fix an invalid cross-site single fabnet service" in configure_description
    assert "per-node/per-site fabnet before submit_slice" in configure_description
    submit_schema = by_name["submit_slice"]["inputSchema"]["properties"]["lease_hours"]
    submit_wait_schema = by_name["submit_slice"]["inputSchema"]["properties"]["wait_for_stableok"]
    renew_schema = by_name["renew_slice"]["inputSchema"]["properties"]["lease_hours"]
    weave_schema = by_name["run_weave"]["inputSchema"]["properties"]["lease_hours"]
    # Leases default to 6 h; the configurable cap is enforced by the backend
    # (Agent Lease Limit), so the schemas must not hardcode a maximum.
    for schema in (submit_schema, renew_schema, weave_schema):
        assert schema["default"] == 6
        assert "maximum" not in schema
    assert submit_wait_schema["default"] is False


def test_loomai_harness_mcp_metatools_are_opt_in() -> None:
    from app.harness_mcp_server import MCPServer

    with patch("app.harness_mcp_server._mcp_metatools_enabled", return_value=False):
        off_response = MCPServer().handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    off_tools = off_response["result"]["tools"]
    off_names = [tool["name"] for tool in off_tools]
    assert "list-endpoints" not in off_names
    assert "describe-endpoint" not in off_names

    with patch("app.harness_mcp_server._mcp_metatools_enabled", return_value=True):
        on_response = MCPServer().handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    on_tools = on_response["result"]["tools"]
    on_names = [tool["name"] for tool in on_tools]
    assert on_names[:len(off_names)] == off_names
    assert on_names[-2:] == ["list-endpoints", "describe-endpoint"]
    assert on_tools[-1]["annotations"]["readOnlyHint"] is True
    assert on_tools[-1]["annotations"]["destructiveHint"] is False


def test_loomai_harness_mcp_metatools_describe_openapi_endpoint() -> None:
    from app.harness_mcp_server import MCPServer

    server = MCPServer()
    with patch("app.harness_mcp_server._mcp_metatools_enabled", return_value=True):
        listed = server.call_tool("list-endpoints", {"path_prefix": "/api/artifacts", "limit": 20})
        described = server.call_tool("describe-endpoint", {
            "method": "POST",
            "path": "/api/artifacts/validate",
        })

    endpoint_keys = {(item["method"], item["path"]) for item in listed["endpoints"]}
    assert ("POST", "/api/artifacts/validate") in endpoint_keys
    assert described["ok"] is True
    assert described["method"] == "POST"
    assert described["path"] == "/api/artifacts/validate"
    assert described["request_body_schema"]
    assert described["request_example"] is not None
    assert "200" in described["responses"]


def test_loomai_harness_mcp_submit_uses_nonblocking_default_and_wait_cap() -> None:
    from app.harness_mcp_server import MCPServer

    class FakeClient:
        def request(self, method: str, path: str, payload: dict | None = None, timeout: int = 300) -> dict:
            return {"method": method, "path": path, "payload": payload, "timeout": timeout}

    class FakeJobs:
        def __init__(self) -> None:
            self.calls = []

        def start(self, tool: str, target, *args, **kwargs) -> str:
            self.calls.append((tool, target, args, kwargs))
            return f"job-{len(self.calls)}"

        def status(self, job_id: str) -> dict:
            return {"job_id": job_id, "status": "not_found"}

    jobs = FakeJobs()
    server = MCPServer(client=FakeClient(), jobs=jobs)

    default_result = server.call_tool("submit_slice", {"slice_name": "draft one", "lease_hours": 6})
    wait_result = server.call_tool(
        "submit_slice",
        {"slice_name": "draft one", "lease_hours": 6, "wait_for_stableok": True},
    )

    assert default_result["job_id"] == "job-1"
    assert default_result["wait_for_stableok"] is False
    assert default_result["wait_timeout_seconds"] is None
    assert "get_job_status" in default_result["message"]
    assert wait_result["job_id"] == "job-2"
    assert wait_result["wait_for_stableok"] is True
    assert wait_result["wait_timeout_seconds"] == 240
    default_call = jobs.calls[0][2]
    wait_call = jobs.calls[1][2]
    assert default_call == (
        "POST",
        "/api/slices/draft%20one/submit",
        {"lease_hours": 6, "wait_for_stableok": False},
        300,
    )
    assert wait_call == (
        "POST",
        "/api/slices/draft%20one/submit",
        {"lease_hours": 6, "wait_for_stableok": True},
        240,
    )


class _HintFakeClient:
    def request(self, method: str, path: str, payload: dict | None = None, timeout: int = 300) -> dict:
        return {"method": method, "path": path, "http_status": 200, "ok": True, "body": {}}


class _HintFakeJobs:
    def __init__(self, status: dict | None = None) -> None:
        self._status = status or {"job_id": "job-1", "status": "not_found"}

    def start(self, tool: str, target, *args, **kwargs) -> str:
        return "job-1"

    def status(self, job_id: str) -> dict:
        return dict(self._status)


def test_loomai_harness_mcp_evidence_closure_hints_on_weak_profile(monkeypatch) -> None:
    import app.settings_manager as settings_manager
    from app.harness_mcp_server import EVIDENCE_CLOSURE_HINTS, MCPServer

    seen_model_keys: list[str] = []

    def fake_gate(model_key: str = "") -> bool:
        seen_model_keys.append(model_key)
        return True

    monkeypatch.setenv("LOOMAI_MCP_MODEL", "fabric:qwen3-coder-30b")
    monkeypatch.setattr(settings_manager, "get_mcp_evidence_closure_hints_enabled", fake_gate)
    server = MCPServer(client=_HintFakeClient(), jobs=_HintFakeJobs())

    submit = server.call_tool("submit_slice", {"slice_name": "draft one"})
    weave = server.call_tool("run_weave", {"template": "My_Weave"})
    recipe = server.call_tool("execute_recipe", {"recipe": "r", "slice_name": "s", "node_name": "n"})
    networking = server.call_tool("configure_networking", {"slice_name": "s"})
    read_only = server.call_tool("get_slice", {"slice_name": "s"})

    assert submit["next_step_hint"] == EVIDENCE_CLOSURE_HINTS["submit_slice"]
    assert weave["next_step_hint"] == EVIDENCE_CLOSURE_HINTS["run_weave"]
    assert recipe["next_step_hint"] == EVIDENCE_CLOSURE_HINTS["execute_recipe"]
    assert networking["next_step_hint"] == EVIDENCE_CLOSURE_HINTS["configure_networking"]
    assert "next_step_hint" not in read_only
    assert seen_model_keys and all(key == "fabric:qwen3-coder-30b" for key in seen_model_keys)
    assert all(len(hint) <= 200 for hint in EVIDENCE_CLOSURE_HINTS.values())


def test_loomai_harness_mcp_evidence_closure_hints_off_baseline_identical(monkeypatch) -> None:
    import app.settings_manager as settings_manager
    from app.harness_mcp_server import MCPServer

    monkeypatch.setattr(settings_manager, "get_mcp_evidence_closure_hints_enabled", lambda model_key="": False)
    server = MCPServer(client=_HintFakeClient(), jobs=_HintFakeJobs())

    submit = server.call_tool("submit_slice", {"slice_name": "draft one"})
    networking = server.call_tool("configure_networking", {"slice_name": "s"})

    assert submit == {
        "job_id": "job-1",
        "status": "started",
        "wait_for_stableok": False,
        "wait_timeout_seconds": None,
        "message": (
            "Submit is running in a LoomAI harness job. Poll get_job_status with this job_id; "
            "after the job succeeds, poll get_slice/list_slices for StableOK before claiming readiness."
        ),
    }
    assert networking == {
        "method": "POST",
        "path": "/api/slices/s/configure-networking",
        "http_status": 200,
        "ok": True,
        "body": {},
    }


def test_loomai_harness_mcp_evidence_closure_hint_on_succeeded_job_status(monkeypatch) -> None:
    import app.settings_manager as settings_manager
    from app.harness_mcp_server import EVIDENCE_CLOSURE_HINTS, MCPServer

    monkeypatch.setattr(settings_manager, "get_mcp_evidence_closure_hints_enabled", lambda model_key="": True)

    succeeded = {"job_id": "job-1", "tool": "submit_slice", "status": "succeeded", "result": {"ok": True}, "error": ""}
    failed = {"job_id": "job-1", "tool": "submit_slice", "status": "failed", "result": None, "error": "boom"}
    http_failed = {"job_id": "job-1", "tool": "submit_slice", "status": "succeeded", "result": {"ok": False}, "error": ""}
    unhinted = {"job_id": "job-1", "tool": "renew_slice", "status": "succeeded", "result": {"ok": True}, "error": ""}

    hinted = MCPServer(client=_HintFakeClient(), jobs=_HintFakeJobs(succeeded)).call_tool("get_job_status", {"job_id": "job-1"})
    assert hinted["next_step_hint"] == EVIDENCE_CLOSURE_HINTS["submit_slice"]

    for status in (failed, http_failed, unhinted):
        result = MCPServer(client=_HintFakeClient(), jobs=_HintFakeJobs(status)).call_tool("get_job_status", {"job_id": "job-1"})
        assert "next_step_hint" not in result


def test_loomai_harness_mcp_validate_slice_calls_backend() -> None:
    from app.harness_mcp_server import MCPServer

    class FakeClient:
        def __init__(self) -> None:
            self.calls = []

        def request(self, method: str, path: str, payload: dict | None = None, timeout: int = 300) -> dict:
            self.calls.append((method, path, payload, timeout))
            return {"method": method, "path": path, "ok": True}

    client = FakeClient()
    result = MCPServer(client=client).call_tool("validate_slice", {"slice_name": "draft one/two"})

    assert result == {"method": "GET", "path": "/api/slices/draft%20one%2Ftwo/validate", "ok": True}
    assert client.calls == [("GET", "/api/slices/draft%20one%2Ftwo/validate", None, 300)]


def test_loomai_harness_mcp_validate_artifact_calls_backend() -> None:
    from app.harness_mcp_server import MCPServer

    class FakeClient:
        def __init__(self) -> None:
            self.calls = []

        def request(self, method: str, path: str, payload: dict | None = None, timeout: int = 300) -> dict:
            self.calls.append((method, path, payload, timeout))
            return {"method": method, "path": path, "payload": payload, "ok": True}

    client = FakeClient()
    result = MCPServer(client=client).call_tool("validate_artifact", {
        "dir_name": "My_Weave",
        "ignored": "not forwarded",
    })

    assert result == {
        "method": "POST",
        "path": "/api/artifacts/validate",
        "payload": {"dir_name": "My_Weave"},
        "ok": True,
    }
    assert client.calls == [("POST", "/api/artifacts/validate", {"dir_name": "My_Weave"}, 300)]


def test_loomai_harness_mcp_delete_slice_calls_backend() -> None:
    from app.harness_mcp_server import MCPServer

    class FakeClient:
        def __init__(self) -> None:
            self.calls = []

        def request(self, method: str, path: str, payload: dict | None = None, timeout: int = 300) -> dict:
            self.calls.append((method, path, payload, timeout))
            return {"method": method, "path": path, "ok": True}

    client = FakeClient()
    result = MCPServer(client=client).call_tool("delete_slice", {"slice_name": "bad lease/slice"})

    assert result == {"method": "DELETE", "path": "/api/slices/bad%20lease%2Fslice", "ok": True}
    assert client.calls == [("DELETE", "/api/slices/bad%20lease%2Fslice", None, 300)]


def test_sync_harness_defaults_preserves_existing_config_values(tmp_path: Path) -> None:
    shared = _shared_assets(tmp_path)
    workspace = tmp_path / "work"
    home = tmp_path / "home"
    workspace.mkdir()
    (workspace / "opencode.json").write_text(
        json.dumps({
            "model": "custom/model",
            "provider": {
                "fabric-reports": {"keep": "this"},
                "fabric": {"models": {"user-model": {"name": "user-model"}}},
            },
            "mcp": {"fabric-reports": {"type": "local", "command": ["custom"]}},
        }),
        encoding="utf-8",
    )
    (workspace / "AGENTS.md").write_text("user instructions", encoding="utf-8")

    with patch("app.harness_config._runtime_ai_settings", return_value={}):
        sync_harness_defaults(shared, workspace, home)

    opencode = json.loads((workspace / "opencode.json").read_text(encoding="utf-8"))
    assert opencode["model"] == "custom/model"
    assert opencode["provider"]["fabric"]["models"]["user-model"]["name"] == "user-model"
    assert "qwen3-coder-30b" in opencode["provider"]["fabric"]["models"]
    assert opencode["mcp"]["fabric-reports"]["command"] == ["custom"]
    assert (workspace / "AGENTS.md").read_text(encoding="utf-8") == "user instructions"

    pi_settings = workspace / "pi" / "agent" / "settings.json"
    pi_settings.parent.mkdir(parents=True, exist_ok=True)
    pi_settings.write_text(
        json.dumps({
            "defaultProvider": "custom",
            "extensions": ["extensions/loomai-surface-guard.ts"],
            "permission": {"default": "ask"},
            "user": {"keep": True},
        }),
        encoding="utf-8",
    )

    with patch("app.harness_config._runtime_ai_settings", return_value={}):
        sync_harness_defaults(shared, workspace, home)

    merged_pi_settings = json.loads(pi_settings.read_text(encoding="utf-8"))
    assert merged_pi_settings["defaultProvider"] == "custom"
    assert merged_pi_settings["defaultModel"] == "gpt-5.5"
    assert merged_pi_settings["user"]["keep"] is True
    assert "permission" not in merged_pi_settings
    assert "extensions/loomai-surface-guard.ts" in merged_pi_settings["extensions"]
    assert "extensions/pi-mcp-adapter/index.ts" in merged_pi_settings["extensions"]
    assert "extensions/@lebronj/pi-lsp/dist/index.js" in merged_pi_settings["extensions"]
    home_pi_settings = home / ".pi" / "agent" / "settings.json"
    home_pi_settings.parent.mkdir(parents=True, exist_ok=True)
    home_pi_settings.write_text(json.dumps({"defaultProvider": "home-custom", "user": {"keep": True}}), encoding="utf-8")

    with patch("app.harness_config._runtime_ai_settings", return_value={}):
        sync_harness_defaults(shared, workspace, home, harnesses=["pi"])

    merged_home_pi_settings = json.loads(home_pi_settings.read_text(encoding="utf-8"))
    assert merged_home_pi_settings["defaultProvider"] == "home-custom"
    assert merged_home_pi_settings["defaultModel"] == "gpt-5.5"
    assert merged_home_pi_settings["user"]["keep"] is True


def test_reset_harness_defaults_overwrites_user_modified_files(tmp_path: Path) -> None:
    shared = _shared_assets(tmp_path)
    workspace = tmp_path / "work"
    home = tmp_path / "home"

    with patch("app.harness_config._runtime_ai_settings", return_value={}):
        sync_harness_defaults(shared, workspace, home, harnesses=["pi"])
    pi_settings = workspace / "pi" / "agent" / "settings.json"
    home_pi_settings = home / ".pi" / "agent" / "settings.json"
    pi_settings.write_text(json.dumps({"defaultProvider": "custom"}), encoding="utf-8")
    home_pi_settings.write_text(json.dumps({"defaultProvider": "home-custom"}), encoding="utf-8")

    with patch("app.harness_config._runtime_ai_settings", return_value={}):
        result = reset_harness_defaults("pi", shared_root=shared, workspace=workspace, home=home)

    restored = json.loads(pi_settings.read_text(encoding="utf-8"))
    restored_home = json.loads(home_pi_settings.read_text(encoding="utf-8"))
    assert restored["defaultProvider"] == "ai-renci"
    assert restored_home["defaultProvider"] == "ai-renci"
    assert restored["sessionDir"] == str(workspace / ".loomai" / "harness-defaults" / "pi" / "sessions")
    assert result["reset_files"] > 0
    assert result["harness"]["status"] == "configured"


def test_cleanup_harness_uninstall_removes_runtime_state_but_keeps_config(tmp_path: Path) -> None:
    shared = _shared_assets(tmp_path)
    workspace = tmp_path / "work"
    home = tmp_path / "home"

    with patch("app.harness_config._runtime_ai_settings", return_value={}):
        sync_harness_defaults(shared, workspace, home, harnesses=["pi"])
    pi_settings = workspace / "pi" / "agent" / "settings.json"
    runtime_file = workspace / ".loomai" / "harness-defaults" / "pi" / "sessions" / "session.json"
    runtime_file.parent.mkdir(parents=True, exist_ok=True)
    runtime_file.write_text("{}", encoding="utf-8")
    project_file = workspace / "my_slices" / "keep.py"
    project_file.parent.mkdir(parents=True, exist_ok=True)
    project_file.write_text("print('keep')\n", encoding="utf-8")

    result = cleanup_harness_uninstall("pi", shared_root=shared, workspace=workspace, home=home)

    assert not runtime_file.exists()
    assert not (workspace / ".loomai" / "harness-defaults" / "pi").exists()
    assert pi_settings.is_file()
    assert project_file.read_text(encoding="utf-8") == "print('keep')\n"
    assert result["removed_config_files"] == 0


def test_cleanup_harness_uninstall_optionally_removes_expected_config(tmp_path: Path) -> None:
    shared = _shared_assets(tmp_path)
    workspace = tmp_path / "work"
    home = tmp_path / "home"

    with patch("app.harness_config._runtime_ai_settings", return_value={}):
        sync_harness_defaults(shared, workspace, home, harnesses=["pi"])
    pi_settings = workspace / "pi" / "agent" / "settings.json"
    home_pi_settings = home / ".pi" / "agent" / "settings.json"
    runtime_file = workspace / ".loomai" / "harness-defaults" / "pi" / "cache" / "cache.json"
    runtime_file.parent.mkdir(parents=True, exist_ok=True)
    runtime_file.write_text("{}", encoding="utf-8")
    project_file = workspace / "my_artifacts" / "experiment.md"
    project_file.parent.mkdir(parents=True, exist_ok=True)
    project_file.write_text("user artifact\n", encoding="utf-8")

    result = cleanup_harness_uninstall("pi", remove_config=True, shared_root=shared, workspace=workspace, home=home)

    assert not runtime_file.exists()
    assert not pi_settings.exists()
    assert not home_pi_settings.exists()
    assert project_file.read_text(encoding="utf-8") == "user artifact\n"
    assert result["removed_config_files"] > 0


def test_sync_harness_defaults_is_idempotent(tmp_path: Path) -> None:
    shared = _shared_assets(tmp_path)
    workspace = tmp_path / "work"
    home = tmp_path / "home"

    with patch("app.harness_config._runtime_ai_settings", return_value={}):
        sync_harness_defaults(shared, workspace, home)
    first = (workspace / "opencode.json").read_text(encoding="utf-8")
    with patch("app.harness_config._runtime_ai_settings", return_value={}):
        sync_harness_defaults(shared, workspace, home)
    second = (workspace / "opencode.json").read_text(encoding="utf-8")

    assert first == second
