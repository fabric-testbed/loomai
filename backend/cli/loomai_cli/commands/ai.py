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


def _print_models(ctx, data):
    if ctx.obj["format"] != "table":
        output(ctx, data)
        return

    fabric = data.get("fabric", [])
    nrp = data.get("nrp", [])
    custom = data.get("custom", [])
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

    if custom:
        click.echo("\nCustom Models:")
        for m in custom:
            model_id = m.get("id", m.get("name", ""))
            marker = " (default)" if model_id == default else ""
            click.echo(f"  {model_id}{marker}")

    if not fabric and not nrp and not custom:
        click.echo("No models available. Configure your API keys in LoomAI settings.")


@ai.group("models", invoke_without_command=True)
@click.pass_context
def models(ctx):
    """List and manage available LLM models.

    Examples:

      loomai ai models

      loomai ai models default

      loomai ai models set-default qwen3-coder-30b
    """
    if ctx.invoked_subcommand is not None:
        return
    data = ctx.obj["client"].get("/ai/models")
    _print_models(ctx, data)


@models.command("list")
@click.pass_context
def list_models(ctx):
    """List available LLM models."""
    data = ctx.obj["client"].get("/ai/models")
    _print_models(ctx, data)


@models.command("default")
@click.pass_context
def default_model(ctx):
    """Show the shared default model."""
    data = ctx.obj["client"].get("/ai/models/default")
    output(ctx, data)


@models.command("set-default")
@click.argument("model")
@click.option("--source", help="Model source: fabric, nrp, or custom:<name>.")
@click.pass_context
def set_default_model(ctx, model, source):
    """Set the shared default model used by the GUI and CLI."""
    data = ctx.obj["client"].put("/ai/models/default", json={
        "model": model,
        "source": source or "",
    })
    if ctx.obj["format"] == "table":
        output_message(f"Default model set to {data.get('default', model)}")
    output(ctx, data)


@models.command("test")
@click.argument("model")
@click.option("--source", default="fabric", help="Model source: fabric, nrp, or custom:<name>.")
@click.pass_context
def test_model(ctx, model, source):
    """Test model health and latency."""
    data = ctx.obj["client"].post("/ai/models/test", json={
        "model": model,
        "source": source,
    })
    output(ctx, data)


@models.command("refresh")
@click.pass_context
def refresh_models(ctx):
    """Refresh model discovery and health checks."""
    data = ctx.obj["client"].post("/ai/models/refresh")
    output(ctx, data)


def _print_agent_or_skill_list(ctx, data):
    output(ctx, data,
           columns=["id", "name", "description", "source"],
           headers=["ID", "Name", "Description", "Source"])


def _read_content_option(content: str | None, content_file: str | None) -> str:
    if content is not None and content_file:
        raise click.UsageError("Use either --content or --file, not both.")
    if content_file:
        if content_file == "-":
            return sys.stdin.read()
        with open(content_file) as f:
            return f.read()
    if content is not None:
        return content
    raise click.UsageError("Provide --content, --file PATH, or --file -.")


def _create_agent_or_skill(ctx, kind: str, item_id: str, name: str, description: str,
                           content: str | None, content_file: str | None):
    body = {
        "name": name or item_id,
        "description": description or "",
        "content": _read_content_option(content, content_file),
    }
    data = ctx.obj["client"].put(f"/ai/{kind}/{item_id}", json=body)
    if ctx.obj["format"] == "table":
        output_message(f"Saved {kind[:-1]} {item_id}")
    output(ctx, data)


def _edit_agent_or_skill(ctx, kind: str, item_id: str, name: str | None,
                         description: str | None, content: str | None,
                         content_file: str | None):
    if name is None and description is None and content is None and not content_file:
        raise click.UsageError("Specify at least one field to update.")
    current = ctx.obj["client"].get(f"/ai/{kind}/{item_id}")
    body = {
        "name": name if name is not None else current.get("name", item_id),
        "description": (
            description if description is not None else current.get("description", "")
        ),
        "content": (
            _read_content_option(content, content_file)
            if content is not None or content_file else current.get("content", "")
        ),
    }
    data = ctx.obj["client"].put(f"/ai/{kind}/{item_id}", json=body)
    if ctx.obj["format"] == "table":
        output_message(f"Updated {kind[:-1]} {item_id}")
    output(ctx, data)


