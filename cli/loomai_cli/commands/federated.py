"""Federated slice commands."""

from __future__ import annotations

import json
import time
from typing import Optional

import click

from loomai_cli.output import output, output_message


@click.group()
def federated():
    """Manage federated slices across FABRIC and Chameleon."""


@federated.command("list")
@click.pass_context
def list_federated(ctx):
    """List federated slices."""
    data = ctx.obj["client"].get("/federated/slices")
    output(ctx, data,
           columns=["id", "name", "state", "kind"],
           headers=["ID", "Name", "State", "Kind"])


@federated.command("show")
@click.argument("slice_id")
@click.pass_context
def show_federated(ctx, slice_id):
    """Show a federated slice with member summaries."""
    data = ctx.obj["client"].get(f"/federated/slices/{slice_id}")
    output(ctx, data)


@federated.command("create")
@click.argument("name")
@click.pass_context
def create_federated(ctx, name):
    """Create a federated slice."""
    data = ctx.obj["client"].post("/federated/slices", json={"name": name})
    if ctx.obj["format"] == "table":
        output_message(f"Created federated slice '{name}'")
    output(ctx, data)


@federated.command("delete")
@click.argument("slice_id")
@click.option("--delete-members", is_flag=True,
              help="Also delete provider member slices.")
@click.option("--delete-imported-resources", is_flag=True,
              help="Delete imported Chameleon resources when deleting members.")
@click.option("--force", is_flag=True, help="Skip confirmation.")
@click.pass_context
def delete_federated(ctx, slice_id, delete_members, delete_imported_resources, force):
    """Delete a federated slice."""
    if not force:
        msg = f"Delete federated slice '{slice_id}'?"
        if delete_members:
            msg += " Provider member slices will also be deleted."
        click.confirm(msg, abort=True)
    data = ctx.obj["client"].delete(f"/federated/slices/{slice_id}", params={
        "delete_members": delete_members,
        "delete_imported_resources": delete_imported_resources,
    })
    if ctx.obj["format"] == "table":
        output_message(f"Deleted federated slice {slice_id}")
    output(ctx, data)


@federated.command("graph")
@click.argument("slice_id")
@click.pass_context
def graph(ctx, slice_id):
    """Show the merged federated topology graph."""
    data = ctx.obj["client"].get(f"/federated/slices/{slice_id}/graph")
    output(ctx, data)


@federated.command("submit")
@click.argument("slice_id")
@click.option("--wait/--no-wait", default=False,
              help="Poll until the federated slice becomes Active or Degraded.")
@click.option("--timeout", default=900, type=int, help="Wait timeout in seconds.")
@click.pass_context
def submit(ctx, slice_id, wait, timeout):
    """Submit provider member slices and connection preparation in parallel."""
    data = ctx.obj["client"].post(f"/federated/slices/{slice_id}/submit", json={})
    output(ctx, data)
    if not wait:
        return

    start = time.time()
    while time.time() - start < timeout:
        current = ctx.obj["client"].get(f"/federated/slices/{slice_id}")
        state = current.get("state", "")
        if state in ("Active", "Degraded", "Error"):
            if ctx.obj["format"] == "table":
                output_message(f"Federated slice reached {state}")
            return
        time.sleep(15)
    if ctx.obj["format"] == "table":
        output_message(f"Timeout waiting for federated slice after {timeout}s")


@federated.group("members")
def members():
    """Manage federated provider members."""


@members.command("list")
@click.argument("slice_id")
@click.pass_context
def members_list(ctx, slice_id):
    """List provider members for a federated slice."""
    data = ctx.obj["client"].get(f"/federated/slices/{slice_id}")
    rows = data.get("members", [])
    output(ctx, rows,
           columns=["provider", "slice_id", "name", "role"],
           headers=["Provider", "Slice ID", "Name", "Role"])


@members.command("add")
@click.argument("slice_id")
@click.argument("provider", type=click.Choice(["fabric", "chameleon"]))
@click.argument("provider_slice_id")
@click.option("--name", help="Display name for this member.")
@click.option("--role", help="Role label.")
@click.pass_context
def members_add(ctx, slice_id, provider, provider_slice_id, name, role):
    """Attach one provider slice to a federated slice."""
    body = {"provider": provider, "slice_id": provider_slice_id}
    if name:
        body["name"] = name
    if role:
        body["role"] = role
    data = ctx.obj["client"].post(f"/federated/slices/{slice_id}/members/add", json=body)
    if ctx.obj["format"] == "table":
        output_message(f"Added {provider} member {provider_slice_id}")
    output(ctx, data)


@members.command("remove")
@click.argument("slice_id")
@click.argument("provider", type=click.Choice(["fabric", "chameleon"]))
@click.argument("provider_slice_id")
@click.pass_context
def members_remove(ctx, slice_id, provider, provider_slice_id):
    """Detach one provider slice from a federated slice."""
    data = ctx.obj["client"].post(f"/federated/slices/{slice_id}/members/remove", json={
        "provider": provider,
        "slice_id": provider_slice_id,
    })
    if ctx.obj["format"] == "table":
        output_message(f"Removed {provider} member {provider_slice_id}")
    output(ctx, data)


@members.command("replace-fabric")
@click.argument("old_id")
@click.argument("new_id")
@click.pass_context
def members_replace_fabric(ctx, old_id, new_id):
    """Replace a FABRIC draft/member ID after submit assigns a new UUID."""
    data = ctx.obj["client"].post("/federated/replace-fabric-member", json={
        "old_id": old_id,
        "new_id": new_id,
    })
    output(ctx, data)


@federated.group("connections")
def connections():
    """Manage federated cross-testbed connection intents."""


