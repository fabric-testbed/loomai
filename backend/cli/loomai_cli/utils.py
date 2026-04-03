"""Shared CLI utilities — polling, wait helpers."""

from __future__ import annotations

import time
from typing import Set

import click

from loomai_cli.client import Client, CliError
from loomai_cli.output import output_message

STABLE_STATES = {"StableOK", "Active"}
TERMINAL_STATES = {"Dead", "Closing", "StableError"}
SETTLED_STATES = STABLE_STATES | TERMINAL_STATES | {"Draft"}


def wait_for_state(
    client: Client,
    slice_name: str,
    target_states: Set[str] | None = None,
    timeout: int = 600,
    interval: int = 15,
) -> dict:
    """Poll slice state until it reaches a target state or times out.

    Returns the final state response dict.
    """
    if target_states is None:
        target_states = STABLE_STATES | TERMINAL_STATES

    start = time.time()
    last_state = ""

    while True:
        elapsed = time.time() - start
        if elapsed > timeout:
            raise CliError(
                f"Timed out after {timeout}s waiting for slice '{slice_name}' "
                f"(last state: {last_state})"
            )

        try:
            resp = client.get(f"/slices/{slice_name}/state")
            state = resp.get("state", "")
        except CliError:
            state = "unknown"

        if state != last_state:
            output_message(f"  State: {last_state or '?'} -> {state} ({int(elapsed)}s)")
            last_state = state

        if state in target_states:
            return resp

        remaining = timeout - elapsed
        sleep_time = min(interval, remaining)
        if sleep_time > 0:
            time.sleep(sleep_time)
