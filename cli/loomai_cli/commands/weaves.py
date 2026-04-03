"""Weave (template) management and background run commands."""

from __future__ import annotations

import time

import click
from loomai_cli.completions import WEAVE, RUN_ID

from loomai_cli.output import output, output_message


@click.group()
def weaves():
    """Manage weaves (deployable experiment templates)."""


@weaves.command("create")
@click.argument("name")
@click.option("--description", "-d", default="", help="Short description of the weave.")
@click.pass_context
def create_weave(ctx, name, description):
    """Create a new weave stub with all default files.

    Creates a runnable single-node weave with: <name>.py, <name>.ipynb,
    weave.sh, weave.json, weave.md, weave.log, and .weaveignore.

    Examples:

      loomai weaves create my_experiment

      loomai weaves create iperf_test -d "Bandwidth test between two nodes"
    """
    client = ctx.obj["client"]
    body = {"name": name}
    if description:
        body["description"] = description
    data = client.post("/templates/create-weave", json=body)
    output_message(f"Created weave '{data.get('dir_name', name)}'")
    files = data.get("files", [])
    if files:
        output_message(f"Files: {', '.join(files)}")
    output(ctx, data)


@weaves.command("list")
@click.pass_context
def list_weaves(ctx):
    """List all local weaves.

    Examples:

      loomai weaves list

      loomai --format json weaves list
    """
    client = ctx.obj["client"]
    data = client.get("/templates")
    output(ctx, data,
           columns=["name", "description", "has_weave_json", "has_weave_sh"],
           headers=["Name", "Description", "weave.json", "weave.sh"])


@weaves.command("show")
@click.argument("name", type=WEAVE)
@click.pass_context
def show_weave(ctx, name):
    """Show detailed weave information.

    Examples:

      loomai weaves show Hello_FABRIC
    """
    client = ctx.obj["client"]
    data = client.get(f"/templates/{name}")
    output(ctx, data)


@weaves.command("load")
@click.argument("name", type=WEAVE)
@click.option("--slice-name", help="Name for the new draft slice (default: auto-generated).")
@click.pass_context
def load_weave(ctx, name, slice_name):
    """Load a weave as a new draft slice.

    Examples:

      loomai weaves load Hello_FABRIC --slice-name my-hello
    """
    client = ctx.obj["client"]
    body = {}
    if slice_name:
        body["slice_name"] = slice_name
    data = client.post(f"/templates/{name}/load", json=body)
    output_message(f"Loaded weave '{name}' as draft")
    output(ctx, data)


@weaves.command("run")
@click.argument("name", type=WEAVE)
@click.option("--args", "run_args", multiple=True, help="KEY=VALUE arguments (repeatable).")
@click.option("--script", default="weave.sh", help="Script to run (default: weave.sh).")
@click.pass_context
def run_weave(ctx, name, run_args, script):
    """Start a weave as a background run.

    Examples:

      loomai weaves run Hello_FABRIC --args SLICE_NAME=my-exp

      loomai weaves run My_Weave --args SLICE_NAME=test --args DURATION=60
    """
    client = ctx.obj["client"]
    args_dict = {}
    for arg in run_args:
        if "=" not in arg:
            raise click.UsageError(f"Invalid arg format: '{arg}' (expected KEY=VALUE)")
        k, v = arg.split("=", 1)
        args_dict[k] = v

    data = client.post(f"/templates/{name}/start-run/{script}", json={"args": args_dict})
    run_id = data.get("run_id", "")
    output_message(f"Started run: {run_id}")
    output(ctx, data)


@weaves.command("stop")
@click.argument("run_id", type=RUN_ID)
@click.pass_context
def stop_run(ctx, run_id):
    """Stop a running weave.

    Examples:

      loomai weaves stop run-abc123def456
    """
    client = ctx.obj["client"]
    data = client.post(f"/templates/runs/{run_id}/stop")
    output_message(f"Stopping run {run_id}...")
    output(ctx, data)


@weaves.command("logs")
@click.argument("run_id", type=RUN_ID)
@click.option("--follow", "-f", is_flag=True, help="Follow output (like tail -f).")
@click.pass_context
def run_logs(ctx, run_id, follow):
    """View output from a background run.

    Examples:

      loomai weaves logs run-abc123def456

      loomai weaves logs run-abc123def456 --follow
    """
    client = ctx.obj["client"]
    offset = 0

    while True:
        data = client.get(f"/templates/runs/{run_id}/output", params={"offset": offset})
        new_output = data.get("output", "")
        if new_output:
            click.echo(new_output, nl=False)
            offset = data.get("offset", offset)

        status = data.get("status", "")
        if not follow or status in ("done", "error", "interrupted", "unknown"):
            if status and status != "running":
                output_message(f"\nRun {status}")
            break

        time.sleep(2)


@weaves.command("runs")
@click.option("--status", help="Filter by status (running, done, error).")
@click.pass_context
def list_runs(ctx, status):
    """List background runs.

    Examples:

      loomai weaves runs

      loomai weaves runs --status running
    """
    client = ctx.obj["client"]
    data = client.get("/templates/runs")
    if status:
        data = [r for r in data if r.get("status") == status]
    output(ctx, data,
           columns=["run_id", "weave_name", "status", "started_at"],
           headers=["Run ID", "Weave", "Status", "Started"])