def _connection_payload(
    conn_type: str,
    fabric_slice: str,
    chameleon_slice: str,
    fabric_node: str,
    chameleon_node: str,
    fabric_site: str,
    chameleon_site: str,
    vlan: str,
    facility_port: str,
    physical_network: str,
    cidr: str,
    bandwidth: Optional[int],
) -> dict:
    fabric_endpoint = {"provider": "fabric", "slice_id": fabric_slice}
    chameleon_endpoint = {"provider": "chameleon", "slice_id": chameleon_slice}
    if fabric_node:
        fabric_endpoint["node"] = fabric_node
    if chameleon_node:
        chameleon_endpoint["node"] = chameleon_node
    if fabric_site:
        fabric_endpoint["site"] = fabric_site
    if chameleon_site:
        chameleon_endpoint["site"] = chameleon_site
    if vlan:
        fabric_endpoint["vlan"] = vlan
        chameleon_endpoint["vlan"] = vlan
    if facility_port:
        fabric_endpoint["facility_port"] = facility_port
    if physical_network:
        chameleon_endpoint["physical_network"] = physical_network
    if cidr:
        chameleon_endpoint["cidr"] = cidr
    if bandwidth is not None:
        fabric_endpoint["bandwidth"] = bandwidth

    body = {
        "type": conn_type,
        "endpoint_a": fabric_endpoint,
        "endpoint_b": chameleon_endpoint,
    }
    if vlan:
        body["vlan"] = vlan
    if facility_port:
        body["facility_port"] = facility_port
    if fabric_site:
        body["fabric_site"] = fabric_site
    if chameleon_site:
        body["chameleon_site"] = chameleon_site
    if physical_network:
        body["physical_network"] = physical_network
    if cidr:
        body["cidr"] = cidr
    return body


@connections.command("list")
@click.argument("slice_id")
@click.pass_context
def connections_list(ctx, slice_id):
    """List cross-testbed connections for a federated slice."""
    data = ctx.obj["client"].get(f"/federated/slices/{slice_id}/connections")
    output(ctx, data,
           columns=["id", "type", "fabric_slice", "chameleon_slice", "vlan", "facility_port"],
           headers=["ID", "Type", "FABRIC", "Chameleon", "VLAN", "Facility Port"])


@connections.command("add")
@click.argument("slice_id")
@click.option("--type", "conn_type", default="fabnetv4_l3",
              type=click.Choice(["fabnetv4_l3", "facility_port_l2", "fabnetv4", "l2_stitch"]),
              help="Connection type.")
@click.option("--fabric-slice", required=True, help="FABRIC member slice ID/name.")
@click.option("--chameleon-slice", required=True, help="Chameleon member slice ID.")
@click.option("--fabric-node", default="", help="FABRIC endpoint node.")
@click.option("--chameleon-node", default="", help="Chameleon endpoint node.")
@click.option("--fabric-site", default="", help="FABRIC site for Facility Port L2.")
@click.option("--chameleon-site", default="", help="Chameleon site for Facility Port L2.")
@click.option("--vlan", default="", help="Negotiated VLAN for Facility Port L2.")
@click.option("--facility-port", default="", help="FABRIC facility port name.")
@click.option("--physical-network", default="", help="Chameleon physical network.")
@click.option("--cidr", default="", help="Chameleon VLAN network CIDR.")
@click.option("--bandwidth", type=int, help="Facility port bandwidth.")
@click.pass_context
def connections_add(
    ctx, slice_id, conn_type, fabric_slice, chameleon_slice, fabric_node,
    chameleon_node, fabric_site, chameleon_site, vlan, facility_port,
    physical_network, cidr, bandwidth,
):
    """Add a cross-testbed connection intent."""
    body = _connection_payload(
        conn_type, fabric_slice, chameleon_slice, fabric_node, chameleon_node,
        fabric_site, chameleon_site, vlan, facility_port, physical_network,
        cidr, bandwidth,
    )
    data = ctx.obj["client"].post(f"/federated/slices/{slice_id}/connections/add", json=body)
    if ctx.obj["format"] == "table":
        output_message(f"Added {conn_type} connection")
    output(ctx, data)


@connections.command("remove")
@click.argument("slice_id")
@click.argument("connection_id")
@click.pass_context
def connections_remove(ctx, slice_id, connection_id):
    """Remove one cross-testbed connection intent."""
    data = ctx.obj["client"].post(f"/federated/slices/{slice_id}/connections/remove", json={
        "id": connection_id,
    })
    if ctx.obj["format"] == "table":
        output_message(f"Removed connection {connection_id}")
    output(ctx, data)


@connections.command("clear")
@click.argument("slice_id")
@click.pass_context
def connections_clear(ctx, slice_id):
    """Remove all cross-testbed connection intents."""
    data = ctx.obj["client"].put(f"/federated/slices/{slice_id}/connections", json=[])
    output(ctx, data)


@connections.command("set")
@click.argument("slice_id")
@click.argument("file", type=click.Path(exists=True))
@click.pass_context
def connections_set(ctx, slice_id, file):
    """Replace all connections from a JSON file containing a list."""
    with open(file) as f:
        body = json.load(f)
    if not isinstance(body, list):
        raise click.UsageError("Connection file must contain a JSON list.")
    data = ctx.obj["client"].put(f"/federated/slices/{slice_id}/connections", json=body)
    output(ctx, data)


@connections.command("plan")
@click.argument("slice_id")
@click.pass_context
def connections_plan(ctx, slice_id):
    """Show provider-side actions for connection intents."""
    data = ctx.obj["client"].get(f"/federated/slices/{slice_id}/connection-plan")
    output(ctx, data,
           columns=["id", "type", "status", "fabric_slice", "chameleon_slice", "vlan", "facility_port"],
           headers=["ID", "Type", "Status", "FABRIC", "Chameleon", "VLAN", "Facility Port"])
