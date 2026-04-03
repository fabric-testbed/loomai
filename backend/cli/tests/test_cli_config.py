"""CLI tests for config, projects, keys, sites, SSH, weaves, and artifacts.

Run mock tests:   pytest tests/test_cli_config.py -v
Run integration:  pytest tests/test_cli_config.py -v --integration
"""

from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Config Commands
# ---------------------------------------------------------------------------

class TestConfigMockHelp:
    @pytest.mark.parametrize("cmd,subcmd", [
        ("config", None), ("config", "show"), ("config", "settings"),
        ("projects", None), ("projects", "list"), ("projects", "switch"),
        ("keys", None), ("keys", "list"), ("keys", "generate"),
    ])
    def test_help(self, invoke, cmd, subcmd):
        args = [cmd, "--help"] if subcmd is None else [cmd, subcmd, "--help"]
        r = invoke(*args)
        assert r.exit_code == 0


class TestConfigMock:
    def test_config_show(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {
                "fabric_config_dir": "/home/fabric/work/fabric_config",
                "token_info": {"exp": 9999999999},
            }
            r = runner.invoke(cli, ["--format", "json", "config", "show"])
            assert r.exit_code == 0

    def test_projects_list(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = [
                {"uuid": "proj-1", "name": "My Project"},
            ]
            r = runner.invoke(cli, ["--format", "json", "projects", "list"])
            assert r.exit_code == 0

    def test_keys_list(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {"bastion_key": True, "slice_keys": ["default"]}
            r = runner.invoke(cli, ["--format", "json", "keys", "list"])
            assert r.exit_code == 0


# ---------------------------------------------------------------------------
# Sites Commands
# ---------------------------------------------------------------------------

class TestSitesMockHelp:
    @pytest.mark.parametrize("cmd", ["list", "show", "hosts", "find"])
    def test_help(self, invoke, cmd):
        r = invoke("sites", cmd, "--help")
        assert r.exit_code == 0


class TestSitesMock:
    def test_list_sites(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = [
                {"name": "RENC", "state": "Active", "cores_available": 200,
                 "location": {"lat": 35.0, "lon": -79.0}},
                {"name": "TACC", "state": "Active", "cores_available": 150,
                 "location": {"lat": 30.0, "lon": -97.0}},
            ]
            r = runner.invoke(cli, ["--format", "json", "sites", "list"])
            assert r.exit_code == 0
            assert "RENC" in r.output

    def test_show_site(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {
                "name": "RENC", "state": "Active",
                "cores_available": 200, "ram_available": 800,
            }
            r = runner.invoke(cli, ["--format", "json", "sites", "show", "RENC"])
            assert r.exit_code == 0

    def test_find_site(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = [
                {"name": "RENC", "state": "Active", "cores_available": 200},
            ]
            r = runner.invoke(cli, ["--format", "json", "sites", "find",
                                    "--cores", "4", "--ram", "8"])
            assert r.exit_code == 0


# ---------------------------------------------------------------------------
# SSH/Exec Commands
# ---------------------------------------------------------------------------

class TestSSHMockHelp:
    def test_ssh_help(self, invoke):
        r = invoke("ssh", "--help")
        assert r.exit_code == 0

    def test_exec_help(self, invoke):
        r = invoke("exec", "--help")
        assert r.exit_code == 0


# ---------------------------------------------------------------------------
# Weaves Commands
# ---------------------------------------------------------------------------

class TestWeavesMockHelp:
    @pytest.mark.parametrize("cmd", ["list", "show", "load", "run", "stop", "logs"])
    def test_help(self, invoke, cmd):
        r = invoke("weaves", cmd, "--help")
        assert r.exit_code == 0


class TestWeavesMock:
    def test_list_weaves(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = [
                {"name": "hello-fabric", "description": "Hello FABRIC weave"},
            ]
            r = runner.invoke(cli, ["--format", "json", "weaves", "list"])
            assert r.exit_code == 0
            assert "hello-fabric" in r.output

    def test_show_weave(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {
                "name": "hello-fabric", "config": {"run_script": "weave.sh"},
            }
            r = runner.invoke(cli, ["--format", "json", "weaves", "show", "hello-fabric"])
            assert r.exit_code == 0


# ---------------------------------------------------------------------------
# Artifacts Commands
# ---------------------------------------------------------------------------

class TestArtifactsMockHelp:
    @pytest.mark.parametrize("cmd", ["list", "search", "show", "get", "publish"])
    def test_help(self, invoke, cmd):
        r = invoke("artifacts", cmd, "--help")
        assert r.exit_code == 0


class TestArtifactsMock:
    def test_list_artifacts(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = [
                {"name": "my-weave", "type": "weave", "version": "1.0"},
            ]
            r = runner.invoke(cli, ["--format", "json", "artifacts", "list"])
            assert r.exit_code == 0


# ---------------------------------------------------------------------------
# Recipes Commands
# ---------------------------------------------------------------------------

class TestRecipesMockHelp:
    @pytest.mark.parametrize("cmd", ["list", "show", "run"])
    def test_help(self, invoke, cmd):
        r = invoke("recipes", cmd, "--help")
        assert r.exit_code == 0


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestConfigIntegration:
    def test_config_show(self, integration_runner):
        from loomai_cli.main import cli
        r = integration_runner.invoke(cli, ["--format", "json", "config", "show"])
        assert r.exit_code == 0

    def test_sites_list(self, integration_runner):
        from loomai_cli.main import cli
        r = integration_runner.invoke(cli, ["--format", "json", "sites", "list"])
        assert r.exit_code == 0

    def test_weaves_list(self, integration_runner):
        from loomai_cli.main import cli
        r = integration_runner.invoke(cli, ["--format", "json", "weaves", "list"])
        assert r.exit_code == 0

    def test_artifacts_list(self, integration_runner):
        from loomai_cli.main import cli
        r = integration_runner.invoke(cli, ["--format", "json", "artifacts", "list"])
        assert r.exit_code == 0

    def test_recipes_list(self, integration_runner):
        from loomai_cli.main import cli
        r = integration_runner.invoke(cli, ["--format", "json", "recipes", "list"])
        assert r.exit_code == 0