@ai.group("agents", invoke_without_command=True)
@click.pass_context
def agents(ctx):
    """List and inspect AI assistant agents.

    Examples:

      loomai ai agents

      loomai ai agents show fabric-expert
    """
    if ctx.invoked_subcommand is not None:
        return
    data = ctx.obj["client"].get("/ai/agents")
    _print_agent_or_skill_list(ctx, data)


@agents.command("list")
@click.pass_context
def list_agents(ctx):
    """List available AI assistant agents."""
    data = ctx.obj["client"].get("/ai/agents")
    _print_agent_or_skill_list(ctx, data)


@agents.command("show")
@click.argument("agent_id")
@click.pass_context
def show_agent(ctx, agent_id):
    """Show a full AI assistant agent."""
    data = ctx.obj["client"].get(f"/ai/agents/{agent_id}")
    output(ctx, data)


@agents.command("create")
@click.argument("agent_id")
@click.option("--name", default="", help="Display name.")
@click.option("--description", default="", help="Short description.")
@click.option("--content", help="Agent prompt body.")
@click.option("--file", "content_file", type=click.Path(),
              help="Read prompt body from a file, or '-' for stdin.")
@click.pass_context
def create_agent(ctx, agent_id, name, description, content, content_file):
    """Create a user-custom AI assistant agent."""
    _create_agent_or_skill(ctx, "agents", agent_id, name, description, content, content_file)


@agents.command("edit")
@click.argument("agent_id")
@click.option("--name", help="Replacement display name.")
@click.option("--description", help="Replacement short description.")
@click.option("--content", help="Replacement prompt body.")
@click.option("--file", "content_file", type=click.Path(),
              help="Read replacement prompt body from a file, or '-' for stdin.")
@click.pass_context
def edit_agent(ctx, agent_id, name, description, content, content_file):
    """Edit a built-in override or user-custom AI assistant agent."""
    _edit_agent_or_skill(ctx, "agents", agent_id, name, description, content, content_file)


@agents.command("reset")
@click.argument("agent_id")
@click.pass_context
def reset_agent(ctx, agent_id):
    """Reset a customized built-in agent to its default content."""
    data = ctx.obj["client"].post(f"/ai/agents/{agent_id}/reset")
    if ctx.obj["format"] == "table":
        output_message(f"Reset agent {agent_id}")
    output(ctx, data)


@agents.command("delete")
@click.argument("agent_id")
@click.option("--force", is_flag=True, help="Skip confirmation.")
@click.pass_context
def delete_agent(ctx, agent_id, force):
    """Delete a user-custom agent."""
    if not force:
        click.confirm(f"Delete custom agent '{agent_id}'?", abort=True)
    data = ctx.obj["client"].delete(f"/ai/agents/{agent_id}")
    if ctx.obj["format"] == "table":
        output_message(f"Deleted agent {agent_id}")
    output(ctx, data)


@ai.group("skills", invoke_without_command=True)
@click.pass_context
def skills(ctx):
    """List and inspect AI tool skills."""
    if ctx.invoked_subcommand is not None:
        return
    data = ctx.obj["client"].get("/ai/skills")
    _print_agent_or_skill_list(ctx, data)


@skills.command("list")
@click.pass_context
def list_skills(ctx):
    """List available AI tool skills."""
    data = ctx.obj["client"].get("/ai/skills")
    _print_agent_or_skill_list(ctx, data)


@skills.command("show")
@click.argument("skill_id")
@click.pass_context
def show_skill(ctx, skill_id):
    """Show a full AI tool skill."""
    data = ctx.obj["client"].get(f"/ai/skills/{skill_id}")
    output(ctx, data)


@skills.command("create")
@click.argument("skill_id")
@click.option("--name", default="", help="Display name.")
@click.option("--description", default="", help="Short description.")
@click.option("--content", help="Skill body.")
@click.option("--file", "content_file", type=click.Path(),
              help="Read skill body from a file, or '-' for stdin.")
