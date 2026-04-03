"""Tests for slice commands — help text and argument parsing."""

from unittest.mock import patch, MagicMock


class TestSlicesHelp:
    def test_slices_help(self, invoke):
        result = invoke("slices", "--help")
        assert result.exit_code == 0
        assert "Manage FABRIC slices" in result.output

    def test_slices_list_help(self, invoke):
        result = invoke("slices", "list", "--help")
        assert result.exit_code == 0
        assert "--state" in result.output
        assert "loomai slices list" in result.output

    def test_slices_show_help(self, invoke):
        result = invoke("slices", "show", "--help")
        assert result.exit_code == 0
        assert "NAME" in result.output

    def test_slices_create_help(self, invoke):
        result = invoke("slices", "create", "--help")
        assert result.exit_code == 0
        assert "NAME" in result.output

    def test_slices_delete_help(self, invoke):
        result = invoke("slices", "delete", "--help")
        assert result.exit_code == 0
        assert "--force" in result.output

    def test_slices_submit_help(self, invoke):
        result = invoke("slices", "submit", "--help")
        assert result.exit_code == 0
        assert "--wait" in result.output
        assert "--timeout" in result.output

    def test_slices_validate_help(self, invoke):
        result = invoke("slices", "validate", "--help")
        assert result.exit_code == 0

    def test_slices_renew_help(self, invoke):
        result = invoke("slices", "renew", "--help")
        assert result.exit_code == 0
        assert "--days" in result.output

    def test_slices_slivers_help(self, invoke):
        result = invoke("slices", "slivers", "--help")
        assert result.exit_code == 0

    def test_slices_wait_help(self, invoke):
        result = invoke("slices", "wait", "--help")
        assert result.exit_code == 0
        assert "--timeout" in result.output

    def test_slices_clone_help(self, invoke):
        result = invoke("slices", "clone", "--help")
        assert result.exit_code == 0
        assert "--new-name" in result.output

    def test_slices_export_help(self, invoke):
        result = invoke("slices", "export", "--help")
        assert result.exit_code == 0

    def test_slices_import_help(self, invoke):
        result = invoke("slices", "import", "--help")
        assert result.exit_code == 0


class TestSlicesCommands:
    """Test command execution with mocked HTTP client."""

    def test_list_calls_api(self, runner):
        from click.testing import CliRunner
        from loomai_cli.main import cli

        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = [
                {"name": "test", "id": "uuid-1", "state": "StableOK", "has_errors": False}
            ]
            result = runner.invoke(cli, ["--format", "json", "slices", "list"])
            assert result.exit_code == 0
            assert "test" in result.output
            assert "StableOK" in result.output

    def test_list_with_state_filter(self, runner):
        from loomai_cli.main import cli

        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = [
                {"name": "a", "id": "1", "state": "StableOK", "has_errors": False},
                {"name": "b", "id": "2", "state": "Dead", "has_errors": False},
            ]
            result = runner.invoke(cli, ["--format", "json", "slices", "list", "--state", "Dead"])
            assert result.exit_code == 0
            assert "Dead" in result.output
            assert "StableOK" not in result.output

    def test_create_calls_post(self, runner):
        from loomai_cli.main import cli

        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {"name": "new-slice", "state": "Draft"}
            result = runner.invoke(cli, ["--format", "json", "slices", "create", "new-slice"])
            assert result.exit_code == 0
            mock.assert_called()

    def test_delete_with_force(self, runner):
        from loomai_cli.main import cli

        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {"status": "deleted"}
            result = runner.invoke(cli, ["slices", "delete", "my-slice", "--force"])
            assert result.exit_code == 0

    def test_delete_prompts_without_force(self, runner):
        from loomai_cli.main import cli

        with patch("loomai_cli.client.Client._request") as mock:
            # Simulate user saying "n" to confirmation
            result = runner.invoke(cli, ["slices", "delete", "my-slice"], input="n\n")
            assert result.exit_code == 1  # Aborted
