"""Slice management commands."""

from __future__ import annotations

import json
from loomai_cli.completions import SLICE
import sys

import click

from loomai_cli.output import output, output_message
from loomai_cli.utils import wait_for_state, STABLE_STATES, TERMINAL_STATES


@click.group()
def slices():
    """Manage FABRIC slices."""


# ---------------------------------------------------------------------------
# Phase 1: Core CRUD
# ---------------------------------------------------------------------------

@slices.command("list")
@click.option("--state", help="Filter by slice state (e.g. StableOK, Configuring, Dead).")
@click.pass_context
def list_slices(ctx, state):
    """List all slices for the current user.

    Examples:

      loomai slices list

      loomai slices list --state StableOK

      loomai --format json slices list
    """
    client = ctx.obj["client"]
    data = client.get("/slices", params={"max_age": 0})
    if state:
        data = [s for s in data if s.get("state") == state]
    output(ctx, data, columns=["name", "id", "state", "has_errors"],
           headers=["Name", "ID", "State", "Errors"])


@slices.command("show")
@click.argument("name", type=SLICE)
@click.pass_context
def show_slice(ctx, name):
    """Show detailed information about a slice.

    NAME can be a slice name or UUID.

    Examples:

      loomai slices show my-slice

      loomai --format json slices show my-slice
    """
    client = ctx.obj["client"]
    data = client.get(f"/slices/{name}")
    output(ctx, data)


@slices.command("create")
@click.argument("name", type=SLICE)
@click.pass_context
def create_slice(ctx, name):
    """Create a new empty draft slice.

    Examples:

      loomai slices create my-experiment
    """
    client = ctx.obj["client"]
    data = client.post("/slices", params={"name": name})
    output_message(f"Created draft slice '{name}'")
    output(ctx, data)


@slices.command("delete")
@click.argument("name", type=SLICE)
@click.option("--force", is_flag=True, help="Skip confirmation prompt.")
@click.pass_context
def delete_slice(ctx, name, force):
    """Delete a slice.

    Examples:

      loomai slices delete my-slice

      loomai slices delete my-slice --force
    """
    if not force:
        click.confirm(f"Delete slice '{name}'?", abort=True)
    client = ctx.obj["client"]
    data = client.delete(f"/slices/{name}")
    output_message(f"Deleted slice '{name}'")


# ---------------------------------------------------------------------------
# Phase 2: Lifecycle
# ---------------------------------------------------------------------------

@slices.command("submit")
@click.argument("name", type=SLICE)
@click.option("--wait", "do_wait", is_flag=True, help="Wait for provisioning to complete.")
@click.option("--timeout", default=600, help="Timeout in seconds when --wait is used.")
@click.pass_context
def submit_slice(ctx, name, do_wait, timeout):
    """Submit a draft slice to FABRIC for provisioning.

    Examples:

      loomai slices submit my-slice

      loomai slices submit my-slice --wait --timeout 600
    """
    client = ctx.obj["client"]
    output_message(f"Submitting slice '{name}'...")
    data = client.post(f"/slices/{name}/submit")
    state = data.get("state", "")
    output_message(f"Submitted — state: {state}")

    if do_wait and state not in STABLE_STATES and state not in TERMINAL_STATES:
        output_message(f"Waiting for provisioning (timeout: {timeout}s)...")
        result = wait_for_state(client, name, timeout=timeout)
        final_state = result.get("state", "")
        if final_state in STABLE_STATES:
            output_message(f"Slice '{name}' is ready ({final_state})")
        else:
            output_message(f"Slice '{name}' reached state: {final_state}")

    output(ctx, data)


@slices.command("modify")
@click.argument("name", type=SLICE)
@click.option("--wait", "do_wait", is_flag=True, help="Wait for modification to complete.")
@click.option("--timeout", default=600, help="Timeout in seconds when --wait is used.")
@click.pass_context
def modify_slice(ctx, name, do_wait, timeout):
    """Submit modifications to a running slice.

    Re-submits a slice that has been edited (nodes added/removed/changed)
    while already provisioned. FABRIC applies the changes incrementally.

    Examples:

      loomai slices modify my-slice

      loomai slices modify my-slice --wait --timeout 300
    """
    client = ctx.obj["client"]
    output_message(f"Submitting modifications for '{name}'...")
    data = client.post(f"/slices/{name}/submit")
    state = data.get("state", "")
    output_message(f"Modifications submitted — state: {state}")

    if do_wait and state not in STABLE_STATES and state not in TERMINAL_STATES:
        output_message(f"Waiting for modifications (timeout: {timeout}s)...")
        result = wait_for_state(client, name, timeout=timeout)
        final_state = result.get("state", "")
        if final_state in STABLE_STATES:
            output_message(f"Slice '{name}' is ready ({final_state})")
        else:
            output_message(f"Slice '{name}' reached state: {final_state}")

    output(ctx, data)


