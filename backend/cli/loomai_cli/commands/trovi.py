"""Trovi marketplace commands for Chameleon shared experiments."""

from __future__ import annotations

import click

from loomai_cli.output import output, output_message


@click.group()
def trovi():
    """Browse and get Chameleon Trovi artifacts."""


@trovi.command("list")
@click.option("--query", "-q", default="", help="Search query.")
@click.option("--tag", default="", help="Filter by Trovi tag.")
@click.option("--limit", default=50, type=click.IntRange(1, 200), help="Maximum rows.")
@click.option("--offset", default=0, type=int, help="Pagination offset.")
@click.pass_context
def list_trovi(ctx, query, tag, limit, offset):
    """List or search Trovi artifacts."""
    data = ctx.obj["client"].get("/trovi/artifacts", params={
        "q": query,
        "tag": tag,
        "limit": limit,
        "offset": offset,
    })
    if ctx.obj["format"] != "table":
        output(ctx, data)
        return
    output(ctx, data.get("artifacts", []),
           columns=["title", "uuid", "short_description", "tags", "versions"],
           headers=["Title", "UUID", "Description", "Tags", "Versions"])
    total = data.get("total")
    if total is not None:
        click.echo(f"Total: {total}")


@trovi.command("search")
@click.argument("query")
@click.option("--tag", default="", help="Filter by Trovi tag.")
@click.option("--limit", default=50, type=click.IntRange(1, 200), help="Maximum rows.")
@click.pass_context
def search_trovi(ctx, query, tag, limit):
    """Search Trovi artifacts."""
    data = ctx.obj["client"].get("/trovi/artifacts", params={
        "q": query,
        "tag": tag,
        "limit": limit,
        "offset": 0,
    })
    if ctx.obj["format"] != "table":
        output(ctx, data)
        return
    output(ctx, data.get("artifacts", []),
           columns=["title", "uuid", "short_description", "tags", "versions"],
           headers=["Title", "UUID", "Description", "Tags", "Versions"])


@trovi.command("show")
@click.argument("uuid")
@click.pass_context
def show_trovi(ctx, uuid):
    """Show a Trovi artifact."""
    data = ctx.obj["client"].get(f"/trovi/artifacts/{uuid}")
    output(ctx, data)


@trovi.command("tags")
@click.pass_context
def list_trovi_tags(ctx):
    """List Trovi tags."""
    data = ctx.obj["client"].get("/trovi/tags")
    if ctx.obj["format"] == "table":
        for tag in data.get("tags", []):
            click.echo(tag)
        return
    output(ctx, data)


@trovi.command("get")
@click.argument("uuid")
@click.pass_context
def get_trovi(ctx, uuid):
    """Download a Trovi artifact into local LoomAI artifacts."""
    data = ctx.obj["client"].post(f"/trovi/artifacts/{uuid}/get")
    if ctx.obj["format"] == "table":
        output_message(f"Downloaded Trovi artifact {uuid}")
    output(ctx, data)
