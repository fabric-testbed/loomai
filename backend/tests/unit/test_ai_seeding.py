"""Tests for AI tool workspace seeding functions in ai_terminal.py.

Verifies that each tool's setup function creates the expected files and
directories in a temporary workspace, with all network calls and external
file-system references mocked.
"""

import json
import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fixtures — mock the external dependencies that seeding functions rely on
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _mock_external_deps(tmp_path):
    """Mock network calls and file-system paths used by seeding functions.

    Creates a minimal ai-tools/ asset tree under tmp_path so the seeding
    functions find the shared skills, agents, and template files they need.
    """
    # Build a fake ai-tools asset tree
    shared_dir = tmp_path / "ai-tools" / "shared"
    shared_dir.mkdir(parents=True)

    # FABRIC_AI.md — needed by _write_agents_md
    fabric_ai_md = shared_dir / "FABRIC_AI.md"
    fabric_ai_md.write_text("# FABRIC AI Context\nShared instructions for all AI tools.\n")

    # Skills
    skills_dir = shared_dir / "skills"
    skills_dir.mkdir()
    (skills_dir / "create-slice.md").write_text(
        "name: create-slice\ndescription: Create a FABRIC slice\n---\nCreate a slice.\n"
    )
    (skills_dir / "deploy-slice.md").write_text(
        "name: deploy-slice\ndescription: Deploy a slice\n---\nDeploy instructions.\n"
    )

    # Agents
    agents_dir = shared_dir / "agents"
    agents_dir.mkdir()
    (agents_dir / "fabric-manager.md").write_text(
        "description: FABRIC resource manager\n---\nYou manage FABRIC resources.\n"
    )

    # Aider defaults
    aider_dir = tmp_path / "ai-tools" / "aider"
    aider_dir.mkdir(parents=True)
    (aider_dir / ".aider.conf.yml").write_text("model: openai/qwen3-coder-30b\n")
    (aider_dir / ".aiderignore").write_text(".git\n__pycache__\n")

    # Claude Code defaults
    claude_dir = tmp_path / "ai-tools" / "claude-code"
    claude_dir.mkdir(parents=True)
    (claude_dir / "CLAUDE.md").write_text("# Claude Code instructions\n")
    (claude_dir / "settings.json").write_text("{}")

    # Crush defaults
    crush_dir = tmp_path / "ai-tools" / "crush"
    crush_dir.mkdir(parents=True)
    (crush_dir / ".crush.json").write_text(json.dumps({"providers": {}, "model": ""}))

    # Deep Agents defaults
    da_dir = tmp_path / "ai-tools" / "deepagents"
    da_dir.mkdir(parents=True)
    (da_dir / "AGENTS.md").write_text("# Deep Agents instructions\n")

    # Mock the module-level path constants and network functions
    patches = [
        patch("app.routes.ai_terminal._FABRIC_AI_MD_PATH", str(fabric_ai_md)),
        patch("app.routes.ai_terminal._SHARED_DIR", str(shared_dir)),
        patch("app.routes.ai_terminal._OPENCODE_DEFAULTS_DIR", str(shared_dir)),
        patch("app.routes.ai_terminal._AIDER_DEFAULTS_DIR", str(aider_dir)),
        patch("app.routes.ai_terminal._CLAUDE_DEFAULTS_DIR", str(claude_dir)),
        patch("app.routes.ai_terminal._CRUSH_DEFAULTS_DIR", str(crush_dir)),
        patch("app.routes.ai_terminal._DEEPAGENTS_DEFAULTS_DIR", str(da_dir)),
        # Mock network calls — return a known model list
        patch(
            "app.routes.ai_terminal._fetch_models",
            return_value=[{"id": "test-model", "context_length": 32000}],
        ),
        patch(
            "app.routes.ai_terminal._fetch_nrp_models",
            return_value=[{"id": "nrp-model", "context_length": 16000}],
        ),
        # Mock API key / URL accessors
        patch("app.routes.ai_terminal._get_ai_api_key", return_value="test-fabric-key"),
        patch("app.routes.ai_terminal._get_nrp_api_key", return_value="test-nrp-key"),
        patch("app.routes.ai_terminal._ai_server_url", return_value="https://ai.test.net"),
        patch("app.routes.ai_terminal._nrp_server_url", return_value="https://nrp.test.net"),
    ]
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOpenCodeSeeding:
    def test_creates_agents_md(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from app.routes.ai_terminal import _setup_opencode_workspace
            _setup_opencode_workspace(tmpdir)
            assert os.path.isfile(os.path.join(tmpdir, "AGENTS.md"))

    def test_creates_skills_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from app.routes.ai_terminal import _setup_opencode_workspace
            _setup_opencode_workspace(tmpdir)
            skills_dir = os.path.join(tmpdir, ".opencode", "skills")
            assert os.path.isdir(skills_dir)
            # Should have at least the two skills we created (minus _SKIP_SKILLS)
            skill_names = os.listdir(skills_dir)
            assert len(skill_names) >= 1

    def test_creates_agent_prompts_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from app.routes.ai_terminal import _setup_opencode_workspace
            _setup_opencode_workspace(tmpdir)
            prompts_dir = os.path.join(tmpdir, ".opencode", "agent-prompts")
            assert os.path.isdir(prompts_dir)

    def test_returns_workspace_config_dict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from app.routes.ai_terminal import _setup_opencode_workspace
            result = _setup_opencode_workspace(tmpdir)
            assert isinstance(result, dict)
            assert "mcp" in result
            assert "agent" in result
            assert "command" in result


class TestOpenCodeConfig:
    def test_build_includes_fabric_provider(self):
        from app.routes.ai_terminal import _build_opencode_config
        config = _build_opencode_config("test-key")
        assert "provider" in config
        assert "fabric" in config["provider"]
        assert config["provider"]["fabric"]["options"]["baseURL"] == "https://ai.test.net/v1"

    def test_build_includes_nrp_provider(self):
        from app.routes.ai_terminal import _build_opencode_config
        config = _build_opencode_config("test-key")
        assert "nrp" in config["provider"]
        assert config["provider"]["nrp"]["options"]["baseURL"] == "https://nrp.test.net/v1"

    def test_build_sets_default_model(self):
        from app.routes.ai_terminal import _build_opencode_config
        config = _build_opencode_config("test-key")
        assert config["model"].startswith("fabric/")
        assert "_default" in config
        assert "_allowed" in config


class TestAiderSeeding:
    def test_creates_agents_md(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from app.routes.ai_terminal import _setup_aider_workspace
            _setup_aider_workspace(tmpdir)
            assert os.path.isfile(os.path.join(tmpdir, "AGENTS.md"))

    def test_creates_aider_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from app.routes.ai_terminal import _setup_aider_workspace
            _setup_aider_workspace(tmpdir)
            assert os.path.isfile(os.path.join(tmpdir, ".aider.conf.yml"))

    def test_creates_aiderignore(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from app.routes.ai_terminal import _setup_aider_workspace
            _setup_aider_workspace(tmpdir)
            assert os.path.isfile(os.path.join(tmpdir, ".aiderignore"))


class TestClaudeSeeding:
    def test_creates_agents_md(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from app.routes.ai_terminal import _setup_claude_workspace
            _setup_claude_workspace(tmpdir)
            assert os.path.isfile(os.path.join(tmpdir, "AGENTS.md"))

    def test_creates_claude_md(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from app.routes.ai_terminal import _setup_claude_workspace
            _setup_claude_workspace(tmpdir)
            assert os.path.isfile(os.path.join(tmpdir, "CLAUDE.md"))

    def test_creates_claude_commands(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from app.routes.ai_terminal import _setup_claude_workspace
            _setup_claude_workspace(tmpdir)
            cmds_dir = os.path.join(tmpdir, ".claude", "commands")
            assert os.path.isdir(cmds_dir)
            # Should have at least one skill converted to a command
            assert len(os.listdir(cmds_dir)) >= 1


class TestCrushSeeding:
    def test_creates_agents_md(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from app.routes.ai_terminal import _setup_crush_workspace
            _setup_crush_workspace(tmpdir, api_key="test-key")
            assert os.path.isfile(os.path.join(tmpdir, "AGENTS.md"))

    def test_creates_crush_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from app.routes.ai_terminal import _setup_crush_workspace
            _setup_crush_workspace(tmpdir, api_key="test-key")
            crush_json = os.path.join(tmpdir, ".crush.json")
            assert os.path.isfile(crush_json)
            with open(crush_json) as f:
                config = json.load(f)
            assert "providers" in config
            assert "fabric" in config["providers"]

    def test_includes_nrp_provider(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from app.routes.ai_terminal import _setup_crush_workspace
            _setup_crush_workspace(tmpdir, api_key="test-key")
            with open(os.path.join(tmpdir, ".crush.json")) as f:
                config = json.load(f)
            assert "nrp" in config["providers"]
            assert config["providers"]["nrp"]["base_url"] == "https://nrp.test.net/v1"

    def test_creates_skills_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from app.routes.ai_terminal import _setup_crush_workspace
            _setup_crush_workspace(tmpdir, api_key="test-key")
            assert os.path.isdir(os.path.join(tmpdir, ".crush", "skills"))

    def test_creates_agents_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from app.routes.ai_terminal import _setup_crush_workspace
            _setup_crush_workspace(tmpdir, api_key="test-key")
            assert os.path.isdir(os.path.join(tmpdir, ".crush", "agents"))


class TestDeepAgentsSeeding:
    def test_creates_agents_md(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from app.routes.ai_terminal import _setup_deepagents_workspace
            _setup_deepagents_workspace(tmpdir, api_key="test-key")
            assert os.path.isfile(os.path.join(tmpdir, "AGENTS.md"))

    def test_creates_deepagents_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from app.routes.ai_terminal import _setup_deepagents_workspace
            _setup_deepagents_workspace(tmpdir, api_key="test-key")
            da_dir = os.path.join(tmpdir, ".deepagents")
            assert os.path.isdir(da_dir)
            assert os.path.isfile(os.path.join(da_dir, "AGENTS.md"))

    def test_creates_config_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from app.routes.ai_terminal import _setup_deepagents_workspace
            _setup_deepagents_workspace(tmpdir, api_key="test-key")
            config_path = os.path.join(tmpdir, ".deepagents", "config.json")
            assert os.path.isfile(config_path)
            with open(config_path) as f:
                config = json.load(f)
            assert "providers" in config
            assert "fabric" in config["providers"]
            assert config["default_provider"] == "fabric"

    def test_includes_nrp_provider(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from app.routes.ai_terminal import _setup_deepagents_workspace
            _setup_deepagents_workspace(tmpdir, api_key="test-key")
            with open(os.path.join(tmpdir, ".deepagents", "config.json")) as f:
                config = json.load(f)
            assert "nrp" in config["providers"]
            assert config["providers"]["nrp"]["base_url"] == "https://nrp.test.net/v1"

    def test_creates_skills_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from app.routes.ai_terminal import _setup_deepagents_workspace
            _setup_deepagents_workspace(tmpdir, api_key="test-key")
            assert os.path.isdir(os.path.join(tmpdir, ".deepagents", "skills"))

    def test_creates_agents_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from app.routes.ai_terminal import _setup_deepagents_workspace
            _setup_deepagents_workspace(tmpdir, api_key="test-key")
            assert os.path.isdir(os.path.join(tmpdir, ".deepagents", "agents"))


class TestPropagateAiConfigs:
    """Test the propagate_ai_configs() function that re-generates all tool configs."""

    def _propagate_patches(self, tmp_path):
        """Return a combined context manager for the standard propagation patches."""
        from contextlib import ExitStack
        stack = ExitStack()
        stack.enter_context(patch("app.settings_manager.get_storage_dir", return_value=str(tmp_path)))
        stack.enter_context(patch("app.routes.jupyter._configure_jupyter_ai"))
        return stack

    def test_propagates_all_tools(self, tmp_path):
        """propagate_ai_configs should return status for all tools."""
        from app.routes.ai_terminal import propagate_ai_configs

        with self._propagate_patches(tmp_path):
            results = propagate_ai_configs()

        assert "opencode" in results
        assert "aider" in results
        assert "claude" in results
        assert "crush" in results
        assert "deepagents" in results
        assert "jupyter_ai" in results

    def test_creates_opencode_json(self, tmp_path):
        """propagate_ai_configs should create opencode.json in the workspace."""
        from app.routes.ai_terminal import propagate_ai_configs

        with self._propagate_patches(tmp_path):
            propagate_ai_configs()

        assert os.path.isfile(os.path.join(tmp_path, "opencode.json"))

    def test_creates_crush_json(self, tmp_path):
        """propagate_ai_configs should create .crush.json in the workspace."""
        from app.routes.ai_terminal import propagate_ai_configs

        with self._propagate_patches(tmp_path):
            propagate_ai_configs()

        assert os.path.isfile(os.path.join(tmp_path, ".crush.json"))

    def test_creates_deepagents_config(self, tmp_path):
        """propagate_ai_configs should create .deepagents/config.json."""
        from app.routes.ai_terminal import propagate_ai_configs

        with self._propagate_patches(tmp_path):
            propagate_ai_configs()

        assert os.path.isfile(os.path.join(tmp_path, ".deepagents", "config.json"))

    def test_handles_individual_tool_failure(self, tmp_path):
        """If one tool fails, others should still succeed."""
        from app.routes.ai_terminal import propagate_ai_configs

        with self._propagate_patches(tmp_path), \
             patch("app.routes.ai_terminal._setup_crush_workspace", side_effect=RuntimeError("boom")):
            results = propagate_ai_configs()

        assert "error" in results["crush"]
        # Other tools should still succeed
        assert results["opencode"] == "ok"
        assert results["aider"] == "ok"

    def test_skips_tools_without_api_key(self, tmp_path):
        """Tools requiring API key should be skipped when key is empty."""
        from app.routes.ai_terminal import propagate_ai_configs

        with self._propagate_patches(tmp_path), \
             patch("app.routes.ai_terminal._get_ai_api_key", return_value=""):
            results = propagate_ai_configs()

        assert "skipped" in results["opencode"]
        assert "skipped" in results["crush"]
