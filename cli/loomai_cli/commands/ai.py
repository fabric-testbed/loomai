"""AI assistant and model commands."""

from __future__ import annotations

import json
import os
import sys

import click
import httpx

from loomai_cli.output import output, output_message


@click.group()
def ai():
    """AI assistant and model management."""


@ai.command("models")
@click.pass_context
def list_models(ctx):
    """List available LLM models from FABRIC AI and NRP servers.

    Examples:

      loomai ai models

      loomai --format json ai models
    """
    client = ctx.obj["client"]
    data = client.get("/ai/models")

    if ctx.obj["format"] != "table":
        output(ctx, data)
        return

    fabric = data.get("fabric", [])
    nrp = data.get("nrp", [])
    has_key = data.get("has_key", {})
    default = data.get("default", "")

    if fabric:
        click.echo("FABRIC AI Models:")
        for m in fabric:
            marker = " (default)" if m.get("id") == default else ""
            click.echo(f"  {m.get('id', m.get('name', ''))}{marker}")
    if not has_key.get("fabric"):
        click.echo("  (no API key — enter your FABRIC AI key in settings)")

    if nrp:
        click.echo("\nNRP/Nautilus Models:")
        for m in nrp:
            marker = " (default)" if m.get("id") == default else ""
            click.echo(f"  {m.get('id', m.get('name', ''))}{marker}")
    if not has_key.get("nrp"):
        click.echo("  (no API key — enter your NRP key in settings)")

    if not fabric and not nrp:
        click.echo("No models available. Configure your API keys in LoomAI settings.")


@ai.command("agents")
@click.pass_context
def list_agents(ctx):
    """List available AI assistant agents.

    Examples:

      loomai ai agents
    """
    client = ctx.obj["client"]
    data = client.get("/ai/chat/agents")
    output(ctx, data,
           columns=["id", "name", "description"],
           headers=["ID", "Name", "Description"])


@ai.command("chat")
@click.argument("message", required=False)
@click.option("--model", help="Override model (e.g. qwen3-coder-30b).")
@click.option("--agent", help="Agent to use (see 'loomai ai agents').")
@click.pass_context
def chat(ctx, message, model, agent):
    """Chat with the LoomAI AI assistant.

    With MESSAGE: one-shot query, prints response and exits.
    Without MESSAGE: interactive chat (type 'exit' or Ctrl+D to quit).

    Examples:

      loomai ai chat "list my active slices"

      loomai ai chat "create a 2-node slice at RENC with an L2 bridge"

      loomai ai chat   # interactive mode
    """
    client = ctx.obj["client"]

    if message:
        # One-shot mode: resolve model if not explicitly set
        if not model:
            model = _resolve_default_model(client)
        _send_chat(client, [{"role": "user", "content": message}], model, agent)
    else:
        # Interactive mode
        click.echo("LoomAI AI Assistant (type 'exit' or Ctrl+D to quit)")
        messages = []
        while True:
            try:
                user_input = click.prompt("You", prompt_suffix="> ")
            except (EOFError, KeyboardInterrupt):
                click.echo("\nBye!")
                break
            if user_input.strip().lower() in ("exit", "quit", "q"):
                break
            messages.append({"role": "user", "content": user_input})
            response = _send_chat(client, messages, model, agent)
            if response:
                messages.append({"role": "assistant", "content": response})


def _resolve_default_model(client) -> str:
    """Resolve the default model: check local config, then query backend."""
    # Check local config first (same as shell.py uses)
    config_path = os.path.expanduser("~/.loomai/config")
    if os.path.isfile(config_path):
        try:
            with open(config_path) as f:
                config = json.load(f)
            if config.get("model"):
                return config["model"]
        except Exception:
            pass

    # Query backend for default
    try:
        data = client.get("/ai/models/default")
        default = data.get("default", "")
        if default:
            source = data.get("source", "fabric")
            mid = f"nrp:{default}" if source == "nrp" else default
            # Persist for next time
            _save_local_config({"model": mid})
            return mid
    except Exception:
        pass

    return ""  # Let the backend use its fallback


def _save_local_config(data: dict) -> None:
    """Save to ~/.loomai/config, merging with existing data."""
    config_path = os.path.expanduser("~/.loomai/config")
    existing = {}
    if os.path.isfile(config_path):
        try:
            with open(config_path) as f:
                existing = json.load(f)
        except Exception:
            pass
    existing.update(data)
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "w") as f:
        json.dump(existing, f, indent=2)


def _send_chat(client, messages, model=None, agent=None) -> str:
    """Send a chat request and stream the response."""
    body: dict = {"messages": messages}
    if model:
        body["model"] = model
    if agent:
        body["agent"] = agent

    # Use httpx directly for SSE streaming
    url = f"{client.base_url}/api/ai/chat/stream"
    collected = []

    try:
        with httpx.stream("POST", url, json=body, timeout=120.0) as resp:
            if resp.status_code >= 400:
                click.echo(f"Error: {resp.read().decode()}", err=True)
                return ""
            for line in resp.iter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload == "[DONE]":
                    break
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if "content" in data:
                    text = data["content"]
                    click.echo(text, nl=False)
                    collected.append(text)
                elif "error" in data:
                    click.echo(f"\nError: {data['error']}", err=True)
    except httpx.ConnectError:
        click.echo("Cannot connect to LoomAI backend", err=True)
        return ""
    except httpx.TimeoutException:
        click.echo("\nRequest timed out", err=True)
        return ""

    click.echo()  # Final newline
    return "".join(collected)
