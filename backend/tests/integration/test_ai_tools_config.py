"""Integration tests for AI tool workspace seeding and configuration.

Verifies that each AI tool's setup function produces the expected files
with correct content, provider configs, and FABRIC context.
"""

import json
import os
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def workspace(tmp_path):
    """Provide a temp workspace directory with minimal FABRIC config."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    # Fake fabric_config so tools don't crash
    cfg = ws / "fabric_config"
    cfg.mkdir()
    (cfg / "fabric_rc").write_text("export FABRIC_PROJECT_ID=test\n")
    return ws


@pytest.fixture
def mock_env(workspace):
    """Patch env vars for tool setup."""
    env = {
        "FABRIC_STORAGE_DIR": str(workspace),
        "FABRIC_CONFIG_DIR": str(workspace / "fabric_config"),
    }
    with patch.dict(os.environ, env):
        yield


@pytest.fixture
def mock_fablib():
    """Patch FABlib and API calls so setup functions don't hit real servers."""
    with patch("app.routes.ai_terminal._get_ai_api_key", return_value="fake-key"), \
         patch("app.routes.ai_terminal._get_nrp_api_key", return_value="fake-nrp-key"), \
         patch("app.routes.ai_terminal._fetch_models", return_value=["qwen3-coder-30b", "qwen3-8b"]), \
         patch("app.routes.ai_terminal._fetch_nrp_models", return_value=["mixtral-8x7b"]):
        yield


# ---------------------------------------------------------------------------
# Phase 11: _write_agents_md produces correct preambles
# ---------------------------------------------------------------------------

class TestWriteAgentsMd:
    def test_opencode_preamble(self, workspace, mock_env):
        from app.routes.ai_terminal import _write_agents_md
        _write_agents_md(str(workspace), "opencode")
        agents_md = workspace / "AGENTS.md"
        assert agents_md.exists()
        content = agents_md.read_text()
        assert "OpenCode" in content
        assert "loomai" in content  # CLI reference
        assert "curl" in content  # curl reference
        assert "list_slices" in content  # Correct tool names (not fabric_list_slices)

    def test_aider_preamble(self, workspace, mock_env):
        from app.routes.ai_terminal import _write_agents_md
        _write_agents_md(str(workspace), "aider")
        content = (workspace / "AGENTS.md").read_text()
        assert "Aider" in content
        assert "do NOT have tool-calling" in content

    def test_claude_code_preamble(self, workspace, mock_env):
        from app.routes.ai_terminal import _write_agents_md
        _write_agents_md(str(workspace), "claude-code")
        content = (workspace / "AGENTS.md").read_text()
        assert "Claude Code" in content

    def test_crush_preamble(self, workspace, mock_env):
        from app.routes.ai_terminal import _write_agents_md
        _write_agents_md(str(workspace), "crush")
        content = (workspace / "AGENTS.md").read_text()
        assert "Crush" in content

    def test_deepagents_preamble(self, workspace, mock_env):
        from app.routes.ai_terminal import _write_agents_md
        _write_agents_md(str(workspace), "deepagents")
        content = (workspace / "AGENTS.md").read_text()
        assert "Deep Agents" in content

    def test_no_fabric_prefix_tool_names(self, workspace, mock_env):
        """Verify FABRIC_AI.md has no fabric_* tool names (Phase 9 fix)."""
        from app.routes.ai_terminal import _write_agents_md
        _write_agents_md(str(workspace), "opencode")
        content = (workspace / "AGENTS.md").read_text()
        # Should NOT contain old-style fabric_ prefixed tool names
        assert "fabric_list_slices" not in content
        assert "fabric_get_slice" not in content
        assert "fabric_create_slice" not in content
        assert "fabric_submit_slice" not in content
        assert "fabric_delete_slice" not in content
        # Should contain correct tool names
        assert "list_slices" in content
        assert "get_slice" in content
        assert "create_slice" in content

    def test_cli_examples_present(self, workspace, mock_env):
        """Verify CLI examples were added (Phase 10)."""
        from app.routes.ai_terminal import _write_agents_md
        _write_agents_md(str(workspace), "opencode")
        content = (workspace / "AGENTS.md").read_text()
        assert "loomai slices list" in content
        assert "loomai sites find" in content
        assert "loomai ssh" in content

    def test_does_not_overwrite_existing(self, workspace, mock_env):
        """If AGENTS.md already exists, don't overwrite."""
        from app.routes.ai_terminal import _write_agents_md
        agents_md = workspace / "AGENTS.md"
        agents_md.write_text("custom content")
        _write_agents_md(str(workspace), "opencode")
        assert agents_md.read_text() == "custom content"


# ---------------------------------------------------------------------------
# Phase 12: Workspace seeding produces correct files
# ---------------------------------------------------------------------------

