"""Resource listing commands — images, component models."""

from __future__ import annotations

import click

from loomai_cli.output import output


@click.command("images")
@click.pass_context
def images(ctx):
    """List available VM images.

    Examples:

      loomai images

      loomai --format json images
    """
    client = ctx.obj["client"]
    data = client.get("/images")
    if ctx.obj["format"] == "table":
        for img in data:
            click.echo(img)
    else:
        output(ctx, data)


@click.command("component-models")
@click.pass_context
def component_models(ctx):
    """List available component models (NICs, GPUs, FPGAs, NVMe).

    Examples:

      loomai component-models

      loomai --format json component-models
    """
    client = ctx.obj["client"]
    data = client.get("/component-models")
    output(ctx, data, columns=["name", "type", "detail"],
           headers=["Model", "Type", "Detail"])
