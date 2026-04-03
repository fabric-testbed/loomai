"""Node management commands for draft slices."""

from __future__ import annotations

import click
from loomai_cli.completions import SLICE

from loomai_cli.output import output, output_message


@click.group()
def nodes():
    """Manage nodes in a draft slice."""


@nodes.command("add")
@click.argument("slice_name", type=SLICE)
@click.argument("node_name")
@click.option("--site", default="auto", help="FABRIC site name or 'auto' (default: auto).")
@click.option("--cores", default=2, type=int, help="Number of CPU cores (default: 2).")
@click.option("--ram", default=8, type=int, help="RAM in GB (default: 8).")
@click.option("--disk", default=50, type=int, help="Disk in GB (default: 50).")
@click.option("--image", default="default_ubuntu_22", help="VM image (default: default_ubuntu_22).")
@click.pass_context
def add_node(ctx, slice_name, node_name, site, cores, ram, disk, image):
    """Add a VM node to a draft slice.

    Examples:

      loomai nodes add my-slice node1

      loomai nodes add my-slice gpu-node --site RENC --cores 8 --ram 32 --disk 100

      loomai nodes add my-slice node2 --image default_centos_9
    """
    client = ctx.obj["client"]
    body = {
        "name": node_name,
        "site": site,
        "cores": cores,
        "ram": ram,
        "disk": disk,
        "image": image,
    }
    data = client.post(f"/slices/{slice_name}/nodes", json=body)
    output_message(f"Added node '{node_name}' to slice '{slice_name}'")
    output(ctx, data)


@nodes.command("update")
@click.argument("slice_name", type=SLICE)
@click.argument("node_name")
@click.option("--site", help="Change site.")
@click.option("--cores", type=int, help="Change CPU cores.")
@click.option("--ram", type=int, help="Change RAM (GB).")
@click.option("--disk", type=int, help="Change disk (GB).")
@click.option("--image", help="Change VM image.")
@click.pass_context
def update_node(ctx, slice_name, node_name, site, cores, ram, disk, image):
    """Update a node's properties in a draft slice.

    Only specified options are changed; others remain as-is.

    Examples:

      loomai nodes update my-slice node1 --cores 8 --ram 32

      loomai nodes update my-slice node1 --site UCSD
    """
    client = ctx.obj["client"]
    body = {}
    if site is not None:
        body["site"] = site
    if cores is not None:
        body["cores"] = cores
    if ram is not None:
        body["ram"] = ram
    if disk is not None:
        body["disk"] = disk
    if image is not None:
        body["image"] = image
    if not body:
        raise click.UsageError("Specify at least one property to update.")
    data = client.put(f"/slices/{slice_name}/nodes/{node_name}", json=body)
    output_message(f"Updated node '{node_name}'")
    output(ctx, data)


@nodes.command("remove")
@click.argument("slice_name", type=SLICE)
@click.argument("node_name")
@click.pass_context
def remove_node(ctx, slice_name, node_name):
    """Remove a node from a draft slice.

    Examples:

      loomai nodes remove my-slice node1
    """
    client = ctx.obj["client"]
    data = client.delete(f"/slices/{slice_name}/nodes/{node_name}")
    output_message(f"Removed node '{node_name}' from slice '{slice_name}'")
    output(ctx, data)
