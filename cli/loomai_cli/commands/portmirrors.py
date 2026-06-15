"""Port mirror management commands for draft slices."""

from __future__ import annotations

import click

from loomai_cli.completions import SLICE
from loomai_cli.output import output, output_message


@click.group("port-mirrors")
def port_mirrors():
    """Manage FABRIC port mirror services in a draft slice."""


@port_mirrors.command("add")
@click.argument("slice_name", type=SLICE)
@click.argument("name")
@click.option("--mirror-interface", required=True,
              help="Interface to mirror.")
@click.option("--receive-interface", required=True,
              help="Interface that receives mirrored traffic.")
@click.option("--direction", default="both",
              type=click.Choice(["both", "ingress", "egress"]),
              help="Traffic direction to mirror.")
@click.pass_context
def add_port_mirror(ctx, slice_name, name, mirror_interface, receive_interface, direction):
    """Add a port mirror service to a draft slice."""
    data = ctx.obj["client"].post(f"/slices/{slice_name}/port-mirrors", json={
        "name": name,
        "mirror_interface_name": mirror_interface,
        "receive_interface_name": receive_interface,
        "mirror_direction": direction,
    })
    if ctx.obj["format"] == "table":
        output_message(f"Added port mirror '{name}'")
    output(ctx, data)


@port_mirrors.command("update")
@click.argument("slice_name", type=SLICE)
@click.argument("name")
@click.option("--mirror-interface", required=True,
              help="Interface to mirror.")
@click.option("--receive-interface", required=True,
              help="Interface that receives mirrored traffic.")
@click.option("--direction", default="both",
              type=click.Choice(["both", "ingress", "egress"]),
              help="Traffic direction to mirror.")
@click.pass_context
def update_port_mirror(ctx, slice_name, name, mirror_interface, receive_interface, direction):
    """Replace a port mirror service under the same name."""
    data = ctx.obj["client"].put(f"/slices/{slice_name}/port-mirrors/{name}", json={
        "mirror_interface_name": mirror_interface,
        "receive_interface_name": receive_interface,
        "mirror_direction": direction,
    })
    if ctx.obj["format"] == "table":
        output_message(f"Updated port mirror '{name}'")
    output(ctx, data)


@port_mirrors.command("remove")
@click.argument("slice_name", type=SLICE)
@click.argument("name")
@click.pass_context
def remove_port_mirror(ctx, slice_name, name):
    """Remove a port mirror service from a draft slice."""
    data = ctx.obj["client"].delete(f"/slices/{slice_name}/port-mirrors/{name}")
    if ctx.obj["format"] == "table":
        output_message(f"Removed port mirror '{name}'")
    output(ctx, data)
