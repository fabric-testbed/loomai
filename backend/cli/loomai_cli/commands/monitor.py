"""Monitoring commands."""

from __future__ import annotations

import click
from loomai_cli.completions import SLICE

from loomai_cli.output import output, output_message


@click.group()
def monitor():
    """Monitor slice node metrics."""


@monitor.command("enable")
@click.argument("slice_name", type=SLICE)
@click.pass_context
def enable_monitoring(ctx, slice_name):
    """Enable monitoring on all nodes (installs node_exporter).

    Examples:

      loomai monitor enable my-slice
    """
    client = ctx.obj["client"]
    output_message(f"Enabling monitoring for '{slice_name}'...")
    data = client.post(f"/monitoring/{slice_name}/enable")
    output(ctx, data)


@monitor.command("disable")
@click.argument("slice_name", type=SLICE)
@click.pass_context
def disable_monitoring(ctx, slice_name):
    """Disable monitoring for a slice.

    Examples:

      loomai monitor disable my-slice
    """
    client = ctx.obj["client"]
    data = client.post(f"/monitoring/{slice_name}/disable")
    if ctx.obj["format"] == "table":
        output_message("Monitoring disabled")
    output(ctx, data)


@monitor.command("status")
@click.argument("slice_name", type=SLICE)
@click.pass_context
def monitoring_status(ctx, slice_name):
    """Show monitoring status for a slice.

    Examples:

      loomai monitor status my-slice
    """
    client = ctx.obj["client"]
    data = client.get(f"/monitoring/{slice_name}/status")
    output(ctx, data)


@monitor.command("metrics")
@click.argument("slice_name", type=SLICE)
@click.pass_context
def get_metrics(ctx, slice_name):
    """Show latest metrics for all monitored nodes.

    Examples:

      loomai monitor metrics my-slice
    """
    client = ctx.obj["client"]
    data = client.get(f"/monitoring/{slice_name}/metrics")
    output(ctx, data)


@monitor.command("history")
@click.argument("slice_name", type=SLICE)
@click.option("--minutes", default=30, type=click.IntRange(1, 60),
              help="History window in minutes.")
@click.pass_context
def metrics_history(ctx, slice_name, minutes):
    """Show recent time-series metrics for monitored nodes."""
    data = ctx.obj["client"].get(
        f"/monitoring/{slice_name}/metrics/history",
        params={"minutes": minutes},
    )
    output(ctx, data)


@monitor.command("infrastructure")
@click.argument("slice_name", type=SLICE)
@click.pass_context
def infrastructure_metrics(ctx, slice_name):
    """Show public FABRIC infrastructure metrics for a slice's sites."""
    data = ctx.obj["client"].get(f"/monitoring/{slice_name}/infrastructure")
    output(ctx, data)


@monitor.group("nodes")
def monitor_nodes():
    """Enable or disable monitoring for individual nodes."""


@monitor_nodes.command("enable")
@click.argument("slice_name", type=SLICE)
@click.argument("node_name")
@click.pass_context
def enable_node_monitoring(ctx, slice_name, node_name):
    """Enable monitoring on one node."""
    data = ctx.obj["client"].post(f"/monitoring/{slice_name}/nodes/{node_name}/enable")
    if ctx.obj["format"] == "table":
        output_message(f"Enabled monitoring for {node_name}")
    output(ctx, data)


@monitor_nodes.command("disable")
@click.argument("slice_name", type=SLICE)
@click.argument("node_name")
@click.pass_context
def disable_node_monitoring(ctx, slice_name, node_name):
    """Disable monitoring on one node."""
    data = ctx.obj["client"].post(f"/monitoring/{slice_name}/nodes/{node_name}/disable")
    if ctx.obj["format"] == "table":
        output_message(f"Disabled monitoring for {node_name}")
    output(ctx, data)


def _parse_chameleon_node(value: str) -> dict:
    """Parse name=ip[,site=...][,key_path=...][,username=...] shorthand."""
    if "=" not in value:
        raise click.UsageError(f"Invalid --node value: {value}")
    first, *rest = value.split(",")
    name, ip = first.split("=", 1)
    node = {"name": name.strip(), "ip": ip.strip()}
    for part in rest:
        if "=" not in part:
            raise click.UsageError(f"Invalid --node field: {part}")
        key, val = part.split("=", 1)
        if key not in {"site", "key_path", "username"}:
            raise click.UsageError(f"Unsupported Chameleon node field: {key}")
        node[key] = val
    return node


@monitor.command("chameleon-enable")
@click.argument("slice_name")
@click.option("--node", "nodes", multiple=True, required=True,
              help="Node as name=ip[,site=...][,key_path=...][,username=...]; repeatable.")
@click.pass_context
def enable_chameleon_monitoring(ctx, slice_name, nodes):
    """Enable monitoring for Chameleon nodes in a LoomAI slice."""
    data = ctx.obj["client"].post("/monitoring/chameleon/enable", json={
        "slice_name": slice_name,
        "nodes": [_parse_chameleon_node(n) for n in nodes],
    })
    if ctx.obj["format"] == "table":
        output_message(f"Enabled Chameleon monitoring for {len(nodes)} node(s)")
    output(ctx, data)
