"""Legacy federated command aliases kept for backward compatibility.

New scripts and docs should use ``loomai federated``.
"""

from __future__ import annotations

import click

from loomai_cli.output import output, output_message


def _is_table(ctx: click.Context) -> bool:
    return ctx.obj["format"] == "table"


def _table_message(ctx: click.Context, message: str) -> None:
    if _is_table(ctx):
        output_message(message)


@click.group()
def composite():
    """Deprecated alias for older cross-testbed workflows.

    Use `loomai federated` for current federated slice commands. This hidden
    compatibility group remains available for existing automation that still
    calls the old endpoint names.

    Examples:

      loomai federated list

      loomai federated create my-experiment

      loomai federated members add <federated-id> fabric <fabric-slice>

      loomai federated submit <federated-id>
    """


@composite.command("list")
@click.pass_context
def list_composites(ctx):
    """List all federated slices.

    Examples:

      loomai federated list

      loomai --format json federated list
    """
    client = ctx.obj["client"]
    data = client.get("/composite/slices")
    output(ctx, data,
           columns=["id", "name", "state",
                     lambda r: str(len(r.get("fabric_slices", []))),
                     lambda r: str(len(r.get("chameleon_slices", [])))],
           headers=["ID", "Name", "State", "FABRIC", "Chameleon"])


@composite.command("show")
@click.argument("slice_id")
@click.pass_context
def show_composite(ctx, slice_id):
    """Show details of a federated slice.

    Examples:

      loomai federated show fed-abc123

      loomai --format json federated show fed-abc123
    """
    client = ctx.obj["client"]
    data = client.get(f"/composite/slices/{slice_id}")
    fmt = ctx.obj["format"]

    if fmt != "table":
        output(ctx, data)
        return

    click.echo(f"Federated Slice: {data.get('name', '?')}")
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
    """Create a new federated slice.

    Examples:

      loomai federated create my-cross-testbed-exp
    """
    client = ctx.obj["client"]
    data = client.post("/composite/slices", json={"name": name})
    _table_message(ctx, f"Created federated slice '{name}' (id: {data.get('id', '?')})")
    output(ctx, data)


@composite.command("delete")
@click.argument("slice_id")
@click.option("--force", is_flag=True, help="Skip confirmation.")
@click.pass_context
def delete_composite(ctx, slice_id, force):
    """Delete a federated slice (member slices are NOT deleted).

    Examples:

      loomai federated delete fed-abc123

      loomai federated delete fed-abc123 --force
    """
    if not force:
        click.confirm(f"Delete federated slice '{slice_id}'? (Member slices are kept.)", abort=True)
    client = ctx.obj["client"]
    data = client.delete(f"/composite/slices/{slice_id}")
    _table_message(ctx, f"Deleted federated slice {slice_id}")
    if not _is_table(ctx):
        output(ctx, data)


@composite.command("add-fabric")
@click.argument("slice_id")
@click.argument("fabric_slice")
@click.pass_context
def add_fabric_member(ctx, slice_id, fabric_slice):
    """Add a FABRIC slice as a member of a federated slice.

    FABRIC_SLICE can be a slice name or UUID.

    Examples:

      loomai federated members add fed-abc123 fabric my-fabric-slice

      loomai federated members add fed-abc123 fabric e2e-test-uuid
    """
    client = ctx.obj["client"]
    # Get current members
    comp = client.get(f"/composite/slices/{slice_id}")
    fab_list = list(comp.get("fabric_slices", []))
    chi_list = list(comp.get("chameleon_slices", []))

    if fabric_slice not in fab_list:
        fab_list.append(fabric_slice)

    data = client.put(f"/composite/slices/{slice_id}/members", json={
        "fabric_slices": fab_list,
        "chameleon_slices": chi_list,
    })
    _table_message(ctx, f"Added FABRIC slice '{fabric_slice}' to federated slice")
    output(ctx, data)


@composite.command("add-chameleon")
@click.argument("slice_id")
@click.argument("chameleon_slice")
@click.pass_context
def add_chameleon_member(ctx, slice_id, chameleon_slice):
    """Add a Chameleon slice as a member of a federated slice.

    CHAMELEON_SLICE is the Chameleon slice ID.

    Examples:

      loomai federated members add fed-abc123 chameleon chi-slice-xyz
    """
    client = ctx.obj["client"]
    comp = client.get(f"/composite/slices/{slice_id}")
    fab_list = list(comp.get("fabric_slices", []))
    chi_list = list(comp.get("chameleon_slices", []))

    if chameleon_slice not in chi_list:
        chi_list.append(chameleon_slice)

    data = client.put(f"/composite/slices/{slice_id}/members", json={
        "fabric_slices": fab_list,
        "chameleon_slices": chi_list,
    })
    _table_message(ctx, f"Added Chameleon slice '{chameleon_slice}' to federated slice")
    output(ctx, data)


@composite.command("remove-fabric")
@click.argument("slice_id")
@click.argument("fabric_slice")
@click.pass_context
def remove_fabric_member(ctx, slice_id, fabric_slice):
    """Remove a FABRIC slice from a federated slice.

    Examples:

      loomai federated members remove fed-abc123 fabric my-fabric-slice
    """
    client = ctx.obj["client"]
    comp = client.get(f"/composite/slices/{slice_id}")
    fab_list = [f for f in comp.get("fabric_slices", []) if f != fabric_slice]
    chi_list = list(comp.get("chameleon_slices", []))

    data = client.put(f"/composite/slices/{slice_id}/members", json={
        "fabric_slices": fab_list,
        "chameleon_slices": chi_list,
    })
    _table_message(ctx, f"Removed FABRIC slice '{fabric_slice}' from federated slice")
    output(ctx, data)


