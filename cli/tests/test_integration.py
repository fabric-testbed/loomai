"""Integration tests — require a running LoomAI backend.

Run with: pytest tests/ --integration
"""

import pytest
from loomai_cli.main import cli


@pytest.mark.integration
class TestSiteDiscovery:
    """Test site/resource queries against live backend."""

    def test_sites_list(self, integration_runner):
        result = integration_runner.invoke(cli, ["--format", "json", "sites", "list"])
        assert result.exit_code == 0

    def test_sites_show(self, integration_runner):
        # First get a site name
        result = integration_runner.invoke(cli, ["--format", "json", "sites", "list"])
        if result.exit_code != 0:
            pytest.skip("Could not list sites")
        import json
        sites = json.loads(result.output)
        if not sites:
            pytest.skip("No sites available")
        name = sites[0].get("name", sites[0].get("id"))
        result = integration_runner.invoke(cli, ["--format", "json", "sites", "show", name])
        assert result.exit_code == 0

    def test_images_list(self, integration_runner):
        result = integration_runner.invoke(cli, ["images"])
        assert result.exit_code == 0


@pytest.mark.integration
class TestSliceOperations:
    """Test slice CRUD against live backend."""

    def test_slices_list(self, integration_runner):
        result = integration_runner.invoke(cli, ["--format", "json", "slices", "list"])
        assert result.exit_code == 0

    def test_create_and_delete(self, integration_runner, test_slice_name):
        # Create
        result = integration_runner.invoke(cli, [
            "slices", "create", test_slice_name,
        ])
        assert result.exit_code == 0

        # Verify it exists
        result = integration_runner.invoke(cli, [
            "--format", "json", "slices", "show", test_slice_name,
        ])
        assert result.exit_code == 0

        # Delete
        result = integration_runner.invoke(cli, [
            "slices", "delete", test_slice_name, "--force",
        ])
        assert result.exit_code == 0


@pytest.mark.integration
class TestArtifacts:
    """Test artifact operations against live backend."""

    def test_list_local(self, integration_runner):
        result = integration_runner.invoke(cli, [
            "--format", "json", "artifacts", "list", "--local",
        ])
        assert result.exit_code == 0

    def test_tags(self, integration_runner):
        result = integration_runner.invoke(cli, [
            "--format", "json", "artifacts", "tags",
        ])
        assert result.exit_code == 0


@pytest.mark.integration
class TestWeaves:
    """Test weave operations against live backend."""

    def test_list(self, integration_runner):
        result = integration_runner.invoke(cli, [
            "--format", "json", "weaves", "list",
        ])
        assert result.exit_code == 0

    def test_runs(self, integration_runner):
        result = integration_runner.invoke(cli, [
            "--format", "json", "weaves", "runs",
        ])
        assert result.exit_code == 0


@pytest.mark.integration
class TestAI:
    """Test AI model listing against live backend."""

    def test_models(self, integration_runner):
        result = integration_runner.invoke(cli, [
            "--format", "json", "ai", "models",
        ])
        assert result.exit_code == 0
