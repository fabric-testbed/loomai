"""CLI tests for Federated slice commands.

Run mock tests:   pytest tests/test_cli_federated.py -v
Run integration:  pytest tests/test_cli_federated.py -v --integration
"""

import json
from unittest.mock import patch

import pytest


class TestFederatedMockHelp:
    """Verify federated command help text."""

    def test_federated_group_help(self, invoke):
        r = invoke("federated", "--help")
        assert r.exit_code == 0
        assert "federated" in r.output.lower()
        assert "composite" not in r.output.lower()

    @pytest.mark.parametrize("args", [
        ("list",),
        ("show",),
        ("create",),
        ("delete",),
        ("graph",),
        ("submit",),
        ("members",),
        ("members", "list"),
        ("members", "add"),
        ("members", "remove"),
        ("members", "replace-fabric"),
        ("connections",),
        ("connections", "list"),
        ("connections", "add"),
        ("connections", "remove"),
        ("connections", "clear"),
        ("connections", "set"),
        ("connections", "plan"),
    ])
    def test_subcommand_help(self, invoke, args):
        r = invoke("federated", *args, "--help")
        assert r.exit_code == 0


class TestFederatedMockCRUD:
    """Test federated CRUD with mocked HTTP."""

    def test_list_federated(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = [
                {"id": "fed-1", "name": "exp1", "state": "Draft", "kind": "federated"},
            ]
            r = runner.invoke(cli, ["federated", "list", "--format", "json"])
            assert r.exit_code == 0
            assert json.loads(r.output)[0]["name"] == "exp1"
            assert mock.call_args.args[:2] == ("GET", "/federated/slices")

    def test_show_federated(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {
                "id": "fed-1",
                "name": "exp1",
                "state": "Active",
                "members": [
                    {"provider": "fabric", "slice_id": "fab-1", "name": "my-fab"},
                    {"provider": "chameleon", "slice_id": "chi-1", "name": "my-chi"},
                ],
            }
            r = runner.invoke(cli, ["federated", "show", "fed-1", "--format", "json"])
            assert r.exit_code == 0
            parsed = json.loads(r.output)
            assert parsed["name"] == "exp1"
            assert parsed["state"] == "Active"

    def test_create_federated(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {"id": "fed-new", "name": "test-fed", "state": "Draft"}
            r = runner.invoke(cli, ["federated", "create", "test-fed", "--format", "json"])
            assert r.exit_code == 0
            assert json.loads(r.output)["id"] == "fed-new"
            assert mock.call_args.args[:2] == ("POST", "/federated/slices")

    def test_delete_with_force(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {"status": "deleted", "id": "fed-1"}
            r = runner.invoke(cli, ["federated", "delete", "fed-1", "--force", "--format", "json"])
            assert r.exit_code == 0
            assert json.loads(r.output)["status"] == "deleted"
            assert mock.call_args.args[:2] == ("DELETE", "/federated/slices/fed-1")

    def test_delete_prompts_without_force(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request"):
            r = runner.invoke(cli, ["federated", "delete", "fed-1"], input="n\n")
            assert r.exit_code == 1


class TestFederatedMockMembers:
    """Test federated member management with mocked HTTP."""

    def test_add_fabric_member(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {
                "id": "fed-1",
                "members": [{"provider": "fabric", "slice_id": "fab-1"}],
            }
            r = runner.invoke(cli, [
                "federated", "members", "add", "fed-1", "fabric", "fab-1",
                "--format", "json",
            ])
            assert r.exit_code == 0
            assert json.loads(r.output)["members"][0]["slice_id"] == "fab-1"
            assert mock.call_args.args[:2] == ("POST", "/federated/slices/fed-1/members/add")

    def test_add_chameleon_member(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {
                "id": "fed-1",
                "members": [{"provider": "chameleon", "slice_id": "chi-1"}],
            }
            r = runner.invoke(cli, [
                "federated", "members", "add", "fed-1", "chameleon", "chi-1",
                "--name", "chi-demo",
            ])
            assert r.exit_code == 0
            assert mock.call_args.kwargs["json"]["name"] == "chi-demo"

    def test_remove_member(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {"id": "fed-1", "members": []}
            r = runner.invoke(cli, [
                "federated", "members", "remove", "fed-1", "fabric", "fab-1",
            ])
            assert r.exit_code == 0
            assert mock.call_args.args[:2] == ("POST", "/federated/slices/fed-1/members/remove")


class TestFederatedMockConnections:
    """Test federated cross-testbed connection management."""

    def test_list_connections(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = [
                {
                    "id": "conn-1",
                    "type": "fabnetv4_l3",
                    "fabric_slice": "fab-1",
                    "chameleon_slice": "chi-1",
                },
            ]
            r = runner.invoke(cli, ["federated", "connections", "list", "fed-1"])
            assert r.exit_code == 0
            assert "fabnetv4_l3" in r.output

    def test_add_connection(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {
                "id": "fed-1",
                "cross_connections": [{"id": "conn-1", "type": "facility_port_l2"}],
            }
            r = runner.invoke(cli, [
                "federated", "connections", "add", "fed-1",
                "--type", "facility_port_l2",
                "--fabric-slice", "fab-1",
                "--chameleon-slice", "chi-1",
                "--fabric-site", "TACC",
                "--chameleon-site", "CHI@TACC",
                "--vlan", "1234",
                "--facility-port", "fp1",
                "--physical-network", "physnet1",
                "--format", "json",
            ])
            assert r.exit_code == 0
            payload = mock.call_args.kwargs["json"]
            assert payload["type"] == "facility_port_l2"
            assert payload["vlan"] == "1234"
            assert payload["endpoint_a"]["provider"] == "fabric"
            assert payload["endpoint_b"]["provider"] == "chameleon"

    def test_clear_connections(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {"id": "fed-1", "cross_connections": []}
            r = runner.invoke(cli, [
                "federated", "connections", "clear", "fed-1", "--format", "json",
            ])
            assert r.exit_code == 0
            assert mock.call_args.args[:2] == ("PUT", "/federated/slices/fed-1/connections")


class TestFederatedMockSubmit:
    """Test federated submit with mocked HTTP."""

    def test_submit_federated(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {
                "id": "fed-1",
                "fabric_results": [{"id": "fab-1", "status": "submitted"}],
                "chameleon_results": [{"id": "chi-1", "status": "submitted"}],
            }
            r = runner.invoke(cli, ["federated", "submit", "fed-1", "--format", "json"])
            assert r.exit_code == 0
            assert json.loads(r.output)["id"] == "fed-1"


@pytest.mark.integration
class TestFederatedIntegration:
    """Real federated operations against live backend."""

    def test_list_federated(self, integration_runner):
        from loomai_cli.main import cli
        r = integration_runner.invoke(cli, ["federated", "list", "--format", "json"])
        assert r.exit_code == 0

    def test_create_and_delete(self, integration_runner):
        from loomai_cli.main import cli

        r = integration_runner.invoke(cli, [
            "federated", "create", "cli-test-fed", "--format", "json",
        ])
        assert r.exit_code == 0
        fed_id = json.loads(r.output).get("id", "")

        if fed_id:
            r = integration_runner.invoke(cli, ["federated", "show", fed_id, "--format", "json"])
            assert r.exit_code == 0

            r = integration_runner.invoke(cli, ["federated", "delete", fed_id, "--force"])
            assert r.exit_code == 0
