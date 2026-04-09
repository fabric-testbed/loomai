"""Shared fixtures and utilities for LoomAI assistant E2E tests.

These tests hit the real LLM via POST /api/ai/chat/stream and optionally
provision real FABRIC slices.  They are gated by ``llm`` and ``fabric``
pytest markers and excluded from default runs.
"""

from __future__ import annotations

import dataclasses
import json
import os
import time

import httpx
import pytest

BASE_URL = os.environ.get("LOOMAI_BASE_URL", "http://localhost:8000")

# Timeouts
SUBMIT_TIMEOUT = 120
STABLE_TIMEOUT = 600
POLL_INTERVAL = 15
EXEC_TIMEOUT = 60
SSH_WAIT_TIMEOUT = 180


# ---------------------------------------------------------------------------
# SSE parser
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class ChatResponse:
    """Parsed result from an SSE chat stream."""

    content: str = ""
    tool_calls: list = dataclasses.field(default_factory=list)
    tool_results: list = dataclasses.field(default_factory=list)
    usage: dict | None = None
    errors: list = dataclasses.field(default_factory=list)
    warnings: list = dataclasses.field(default_factory=list)
    raw_events: list = dataclasses.field(default_factory=list)
    tool_limit_reached: bool = False


def parse_sse_stream(text: str) -> ChatResponse:
    """Parse raw SSE text into a ChatResponse."""
    resp = ChatResponse()
    for line in text.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[6:].strip()
        if payload == "[DONE]":
            break
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        resp.raw_events.append(event)

        if "content" in event:
            resp.content += event["content"]
        elif "tool_call" in event:
            resp.tool_calls.append(event["tool_call"])
        elif "tool_result" in event:
            resp.tool_results.append(event["tool_result"])
        elif "usage" in event:
            resp.usage = event["usage"]
        elif "error" in event:
            resp.errors.append(event["error"])
        elif "warning" in event:
            resp.warnings.append(event["warning"])
        elif "tool_limit_reached" in event:
            resp.tool_limit_reached = True
    return resp


# ---------------------------------------------------------------------------
# Chat helper
# ---------------------------------------------------------------------------

def send_chat(
    api: httpx.Client,
    prompt: str,
    model: str | None = None,
    agent: str | None = None,
    timeout: float = 120.0,
) -> ChatResponse:
    """Send a message to the LoomAI assistant and return the full response."""
    body: dict = {"messages": [{"role": "user", "content": prompt}]}
    if model:
        body["model"] = model
    if agent:
        body["agent"] = agent

    resp = api.post(
        "/ai/chat/stream",
        json=body,
        timeout=timeout,
    )
    assert resp.status_code == 200, f"Chat stream failed ({resp.status_code}): {resp.text[:300]}"
    return parse_sse_stream(resp.text)


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------

def assert_response_contains(resp: ChatResponse, keywords: list[str], min_matches: int = 1):
    """Assert that the response content contains at least *min_matches* of *keywords*."""
    lower = resp.content.lower()
    # Also search tool results for keyword matches
    all_text = lower
    for tr in resp.tool_results:
        all_text += " " + str(tr.get("result", "")).lower()
        all_text += " " + str(tr.get("summary", "")).lower()
    matches = [kw for kw in keywords if kw.lower() in all_text]
    assert len(matches) >= min_matches, (
        f"Expected >= {min_matches} of {keywords} in response, "
        f"found {len(matches)}: {matches}\n"
        f"Content preview: {resp.content[:500]}"
    )


def assert_tool_was_called(resp: ChatResponse, tool_name: str):
    """Assert that a specific tool was called during the chat.

    Checks both tool_calls and tool_results because the intent pre-fetch
    system emits tool_result events for pre-fetched tools.
    """
    call_names = [tc.get("name", "") for tc in resp.tool_calls]
    result_names = [tr.get("name", "") for tr in resp.tool_results]
    all_names = set(call_names + result_names)
    assert tool_name in all_names, (
        f"Expected tool '{tool_name}' to be called. "
        f"Tool calls: {call_names}, Tool results: {result_names}"
    )


