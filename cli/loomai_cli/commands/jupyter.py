"""JupyterLab and notebook artifact commands."""

from __future__ import annotations

import click

from loomai_cli.output import output, output_message


@click.group()
def jupyter():
    """Start, stop, and inspect the LoomAI JupyterLab server."""


@jupyter.command("start")
@click.pass_context
def start_jupyter(ctx):
    """Start JupyterLab."""
    data = ctx.obj["client"].post("/jupyter/start")
    if ctx.obj["format"] == "table":
        output_message("JupyterLab start requested")
    output(ctx, data)


@jupyter.command("stop")
@click.pass_context
def stop_jupyter(ctx):
    """Stop JupyterLab."""
    data = ctx.obj["client"].post("/jupyter/stop")
    if ctx.obj["format"] == "table":
        output_message("JupyterLab stopped")
    output(ctx, data)


@jupyter.command("status")
@click.pass_context
def status_jupyter(ctx):
    """Show JupyterLab status."""
    data = ctx.obj["client"].get("/jupyter/status")
    output(ctx, data)


@click.group()
def notebooks():
    """Launch, reset, inspect, and publish notebook artifacts."""


@notebooks.command("launch")
@click.argument("name")
@click.option("--force-refresh", is_flag=True,
              help="Replace any existing working copy before launch.")
@click.pass_context
def launch_notebook(ctx, name, force_refresh):
    """Launch a notebook artifact in JupyterLab."""
    data = ctx.obj["client"].post(
        f"/notebooks/{name}/launch",
        params={"force_refresh": force_refresh},
    )
    if ctx.obj["format"] == "table":
        output_message(f"Launched notebook {name}")
    output(ctx, data)


@notebooks.command("reset")
@click.argument("name")
@click.option("--force", is_flag=True, help="Skip confirmation.")
@click.pass_context
def reset_notebook(ctx, name, force):
    """Reset a notebook working copy to the original artifact."""
    if not force:
        click.confirm(f"Reset notebook workspace '{name}'?", abort=True)
    data = ctx.obj["client"].post(f"/notebooks/{name}/reset")
    if ctx.obj["format"] == "table":
        output_message(f"Reset notebook {name}")
    output(ctx, data)


@notebooks.command("status")
@click.argument("name")
@click.pass_context
def status_notebook(ctx, name):
    """Show notebook workspace status."""
    data = ctx.obj["client"].get(f"/notebooks/{name}/status")
    output(ctx, data)


@notebooks.command("publish-fork")
@click.argument("name")
@click.option("--title", required=True, help="Title for the forked artifact.")
@click.option("--description", default="", help="Short description.")
@click.option("--description-long", default="", help="Long description.")
@click.option("--visibility", default="author",
              type=click.Choice(["author", "project", "public"]),
              help="Artifact visibility.")
@click.option("--project-uuid", default="", help="Project UUID for project visibility.")
@click.option("--tags", default="", help="Comma-separated artifact tags.")
@click.pass_context
def publish_notebook_fork(ctx, name, title, description, description_long,
                          visibility, project_uuid, tags):
    """Publish the notebook working copy as a forked artifact."""
    body = {
        "title": title,
        "description": description,
        "description_long": description_long,
        "visibility": visibility,
        "project_uuid": project_uuid,
        "tags": [t.strip() for t in tags.split(",") if t.strip()],
    }
    data = ctx.obj["client"].post(f"/notebooks/{name}/publish-fork", json=body)
    if ctx.obj["format"] == "table":
        output_message(f"Published fork of notebook {name}")
    output(ctx, data)
