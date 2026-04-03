"""CLI tests for Composite slice commands.

Run mock tests:   pytest tests/test_cli_composite.py -v
Run integration:  pytest tests/test_cli_composite.py -v --integration
"""

from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Mock Tests
# ---------------------------------------------------------------------------

class TestCompositeMockHelp:
    """Verify composite command help text."""

    def test_composite_group_help(self, invoke):
        r = invoke("composite", "--help")
        assert r.exit_code == 0
        assert "composite" in r.output.lower()

    @pytest.mark.parametrize("cmd", [
        "list", "show", "create", "delete",
        "add-fabric", "add-chameleon",
        "remove-fabric", "remove-chameleon",
        "cross-connections", "graph", "submit",
    ])
    def test_subcommand_help(self, invoke, cmd):
        r = invoke("composite", cmd, "--help")
        assert r.exit_code == 0


class TestCompositeMockCRUD:
    """Test composite CRUD with mocked HTTP."""

    def test_list_composites(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = [
                {"id": "comp-1", "name": "exp1", "state": "Draft",
                 "fabric_slices": ["fab-1"], "chameleon_slices": []},
            ]
            r = runner.invoke(cli, ["--format", "json", "composite", "list"])
            assert r.exit_code == 0
            assert "exp1" in r.output

    def test_show_composite(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {
                "id": "comp-1", "name": "exp1", "state": "Active",
                "fabric_slices": ["fab-1"], "chameleon_slices": ["chi-1"],
                "fabric_member_summaries": [
                    {"id": "fab-1", "name": "my-fab", "state": "StableOK"},
                ],
                "chameleon_member_summaries": [
                    {"id": "chi-1", "name": "my-chi", "state": "Active"},
                ],
                "cross_connections": [],
            }
            r = runner.invoke(cli, ["composite", "show", "comp-1"])
            assert r.exit_code == 0
            assert "exp1" in r.output
            assert "Active" in r.output

    def test_create_composite(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {"id": "comp-new", "name": "test-comp", "state": "Draft"}
            r = runner.invoke(cli, ["--format", "json", "composite", "create", "test-comp"])
            assert r.exit_code == 0
            assert "comp-new" in r.output

    def test_delete_with_force(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {"status": "deleted", "id": "comp-1"}
            r = runner.invoke(cli, ["composite", "delete", "comp-1", "--force"])
            assert r.exit_code == 0

    def test_delete_prompts_without_force(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            r = runner.invoke(cli, ["composite", "delete", "comp-1"], input="n\n")
            assert r.exit_code == 1


class TestCompositeMockMembers:
    """Test composite member management with mocked HTTP."""

    def test_add_fabric_member(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            # First call: get composite (to read current members)
            # Second call: put members
            mock.side_effect = [
                {"id": "comp-1", "fabric_slices": [], "chameleon_slices": []},
                {"id": "comp-1", "fabric_slices": ["fab-1"], "chameleon_slices": []},
            ]
            r = runner.invoke(cli, ["composite", "add-fabric", "comp-1", "fab-1"])
            assert r.exit_code == 0

    def test_add_chameleon_member(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.side_effect = [
                {"id": "comp-1", "fabric_slices": [], "chameleon_slices": []},
                {"id": "comp-1", "fabric_slices": [], "chameleon_slices": ["chi-1"]},
            ]
            r = runner.invoke(cli, ["composite", "add-chameleon", "comp-1", "chi-1"])
            assert r.exit_code == 0

    def test_remove_fabric_member(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.side_effect = [
                {"id": "comp-1", "fabric_slices": ["fab-1"], "chameleon_slices": []},
                {"id": "comp-1", "fabric_slices": [], "chameleon_slices": []},
            ]
            r = runner.invoke(cli, ["composite", "remove-fabric", "comp-1", "fab-1"])
            assert r.exit_code == 0

    def test_remove_chameleon_member(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.side_effect = [
                {"id": "comp-1", "fabric_slices": [], "chameleon_slices": ["chi-1"]},
                {"id": "comp-1", "fabric_slices": [], "chameleon_slices": []},
            ]
            r = runner.invoke(cli, ["composite", "remove-chameleon", "comp-1", "chi-1"])
            assert r.exit_code == 0


class TestCompositeMockCrossConnections:
    """Test cross-connection management with mocked HTTP."""

    def test_show_cross_connections(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {
                "id": "comp-1", "cross_connections": [
                    {"type": "fabnetv4", "fabric_node": "n1", "chameleon_node": "cn1"},
                ],
            }
            r = runner.invoke(cli, ["composite", "cross-connections", "comp-1"])
            assert r.exit_code == 0
            assert "fabnetv4" in r.output

    def test_clear_cross_connections(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {"id": "comp-1", "cross_connections": []}
            r = runner.invoke(cli, ["composite", "cross-connections", "comp-1", "--clear"])
            assert r.exit_code == 0


class TestCompositeMockSubmit:
    """Test composite submit with mocked HTTP."""

    def test_submit_composite(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {
                "composite_id": "comp-1",
                "fabric_results": [{"id": "fab-1", "status": "submitted", "name": "fab-slice"}],
                "chameleon_results": [{"id": "chi-1", "status": "submitted"}],
            }
            r = runner.invoke(cli, ["composite", "submit", "comp-1"])
            assert r.exit_code == 0

    def test_submit_shows_errors(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {
                "composite_id": "comp-1",
                "fabric_results": [{"id": "fab-1", "status": "error", "error": "no resources"}],
                "chameleon_results": [],
            }
            r = runner.invoke(cli, ["composite", "submit", "comp-1"])
            assert r.exit_code == 0
            assert "ERROR" in r.output


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestCompositeIntegration:
    """Real composite operations against live backend."""

    def test_list_composites(self, integration_runner):
        from loomai_cli.main import cli
        r = integration_runner.invoke(cli, ["--format", "json", "composite", "list"])
        assert r.exit_code == 0

    def test_create_and_delete(self, integration_runner):
        from loomai_cli.main import cli
        import json

        # Create
        r = integration_runner.invoke(cli, ["--format", "json", "composite", "create", "cli-test-comp"])
        assert r.exit_code == 0

        # Parse ID from output
        try:
            data = json.loads(r.output.strip().split("\n")[-1])
            comp_id = data.get("id", "")
        except Exception:
            # Try to find ID in output
            comp_id = ""
            for line in r.output.split("\n"):
                if "comp-" in line:
                    import re
                    m = re.search(r"(comp-[a-f0-9-]+)", line)
                    if m:
                        comp_id = m.group(1)
                        break

        if comp_id:
            # Show
            r = integration_runner.invoke(cli, ["composite", "show", comp_id])
            assert r.exit_code == 0

            # Delete
            r = integration_runner.invoke(cli, ["composite", "delete", comp_id, "--force"])
            assert r.exit_code == 0

    def test_full_lifecycle(self, integration_runner, test_slice_name):
        """Create composite, add FABRIC draft, show, delete."""
        from loomai_cli.main import cli
        import json

        comp_name = f"cli-comp-{test_slice_name}"
        fab_name = f"cli-fab-{test_slice_name}"

        try:
            # Create FABRIC draft
            integration_runner.invoke(cli, ["slices", "create", fab_name])

            # Create composite
            r = integration_runner.invoke(cli, ["--format", "json", "composite", "create", comp_name])
            assert r.exit_code == 0

            # Parse composite ID
            comp_id = ""
            try:
                for line in r.output.strip().split("\n"):
                    if line.strip().startswith("{"):
                        data = json.loads(line)
                        comp_id = data.get("id", "")
                        break
            except Exception:
                pass

            if comp_id:
                # Add FABRIC member
                r = integration_runner.invoke(cli, ["composite", "add-fabric", comp_id, fab_name])
                assert r.exit_code == 0

                # Show — should list the FABRIC member
                r = integration_runner.invoke(cli, ["composite", "show", comp_id])
                assert r.exit_code == 0

                # Delete composite
                integration_runner.invoke(cli, ["composite", "delete", comp_id, "--force"])
        finally:
            integration_runner.invoke(cli, ["slices", "delete", fab_name, "--force"])
