"""Configuration and project management commands."""

from __future__ import annotations

import json
from copy import deepcopy

import click

from loomai_cli.output import output, output_message


SETTING_ALIASES = {
    "views.composite_enabled": "views.federated_enabled",
}


def _canonical_setting_path(path: str) -> str:
    return SETTING_ALIASES.get(path, path)


def _display_setting_path(path: str) -> str:
    if path == "views.composite_enabled":
        return "views.federated_enabled"
    return path


def _display_settings(data):
    """Expose current terminology while preserving compatibility aliases."""
    if not isinstance(data, dict):
        return data
    shown = deepcopy(data)
    views = shown.get("views")
    if isinstance(views, dict) and "composite_enabled" in views:
        if "federated_enabled" not in views:
            views["federated_enabled"] = views["composite_enabled"]
        del views["composite_enabled"]
    return shown


@click.group()
def config():
    """View and manage LoomAI configuration."""


@config.command("show")
@click.pass_context
def show_config(ctx):
    """Show current configuration status.

    Examples:

      loomai config show

      loomai --format json config show
    """
    client = ctx.obj["client"]
    data = client.get("/config")
    output(ctx, data)


@config.command("settings")
@click.pass_context
def show_settings(ctx):
    """Show all settings.

    Examples:

      loomai config settings
    """
    client = ctx.obj["client"]
    data = client.get("/settings")
    output(ctx, data)


@config.command("paste-token")
@click.option("--file", "token_file", required=True, type=click.Path(exists=True),
              help="Path to a FABRIC token JSON file.")
@click.pass_context
def paste_token(ctx, token_file):
    """Save a FABRIC token JSON file into LoomAI config."""
    with open(token_file) as f:
        token_text = f.read()
    data = ctx.obj["client"].post("/config/token/paste", json={"token_text": token_text})
    if ctx.obj["format"] == "table":
        output_message("Token saved")
    output(ctx, data)


@config.command("logout")
@click.pass_context
def logout(ctx):
    """Clear active LoomAI/FABRIC login state."""
    data = ctx.obj["client"].post("/config/logout")
    if ctx.obj["format"] == "table":
        output_message("Logged out")
    output(ctx, data)


@config.command("auto-setup")
@click.argument("project_id")
@click.pass_context
def auto_setup(ctx, project_id):
    """Run post-login setup for a FABRIC project."""
    data = ctx.obj["client"].post("/config/auto-setup", json={"project_id": project_id})
    if ctx.obj["format"] == "table":
        output_message(f"Auto-setup completed for project {project_id}")
    output(ctx, data)


@config.command("check-update")
@click.pass_context
def check_update(ctx):
    """Check whether a newer LoomAI image is available."""
    data = ctx.obj["client"].get("/config/check-update")
    output(ctx, data)


@config.command("rebuild-storage")
@click.pass_context
def rebuild_storage(ctx):
    """Re-create expected LoomAI storage directories."""
    data = ctx.obj["client"].post("/config/rebuild-storage")
    if ctx.obj["format"] == "table":
        output_message("Storage layout rebuilt")
    output(ctx, data)


@config.command("views-status")
@click.pass_context
def views_status(ctx):
    """Show enabled top-level views."""
    data = ctx.obj["client"].get("/views/status")
    output(ctx, data)


@config.command("ai-tools")
@click.pass_context
def ai_tools(ctx):
    """Show enabled AI companion tools."""
    data = ctx.obj["client"].get("/config/ai-tools")
    output(ctx, data)


@config.command("set-ai-tool")
@click.argument("tool")
@click.argument("enabled", type=bool)
@click.pass_context
def set_ai_tool(ctx, tool, enabled):
    """Enable or disable an AI companion tool."""
    current = ctx.obj["client"].get("/config/ai-tools")
    current[tool] = enabled
    data = ctx.obj["client"].post("/config/ai-tools", json=current)
    if ctx.obj["format"] == "table":
        state = "enabled" if enabled else "disabled"
        output_message(f"{tool} {state}")
    output(ctx, data)


@config.command("tool-configs")
@click.pass_context
def tool_configs(ctx):
    """List per-tool config status."""
    data = ctx.obj["client"].get("/config/tool-configs")
    output(ctx, data)


@config.command("reset-tool-config")
@click.argument("tool")
@click.pass_context
def reset_tool_config(ctx, tool):
    """Reset a tool's generated config to defaults."""
    data = ctx.obj["client"].post(f"/config/tool-configs/{tool}/reset")
    if ctx.obj["format"] == "table":
        output_message(f"Reset tool config for {tool}")
    output(ctx, data)


@click.group()
def settings():
    """Get, set, and test LoomAI settings."""


def _parse_setting_value(value: str):
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _get_nested(data: dict, path: str):
    current = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise click.ClickException(f"Setting '{path}' not found")
        current = current[part]
    return current


