"""Component management commands for draft slice nodes."""

from __future__ import annotations

import click
from loomai_cli.completions import SLICE

from loomai_cli.output import output, output_message


@click.group()
def components():
    """Manage components (NICs, GPUs, FPGAs) on slice nodes."""


@components.command("add")
@click.argument("slice_name", type=SLICE)
@click.argument("node_name")
@click.argument("comp_name")
@click.option("--model", required=True,
              help="Component model (e.g. NIC_Basic, GPU_RTX6000, GPU_A30, SmartNIC_ConnectX_6).")
@click.pass_context
def add_component(ctx, slice_name, node_name, comp_name, model):
    """Add a component to a node in a draft slice.

    Examples:

      loomai components add my-slice node1 gpu1 --model GPU_RTX6000

      loomai components add my-slice node1 nic1 --model NIC_Basic
    """
    client = ctx.obj["client"]
    body = {"name": comp_name, "model": model}
    data = client.post(f"/slices/{slice_name}/nodes/{node_name}/components", json=body)
    output_message(f"Added component '{comp_name}' ({model}) to '{node_name}'")
    output(ctx, data)


@components.command("remove")
@click.argument("slice_name", type=SLICE)
@click.argument("node_name")
@click.argument("comp_name")
@click.pass_context
def remove_component(ctx, slice_name, node_name, comp_name):
    """Remove a component from a node in a draft slice.

    Examples:

      loomai components remove my-slice node1 gpu1
    """
    client = ctx.obj["client"]
    data = client.delete(f"/slices/{slice_name}/nodes/{node_name}/components/{comp_name}")
    output_message(f"Removed component '{comp_name}' from '{node_name}'")
    output(ctx, data)
