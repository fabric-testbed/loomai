"""Shared test fixtures for CLI tests."""

import os
import uuid

import pytest
from click.testing import CliRunner

from loomai_cli.main import cli


# ---------------------------------------------------------------------------
# pytest hooks for integration tests
# ---------------------------------------------------------------------------

def pytest_addoption(parser):
    parser.addoption("--integration", action="store_true", default=False,
                     help="Run integration tests (requires running backend)")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--integration"):
        skip = pytest.mark.skip(reason="need --integration flag to run")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip)


# ---------------------------------------------------------------------------
# Unit test fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def runner():
    """Click test runner."""
    return CliRunner()


@pytest.fixture
def invoke(runner):
    """Shortcut to invoke CLI commands with the test runner."""
    def _invoke(*args, **kwargs):
        return runner.invoke(cli, list(args), catch_exceptions=False, **kwargs)
    return _invoke


# ---------------------------------------------------------------------------
# Integration test fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def integration_url():
    """Backend URL for integration tests."""
    return os.environ.get("LOOMAI_URL", "http://localhost:8000")


@pytest.fixture
def integration_runner():
    """CLI runner with env pointing to live backend."""
    return CliRunner(env={"LOOMAI_URL": os.environ.get("LOOMAI_URL", "http://localhost:8000")})


@pytest.fixture
def test_slice_name():
    """Generate a unique slice name for integration tests."""
    return f"cli-test-{uuid.uuid4().hex[:8]}"
