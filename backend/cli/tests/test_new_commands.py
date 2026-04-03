"""Tests for newly added CLI commands — archive, boot-config set,
facility-ports, artifact versions, rsync, completions."""

import json
import os
import tempfile
from unittest.mock import patch

from click.testing import CliRunner
from loomai_cli.main import cli


class TestSliceArchive:
    def test_archive_single_with_force(self, runner):
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {"status": "archived", "name": "my-slice"}
            result = runner.invoke(cli, ["slices", "archive", "my-slice", "--force"])
            assert result.exit_code == 0

    def test_archive_prompts_without_force(self, runner):
        with patch("loomai_cli.client.Client._request"):
            result = runner.invoke(cli, ["slices", "archive", "my-slice"], input="n\n")
            assert result.exit_code == 1  # Aborted

    def test_archive_all_terminal(self, runner):
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {"archived": ["s1", "s2"], "count": 2}
            result = runner.invoke(cli, ["slices", "archive", "--all-terminal"])
            assert result.exit_code == 0

    def test_archive_no_args_fails(self, runner):
        result = runner.invoke(cli, ["slices", "archive"])
        assert result.exit_code != 0


class TestBootConfigSet:
    def test_set_with_commands(self, runner):
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {}
            result = runner.invoke(cli, [
                "boot-config", "set", "my-slice", "node1",
                "-c", "apt update", "-c", "apt install -y nginx",
            ])
            assert result.exit_code == 0

    def test_set_from_file(self, runner):
        config = {"commands": [{"command": "echo hi", "order": 0}],
                  "uploads": [], "network": []}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config, f)
            f.flush()
            try:
                with patch("loomai_cli.client.Client._request") as mock:
                    mock.return_value = {}
                    result = runner.invoke(cli, [
                        "boot-config", "set", "my-slice", "node1",
                        "--from-file", f.name,
                    ])
                    assert result.exit_code == 0
            finally:
                os.unlink(f.name)

    def test_set_no_args_fails(self, runner):
        result = runner.invoke(cli, ["boot-config", "set", "my-slice", "node1"])
        assert result.exit_code != 0


class TestFacilityPorts:
    def test_list(self, runner):
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = [
                {"name": "fp1", "site": "CERN", "vlan": "800", "bandwidth": 10}
            ]
            result = runner.invoke(cli, ["facility-ports", "list"])
            assert result.exit_code == 0

    def test_add(self, runner):
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {"name": "fp1", "site": "CERN"}
            result = runner.invoke(cli, [
                "facility-ports", "add", "my-slice", "fp1",
                "--site", "CERN", "--vlan", "800",
            ])
            assert result.exit_code == 0

    def test_add_requires_site(self, runner):
        result = runner.invoke(cli, [
            "facility-ports", "add", "my-slice", "fp1",
        ])
        assert result.exit_code != 0
        assert "site" in result.output.lower() or "required" in result.output.lower()

    def test_remove(self, runner):
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {}
            result = runner.invoke(cli, [
                "facility-ports", "remove", "my-slice", "fp1",
            ])
            assert result.exit_code == 0


class TestArtifactVersions:
    def test_versions(self, runner):
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {
                "uuid": "abc-123",
                "versions": [
                    {"uuid": "v1", "version": "1.0", "active": True,
                     "created_at": "2025-01-01"},
                ],
            }
            result = runner.invoke(cli, [
                "--format", "json", "artifacts", "versions", "abc-123",
            ])
            assert result.exit_code == 0

    def test_push_version(self, runner):
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {"status": "ok"}
            result = runner.invoke(cli, [
                "artifacts", "push-version", "abc-123", "My_Weave",
            ])
            assert result.exit_code == 0

    def test_delete_version_with_force(self, runner):
        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {}
            result = runner.invoke(cli, [
                "artifacts", "delete-version", "abc-123", "v1", "--force",
            ])
            assert result.exit_code == 0

    def test_delete_version_prompts_without_force(self, runner):
        with patch("loomai_cli.client.Client._request"):
            result = runner.invoke(cli, [
                "artifacts", "delete-version", "abc-123", "v1",
            ], input="n\n")
            assert result.exit_code == 1


class TestRsync:
    def test_rsync_help(self, runner):
        result = runner.invoke(cli, ["rsync", "--help"])
        assert result.exit_code == 0
        assert "--all" in result.output

    def test_rsync_single_node(self, runner, tmp_path):
        # Create a small temp directory with files
        (tmp_path / "a.txt").write_text("hello")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "b.txt").write_text("world")

        with patch("loomai_cli.client.Client._request") as mock:
            mock.return_value = {}
            result = runner.invoke(cli, [
                "rsync", "my-slice", "node1", str(tmp_path), "/tmp/dest",
            ])
            assert result.exit_code == 0


class TestCompletions:
    def test_bash(self, runner):
        result = runner.invoke(cli, ["completions", "bash"])
        assert result.exit_code == 0
        assert "LOOMAI_COMPLETE" in result.output

    def test_zsh(self, runner):
        result = runner.invoke(cli, ["completions", "zsh"])
        assert result.exit_code == 0
        assert "LOOMAI_COMPLETE" in result.output

    def test_fish(self, runner):
        result = runner.invoke(cli, ["completions", "fish"])
        assert result.exit_code == 0

    def test_invalid_shell(self, runner):
        result = runner.invoke(cli, ["completions", "powershell"])
        assert result.exit_code != 0