@slices.command("validate")
@click.argument("name", type=SLICE)
@click.pass_context
def validate_slice(ctx, name):
    """Validate slice topology before submission.

    Examples:

      loomai slices validate my-slice
    """
    client = ctx.obj["client"]
    data = client.get(f"/slices/{name}/validate")

    issues = data.get("issues", [])
    errors = [i for i in issues if i.get("severity") == "error"]
    warnings = [i for i in issues if i.get("severity") == "warning"]

    if ctx.obj["format"] != "table":
        output(ctx, data)
        return

    if not issues:
        click.echo("Validation passed — no issues found.")
    else:
        if errors:
            click.echo(f"\n{len(errors)} error(s):")
            for i in errors:
                click.echo(f"  ERROR: {i.get('message', '')}")
                if i.get("remedy"):
                    click.echo(f"         Remedy: {i['remedy']}")
        if warnings:
            click.echo(f"\n{len(warnings)} warning(s):")
            for i in warnings:
                click.echo(f"  WARN: {i.get('message', '')}")


@slices.command("renew")
@click.argument("name", type=SLICE)
@click.option("--days", required=True, type=int, help="Number of days to extend.")
@click.pass_context
def renew_slice(ctx, name, days):
    """Extend slice lease expiration.

    Examples:

      loomai slices renew my-slice --days 7
    """
    client = ctx.obj["client"]
    data = client.post(f"/slices/{name}/renew", json={"days": days})
    output_message(f"Renewed slice '{name}' for {days} days")
    output(ctx, data)


@slices.command("refresh")
@click.argument("name", type=SLICE)
@click.pass_context
def refresh_slice(ctx, name):
    """Refresh slice state from FABRIC (discards local edits).

    Examples:

      loomai slices refresh my-slice
    """
    client = ctx.obj["client"]
    data = client.post(f"/slices/{name}/refresh")
    output_message(f"Refreshed slice '{name}' — state: {data.get('state', '?')}")
    output(ctx, data)


@slices.command("state")
@click.argument("name", type=SLICE)
@click.pass_context
def slice_state(ctx, name):
    """Show the current slice state.

    Examples:

      loomai slices state my-slice

      loomai slices state my-slice --format json
    """
    client = ctx.obj["client"]
    data = client.get(f"/slices/{name}/state")
    output(ctx, data)


@slices.command("slivers")
@click.argument("name", type=SLICE)
@click.pass_context
def slivers(ctx, name):
    """Show per-node sliver states for a slice.

    Examples:

      loomai slices slivers my-slice
    """
    client = ctx.obj["client"]
    data = client.get(f"/slices/{name}/slivers")

    if ctx.obj["format"] != "table":
        output(ctx, data)
        return

    click.echo(f"Slice: {data.get('slice_name', name)}  State: {data.get('slice_state', '?')}")
    nodes = data.get("nodes", [])
    if nodes:
        output(ctx, nodes,
               columns=["name", "reservation_state", "site", "management_ip"],
               headers=["Node", "State", "Site", "Management IP"])
    else:
        click.echo("(no slivers)")


@slices.command("resolve-sites")
@click.argument("name", type=SLICE)
@click.option("--override", "overrides", multiple=True,
              help="Pin a group to a site, e.g. --override @edge=TACC. Repeatable.")
@click.option("--all", "resolve_all", is_flag=True,
              help="Re-resolve every node, not only @group nodes.")
@click.pass_context
def resolve_sites(ctx, name, overrides, resolve_all):
    """Re-resolve draft node site assignments from current availability."""
    group_overrides = {}
    for item in overrides:
        if "=" not in item:
            raise click.UsageError(f"Invalid override '{item}' (expected @group=SITE)")
        group, site = item.split("=", 1)
        group_overrides[group.strip()] = site.strip()

    data = ctx.obj["client"].post(f"/slices/{name}/resolve-sites", json={
        "group_overrides": group_overrides,
        "resolve_all": resolve_all,
    })
    if ctx.obj["format"] == "table":
        output_message(f"Resolved sites for '{name}'")
    output(ctx, data)


@slices.command("check-availability")
@click.argument("name", type=SLICE)
@click.pass_context
def check_availability(ctx, name):
    """Check whether a draft slice can be satisfied now or soon."""
    data = ctx.obj["client"].post(f"/slices/{name}/check-availability")
    if ctx.obj["format"] != "table":
        output(ctx, data)
        return

    status = data.get("status") or data.get("availability") or data.get("message", "")
    if status:
        click.echo(f"Availability: {status}")
    if data.get("node_requirements"):
        click.echo("\nNode requirements:")
        output(ctx, data["node_requirements"],
               columns=["name", "site", "cores", "ram", "disk", "components"],
               headers=["Node", "Site", "Cores", "RAM", "Disk", "Components"])
    elif isinstance(data, dict):
        output(ctx, data)


