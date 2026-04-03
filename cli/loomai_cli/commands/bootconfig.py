"""Boot configuration commands."""

from __future__ import annotations

import json

import click
from loomai_cli.completions import SLICE

from loomai_cli.output import output, output_message


@click.group("boot-config")
def boot_config():
    """Manage node boot configurations."""


@boot_config.command("show")
@click.argument("slice_name", type=SLICE)
@click.argument("node_name")
@click.pass_context
def show_boot(ctx, slice_name, node_name):
    """Show boot configuration for a node.

    Examples:

      loomai boot-config show my-slice node1
    """
    client = ctx.obj["client"]
    data = client.get(f"/files/boot-config/{slice_name}/{node_name}")
    output(ctx, data)


@boot_config.command("run")
@click.argument("slice_name", type=SLICE)
@click.argument("node_name", required=False)
@click.option("--all", "all_nodes", is_flag=True, help="Run on all nodes.")
@click.pass_context
def run_boot(ctx, slice_name, node_name, all_nodes):
    """Execute boot configuration on a node or all nodes.

    Examples:

      loomai boot-config run my-slice node1

      loomai boot-config run my-slice --all
    """
    client = ctx.obj["client"]
    if all_nodes:
        output_message(f"Running boot config on all nodes of '{slice_name}'...")
        data = client.post(f"/files/boot-config/{slice_name}/execute-all")
        output(ctx, data)
    elif node_name:
        output_message(f"Running boot config on '{node_name}'...")
        data = client.post(f"/files/boot-config/{slice_name}/{node_name}/execute")
        output(ctx, data)
    else:
        raise click.UsageError("Specify NODE_NAME or use --all")


@boot_config.command("log")
@click.argument("slice_name", type=SLICE)
@click.pass_context
def boot_log(ctx, slice_name):
    """View boot execution log.

    Examples:

      loomai boot-config log my-slice
    """
    client = ctx.obj["client"]
    data = client.get(f"/files/boot-config/{slice_name}/log")
    if isinstance(data, dict) and "log" in data:
        click.echo(data["log"])
    else:
        output(ctx, data)


@boot_config.command("set")
@click.argument("slice_name", type=SLICE)
@click.argument("node_name")
@click.option("--command", "-c", "commands", multiple=True,
              help="Boot command to run (repeatable).")
@click.option("--from-file", "config_file", type=click.Path(exists=True),
              help="Load boot config from JSON file ({uploads, commands, network}).")
@click.pass_context
def set_boot(ctx, slice_name, node_name, commands, config_file):
    """Set boot configuration for a node.

    Examples:

      loomai boot-config set my-slice node1 -c "apt update" -c "apt install -y nginx"

      loomai boot-config set my-slice node1 --from-file boot.json
    """
    client = ctx.obj["client"]
    if config_file:
        with open(config_file) as f:
            body = json.load(f)
    elif commands:
        body = {
            "commands": [{"command": cmd, "order": i}
                         for i, cmd in enumerate(commands)],
            "uploads": [],
            "network": [],
        }
    else:
        raise click.UsageError("Specify --command/-c or --from-file")
    client.put(f"/files/boot-config/{slice_name}/{node_name}", json=body)
    output_message(f"Boot config set for {node_name} in '{slice_name}'")