def assert_no_errors(resp: ChatResponse):
    """Assert the response has no error events."""
    assert not resp.errors, f"Chat returned errors: {resp.errors}"


# ---------------------------------------------------------------------------
# FABRIC slice helpers (reused from test_fabric_provision_e2e.py)
# ---------------------------------------------------------------------------

def wait_stable_ok(api: httpx.Client, name: str, timeout: int = STABLE_TIMEOUT) -> dict:
    """Poll until slice reaches StableOK.  Fails on StableError/Dead."""
    start = time.time()
    while time.time() - start < timeout:
        resp = api.get(f"/slices/{name}")
        if resp.status_code == 200:
            data = resp.json()
            state = data.get("state", "")
            if state == "StableOK":
                return data
            if state in ("StableError", "Dead"):
                errors = data.get("error_messages", [])
                pytest.fail(f"Slice '{name}' entered {state}: {errors}")
        time.sleep(POLL_INTERVAL)
    pytest.fail(f"Slice '{name}' did not reach StableOK within {timeout}s")


def cleanup_slice(api: httpx.Client, name: str):
    """Best-effort delete a FABRIC slice."""
    try:
        api.delete(f"/slices/{name}", timeout=120.0)
    except Exception:
        pass


def exec_on_node(
    api: httpx.Client, slice_name: str, node_name: str, command: str,
    timeout: int = EXEC_TIMEOUT,
) -> dict:
    """Execute a command on a FABRIC VM node."""
    resp = api.post(
        f"/files/vm/{slice_name}/{node_name}/execute",
        json={"command": command},
        timeout=float(timeout),
    )
    assert resp.status_code == 200, f"Execute failed ({resp.status_code}): {resp.text[:300]}"
    return resp.json()


def wait_ssh_ready(
    api: httpx.Client, slice_name: str, node_name: str,
    timeout: int = SSH_WAIT_TIMEOUT,
) -> bool:
    """Poll until SSH is reachable on a node."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            result = exec_on_node(api, slice_name, node_name, "echo ok", timeout=15)
            if "ok" in result.get("stdout", ""):
                return True
        except Exception:
            pass
        time.sleep(10)
    pytest.fail(f"SSH not ready on {node_name} of {slice_name} within {timeout}s")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def api():
    """httpx.Client pointed at the running backend."""
    return httpx.Client(base_url=f"{BASE_URL}/api", timeout=60.0)


@pytest.fixture(scope="session")
def fabric_ok(api):
    """Skip unless FABRIC is configured with a valid token."""
    try:
        resp = api.get("/config")
        if resp.status_code != 200:
            pytest.skip("Backend not running")
        data = resp.json()
        exp = data.get("token_info", {}).get("exp", 0)
        if exp * 1000 < time.time() * 1000:
            pytest.skip("FABRIC token expired — re-login required")
        return data
    except Exception:
        pytest.skip("Backend not running or unreachable")


@pytest.fixture(scope="session")
def llm_ok(api):
    """Skip unless an LLM model is healthy.  Returns the model name."""
    try:
        resp = api.get("/ai/models", timeout=90.0)
        if resp.status_code != 200:
            pytest.skip("AI models endpoint not available")
        data = resp.json()
        # Pick first healthy FABRIC model
        for group in data.get("groups", data.get("fabric", [])):
            models = group if isinstance(group, list) else group.get("models", [])
            for m in models if isinstance(models, list) else []:
                mid = m.get("id", "") if isinstance(m, dict) else m
                if mid:
                    # Quick health check
                    test_resp = api.post(
                        "/ai/models/test",
                        json={"model": mid, "source": "fabric"},
                        timeout=30.0,
                    )
                    if test_resp.status_code == 200 and test_resp.json().get("healthy"):
                        return mid
        # Fallback: try the default model
        default_resp = api.get("/ai/models/default", timeout=30.0)
        if default_resp.status_code == 200:
            default_model = default_resp.json().get("default", "")
            if default_model:
                return default_model
        pytest.skip("No healthy LLM model found")
    except Exception as e:
        pytest.skip(f"LLM not available: {e}")


@pytest.fixture(scope="session")
def healthy_model(llm_ok):
    """Returns the name of a healthy LLM model."""
    return llm_ok