@click.pass_context
def create_skill(ctx, skill_id, name, description, content, content_file):
    """Create a user-custom AI tool skill."""
    _create_agent_or_skill(ctx, "skills", skill_id, name, description, content, content_file)


@skills.command("edit")
@click.argument("skill_id")
@click.option("--name", help="Replacement display name.")
@click.option("--description", help="Replacement short description.")
@click.option("--content", help="Replacement skill body.")
@click.option("--file", "content_file", type=click.Path(),
              help="Read replacement skill body from a file, or '-' for stdin.")
@click.pass_context
def edit_skill(ctx, skill_id, name, description, content, content_file):
    """Edit a built-in override or user-custom AI tool skill."""
    _edit_agent_or_skill(ctx, "skills", skill_id, name, description, content, content_file)


@skills.command("reset")
@click.argument("skill_id")
@click.pass_context
def reset_skill(ctx, skill_id):
    """Reset a customized built-in skill to its default content."""
    data = ctx.obj["client"].post(f"/ai/skills/{skill_id}/reset")
    if ctx.obj["format"] == "table":
        output_message(f"Reset skill {skill_id}")
    output(ctx, data)


@skills.command("delete")
@click.argument("skill_id")
@click.option("--force", is_flag=True, help="Skip confirmation.")
@click.pass_context
def delete_skill(ctx, skill_id, force):
    """Delete a user-custom skill."""
    if not force:
        click.confirm(f"Delete custom skill '{skill_id}'?", abort=True)
    data = ctx.obj["client"].delete(f"/ai/skills/{skill_id}")
    if ctx.obj["format"] == "table":
        output_message(f"Deleted skill {skill_id}")
    output(ctx, data)


@ai.group("rag")
def rag():
    """Inspect and rebuild the LoomAI RAG index."""


@rag.command("status")
@click.pass_context
def rag_status(ctx):
    """Show RAG index diagnostics."""
    data = ctx.obj["client"].get("/ai/rag/status")
    output(ctx, data)


@rag.command("search")
@click.argument("query")
@click.option("-k", default=5, type=int, help="Number of results.")
@click.option("--min-score", default=0.25, type=float, help="Minimum retrieval score.")
@click.option("--weave-bias", is_flag=True, help="Boost weave/example matches.")
@click.option("--source-type", "source_types", multiple=True,
              help="Restrict to source type; repeatable.")
@click.pass_context
def rag_search(ctx, query, k, min_score, weave_bias, source_types):
    """Search the RAG corpus."""
    body = {
        "query": query,
        "k": k,
        "min_score": min_score,
        "weave_bias": weave_bias,
    }
    if source_types:
        body["source_types"] = list(source_types)
    data = ctx.obj["client"].post("/ai/rag/search", json=body)
    if ctx.obj["format"] != "table":
        output(ctx, data)
        return
    output(ctx, data.get("hits", []),
           columns=["score", "source_type", "source_path", "section", "preview"],
           headers=["Score", "Type", "Source", "Section", "Preview"])


@rag.command("rebuild")
@click.option("--full", is_flag=True, help="Drop the current index and rebuild from scratch.")
@click.pass_context
def rag_rebuild(ctx, full):
    """Refresh or fully rebuild the RAG index."""
    data = ctx.obj["client"].post("/ai/rag/rebuild", params={"full": full})
    if ctx.obj["format"] == "table":
        output_message("RAG rebuild requested")
    output(ctx, data)


@ai.command("propagate-config")
@click.pass_context
def propagate_config(ctx):
    """Regenerate AI tool configuration files from current settings."""
    data = ctx.obj["client"].post("/ai/propagate-config")
    if ctx.obj["format"] == "table":
        output_message("AI tool configs propagated")
    output(ctx, data)


@ai.group("tools", invoke_without_command=True)
@click.pass_context
def tools(ctx):
    """Install, inspect, and launch optional AI companion tools."""
    if ctx.invoked_subcommand is not None:
        return
    _show_tool_status(ctx)


def _tool_status_rows(data):
    if isinstance(data, dict):
        return [
            {"tool": tool_id, **(info if isinstance(info, dict) else {"status": info})}
            for tool_id, info in data.items()
        ]
    return data