def _set_nested(data: dict, path: str, value):
    current = data
    parts = path.split(".")
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


@settings.command("get")
@click.argument("path", required=False)
@click.pass_context
def settings_get(ctx, path):
    """Show all settings or one dot-path setting."""
    data = ctx.obj["client"].get("/settings")
    if path:
        data = {_display_setting_path(path): _get_nested(data, _canonical_setting_path(path))}
    output(ctx, _display_settings(data))


@settings.command("set")
@click.argument("path")
@click.argument("value")
@click.pass_context
def settings_set(ctx, path, value):
    """Set a dot-path setting and save the full settings document."""
    client = ctx.obj["client"]
    data = client.get("/settings")
    canonical_path = _canonical_setting_path(path)
    _set_nested(data, canonical_path, _parse_setting_value(value))
    saved = client.put("/settings", json=data)
    if ctx.obj["format"] == "table":
        output_message(f"Set {path}")
    output(ctx, _display_settings(saved))


@settings.command("test")
@click.argument("name")
@click.option("--project-id", help="Project UUID when testing project settings.")
@click.pass_context
def settings_test(ctx, name, project_id):
    """Test one setting group such as token, fablib, project, or ai_server."""
    body = {"project_id": project_id} if project_id else {}
    data = ctx.obj["client"].post(f"/settings/test/{name}", json=body)
    output(ctx, data)


@settings.command("test-all")
@click.pass_context
def settings_test_all(ctx):
    """Run all settings checks."""
    data = ctx.obj["client"].post("/settings/test-all")
    output(ctx, data)


@settings.command("test-provider")
@click.option("--base-url", required=True, help="OpenAI-compatible provider base URL.")
@click.option("--api-key", default="", help="Provider API key.")
@click.pass_context
def settings_test_provider(ctx, base_url, api_key):
    """Test a custom OpenAI-compatible provider."""
    data = ctx.obj["client"].post("/settings/test-custom-provider", json={
        "base_url": base_url,
        "api_key": api_key,
    })
    output(ctx, data)


# --- Projects ---

@click.group()
def projects():
    """Manage FABRIC projects."""


@projects.command("list")
@click.pass_context
def list_projects(ctx):
    """List user's FABRIC projects.

    Examples:

      loomai projects list
    """
    client = ctx.obj["client"]
    data = client.get("/projects")
    proj_list = data.get("projects", data) if isinstance(data, dict) else data
    if isinstance(proj_list, list):
        output(ctx, proj_list,
               columns=["name", "uuid", "is_active"],
               headers=["Name", "UUID", "Active"])
    else:
        output(ctx, data)


@projects.command("switch")
@click.argument("uuid")
@click.pass_context
def switch_project(ctx, uuid):
    """Switch the active FABRIC project.

    Examples:

      loomai projects switch abc-123-def-456
    """
    client = ctx.obj["client"]
    data = client.post("/projects/switch", json={"project_uuid": uuid})
    if ctx.obj["format"] == "table":
        output_message(f"Switched to project {uuid}")
    output(ctx, data)


# --- Keys ---

@click.group()
def keys():
    """Manage SSH keys."""


@keys.command("list")
@click.pass_context
def list_keys(ctx):
    """List SSH key sets.

    Examples:

      loomai keys list
    """
    client = ctx.obj["client"]
    data = client.get("/config/keys/slice/list")
    output(ctx, data)


@keys.command("generate")
@click.option("--name", default="default", help="Key set name (default: default).")
@click.pass_context
def generate_keys(ctx, name):
    """Generate a new SSH key pair.

    Examples:

      loomai keys generate

      loomai keys generate --name my-keys
    """
    client = ctx.obj["client"]
    data = client.post("/config/keys/slice/generate", params={"key_name": name})
    if ctx.obj["format"] == "table":
        output_message(f"Generated key set '{name}'")
    output(ctx, data)


@keys.command("set-default")
@click.argument("name")
@click.pass_context
def set_default_key(ctx, name):
    """Set the default SSH key set for new slices."""
    data = ctx.obj["client"].put("/config/keys/slice/default", params={"key_name": name})
    if ctx.obj["format"] == "table":
        output_message(f"Default key set is now '{name}'")
    output(ctx, data)


@keys.command("delete")
@click.argument("name")
@click.option("--force", is_flag=True, help="Skip confirmation.")
@click.pass_context
def delete_key(ctx, name, force):
    """Delete a non-default SSH key set."""
    if not force:
        click.confirm(f"Delete key set '{name}'?", abort=True)
    data = ctx.obj["client"].delete(f"/config/keys/slice/{name}")
    if ctx.obj["format"] == "table":
        output_message(f"Deleted key set '{name}'")
    output(ctx, data)
