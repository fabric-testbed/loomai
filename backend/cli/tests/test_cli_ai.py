"""CLI tests for AI/LLM commands.

Run mock tests:   pytest tests/test_cli_ai.py -v
Run integration:  pytest tests/test_cli_ai.py -v --integration

The integration tests query real FABRIC AI and NRP model endpoints.
"""

from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Mock Tests
# ---------------------------------------------------------------------------

class TestAIMockHelp:
    """Verify AI command help text."""

    def test_ai_group_help(self, invoke):
        r = invoke("ai", "--help")
        assert r.exit_code == 0
        assert "AI" in r.output or "chat" in r.output

    @pytest.mark.parametrize("cmd", ["models", "agents", "chat"])
    def test_subcommand_help(self, invoke, cmd):
        r = invoke("ai", cmd, "--help")
        assert r.exit_code == 0


class TestAIMockModels:
    """Test AI model listing with mocked HTTP."""

    def test_list_models_table(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {
                "fabric": [
                    {"id": "qwen3-coder-30b", "name": "Qwen3 Coder 30B"},
                    {"id": "llama3.1-70b", "name": "Llama 3.1 70B"},
                ],
                "nrp": [
                    {"id": "deepseek-r1", "name": "DeepSeek R1"},
                ],
                "has_key": {"fabric": True, "nrp": True},
                "default": "qwen3-coder-30b",
            }
            r = runner.invoke(cli, ["ai", "models"])
            assert r.exit_code == 0
            assert "qwen3-coder-30b" in r.output
            assert "FABRIC" in r.output
            assert "NRP" in r.output
            assert "(default)" in r.output

    def test_list_models_json(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {
                "fabric": [{"id": "model1"}],
                "nrp": [],
                "has_key": {"fabric": True, "nrp": False},
                "default": "model1",
            }
            r = runner.invoke(cli, ["--format", "json", "ai", "models"])
            assert r.exit_code == 0
            assert "model1" in r.output

    def test_no_models_available(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {
                "fabric": [], "nrp": [],
                "has_key": {"fabric": False, "nrp": False},
                "default": "",
            }
            r = runner.invoke(cli, ["ai", "models"])
            assert r.exit_code == 0
            assert "No models" in r.output or "no API key" in r.output.lower()

    def test_fabric_no_key_message(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {
                "fabric": [], "nrp": [{"id": "nrp-model"}],
                "has_key": {"fabric": False, "nrp": True},
                "default": "",
            }
            r = runner.invoke(cli, ["ai", "models"])
            assert r.exit_code == 0
            assert "no API key" in r.output.lower() or "settings" in r.output.lower()


class TestAIMockAgents:
    """Test AI agent listing with mocked HTTP."""

    def test_list_agents(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = [
                {"id": "fabric-expert", "name": "FABRIC Expert", "description": "Helps with FABRIC"},
                {"id": "general", "name": "General", "description": "General assistant"},
            ]
            r = runner.invoke(cli, ["--format", "json", "ai", "agents"])
            assert r.exit_code == 0
            assert "fabric-expert" in r.output


class TestAIMockChat:
    """Test AI chat with mocked HTTP (one-shot mode)."""

    def test_one_shot_chat(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as req_mock, \
             patch("httpx.stream") as stream_mock:
            # Mock model resolution
            req_mock.return_value = {"default": "test-model", "source": "fabric"}

            # Mock SSE stream
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.iter_lines.return_value = [
                'data: {"content": "Hello"}',
                'data: {"content": "!"}',
                'data: [DONE]',
            ]
            stream_mock.return_value.__enter__ = MagicMock(return_value=mock_response)
            stream_mock.return_value.__exit__ = MagicMock(return_value=False)

            r = runner.invoke(cli, ["ai", "chat", "say hello"])
            assert r.exit_code == 0
            assert "Hello" in r.output

    def test_chat_with_explicit_model(self, runner):
        from loomai_cli.main import cli
        with patch("httpx.stream") as stream_mock:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.iter_lines.return_value = [
                'data: {"content": "Response"}',
                'data: [DONE]',
            ]
            stream_mock.return_value.__enter__ = MagicMock(return_value=mock_response)
            stream_mock.return_value.__exit__ = MagicMock(return_value=False)

            r = runner.invoke(cli, ["ai", "chat", "--model", "llama3.1-70b", "test query"])
            assert r.exit_code == 0

    def test_chat_connection_error(self, runner):
        from loomai_cli.main import cli
        import httpx
        with patch("loomai_cli.client.Client._request") as req_mock, \
             patch("httpx.stream") as stream_mock:
            req_mock.return_value = {"default": "", "source": ""}
            stream_mock.side_effect = httpx.ConnectError("Connection refused")

            r = runner.invoke(cli, ["ai", "chat", "hello"])
            assert r.exit_code == 0  # Prints error message, doesn't crash
            assert "Cannot connect" in r.output


# ---------------------------------------------------------------------------
# Integration Tests — FABRIC AI and NRP
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestAIIntegration:
    """Real AI operations against live backend."""

    def test_list_models(self, integration_runner):
        from loomai_cli.main import cli
        r = integration_runner.invoke(cli, ["--format", "json", "ai", "models"])
        assert r.exit_code == 0
        # Should have at least fabric or nrp section
        assert "fabric" in r.output or "nrp" in r.output

    def test_list_agents(self, integration_runner):
        from loomai_cli.main import cli
        r = integration_runner.invoke(cli, ["--format", "json", "ai", "agents"])
        assert r.exit_code == 0

    def test_one_shot_query_fabric(self, integration_runner):
        """One-shot query using FABRIC AI model."""
        from loomai_cli.main import cli
        r = integration_runner.invoke(cli, [
            "ai", "chat", "--model", "qwen3-coder-30b",
            "Respond with exactly the word PONG"
        ])
        # May fail if model unavailable — that's acceptable
        if r.exit_code == 0 and "Cannot connect" not in r.output:
            assert len(r.output.strip()) > 0

    def test_one_shot_query_nrp(self, integration_runner):
        """One-shot query using NRP model."""
        from loomai_cli.main import cli
        r = integration_runner.invoke(cli, [
            "ai", "chat", "--model", "nrp:deepseek-r1",
            "Respond with exactly the word PONG"
        ])
        # May fail if NRP not configured — acceptable
        if r.exit_code == 0 and "Cannot connect" not in r.output:
            assert len(r.output.strip()) > 0

    def test_one_shot_default_model(self, integration_runner):
        """One-shot query using the default model (auto-resolved)."""
        from loomai_cli.main import cli
        r = integration_runner.invoke(cli, [
            "ai", "chat", "What is 2+2? Reply with just the number."
        ])
        if r.exit_code == 0 and "Cannot connect" not in r.output:
            assert len(r.output.strip()) > 0
