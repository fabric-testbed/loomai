"""Resource scheduling and future reservation commands."""

from __future__ import annotations

import click

from loomai_cli.output import output, output_message


@click.group()
def schedule():
    """Inspect resource calendars and manage scheduled submissions."""


@schedule.command("calendar")
@click.option("--days", default=14, type=click.IntRange(1, 30), help="Days to include.")
@click.option("--interval", default="day", type=click.Choice(["hour", "day", "week"]),
              help="Calendar interval.")
@click.option("--site", help="Comma-separated sites to include.")
@click.option("--exclude-site", help="Comma-separated sites to exclude.")
@click.option("--show", default="sites", type=click.Choice(["sites", "hosts", "all"]),
              help="Resource level to show.")
@click.pass_context
def calendar(ctx, days, interval, site, exclude_site, show):
    """Show FABRIC resource availability over time.

    Examples:

      loomai schedule calendar --days 7

      loomai schedule calendar --site TACC,MAX --interval hour
    """
    client = ctx.obj["client"]
    data = client.get("/schedule/calendar", params={
        "days": days,
        "interval": interval,
        "site": site,
        "exclude_site": exclude_site,
        "show": show,
    })
    if ctx.obj["format"] != "table":
        output(ctx, data)
        return

    rows = data.get("data", []) if isinstance(data, dict) else []
    total = data.get("total", len(rows)) if isinstance(data, dict) else len(rows)
    click.echo(f"Calendar: {total} slot(s), interval={data.get('interval', interval) if isinstance(data, dict) else interval}")
    if rows:
        preview = rows[:20]
        output(ctx, preview,
               columns=["start", "end", "sites", "hosts"],
               headers=["Start", "End", "Sites", "Hosts"])
        if len(rows) > len(preview):
            click.echo(f"... {len(rows) - len(preview)} more slot(s)")


@schedule.command("next-available")
@click.option("--cores", default=0, type=int, help="Required cores.")
@click.option("--ram", default=0, type=int, help="Required RAM in GB.")
@click.option("--disk", default=0, type=int, help="Required disk in GB.")
@click.option("--gpu", default="", help="Required GPU/component model.")
@click.option("--site", default="", help="Restrict search to one site.")
@click.pass_context
def next_available(ctx, cores, ram, disk, gpu, site):
    """Find where requested resources are available now or soon.

    Examples:

      loomai schedule next-available --cores 8 --ram 32

      loomai schedule next-available --gpu GPU_RTX6000
    """
    if cores == 0 and ram == 0 and disk == 0 and not gpu:
        raise click.UsageError("Specify at least one resource constraint.")

    client = ctx.obj["client"]
    data = client.get("/schedule/next-available", params={
        "cores": cores,
        "ram": ram,
        "disk": disk,
        "gpu": gpu,
        "site": site,
    })
    if ctx.obj["format"] != "table":
        output(ctx, data)
        return

    available_now = data.get("available_now", [])
    available_soon = data.get("available_soon", [])
    not_available = data.get("not_available", [])
    if available_now:
        click.echo("Available now:")
        output(ctx, available_now,
               columns=["site", "cores_available", "ram_available"],
               headers=["Site", "Cores", "RAM"])
    if available_soon:
        click.echo("\nAvailable soon:")
        output(ctx, available_soon,
               columns=["site", "earliest_time"],
               headers=["Site", "Earliest Time"])
    if not_available:
        click.echo("\nNot available:")
        output(ctx, not_available,
               columns=["site", "reason"],
               headers=["Site", "Reason"])
    if not available_now and not available_soon and not not_available:
        click.echo("No availability data returned.")


@schedule.command("alternatives")
@click.option("--cores", default=0, type=int, help="Required cores.")
@click.option("--ram", default=0, type=int, help="Required RAM in GB.")
@click.option("--disk", default=0, type=int, help="Required disk in GB.")
@click.option("--gpu", default="", help="Required GPU/component model.")
@click.option("--preferred-site", default="", help="Preferred FABRIC site.")
@click.pass_context
def alternatives(ctx, cores, ram, disk, gpu, preferred_site):
    """Suggest alternatives when requested resources are unavailable.

    Examples:

      loomai schedule alternatives --cores 16 --ram 64 --preferred-site TACC
    """
    if cores == 0 and ram == 0 and disk == 0 and not gpu:
        raise click.UsageError("Specify at least one resource constraint.")

    client = ctx.obj["client"]
    data = client.get("/schedule/alternatives", params={
        "cores": cores,
        "ram": ram,
        "disk": disk,
        "gpu": gpu,
        "preferred_site": preferred_site,
    })
    if ctx.obj["format"] != "table":
        output(ctx, data)
        return

    if data.get("preferred_available"):
        click.echo(f"Preferred site {preferred_site or data.get('preferred_site', '')} is available.")
        return

    rows = data.get("alternatives", [])
    if rows:
        output(ctx, rows,
               columns=["type", "site", "available_now", "suggestion", "earliest_time"],
               headers=["Type", "Site", "Now", "Suggestion", "Earliest Time"])
    else:
        click.echo("No alternatives found.")


@schedule.group("reservations")
def reservations():
    """Manage scheduled slice submissions."""


@reservations.command("list")
@click.pass_context
def reservations_list(ctx):
    """List scheduled slice submissions."""
    client = ctx.obj["client"]
    data = client.get("/schedule/reservations")
    output(ctx, data,
           columns=["id", "slice_name", "scheduled_time", "duration_hours", "auto_submit", "status"],
           headers=["ID", "Slice", "Scheduled", "Hours", "Auto", "Status"])


@reservations.command("create")
@click.argument("slice_name")
@click.argument("scheduled_time")
@click.option("--duration-hours", default=24, type=int, help="Reservation duration in hours.")
@click.option("--auto-submit/--no-auto-submit", default=True,
              help="Submit automatically when the scheduled time arrives.")
@click.pass_context
def reservations_create(ctx, slice_name, scheduled_time, duration_hours, auto_submit):
    """Create a scheduled slice submission.

    SCHEDULED_TIME should be an ISO timestamp, for example 2026-06-15T14:00:00Z.
    """
    client = ctx.obj["client"]
    data = client.post("/schedule/reservations", json={
        "slice_name": slice_name,
        "scheduled_time": scheduled_time,
        "duration_hours": duration_hours,
        "auto_submit": auto_submit,
    })
    if ctx.obj["format"] == "table":
        output_message(f"Scheduled '{slice_name}' for {scheduled_time}")
    output(ctx, data)


@reservations.command("delete")
@click.argument("reservation_id")
@click.pass_context
def reservations_delete(ctx, reservation_id):
    """Cancel a scheduled slice submission."""
    client = ctx.obj["client"]
    data = client.delete(f"/schedule/reservations/{reservation_id}")
    if ctx.obj["format"] == "table":
        output_message(f"Cancelled reservation {reservation_id}")
    output(ctx, data)
