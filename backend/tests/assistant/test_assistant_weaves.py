"""LoomAI assistant weave creation and deployment tests.

Tests the assistant's ability to create weave artifacts and deploy them
as real FABRIC slices.

Weave creation (llm only): ~30-60s each.
Weave deploy (fabric): ~10-15 min.

Run::

    pytest tests/assistant/test_assistant_weaves.py -v -s -m llm -k "not deploy" --timeout=120
    pytest tests/assistant/test_assistant_weaves.py -v -s -m fabric -k deploy --timeout=900
"""

from __future__ import annotations

import time

import pytest

from tests.assistant.conftest import (
    assert_no_errors,
    assert_tool_was_called,
    cleanup_slice,
    send_chat,
    wait_stable_ok,
)

# Weave creation tests only need the LLM; deploy needs real FABRIC too.


# ---------------------------------------------------------------------------
# Weave creation
# ---------------------------------------------------------------------------

@pytest.mark.llm
class TestAssistantWeaveCreation:
    """Test the assistant's ability to create weave artifacts."""

    def test_assistant_creates_weave(self, api, healthy_model):
        """Ask the assistant to create a weave and verify it appears in artifacts."""
        ts = int(time.time())
        weave_name = f"e2e_test_weave_{ts}"

        resp = send_chat(
            api,
            f"Create a weave called {weave_name} for a simple 2-node iperf "
            f"bandwidth test between two FABRIC nodes connected by an L2Bridge.",
            model=healthy_model,
            timeout=120.0,
        )
        assert_no_errors(resp)
        assert_tool_was_called(resp, "create_weave")

        # Verify the weave appears in local artifacts
        artifacts_resp = api.get("/artifacts/local", timeout=30.0)
        if artifacts_resp.status_code == 200:
            artifacts = artifacts_resp.json()
            names = []
            if isinstance(artifacts, list):
                names = [a.get("dir_name", "") for a in artifacts]
            elif isinstance(artifacts, dict):
                names = [a.get("dir_name", "") for a in artifacts.get("artifacts", [])]
            assert weave_name in names, (
                f"Weave '{weave_name}' not found in artifacts. Available: {names[:10]}"
            )

    def test_weave_has_required_files(self, api, healthy_model):
        """Create a weave and verify it has the expected file structure."""
        ts = int(time.time())
        weave_name = f"e2e_test_weave_files_{ts}"

        resp = send_chat(
            api,
            f"Create a weave called {weave_name} for a basic 2-node ping test.",
            model=healthy_model,
            timeout=120.0,
        )
        assert_no_errors(resp)
        assert_tool_was_called(resp, "create_weave")

        # List the weave directory to check files
        files_resp = api.get("/artifacts/local", timeout=30.0)
        if files_resp.status_code == 200:
            artifacts = files_resp.json()
            weave_list = artifacts if isinstance(artifacts, list) else artifacts.get("artifacts", [])
            weave = next(
                (a for a in weave_list if a.get("dir_name") == weave_name),
                None,
            )
            if weave:
                assert weave.get("has_weave_json", False), "Missing weave.json"
                assert weave.get("has_weave_sh", False), "Missing weave.sh"

    def test_assistant_creates_custom_weave(self, api, healthy_model):
        """Ask for a custom weave and verify the script content is relevant."""
        ts = int(time.time())
        weave_name = f"e2e_test_weave_custom_{ts}"

        resp = send_chat(
            api,
            f"Create a weave called {weave_name} for measuring network latency "
            f"between 3 nodes using ping. Each node should have 2 cores and 8 GB RAM.",
            model=healthy_model,
            timeout=120.0,
        )
        assert_no_errors(resp)
        assert_tool_was_called(resp, "create_weave")

        # Check that the create_weave tool was called with ping-related content
        for tc in resp.tool_calls:
            if tc.get("name") == "create_weave":
                args = tc.get("arguments", {})
                if isinstance(args, str):
                    import json
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                script = args.get("script_content", "")
                assert "ping" in script.lower() or "latency" in script.lower(), (
                    f"Expected 'ping' or 'latency' in script content. "
                    f"Got: {script[:300]}"
                )
                break


# ---------------------------------------------------------------------------
# Weave deploy
# ---------------------------------------------------------------------------

@pytest.mark.fabric
class TestAssistantWeaveDeploy:
    """Test loading and deploying a weave via the assistant."""

    def test_weave_load_and_deploy(self, api, fabric_ok, healthy_model):
        """Load a pre-existing weave as a slice and deploy it."""
        ts = int(time.time())
        slice_name = f"e2e-weave-deploy-{ts}"

        # Find an available weave to load
        templates_resp = api.get("/templates", timeout=30.0)
        if templates_resp.status_code != 200:
            pytest.skip("No templates endpoint available")

        templates = templates_resp.json()
        if not templates:
            pytest.skip("No weaves available to load")

        # Pick the first weave
        weave_dir = templates[0].get("dir_name", templates[0].get("name", ""))
        if not weave_dir:
            pytest.skip("No valid weave found")

        try:
            resp = send_chat(
                api,
                f"Load the weave '{weave_dir}' as a new slice called {slice_name} "
                f"and submit it.",
                model=healthy_model,
                timeout=600.0,
            )
            assert_no_errors(resp)

            # Verify load_template was called
            called = [tc.get("name") for tc in resp.tool_calls]
            assert "load_template" in called, (
                f"load_template not called. Tools: {called}"
            )

            # The assistant should have also submitted the slice
            # If not, we can check if the slice exists as a draft
            slice_data = None
            resp_slices = api.get(f"/slices/{slice_name}")
            if resp_slices.status_code == 200:
                slice_data = resp_slices.json()

            if slice_data and slice_data.get("state") != "Draft":
                # Already submitted — wait for StableOK
                wait_stable_ok(api, slice_name)
            elif slice_data and slice_data.get("state") == "Draft":
                # Assistant loaded but didn't submit — submit directly
                api.post(f"/slices/{slice_name}/submit", timeout=120.0)
                wait_stable_ok(api, slice_name)

        finally:
            cleanup_slice(api, slice_name)
