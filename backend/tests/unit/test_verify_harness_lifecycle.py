"""Unit coverage for the post-deploy harness lifecycle verifier."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest


_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_harness_lifecycle.py"
_SPEC = importlib.util.spec_from_file_location("verify_harness_lifecycle", _SCRIPT)
assert _SPEC is not None
assert _SPEC.loader is not None
vhl = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(vhl)


class FakeApi:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = responses
        self.posts: list[tuple[str, dict[str, Any] | None]] = []

    def post(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.posts.append((path, params))
        return self.responses.pop(0)


def test_post_status_surfaces_installer_output() -> None:
    api = FakeApi([{"status": "error", "output": "curl: transfer failed"}])

    with pytest.raises(vhl.CheckError, match="curl: transfer failed"):
        vhl._post_status(api, "/ai/tools/goose/install", "goose", vhl.INSTALL_OK, "install")


def test_uninstall_active_process_refusal_is_expected_when_requested() -> None:
    api = FakeApi([{"status": "running", "error": "claude process is still active"}])

    data = vhl._post_uninstall(api, "claude", "active-process refusal", expect_refusal=True)

    assert data["status"] == "running"
    assert api.posts == [("/ai/tools/claude/uninstall", None)]


def test_uninstall_active_process_refusal_fails_normal_lifecycle() -> None:
    api = FakeApi([{"status": "running", "error": "claude process is still active"}])

    with pytest.raises(vhl.CheckError, match="stop the active process"):
        vhl._post_uninstall(api, "claude", "uninstall")


def test_pinned_version_parity_rejects_drift() -> None:
    entry = {
        "version_drift": True,
        "package_versions": {
            "@anthropic-ai/claude-code": {
                "installed": "2.1.170",
                "pinned": "2.1.202",
                "drift": True,
            },
        },
    }

    with pytest.raises(vhl.CheckError, match="version drift"):
        vhl._expect_pinned_versions_current(entry, "claude", "install")


def test_uninstalled_package_assertion_rejects_remaining_packages() -> None:
    entry = {
        "package_versions": {
            "aider-chat": {"installed": "0.85.1", "pinned": "0.85.1"},
        },
    }

    with pytest.raises(vhl.CheckError, match="packages remain"):
        vhl._expect_uninstalled_packages_absent(entry, "aider", "uninstall")
