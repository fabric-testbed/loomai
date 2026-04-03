"""Recipe commands."""

from __future__ import annotations

import click
from loomai_cli.completions import SLICE

from loomai_cli.output import output, output_message


@click.group()
def recipes():
    """Manage and execute VM recipes."""


@recipes.command("list")
@click.pass_context
def list_recipes(ctx):
    """List available recipes.

    Examples:

      loomai recipes list
    """
    client = ctx.obj["client"]
    data = client.get("/recipes")
    output(ctx, data,
           columns=["name", "description", "starred"],
           headers=["Name", "Description", "Starred"])


@recipes.command("show")
@click.argument("name")
@click.pass_context
def show_recipe(ctx, name):
    """Show recipe details.

    Examples:

      loomai recipes show install_docker
    """
    client = ctx.obj["client"]
    data = client.get(f"/recipes/{name}")
    output(ctx, data)


@recipes.command("run")
@click.argument("recipe")
@click.argument("slice_name", type=SLICE)
@click.argument("node_name")
@click.pass_context
def run_recipe(ctx, recipe, slice_name, node_name):
    """Execute a recipe on a VM node.

    Examples:

      loomai recipes run install_docker my-slice node1
    """
    client = ctx.obj["client"]
    output_message(f"Running recipe '{recipe}' on {node_name}...")
    data = client.post(f"/recipes/{recipe}/execute/{slice_name}/{node_name}")
    output(ctx, data)
