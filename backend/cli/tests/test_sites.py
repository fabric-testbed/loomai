"""Tests for site and resource commands."""

from unittest.mock import patch


MOCK_SITES = [
    {"name": "RENC", "state": "Active", "cores_available": 100, "cores_capacity": 200,
     "ram_available": 500, "disk_available": 10000, "hosts": 3,
     "components": {"GPU_RTX6000": {"capacity": 4, "available": 2}}},
    {"name": "UCSD", "state": "Active", "cores_available": 50, "cores_capacity": 100,
     "ram_available": 200, "disk_available": 5000, "hosts": 2, "components": {}},
    {"name": "DOWN", "state": "Maintenance", "cores_available": 0, "cores_capacity": 100,
     "ram_available": 0, "disk_available": 0, "hosts": 1, "components": {}},
]


class TestSitesHelp:
    def test_sites_help(self, invoke):
        result = invoke("sites", "--help")
        assert result.exit_code == 0
        assert "list" in result.output
        assert "show" in result.output
        assert "hosts" in result.output
        assert "find" in result.output


class TestSitesList:
    def test_list_all(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request", return_value=MOCK_SITES):
            result = runner.invoke(cli, ["sites", "list"])
            assert result.exit_code == 0
            assert "RENC" in result.output
            assert "UCSD" in result.output

    def test_list_available_only(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request", return_value=MOCK_SITES):
            result = runner.invoke(cli, ["sites", "list", "--available"])
            assert result.exit_code == 0
            assert "RENC" in result.output
            assert "DOWN" not in result.output

    def test_list_min_cores(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request", return_value=MOCK_SITES):
            result = runner.invoke(cli, ["sites", "list", "--min-cores", "60"])
            assert result.exit_code == 0
            assert "RENC" in result.output
            assert "UCSD" not in result.output


class TestSitesFind:
    def test_find_gpu(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request", return_value=MOCK_SITES):
            result = runner.invoke(cli, ["sites", "find", "--gpu", "GPU_RTX6000"])
            assert result.exit_code == 0
            assert "RENC" in result.output
            assert "UCSD" not in result.output

    def test_find_cores_and_ram(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request", return_value=MOCK_SITES):
            result = runner.invoke(cli, ["sites", "find", "--cores", "80", "--ram", "400"])
            assert result.exit_code == 0
            assert "RENC" in result.output


class TestImages:
    def test_images_help(self, invoke):
        result = invoke("images", "--help")
        assert result.exit_code == 0

    def test_images_list(self, runner):
        from loomai_cli.main import cli
        with patch("loomai_cli.client.Client._request", return_value=["ubuntu_22", "centos_9"]):
            result = runner.invoke(cli, ["images"])
            assert result.exit_code == 0
            assert "ubuntu_22" in result.output


class TestComponentModels:
    def test_help(self, invoke):
        result = invoke("component-models", "--help")
        assert result.exit_code == 0