def _show_tool_status(ctx):
    data = ctx.obj["client"].get("/ai/tools/status")
    if ctx.obj["format"] != "table":
        output(ctx, data)
        return
    rows = _tool_status_rows(data)
    output(ctx, rows,
           columns=["tool", "display_name", "installed", "type", "size_estimate"],
           headers=["Tool", "Name", "Installed", "Type", "Size"])


def _output_tool_action(ctx, data):
    if ctx.obj["format"] == "table" and isinstance(data, dict):
        summary = {k: v for k, v in data.items() if k != "output"}
        output(ctx, summary)
        return
    output(ctx, data)


@tools.command("status")
@click.pass_context
def tools_status(ctx):
    """Show install status for all optional AI tools."""
    _show_tool_status(ctx)


@tools.command("disk-space")
@click.argument("tool", required=False)
@click.pass_context
def tools_disk_space(ctx, tool):
    """Check available disk space before installing an AI tool."""
    params = {"tool_id": tool} if tool else {}
    data = ctx.obj["client"].get("/ai/tools/disk-space", params=params)
    output(ctx, data)


@tools.command("install")
@click.argument("tool")
@click.pass_context
def tools_install(ctx, tool):
    """Install an optional AI tool and return the final install result."""
    data = ctx.obj["client"].post(f"/ai/tools/{tool}/install")
    if ctx.obj["format"] == "table":
        output_message(f"Install requested for {tool}")
    _output_tool_action(ctx, data)


@tools.command("uninstall")
@click.argument("tool")
@click.option("--force", is_flag=True, help="Skip confirmation.")
@click.pass_context
def tools_uninstall(ctx, tool, force):
    """Uninstall an optional AI tool."""
    if not force:
        click.confirm(f"Uninstall AI tool '{tool}'?", abort=True)
    data = ctx.obj["client"].post(f"/ai/tools/{tool}/uninstall")
    if ctx.obj["format"] == "table":
        output_message(f"Uninstall requested for {tool}")
    _output_tool_action(ctx, data)


@tools.command("propagate-config")
@click.pass_context
def tools_propagate_config(ctx):
    """Regenerate config files for installed AI tools."""
    data = ctx.obj["client"].post("/ai/propagate-config")
    if ctx.obj["format"] == "table":
        output_message("AI tool configs propagated")
    output(ctx, data)


@tools.group("web")
def web_tools():
    """Start, stop, and inspect web-based AI tools."""


def _normalize_web_tool(tool: str) -> str:
    normalized = tool[:-4] if tool.endswith("-web") else tool
    if normalized not in {"aider", "opencode"}:
        raise click.UsageError("TOOL must be one of: aider, opencode")
    return normalized


@web_tools.command("start")
@click.argument("tool", type=click.Choice(["aider", "opencode", "aider-web", "opencode-web"]))
@click.option("--model", default="", help="Model override for tools that support it.")
@click.pass_context
def web_tools_start(ctx, tool, model):
    """Start Aider or OpenCode in browser mode."""
    tool_id = _normalize_web_tool(tool)
    params = {"model": model} if model else {}
    data = ctx.obj["client"].post(f"/ai/{tool_id}-web/start", params=params)
    if ctx.obj["format"] == "table":
        output_message(f"Started {tool_id} web tool")
    output(ctx, data)


@web_tools.command("stop")
@click.argument("tool", type=click.Choice(["aider", "opencode", "aider-web", "opencode-web"]))
@click.pass_context
def web_tools_stop(ctx, tool):
    """Stop Aider or OpenCode browser mode."""
    tool_id = _normalize_web_tool(tool)
    data = ctx.obj["client"].post(f"/ai/{tool_id}-web/stop")
    if ctx.obj["format"] == "table":
        output_message(f"Stopped {tool_id} web tool")
    output(ctx, data)


@web_tools.command("status")
@click.argument("tool", type=click.Choice(["aider", "opencode", "aider-web", "opencode-web"]))
@click.pass_context
def web_tools_status(ctx, tool):
    """Show Aider or OpenCode browser-mode status."""
    tool_id = _normalize_web_tool(tool)
    data = ctx.obj["client"].get(f"/ai/{tool_id}-web/status")
    output(ctx, data)


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
