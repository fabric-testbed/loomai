"""SSH tunnel commands for exposing VM services through LoomAI."""

from __future__ import annotations

import click

from loomai_cli.completions import SLICE
from loomai_cli.output import output, output_message


@click.group()
def tunnels():
    """Open and manage browser-safe tunnels to VM services."""


@tunnels.command("list")
@click.pass_context
def list_tunnels(ctx):
    """List active tunnels."""
    data = ctx.obj["client"].get("/tunnels")
    output(ctx, data,
           columns=["id", "slice_name", "node_name", "remote_port", "local_port", "protocol", "status"],
           headers=["ID", "Slice", "Node", "Remote", "Local", "Protocol", "Status"])


@tunnels.command("open")
@click.argument("slice_name", type=SLICE)
@click.argument("node_name")
@click.argument("port", type=int)
@click.option("--protocol", default="http", type=click.Choice(["http", "https"]),
              help="Protocol spoken by the service on the VM.")
@click.pass_context
def open_tunnel(ctx, slice_name, node_name, port, protocol):
    """Open or reuse a tunnel to a VM service port."""
    data = ctx.obj["client"].post("/tunnels", json={
        "slice_name": slice_name,
        "node_name": node_name,
        "port": port,
        "protocol": protocol,
    })
    if ctx.obj["format"] == "table":
        output_message(f"Opened tunnel to {slice_name}/{node_name}:{port}")
    output(ctx, data)


@tunnels.command("close")
@click.argument("tunnel_id")
@click.pass_context
def close_tunnel(ctx, tunnel_id):
    """Close an active tunnel."""
    data = ctx.obj["client"].delete(f"/tunnels/{tunnel_id}")
    if ctx.obj["format"] == "table":
        output_message(f"Closed tunnel {tunnel_id}")
    output(ctx, data)
