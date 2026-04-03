"""Composite slice commands — cross-testbed experiment management."""

from __future__ import annotations

import json

import click

from loomai_cli.output import output, output_message


@click.group()
def composite():
    """Manage composite slices (cross-testbed experiments).

    Composite slices group FABRIC and Chameleon member slices into
    a unified experiment.  They don't hold resources directly — they
    reference existing slices from each testbed.

    Examples:

      loomai composite list

      loomai composite create my-experiment

      loomai composite add-fabric <composite-id> <fabric-slice>

      loomai composite submit <composite-id>
    """


@composite.command("list")
@click.pass_context
def list_composites(ctx):
    """List all composite slices.

    Examples:

      loomai composite list

      loomai --format json composite list
    """
    client = ctx.obj["client"]
    data = client.get("/composite/slices")
    output(ctx, data,
           columns=["id", "name", "state",
                     lambda r: str(len(r.get("fabric_slices", []))),
                     lambda r: str(len(r.get("chameleon_slices", [])))],
           headers=["ID", "Name", "State", "FABRIC", "Chameleon"])


@composite.command("show")
@click.argument("composite_id")
@click.pass_context
def show_composite(ctx, composite_id):
    """Show details of a composite slice.

    Examples:

      loomai composite show comp-abc123

      loomai --format json composite show comp-abc123
    """
    client = ctx.obj["client"]
    data = client.get(f"/composite/slices/{composite_id}")
    fmt = ctx.obj["format"]

    if fmt != "table":
        output(ctx, data)
        return

    click.echo(f"Composite: {data.get('name', '?')}")
    click.echo(f"ID:        {data.get('id', '?')}")
    click.echo(f"State:     {data.get('state', '?')}")

    fab = data.get("fabric_member_summaries", [])
    if fab:
        click.echo(f"\nFABRIC Members ({len(fab)}):")
        for m in fab:
            click.echo(f"  {m.get('name', '?')} ({m.get('id', '?')[:12]}...) — {m.get('state', '?')}")

    chi = data.get("chameleon_member_summaries", [])
    if chi:
        click.echo(f"\nChameleon Members ({len(chi)}):")
        for m in chi:
            click.echo(f"  {m.get('name', '?')} ({m.get('id', '?')[:12]}...) — {m.get('state', '?')}")

    xconn = data.get("cross_connections", [])
    if xconn:
        click.echo(f"\nCross-Connections ({len(xconn)}):")
        for c in xconn:
            click.echo(f"  {c.get('type', '?')}: {c.get('fabric_node', '?')} <-> {c.get('chameleon_node', '?')}")


@composite.command("create")
@click.argument("name")
@click.pass_context
def create_composite(ctx, name):
    """Create a new composite slice.

    Examples:

      loomai composite create my-cross-testbed-exp
    """
    client = ctx.obj["client"]
    data = client.post("/composite/slices", json={"name": name})
    output_message(f"Created composite '{name}' (id: {data.get('id', '?')})")
    output(ctx, data)


@composite.command("delete")
@click.argument("composite_id")
@click.option("--force", is_flag=True, help="Skip confirmation.")
@click.pass_context
def delete_composite(ctx, composite_id, force):
    """Delete a composite slice (member slices are NOT deleted).

    Examples:

      loomai composite delete comp-abc123

      loomai composite delete comp-abc123 --force
    """
    if not force:
        click.confirm(f"Delete composite '{composite_id}'? (Member slices are kept.)", abort=True)
    client = ctx.obj["client"]
    data = client.delete(f"/composite/slices/{composite_id}")
    output_message(f"Deleted composite {composite_id}")


@composite.command("add-fabric")
@click.argument("composite_id")
@click.argument("fabric_slice")
@click.pass_context
def add_fabric_member(ctx, composite_id, fabric_slice):
    """Add a FABRIC slice as a member of a composite.

    FABRIC_SLICE can be a slice name or UUID.

    Examples:

      loomai composite add-fabric comp-abc123 my-fabric-slice

      loomai composite add-fabric comp-abc123 e2e-test-uuid
    """
    client = ctx.obj["client"]
    # Get current members
    comp = client.get(f"/composite/slices/{composite_id}")
    fab_list = list(comp.get("fabric_slices", []))
    chi_list = list(comp.get("chameleon_slices", []))

    if fabric_slice not in fab_list:
        fab_list.append(fabric_slice)

    data = client.put(f"/composite/slices/{composite_id}/members", json={
        "fabric_slices": fab_list,
        "chameleon_slices": chi_list,
    })
    output_message(f"Added FABRIC slice '{fabric_slice}' to composite")


@composite.command("add-chameleon")
@click.argument("composite_id")
@click.argument("chameleon_slice")
@click.pass_context
def add_chameleon_member(ctx, composite_id, chameleon_slice):
    """Add a Chameleon slice as a member of a composite.

    CHAMELEON_SLICE is the Chameleon slice ID.

    Examples:

      loomai composite add-chameleon comp-abc123 chi-slice-xyz
    """
    client = ctx.obj["client"]
    comp = client.get(f"/composite/slices/{composite_id}")
    fab_list = list(comp.get("fabric_slices", []))
    chi_list = list(comp.get("chameleon_slices", []))

    if chameleon_slice not in chi_list:
        chi_list.append(chameleon_slice)

    data = client.put(f"/composite/slices/{composite_id}/members", json={
        "fabric_slices": fab_list,
        "chameleon_slices": chi_list,
    })
    output_message(f"Added Chameleon slice '{chameleon_slice}' to composite")


