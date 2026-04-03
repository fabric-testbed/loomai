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
    output_message("Monitoring disabled")


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
