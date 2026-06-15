"""Multi-user profile commands."""

from __future__ import annotations

import click

from loomai_cli.output import output, output_message


@click.group(invoke_without_command=True)
@click.pass_context
def users(ctx):
    """List, switch, delete, and migrate LoomAI user profiles."""
    if ctx.invoked_subcommand is not None:
        return
    _show_users(ctx)


def _show_users(ctx):
    data = ctx.obj["client"].get("/users")
    if ctx.obj["format"] != "table":
        output(ctx, data)
        return

    click.echo(f"Multi-user mode: {data.get('multiuser', False)}")
    active = data.get("active_user") or ""
    if active:
        click.echo(f"Active user: {active}")
    rows = data.get("users", [])
    output(ctx, rows,
           columns=["uuid", "name", "email", "is_active"],
           headers=["UUID", "Name", "Email", "Active"])


@users.command("list")
@click.pass_context
def list_users(ctx):
    """List registered LoomAI users."""
    _show_users(ctx)


@users.command("switch")
@click.argument("uuid")
@click.pass_context
def switch_user(ctx, uuid):
    """Switch the active LoomAI user profile."""
    data = ctx.obj["client"].post("/users/switch", json={"uuid": uuid})
    if ctx.obj["format"] == "table":
        output_message(f"Switched active user to {uuid}")
    output(ctx, data)


@users.command("delete")
@click.argument("uuid")
@click.option("--delete-data/--keep-data", default=True,
              help="Remove the user's stored data directory.")
@click.option("--force", is_flag=True, help="Skip confirmation.")
@click.pass_context
def delete_user(ctx, uuid, delete_data, force):
    """Delete a LoomAI user profile."""
    if not force:
        detail = "including stored data" if delete_data else "keeping stored data"
        click.confirm(f"Delete user '{uuid}' ({detail})?", abort=True)
    data = ctx.obj["client"].delete(
        f"/users/{uuid}",
        params={"delete_data": delete_data},
    )
    if ctx.obj["format"] == "table":
        output_message(f"Deleted user {uuid}")
    output(ctx, data)


@users.command("migrate-current")
@click.pass_context
def migrate_current_user(ctx):
    """Migrate the current flat storage layout into multi-user storage."""
    data = ctx.obj["client"].post("/users/migrate-current")
    if ctx.obj["format"] == "table":
        output_message("User storage migration requested")
    output(ctx, data)