@slices.command("wait")
@click.argument("name", type=SLICE)
@click.option("--timeout", default=600, help="Timeout in seconds.")
@click.pass_context
def wait_slice(ctx, name, timeout):
    """Wait for a slice to reach a stable or terminal state.

    Examples:

      loomai slices wait my-slice --timeout 300
    """
    client = ctx.obj["client"]
    output_message(f"Waiting for slice '{name}' (timeout: {timeout}s)...")
    result = wait_for_state(client, name, timeout=timeout)
    state = result.get("state", "")
    if state in STABLE_STATES:
        output_message(f"Slice '{name}' is ready ({state})")
    else:
        output_message(f"Slice '{name}' reached state: {state}")
    output(ctx, result)


@slices.command("clone")
@click.argument("name", type=SLICE)
@click.option("--new-name", required=True, help="Name for the cloned slice.")
@click.pass_context
def clone_slice(ctx, name, new_name):
    """Clone a slice.

    Examples:

      loomai slices clone my-slice --new-name my-slice-copy
    """
    client = ctx.obj["client"]
    data = client.post(f"/slices/{name}/clone", json={"new_name": new_name})
    output_message(f"Cloned '{name}' as '{new_name}'")
    output(ctx, data)


@slices.command("export")
@click.argument("name", type=SLICE)
@click.option("--output-file", "-o", type=click.Path(), help="Write to file instead of stdout.")
@click.pass_context
def export_slice(ctx, name, output_file):
    """Export slice topology as JSON.

    Examples:

      loomai slices export my-slice -o slice.json

      loomai slices export my-slice | jq .
    """
    client = ctx.obj["client"]
    data = client.get(f"/slices/{name}/export")
    text = json.dumps(data, indent=2)
    if output_file:
        with open(output_file, "w") as f:
            f.write(text)
        output_message(f"Exported to {output_file}")
    else:
        click.echo(text)


@slices.command("import")
@click.argument("file", type=click.Path(exists=True))
@click.option("--name", help="Override slice name from file.")
@click.pass_context
def import_slice(ctx, file, name):
    """Import a slice topology from a JSON file.

    Examples:

      loomai slices import slice.json

      loomai slices import slice.json --name new-name
    """
    with open(file) as f:
        model = json.load(f)
    if name:
        model["name"] = name
    client = ctx.obj["client"]
    data = client.post("/slices/import", json=model)
    output_message(f"Imported slice '{data.get('name', '?')}'")
    output(ctx, data)


@slices.command("reconcile-projects")
@click.pass_context
def reconcile_projects(ctx):
    """Refresh local slice project tags from FABRIC."""
    data = ctx.obj["client"].post("/slices/reconcile-projects")
    if ctx.obj["format"] == "table":
        output_message("Reconciled slice project metadata")
    output(ctx, data)


@slices.command("save-to-storage")
@click.argument("name", type=SLICE)
@click.pass_context
def save_to_storage(ctx, name):
    """Save a slice definition to container storage."""
    data = ctx.obj["client"].post(f"/slices/{name}/save-to-storage")
    if ctx.obj["format"] == "table":
        output_message(f"Saved '{name}' to storage")
    output(ctx, data)


@slices.command("storage-files")
@click.pass_context
def storage_files(ctx):
    """List saved .fabric.json slice definitions."""
    data = ctx.obj["client"].get("/slices/storage-files")
    output(ctx, data,
           columns=["name", "size", "modified"],
           headers=["Name", "Size", "Modified"])


@slices.command("open-from-storage")
@click.argument("filename")
@click.pass_context
def open_from_storage(ctx, filename):
    """Open a saved slice definition from container storage."""
    data = ctx.obj["client"].post("/slices/open-from-storage", json={"filename": filename})
    if ctx.obj["format"] == "table":
        output_message(f"Opened '{filename}' from storage")
    output(ctx, data)


@slices.command("archive")
@click.argument("name", type=SLICE, required=False)
@click.option("--all-terminal", is_flag=True, help="Archive all dead/closed slices.")
@click.option("--force", is_flag=True, help="Skip confirmation prompt.")
@click.pass_context
def archive_slice(ctx, name, all_terminal, force):
    """Archive slices (hide without deleting).

    Examples:

      loomai slices archive my-dead-slice

      loomai slices archive --all-terminal
    """
    client = ctx.obj["client"]
    if all_terminal:
        data = client.post("/slices/archive-terminal")
        count = data.get("count", 0)
        archived = data.get("archived", [])
        if ctx.obj["format"] == "table":
            output_message(f"Archived {count} terminal slice(s)")
        if archived and ctx.obj["format"] == "table":
            for s in archived:
                click.echo(f"  {s}")
        else:
            output(ctx, data)
    elif name:
        if not force:
            click.confirm(f"Archive slice '{name}'?", abort=True)
        data = client.post(f"/slices/{name}/archive")
        if ctx.obj["format"] == "table":
            output_message(f"Archived slice '{name}'")
        output(ctx, data)
    else:
        raise click.UsageError("Specify a slice NAME or use --all-terminal")
