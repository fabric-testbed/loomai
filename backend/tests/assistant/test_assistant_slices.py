"""LoomAI assistant slice creation and engagement tests.

Tests the assistant's ability to create real FABRIC slices via natural
language, and to interact with running slices (run commands, install software).

Gate: ``@pytest.mark.fabric`` — excluded from default runs.
Run::

    pytest tests/assistant/test_assistant_slices.py -v -s -m fabric --timeout=900
"""

from __future__ import annotations

import time

import pytest

from tests.assistant.conftest import (
    assert_no_errors,
    assert_response_contains,
    assert_tool_was_called,
    cleanup_slice,
    exec_on_node,
    send_chat,
    wait_ssh_ready,
    wait_stable_ok,
)

pytestmark = pytest.mark.fabric


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_slice(api, name: str) -> dict | None:
    """Try to find a slice by name, return its data or None."""
    resp = api.get(f"/slices/{name}")
    if resp.status_code == 200:
        return resp.json()
    return None


def _find_node_name(slice_data: dict) -> str | None:
    """Extract the first node name from slice data."""
    nodes = slice_data.get("nodes", [])
    return nodes[0]["name"] if nodes else None


# ---------------------------------------------------------------------------
# Slice creation via assistant
# ---------------------------------------------------------------------------

class TestAssistantSliceCreation:
    """Test the assistant's ability to create and deploy FABRIC slices."""

    def test_assistant_creates_single_node_slice(self, api, fabric_ok, healthy_model):
        """Ask the assistant to create a single-node slice and verify it deploys."""
        ts = int(time.time())
        name = f"e2e-assist-single-{ts}"

        try:
            resp = send_chat(
                api,
                f"Create a FABRIC slice called {name} with one node named node1, "
                f"2 cores, 8 GB RAM, 10 GB disk, Ubuntu 22, at any available site. "
                f"Then submit it.",
                model=healthy_model,
                timeout=600.0,
            )
            assert_no_errors(resp)

            # Verify the assistant used the right tools
            called = [tc.get("name") for tc in resp.tool_calls]
            assert "create_slice" in called, f"create_slice not called. Tools: {called}"
            assert "submit_slice" in called, f"submit_slice not called. Tools: {called}"

            # Wait for the slice to reach StableOK
            data = wait_stable_ok(api, name)
            assert data["state"] == "StableOK"

            # Verify the node is accessible
            node_name = _find_node_name(data)
            assert node_name, "No nodes found in slice"
            wait_ssh_ready(api, name, node_name)

            result = exec_on_node(api, name, node_name, "hostname")
            assert result.get("stdout", "").strip(), "hostname returned empty output"

        finally:
            cleanup_slice(api, name)

    def test_assistant_creates_two_node_slice(self, api, fabric_ok, healthy_model):
        """Ask the assistant to create a two-node networked slice."""
        ts = int(time.time())
        name = f"e2e-assist-net-{ts}"

        try:
            resp = send_chat(
                api,
                f"Create a FABRIC slice called {name} with two nodes (node1 and node2), "
                f"each with 2 cores, 8 GB RAM, 10 GB disk, Ubuntu 22. "
                f"Connect them with a FABNetv4 network. Submit the slice.",
                model=healthy_model,
                timeout=600.0,
            )
            assert_no_errors(resp)

            # Verify multiple add_node calls
            called = [tc.get("name") for tc in resp.tool_calls]
            add_node_count = called.count("add_node")
            assert add_node_count >= 2, f"Expected >=2 add_node calls, got {add_node_count}"
            assert "submit_slice" in called, f"submit_slice not called. Tools: {called}"

            # Wait for StableOK
            data = wait_stable_ok(api, name)
            assert len(data.get("nodes", [])) >= 2, (
                f"Expected >=2 nodes, got {len(data.get('nodes', []))}"
            )

        finally:
            cleanup_slice(api, name)


# ---------------------------------------------------------------------------
# Slice engagement via assistant
# ---------------------------------------------------------------------------

@pytest.fixture(scope="class")
def running_slice(api, fabric_ok):
    """Create a slice via direct API for engagement tests."""
    name = f"e2e-assist-engage-{int(time.time())}"
    try:
        # Create and submit via direct API (deterministic, faster)
        resp = api.post(f"/slices?name={name}")
        assert resp.status_code == 200, f"Create failed: {resp.text[:200]}"

        resp = api.post(
            f"/slices/{name}/nodes",
            json={
                "name": "node1",
                "site": "auto",
                "cores": 2,
                "ram": 8,
                "disk": 10,
                "image": "default_ubuntu_22",
            },
        )
        assert resp.status_code == 200, f"Add node failed: {resp.text[:200]}"

        resp = api.post(f"/slices/{name}/submit", timeout=120.0)
        assert resp.status_code == 200, f"Submit failed: {resp.text[:200]}"

        wait_stable_ok(api, name)
        wait_ssh_ready(api, name, "node1")

        yield name
    finally:
        cleanup_slice(api, name)


class TestAssistantSliceEngagement:
    """Test the assistant's ability to interact with running slices."""

    def test_assistant_runs_command(self, api, healthy_model, running_slice):
        """Ask the assistant to run a command on a slice node."""
        resp = send_chat(
            api,
            f"Run 'uname -a' on node1 of slice {running_slice}",
            model=healthy_model,
            timeout=120.0,
        )
        assert_no_errors(resp)
        assert_tool_was_called(resp, "ssh_execute")
        # The response or tool results should contain Linux kernel info
        assert_response_contains(resp, ["linux"], min_matches=1)

    def test_assistant_installs_software(self, api, healthy_model, running_slice):
        """Ask the assistant to install software and verify it worked."""
        resp = send_chat(
            api,
            f"Install htop on node1 of slice {running_slice}. "
            f"Use sudo apt-get install -y htop.",
            model=healthy_model,
            timeout=180.0,
        )
        assert_no_errors(resp)
        assert_tool_was_called(resp, "ssh_execute")

        # Directly verify htop was installed
        result = exec_on_node(api, running_slice, "node1", "which htop", timeout=30)
        assert "htop" in result.get("stdout", ""), (
            f"htop not found after install: {result}"
        )

    def test_assistant_checks_disk(self, api, healthy_model, running_slice):
        """Ask the assistant to check disk usage."""
        resp = send_chat(
            api,
            f"Check disk usage on node1 of slice {running_slice}",
            model=healthy_model,
            timeout=120.0,
        )
        assert_no_errors(resp)
        assert_tool_was_called(resp, "ssh_execute")
        # Response should mention disk-related info
        assert_response_contains(
            resp,
            ["disk", "usage", "filesystem", "available", "used", "gb", "mount", "/dev"],
            min_matches=1,
        )