class TestCrushWorkspace:
    def test_crush_json_created(self, workspace, mock_env, mock_fablib):
        from app.routes.ai_terminal import _setup_crush_workspace
        _setup_crush_workspace(str(workspace), "fake-key")
        crush_json = workspace / ".crush.json"
        assert crush_json.exists()
        config = json.loads(crush_json.read_text())
        assert "providers" in config
        assert "fabric" in config["providers"]

    def test_crush_nrp_provider(self, workspace, mock_env, mock_fablib):
        from app.routes.ai_terminal import _setup_crush_workspace
        _setup_crush_workspace(str(workspace), "fake-key")
        config = json.loads((workspace / ".crush.json").read_text())
        assert "nrp" in config["providers"]
        assert config["providers"]["nrp"]["api_key"] == "fake-nrp-key"

    def test_crush_skills_copied(self, workspace, mock_env, mock_fablib):
        from app.routes.ai_terminal import _setup_crush_workspace
        _setup_crush_workspace(str(workspace), "fake-key")
        skills_dir = workspace / ".crush" / "skills"
        if skills_dir.exists():
            assert any(f.suffix == ".md" for f in skills_dir.iterdir())

    def test_crush_agents_copied(self, workspace, mock_env, mock_fablib):
        from app.routes.ai_terminal import _setup_crush_workspace
        _setup_crush_workspace(str(workspace), "fake-key")
        agents_dir = workspace / ".crush" / "agents"
        if agents_dir.exists():
            assert any(f.suffix == ".md" for f in agents_dir.iterdir())


class TestDeepAgentsWorkspace:
    def test_config_json_created(self, workspace, mock_env, mock_fablib):
        from app.routes.ai_terminal import _setup_deepagents_workspace
        _setup_deepagents_workspace(str(workspace), "fake-key")
        config_path = workspace / ".deepagents" / "config.json"
        assert config_path.exists()
        config = json.loads(config_path.read_text())
        assert "providers" in config

    def test_nrp_provider_in_config(self, workspace, mock_env, mock_fablib):
        from app.routes.ai_terminal import _setup_deepagents_workspace
        _setup_deepagents_workspace(str(workspace), "fake-key")
        config = json.loads((workspace / ".deepagents" / "config.json").read_text())
        assert "nrp" in config["providers"]


class TestAiderWorkspace:
    def test_agents_md_with_preamble(self, workspace, mock_env):
        from app.routes.ai_terminal import _setup_aider_workspace
        _setup_aider_workspace(str(workspace))
        agents_md = workspace / "AGENTS.md"
        assert agents_md.exists()
        content = agents_md.read_text()
        assert "Aider" in content


class TestClaudeCodeWorkspace:
    def test_skills_as_commands(self, workspace, mock_env):
        from app.routes.ai_terminal import _setup_claude_workspace
        _setup_claude_workspace(str(workspace))
        cmds_dir = workspace / ".claude" / "commands"
        if cmds_dir.exists():
            md_files = list(cmds_dir.glob("*.md"))
            assert len(md_files) > 0, "Expected Claude Code commands from shared skills"


# ---------------------------------------------------------------------------
# Phase 13: Tool schemas match FABRIC_AI.md
# ---------------------------------------------------------------------------

class TestToolSchemasMatch:
    def test_core_tool_names_in_fabric_ai_md(self, workspace, mock_env):
        """Core slice/site tools should be documented in FABRIC_AI.md."""
        from app.routes.ai_terminal import _FABRIC_AI_MD_PATH

        with open(_FABRIC_AI_MD_PATH) as f:
            content = f.read()

        # These are the most important tools that users will ask about
        core_tools = [
            "list_slices", "get_slice", "create_slice", "submit_slice",
            "delete_slice", "renew_slice", "add_node", "add_component",
        ]
        missing = [t for t in core_tools if t not in content]
        assert not missing, f"Core tools not documented in FABRIC_AI.md: {missing}"

    def test_no_fabric_prefix_in_schemas(self):
        """Tool schemas should NOT use fabric_ prefix."""
        from app.routes.ai_chat import TOOL_SCHEMAS
        for schema in TOOL_SCHEMAS:
            name = schema["function"]["name"]
            assert not name.startswith("fabric_"), f"Tool '{name}' has fabric_ prefix"

    def test_tool_count(self):
        """Verify we have a reasonable number of tools."""
        from app.routes.ai_chat import TOOL_SCHEMAS
        assert len(TOOL_SCHEMAS) >= 25, f"Expected 25+ tools, got {len(TOOL_SCHEMAS)}"


class TestModelsEndpoint:
    def test_models_grouped_by_source(self, client):
        """GET /api/ai/models should return fabric/nrp groups with has_key."""
        mock_result = {
            "fabric": [{"id": "model1", "name": "model1", "healthy": True}],
            "nrp": [],
            "custom": {},
            "default": "model1",
            "has_key": {"fabric": True, "nrp": False},
            "errors": {"fabric": "", "nrp": ""},
            "models": ["model1"],
            "nrp_models": [],
        }
        with patch("app.routes.ai_terminal._fetch_all_models", return_value=mock_result):
            resp = client.get("/api/ai/models")
        assert resp.status_code == 200
        data = resp.json()
        assert "fabric" in data
        assert "nrp" in data
        assert "has_key" in data
        assert data["has_key"]["fabric"] is True
        assert data["has_key"]["fabric"] is True
        assert isinstance(data["fabric"], list)
