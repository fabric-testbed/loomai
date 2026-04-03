"""Facility port management commands for draft slices."""

from __future__ import annotations

import click
from loomai_cli.completions import SLICE

from loomai_cli.output import output, output_message


@click.group("facility-ports")
def facility_ports():
    """Manage facility ports in a draft slice."""


@facility_ports.command("list")
@click.pass_context
def list_fps(ctx):
    """List available facility ports across FABRIC sites.

    Examples:

      loomai facility-ports list
    """
    client = ctx.obj["client"]
    data = client.get("/facility-ports")
    if isinstance(data, list):
        output(ctx, data,
               columns=["name", "site", "vlan", "bandwidth"],
               headers=["Name", "Site", "VLAN", "Bandwidth"])
    else:
        output(ctx, data)


@facility_ports.command("add")
@click.argument("slice_name", type=SLICE)
@click.argument("fp_name")
@click.option("--site", required=True, help="FABRIC site name.")
@click.option("--vlan", default="", help="VLAN tag.")
@click.option("--bandwidth", default=10, type=int, help="Bandwidth in Gbps (default: 10).")
@click.pass_context
def add_fp(ctx, slice_name, fp_name, site, vlan, bandwidth):
    """Add a facility port to a draft slice.

    Examples:

      loomai facility-ports add my-slice my-fp --site CERN --vlan 800

      loomai facility-ports add my-slice fp1 --site RENC --bandwidth 25
    """
    client = ctx.obj["client"]
    body = {"name": fp_name, "site": site, "vlan": vlan, "bandwidth": bandwidth}
    data = client.post(f"/slices/{slice_name}/facility-ports", json=body)
    output_message(f"Added facility port '{fp_name}' to slice '{slice_name}'")
    output(ctx, data)


@facility_ports.command("remove")
@click.argument("slice_name", type=SLICE)
@click.argument("fp_name")
@click.pass_context
def remove_fp(ctx, slice_name, fp_name):
    """Remove a facility port from a draft slice.

    Examples:

      loomai facility-ports remove my-slice my-fp
    """
    client = ctx.obj["client"]
    data = client.delete(f"/slices/{slice_name}/facility-ports/{fp_name}")
    output_message(f"Removed facility port '{fp_name}' from slice '{slice_name}'")
    output(ctx, data)