@composite.command("remove-fabric")
@click.argument("composite_id")
@click.argument("fabric_slice")
@click.pass_context
def remove_fabric_member(ctx, composite_id, fabric_slice):
    """Remove a FABRIC slice from a composite.

    Examples:

      loomai composite remove-fabric comp-abc123 my-fabric-slice
    """
    client = ctx.obj["client"]
    comp = client.get(f"/composite/slices/{composite_id}")
    fab_list = [f for f in comp.get("fabric_slices", []) if f != fabric_slice]
    chi_list = list(comp.get("chameleon_slices", []))

    client.put(f"/composite/slices/{composite_id}/members", json={
        "fabric_slices": fab_list,
        "chameleon_slices": chi_list,
    })
    output_message(f"Removed FABRIC slice '{fabric_slice}' from composite")


@composite.command("remove-chameleon")
@click.argument("composite_id")
@click.argument("chameleon_slice")
@click.pass_context
def remove_chameleon_member(ctx, composite_id, chameleon_slice):
    """Remove a Chameleon slice from a composite.

    Examples:

      loomai composite remove-chameleon comp-abc123 chi-slice-xyz
    """
    client = ctx.obj["client"]
    comp = client.get(f"/composite/slices/{composite_id}")
    fab_list = list(comp.get("fabric_slices", []))
    chi_list = [c for c in comp.get("chameleon_slices", []) if c != chameleon_slice]

    client.put(f"/composite/slices/{composite_id}/members", json={
        "fabric_slices": fab_list,
        "chameleon_slices": chi_list,
    })
    output_message(f"Removed Chameleon slice '{chameleon_slice}' from composite")


@composite.command("cross-connections")
@click.argument("composite_id")
@click.option("--add", "add_conn", nargs=4, multiple=True,
              metavar="TYPE FAB_NODE CHI_SLICE CHI_NODE",
              help="Add a cross-connection (e.g. fabnetv4 fab-node1 chi-slice-id chi-node1).")
@click.option("--clear", is_flag=True, help="Clear all cross-connections.")
@click.pass_context
def cross_connections(ctx, composite_id, add_conn, clear):
    """View or update cross-connections between FABRIC and Chameleon nodes.

    Examples:

      loomai composite cross-connections comp-abc123

      loomai composite cross-connections comp-abc123 --add fabnetv4 fab-node1 chi-id chi-node1

      loomai composite cross-connections comp-abc123 --clear
    """
    client = ctx.obj["client"]

    if clear:
        client.put(f"/composite/slices/{composite_id}/cross-connections", json=[])
        output_message("Cleared all cross-connections")
        return

    if add_conn:
        # Get existing cross-connections
        comp = client.get(f"/composite/slices/{composite_id}")
        xconns = list(comp.get("cross_connections", []))

        for conn_type, fab_node, chi_slice, chi_node in add_conn:
            xconns.append({
                "type": conn_type,
                "fabric_node": fab_node,
                "chameleon_slice": chi_slice,
                "chameleon_node": chi_node,
            })

        client.put(f"/composite/slices/{composite_id}/cross-connections", json=xconns)
        output_message(f"Added {len(add_conn)} cross-connection(s)")
        return

    # Show cross-connections
    comp = client.get(f"/composite/slices/{composite_id}")
    xconns = comp.get("cross_connections", [])
    if not xconns:
        click.echo("No cross-connections defined.")
        return
    output(ctx, xconns,
           columns=["type", "fabric_node", "chameleon_node"],
           headers=["Type", "FABRIC Node", "Chameleon Node"])


@composite.command("graph")
@click.argument("composite_id")
@click.pass_context
def composite_graph(ctx, composite_id):
    """Show the merged topology graph of a composite slice.

    Examples:

      loomai --format json composite graph comp-abc123
    """
    client = ctx.obj["client"]
    data = client.get(f"/composite/slices/{composite_id}/graph")
    output(ctx, data)


@composite.command("submit")
@click.argument("composite_id")
@click.option("--wait/--no-wait", default=False, help="Wait for all members to become active.")
@click.option("--timeout", default=900, help="Timeout in seconds when waiting (default: 900).")
@click.pass_context
def submit_composite(ctx, composite_id, wait, timeout):
    """Submit a composite slice — deploys all member slices in parallel.

    FABRIC members are submitted to FABRIC, Chameleon members are deployed
    via full_deploy.  Both happen in parallel.

    Examples:

      loomai composite submit comp-abc123

      loomai composite submit comp-abc123 --wait --timeout 1200
    """
    import time

    client = ctx.obj["client"]
    output_message("Submitting composite slice...")
    data = client.post(f"/composite/slices/{composite_id}/submit", json={})

    # Report results
    fab_results = data.get("fabric_results", [])
    chi_results = data.get("chameleon_results", [])

    for r in fab_results:
        status = r.get("status", "?")
        name = r.get("name", r.get("id", "?"))
        if status == "error":
            output_message(f"  FABRIC {name}: ERROR — {r.get('error', '?')}")
        else:
            output_message(f"  FABRIC {name}: {status}")

    for r in chi_results:
        status = r.get("status", "?")
        cid = r.get("id", "?")
        if status == "error":
            output_message(f"  Chameleon {cid}: ERROR — {r.get('error', '?')}")
        else:
            output_message(f"  Chameleon {cid}: {status}")

    if not wait:
        return

    # Poll until composite is Active or Degraded
    output_message(f"Waiting for composite to reach Active (timeout: {timeout}s)...")
    start = time.time()
    while time.time() - start < timeout:
        comp = client.get(f"/composite/slices/{composite_id}")
        state = comp.get("state", "")
        if state == "Active":
            output_message("Composite is Active!")
            return
        if state == "Degraded":
            output_message("Composite is Degraded — some members have errors.")
            return
        time.sleep(15)

    output_message(f"Timeout waiting for composite to become Active after {timeout}s")
