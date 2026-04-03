"""Tests for CLI Phases 3-8 — help text and argument parsing."""

from unittest.mock import patch


class TestSSH:
    def test_ssh_help(self, invoke):
        result = invoke("ssh", "--help")
        assert result.exit_code == 0
        assert "SLICE_NAME" in result.output

    def test_exec_help(self, invoke):
        result = invoke("exec", "--help")
        assert result.exit_code == 0
        assert "--all" in result.output
        assert "--parallel" in result.output
        assert "--nodes" in result.output

    def test_exec_requires_target(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            result = runner.invoke(cli, ["exec", "my-slice", "hostname"])
            assert result.exit_code != 0


class TestSCP:
    def test_scp_help(self, invoke):
        result = invoke("scp", "--help")
        assert result.exit_code == 0
        assert "--download" in result.output
        assert "--all" in result.output
        assert "--parallel" in result.output


class TestWeaves:
    def test_weaves_help(self, invoke):
        result = invoke("weaves", "--help")
        assert result.exit_code == 0
        for cmd in ["list", "show", "load", "run", "stop", "logs", "runs"]:
            assert cmd in result.output

    def test_list_help(self, invoke):
        result = invoke("weaves", "list", "--help")
        assert result.exit_code == 0

    def test_run_help(self, invoke):
        result = invoke("weaves", "run", "--help")
        assert result.exit_code == 0
        assert "--args" in result.output
        assert "--script" in result.output

    def test_logs_help(self, invoke):
        result = invoke("weaves", "logs", "--help")
        assert result.exit_code == 0
        assert "--follow" in result.output


class TestBootConfig:
    def test_help(self, invoke):
        result = invoke("boot-config", "--help")
        assert result.exit_code == 0
        assert "show" in result.output
        assert "run" in result.output
        assert "log" in result.output


class TestArtifacts:
    def test_help(self, invoke):
        result = invoke("artifacts", "--help")
        assert result.exit_code == 0
        for cmd in ["list", "search", "show", "get", "publish", "update", "delete", "tags"]:
            assert cmd in result.output

    def test_publish_help(self, invoke):
        result = invoke("artifacts", "publish", "--help")
        assert result.exit_code == 0
        assert "--title" in result.output
        assert "--description" in result.output
        assert "--tags" in result.output
        assert "--category" in result.output
        assert "--visibility" in result.output

    def test_list_with_mocked_api(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = [
                {"name": "Test Weave", "category": "weave", "description": "A test"}
            ]
            result = runner.invoke(cli, ["--format", "json", "artifacts", "list", "--local"])
            assert result.exit_code == 0
            assert "Test Weave" in result.output


class TestRecipes:
    def test_help(self, invoke):
        result = invoke("recipes", "--help")
        assert result.exit_code == 0
        assert "list" in result.output
        assert "show" in result.output
        assert "run" in result.output


class TestVMTemplates:
    def test_help(self, invoke):
        result = invoke("vm-templates", "--help")
        assert result.exit_code == 0
        assert "list" in result.output
        assert "show" in result.output


class TestMonitor:
    def test_help(self, invoke):
        result = invoke("monitor", "--help")
        assert result.exit_code == 0
        for cmd in ["enable", "disable", "status", "metrics"]:
            assert cmd in result.output


class TestConfig:
    def test_config_help(self, invoke):
        result = invoke("config", "--help")
        assert result.exit_code == 0
        assert "show" in result.output
        assert "settings" in result.output

    def test_projects_help(self, invoke):
        result = invoke("projects", "--help")
        assert result.exit_code == 0
        assert "list" in result.output
        assert "switch" in result.output

    def test_keys_help(self, invoke):
        result = invoke("keys", "--help")
        assert result.exit_code == 0
        assert "list" in result.output
        assert "generate" in result.output


class TestAI:
    def test_help(self, invoke):
        result = invoke("ai", "--help")
        assert result.exit_code == 0
        assert "chat" in result.output
        assert "models" in result.output
        assert "agents" in result.output

    def test_models_with_mock(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {
                "fabric": [{"id": "qwen3", "name": "qwen3"}],
                "nrp": [],
                "default": "qwen3",
                "has_key": {"fabric": True, "nrp": False},
                "models": ["qwen3"],
                "nrp_models": [],
            }
            result = runner.invoke(cli, ["ai", "models"])
            assert result.exit_code == 0
            assert "qwen3" in result.output
            assert "FABRIC" in result.output

    def test_chat_help(self, invoke):
        result = invoke("ai", "chat", "--help")
        assert result.exit_code == 0
        assert "--model" in result.output
        assert "--agent" in result.output
