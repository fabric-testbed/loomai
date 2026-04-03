"""Configuration and project management commands."""

from __future__ import annotations

import click

from loomai_cli.output import output, output_message


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
    output_message(f"Generated key set '{name}'")
    output(ctx, data)