@composite.command("remove-chameleon")
@click.argument("slice_id")
@click.argument("chameleon_slice")
@click.pass_context
def remove_chameleon_member(ctx, slice_id, chameleon_slice):
    """Remove a Chameleon slice from a federated slice.

    Examples:

      loomai federated members remove fed-abc123 chameleon chi-slice-xyz
    """
    client = ctx.obj["client"]
    comp = client.get(f"/composite/slices/{slice_id}")
    fab_list = list(comp.get("fabric_slices", []))
    chi_list = [c for c in comp.get("chameleon_slices", []) if c != chameleon_slice]

    data = client.put(f"/composite/slices/{slice_id}/members", json={
        "fabric_slices": fab_list,
        "chameleon_slices": chi_list,
    })
    _table_message(ctx, f"Removed Chameleon slice '{chameleon_slice}' from federated slice")
    output(ctx, data)


@composite.command("cross-connections")
@click.argument("slice_id")
@click.option("--add", "add_conn", nargs=4, multiple=True,
              metavar="TYPE FAB_NODE CHI_SLICE CHI_NODE",
              help="Add a cross-connection (e.g. fabnetv4 fab-node1 chi-slice-id chi-node1).")
@click.option("--clear", is_flag=True, help="Clear all cross-connections.")
@click.pass_context
def cross_connections(ctx, slice_id, add_conn, clear):
    """View or update cross-connections between FABRIC and Chameleon nodes.

    Examples:

      loomai federated connections list fed-abc123

      loomai federated connections add fed-abc123 --type fabnetv4 --fabric-node fab-node1 --chameleon-slice chi-id --chameleon-node chi-node1

      loomai federated connections clear fed-abc123
    """
    client = ctx.obj["client"]

    if clear:
        data = client.put(f"/composite/slices/{slice_id}/cross-connections", json=[])
        _table_message(ctx, "Cleared all cross-connections")
        if not _is_table(ctx):
            output(ctx, data)
        return

    if add_conn:
        # Get existing cross-connections
        comp = client.get(f"/composite/slices/{slice_id}")
        xconns = list(comp.get("cross_connections", []))

        for conn_type, fab_node, chi_slice, chi_node in add_conn:
            xconns.append({
                "type": conn_type,
                "fabric_node": fab_node,
                "chameleon_slice": chi_slice,
                "chameleon_node": chi_node,
            })

        data = client.put(f"/composite/slices/{slice_id}/cross-connections", json=xconns)
        _table_message(ctx, f"Added {len(add_conn)} cross-connection(s)")
        output(ctx, data)
        return

    # Show cross-connections
    comp = client.get(f"/composite/slices/{slice_id}")
    xconns = comp.get("cross_connections", [])
    if not xconns:
        if _is_table(ctx):
            click.echo("No cross-connections defined.")
        else:
            output(ctx, [])
        return
    output(ctx, xconns,
           columns=["type", "fabric_node", "chameleon_node"],
           headers=["Type", "FABRIC Node", "Chameleon Node"])


@composite.command("graph")
@click.argument("slice_id")
@click.pass_context
def composite_graph(ctx, slice_id):
    """Show the merged topology graph of a federated slice.

    Examples:

      loomai --format json federated graph fed-abc123
    """
    client = ctx.obj["client"]
    data = client.get(f"/composite/slices/{slice_id}/graph")
    output(ctx, data)


@composite.command("submit")
@click.argument("slice_id")
@click.option("--wait/--no-wait", default=False, help="Wait for all members to become active.")
@click.option("--timeout", default=900, help="Timeout in seconds when waiting (default: 900).")
@click.pass_context
def submit_composite(ctx, slice_id, wait, timeout):
    """Submit a federated slice — deploys all member slices in parallel.

    FABRIC members are submitted to FABRIC, Chameleon members are deployed
    via full_deploy.  Both happen in parallel.

    Examples:

      loomai federated submit fed-abc123

      loomai federated submit fed-abc123 --wait --timeout 1200
    """
    import time

    client = ctx.obj["client"]
    fmt = ctx.obj["format"]
    if fmt == "table":
        output_message("Submitting federated slice...")
    data = client.post(f"/composite/slices/{slice_id}/submit", json={})
    result = dict(data) if isinstance(data, dict) else {"submit": data}

    # Report results
    fab_results = data.get("fabric_results", [])
    chi_results = data.get("chameleon_results", [])

    if fmt == "table":
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
        if fmt != "table":
            output(ctx, result)
        return

    # Poll until the federated slice is Active or Degraded.
    if fmt == "table":
        output_message(f"Waiting for federated slice to reach Active (timeout: {timeout}s)...")
    start = time.time()
    while time.time() - start < timeout:
        comp = client.get(f"/composite/slices/{slice_id}")
        state = comp.get("state", "")
        if state == "Active":
            result["final_state"] = state
            result["federated"] = comp
            if fmt == "table":
                output_message("Federated slice is Active!")
            else:
                output(ctx, result)
            return
        if state == "Degraded":
            result["final_state"] = state
            result["federated"] = comp
            if fmt == "table":
                output_message("Federated slice is Degraded — some members have errors.")
            else:
                output(ctx, result)
            return
        time.sleep(15)

    result["timeout"] = True
    result["timeout_seconds"] = timeout
    if fmt == "table":
        output_message(f"Timeout waiting for federated slice to become Active after {timeout}s")
    else:
        output(ctx, result)
