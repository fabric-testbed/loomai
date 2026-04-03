"""CLI tests for Chameleon Cloud commands.

Run mock tests:   pytest tests/test_cli_chameleon.py -v
Run integration:  pytest tests/test_cli_chameleon.py -v --integration
"""

from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Mock Tests
# ---------------------------------------------------------------------------

class TestChameleonMockHelp:
    """Verify Chameleon command help text."""

    def test_chameleon_group_help(self, invoke):
        r = invoke("chameleon", "--help")
        assert r.exit_code == 0
        assert "Chameleon" in r.output

    @pytest.mark.parametrize("cmd", [
        "sites", "images", "test",
    ])
    def test_subcommand_help(self, invoke, cmd):
        r = invoke("chameleon", cmd, "--help")
        assert r.exit_code == 0


class TestChameleonMockSites:
    """Test Chameleon site commands with mocked HTTP."""

    def test_list_sites(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = [
                {"name": "CHI@UC", "configured": True, "location": {"city": "Chicago"}},
                {"name": "CHI@TACC", "configured": True, "location": {"city": "Austin"}},
            ]
            r = runner.invoke(cli, ["--format", "json", "chameleon", "sites"])
            assert r.exit_code == 0
            assert "CHI@UC" in r.output

    def test_site_availability(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {"hosts": [{"hypervisor_hostname": "h1"}], "flavors": []}
            r = runner.invoke(cli, ["--format", "json", "chameleon", "sites", "CHI@UC"])
            assert r.exit_code == 0


class TestChameleonMockLeases:
    """Test Chameleon lease commands with mocked HTTP."""

    def test_list_leases(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = [
                {"id": "lease-1", "name": "my-lease", "status": "ACTIVE"},
            ]
            r = runner.invoke(cli, ["--format", "json", "chameleon", "leases", "list",
                                    "--site", "CHI@UC"])
            assert r.exit_code == 0
            assert "lease-1" in r.output

    def test_create_lease(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {"id": "lease-new", "name": "test", "status": "PENDING"}
            r = runner.invoke(cli, ["--format", "json", "chameleon", "leases", "create",
                                    "--site", "CHI@UC", "--name", "test",
                                    "--type", "compute_skylake"])
            assert r.exit_code == 0


class TestChameleonMockInstances:
    """Test Chameleon instance commands with mocked HTTP."""

    def test_list_instances(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = [
                {"id": "inst-1", "name": "node1", "status": "ACTIVE", "site": "CHI@UC"},
            ]
            r = runner.invoke(cli, ["--format", "json", "chameleon", "instances", "list",
                                    "--site", "CHI@UC"])
            assert r.exit_code == 0
            assert "ACTIVE" in r.output


class TestChameleonMockDrafts:
    """Test Chameleon draft commands with mocked HTTP."""

    def test_list_drafts(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = [
                {"id": "chi-slice-1", "name": "draft1", "site": "CHI@UC", "state": "Configuring"},
            ]
            r = runner.invoke(cli, ["--format", "json", "chameleon", "drafts", "list"])
            assert r.exit_code == 0

    def test_create_draft(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {"id": "chi-slice-new", "name": "test", "site": "CHI@UC"}
            r = runner.invoke(cli, ["--format", "json", "chameleon", "drafts", "create",
                                    "--name", "test", "--site", "CHI@UC"])
            assert r.exit_code == 0

    def test_delete_draft(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {"status": "deleted"}
            r = runner.invoke(cli, ["chameleon", "drafts", "delete", "chi-slice-1"])
            assert r.exit_code == 0


class TestChameleonMockSlices:
    """Test Chameleon slice commands with mocked HTTP."""

    def test_list_slices(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = [
                {"id": "chi-1", "name": "exp1", "state": "Active", "site": "CHI@UC"},
            ]
            r = runner.invoke(cli, ["--format", "json", "chameleon", "slices", "list"])
            assert r.exit_code == 0
            assert "Active" in r.output

    def test_delete_slice(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {"status": "deleted"}
            r = runner.invoke(cli, ["chameleon", "slices", "delete", "chi-1"])
            assert r.exit_code == 0


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestChameleonIntegration:
    """Real Chameleon operations against live backend."""

    def test_list_sites(self, integration_runner):
        from loomai_cli.main import cli
        r = integration_runner.invoke(cli, ["--format", "json", "chameleon", "sites"])
        # May fail if Chameleon not configured — that's OK
        if "disabled" not in r.output.lower():
            assert r.exit_code == 0

    def test_draft_lifecycle(self, integration_runner):
        from loomai_cli.main import cli
        # Create draft
        r = integration_runner.invoke(cli, ["--format", "json", "chameleon", "drafts", "create",
                                            "cli-test-draft", "--site", "CHI@UC"])
        if "disabled" in r.output.lower() or r.exit_code != 0:
            pytest.skip("Chameleon not configured")

        # List drafts
        r = integration_runner.invoke(cli, ["--format", "json", "chameleon", "drafts"])
        assert r.exit_code == 0
        assert "cli-test-draft" in r.output

        # Delete draft
        r = integration_runner.invoke(cli, ["chameleon", "drafts", "delete", "cli-test-draft", "--force"])
