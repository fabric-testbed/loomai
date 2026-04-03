"""Tests for node/network/component commands."""

from unittest.mock import patch


class TestNodesHelp:
    def test_nodes_help(self, invoke):
        result = invoke("nodes", "--help")
        assert result.exit_code == 0
        assert "add" in result.output
        assert "update" in result.output
        assert "remove" in result.output

    def test_add_help(self, invoke):
        result = invoke("nodes", "add", "--help")
        assert result.exit_code == 0
        assert "--site" in result.output
        assert "--cores" in result.output
        assert "--ram" in result.output
        assert "--image" in result.output

    def test_update_help(self, invoke):
        result = invoke("nodes", "update", "--help")
        assert result.exit_code == 0


class TestNetworksHelp:
    def test_networks_help(self, invoke):
        result = invoke("networks", "--help")
        assert result.exit_code == 0
        assert "add" in result.output

    def test_add_help(self, invoke):
        result = invoke("networks", "add", "--help")
        assert result.exit_code == 0
        assert "--type" in result.output
        assert "--interfaces" in result.output


class TestComponentsHelp:
    def test_components_help(self, invoke):
        result = invoke("components", "--help")
        assert result.exit_code == 0

    def test_add_help(self, invoke):
        result = invoke("components", "add", "--help")
        assert result.exit_code == 0
        assert "--model" in result.output


class TestNodeCommands:
    def test_add_node(self, runner):
        from loomai_cli.main import cli

        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {"name": "test-slice"}
            result = runner.invoke(cli, [
                "--format", "json", "nodes", "add",
                "my-slice", "node1",
                "--site", "RENC", "--cores", "8", "--ram", "32",
            ])
            assert result.exit_code == 0

    def test_update_node_requires_option(self, runner):
        from loomai_cli.main import cli

        result = runner.invoke(cli, ["nodes", "update", "slice", "node1"])
        assert result.exit_code != 0
        assert "at least one" in result.output.lower() or "error" in result.output.lower()

    def test_remove_node(self, runner):
        from loomai_cli.main import cli

        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {"name": "test-slice"}
            result = runner.invoke(cli, ["nodes", "remove", "my-slice", "node1"])
            assert result.exit_code == 0
