"""Network management commands for draft slices."""

from __future__ import annotations

import click
from loomai_cli.completions import SLICE

from loomai_cli.output import output, output_message


@click.group()
def networks():
    """Manage networks in a draft slice."""


@networks.command("add")
@click.argument("slice_name", type=SLICE)
@click.argument("net_name")
@click.option("--type", "net_type", default="L2Bridge",
              type=click.Choice(["L2Bridge", "L2STS", "L2PTP", "FABNetv4", "FABNetv6"]),
              help="Network type (default: L2Bridge).")
@click.option("--interfaces", "-i", help="Comma-separated interface names (e.g. node1-nic1-p1,node2-nic1-p1).")
@click.pass_context
def add_network(ctx, slice_name, net_name, net_type, interfaces):
    """Add a network to a draft slice.

    Examples:

      loomai networks add my-slice my-net --type L2Bridge -i node1-nic1-p1,node2-nic1-p1

      loomai networks add my-slice internet --type FABNetv4
    """
    client = ctx.obj["client"]
    body: dict = {"name": net_name, "type": net_type}
    if interfaces:
        body["interfaces"] = [s.strip() for s in interfaces.split(",")]
    data = client.post(f"/slices/{slice_name}/networks", json=body)
    output_message(f"Added network '{net_name}' to slice '{slice_name}'")
    output(ctx, data)


@networks.command("update")
@click.argument("slice_name", type=SLICE)
@click.argument("net_name")
@click.option("--type", "net_type", help="Change network type.")
@click.pass_context
def update_network(ctx, slice_name, net_name, net_type):
    """Update a network in a draft slice.

    Examples:

      loomai networks update my-slice my-net --type L2STS
    """
    client = ctx.obj["client"]
    body = {}
    if net_type:
        body["type"] = net_type
    if not body:
        raise click.UsageError("Specify at least one property to update.")
    data = client.put(f"/slices/{slice_name}/networks/{net_name}", json=body)
    output_message(f"Updated network '{net_name}'")
    output(ctx, data)


@networks.command("remove")
@click.argument("slice_name", type=SLICE)
@click.argument("net_name")
@click.pass_context
def remove_network(ctx, slice_name, net_name):
    """Remove a network from a draft slice.

    Examples:

      loomai networks remove my-slice my-net
    """
    client = ctx.obj["client"]
    data = client.delete(f"/slices/{slice_name}/networks/{net_name}")
    output_message(f"Removed network '{net_name}' from slice '{slice_name}'")
    output(ctx, data)
