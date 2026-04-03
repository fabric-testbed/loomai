"""CLI tests for FABRIC slice commands.

Run mock tests:   pytest tests/test_cli_slices.py -v
Run integration:  pytest tests/test_cli_slices.py -v --integration
Run both:         pytest tests/test_cli_slices.py -v --integration
"""

import uuid
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Mock Tests — no backend needed
# ---------------------------------------------------------------------------

class TestSlicesMockHelp:
    """Verify all slice command help text renders correctly."""

    def test_slices_group_help(self, invoke):
        r = invoke("slices", "--help")
        assert r.exit_code == 0
        assert "Manage FABRIC slices" in r.output

    @pytest.mark.parametrize("cmd", [
        "list", "show", "create", "delete", "submit", "validate",
        "renew", "slivers", "wait", "clone", "export", "import",
    ])
    def test_subcommand_help(self, invoke, cmd):
        r = invoke("slices", cmd, "--help")
        assert r.exit_code == 0


class TestSlicesMockCRUD:
    """Test slice CRUD with mocked HTTP client."""

    def test_list_slices(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = [
                {"name": "s1", "id": "uuid-1", "state": "StableOK", "has_errors": False},
                {"name": "s2", "id": "uuid-2", "state": "Draft", "has_errors": False},
            ]
            r = runner.invoke(cli, ["--format", "json", "slices", "list"])
            assert r.exit_code == 0
            assert "s1" in r.output
            assert "StableOK" in r.output

    def test_list_with_state_filter(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = [
                {"name": "a", "id": "1", "state": "StableOK", "has_errors": False},
                {"name": "b", "id": "2", "state": "Dead", "has_errors": False},
            ]
            r = runner.invoke(cli, ["--format", "json", "slices", "list", "--state", "Dead"])
            assert r.exit_code == 0
            assert "Dead" in r.output
            assert "StableOK" not in r.output

    def test_create_slice(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {"name": "test-slice", "id": "draft-123", "state": "Draft"}
            r = runner.invoke(cli, ["--format", "json", "slices", "create", "test-slice"])
            assert r.exit_code == 0
            mock.assert_called()

    def test_show_slice(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {
                "name": "test", "id": "uuid-1", "state": "StableOK",
                "nodes": [{"name": "n1", "site": "RENC", "cores": 4}],
                "networks": [],
            }
            r = runner.invoke(cli, ["--format", "json", "slices", "show", "test"])
            assert r.exit_code == 0
            assert "test" in r.output

    def test_delete_with_force(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {"status": "deleted"}
            r = runner.invoke(cli, ["slices", "delete", "test", "--force"])
            assert r.exit_code == 0

    def test_delete_prompts_without_force(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            r = runner.invoke(cli, ["slices", "delete", "test"], input="n\n")
            assert r.exit_code == 1

    def test_submit_slice(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {"name": "test", "state": "Configuring"}
            r = runner.invoke(cli, ["--format", "json", "slices", "submit", "test"])
            assert r.exit_code == 0

    def test_validate_slice(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {"valid": True, "issues": []}
            r = runner.invoke(cli, ["--format", "json", "slices", "validate", "test"])
            assert r.exit_code == 0

    def test_slivers_slice(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {"name": "test", "nodes": [
                {"name": "n1", "site": "RENC", "state": "Active", "management_ip": "1.2.3.4"},
            ]}
            r = runner.invoke(cli, ["--format", "json", "slices", "slivers", "test"])
            assert r.exit_code == 0


class TestSlicesMockNodes:
    """Test node operations with mocked HTTP client."""

    def test_add_node(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {"name": "test", "nodes": [{"name": "n1"}]}
            r = runner.invoke(cli, ["nodes", "add", "test", "n1", "--site", "RENC"])
            assert r.exit_code == 0

    def test_add_node_with_components(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {"name": "test", "nodes": [{"name": "n1", "components": []}]}
            r = runner.invoke(cli, ["nodes", "add", "test", "gpu-node",
                                    "--site", "UCSD", "--cores", "8", "--ram", "32"])
            assert r.exit_code == 0


class TestSlicesMockNetworks:
    """Test network operations with mocked HTTP client."""

    def test_add_network(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {"name": "test", "networks": [{"name": "net1"}]}
            r = runner.invoke(cli, ["networks", "add", "test", "net1", "--type", "L2Bridge"])
            assert r.exit_code == 0


# ---------------------------------------------------------------------------
# Integration Tests — requires running backend (--integration flag)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestSlicesIntegration:
    """Real FABRIC slice operations against live backend."""

    def test_list_slices(self, integration_runner):
        from loomai_cli.main import cli
        r = integration_runner.invoke(cli, ["--format", "json", "slices", "list"])
        assert r.exit_code == 0

    def test_create_and_delete_draft(self, integration_runner, test_slice_name):
        from loomai_cli.main import cli
        # Create
        r = integration_runner.invoke(cli, ["--format", "json", "slices", "create", test_slice_name])
        assert r.exit_code == 0
        assert test_slice_name in r.output

        # Delete
        r = integration_runner.invoke(cli, ["slices", "delete", test_slice_name, "--force"])
        assert r.exit_code == 0

    def test_create_add_node_validate(self, integration_runner, test_slice_name):
        from loomai_cli.main import cli
        name = f"{test_slice_name}-node"

        try:
            # Create
            integration_runner.invoke(cli, ["slices", "create", name])

            # Add node
            r = integration_runner.invoke(cli, ["nodes", "add", name, "n1", "--site", "RENC"])
            assert r.exit_code == 0

            # Validate
            r = integration_runner.invoke(cli, ["--format", "json", "slices", "validate", name])
            assert r.exit_code == 0
        finally:
            integration_runner.invoke(cli, ["slices", "delete", name, "--force"])

    def test_show_slice_json(self, integration_runner, test_slice_name):
        from loomai_cli.main import cli
        name = f"{test_slice_name}-show"

        try:
            integration_runner.invoke(cli, ["slices", "create", name])
            r = integration_runner.invoke(cli, ["--format", "json", "slices", "show", name])
            assert r.exit_code == 0
            assert name in r.output
        finally:
            integration_runner.invoke(cli, ["slices", "delete", name, "--force"])
