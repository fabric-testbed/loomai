"""VM template commands."""

from __future__ import annotations

import click

from loomai_cli.output import output


@click.group("vm-templates")
def vm_templates():
    """Manage VM templates."""


@vm_templates.command("list")
@click.pass_context
def list_vm_templates(ctx):
    """List VM templates.

    Examples:

      loomai vm-templates list
    """
    client = ctx.obj["client"]
    data = client.get("/vm_templates")
    output(ctx, data,
           columns=["name", "description", "image"],
           headers=["Name", "Description", "Image"])


@vm_templates.command("show")
@click.argument("name")
@click.pass_context
def show_vm_template(ctx, name):
    """Show VM template details.

    Examples:

      loomai vm-templates show My_VM
    """
    client = ctx.obj["client"]
    data = client.get(f"/vm_templates/{name}")
    output(ctx, data)
