"""Runnable weave and cross-testbed experiment commands."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from loomai_cli.output import output, output_message


@click.group()
def experiments():
    """Manage runnable weaves and cross-testbed experiment templates."""


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _read_text_arg(content: str | None, file_path: str | None) -> str:
    if content is not None and file_path:
        raise click.UsageError("Use either --content or --file, not both.")
    if file_path:
        if file_path == "-":
            return sys.stdin.read()
        return Path(file_path).read_text()
    if content is not None:
        return content
    raise click.UsageError("Provide --content, --file PATH, or --file -.")


def _parse_key_value(values: tuple[str, ...]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise click.UsageError(f"Invalid KEY=VALUE value: {item}")
        key, value = item.split("=", 1)
        parsed[key] = value
    return parsed


def _variable_defs(values: tuple[str, ...]) -> list[dict]:
    variables = []
    for name, default in _parse_key_value(values).items():
        variables.append({
            "name": name,
            "label": name.replace("_", " ").title(),
            "type": "string",
            "default": default,
            "required": True,
        })
    return variables


@experiments.command("list")
@click.pass_context
def list_experiments(ctx):
    """List runnable local experiment artifacts."""
    data = ctx.obj["client"].get("/experiments")
    output(ctx, data,
           columns=["name", "description", "author", "tags", "script_count", "has_template"],
           headers=["Name", "Description", "Author", "Tags", "Scripts", "Template"])


@experiments.command("create")
@click.argument("name")
@click.option("--description", default="", help="Short description.")
@click.option("--author", default="", help="Author name.")
@click.option("--tags", default="", help="Comma-separated tags.")
@click.option("--slice-name", default="", help="Export the current slice as the template.")
@click.pass_context
def create_experiment(ctx, name, description, author, tags, slice_name):
    """Create a new experiment artifact."""
    body = {
        "name": name,
        "description": description,
        "author": author,
        "tags": _csv(tags),
        "slice_name": slice_name,
    }
    data = ctx.obj["client"].post("/experiments", json=body)
    if ctx.obj["format"] == "table":
        output_message(f"Created experiment {name}")
    output(ctx, data)


@experiments.command("show")
@click.argument("name")
@click.pass_context
def show_experiment(ctx, name):
    """Show experiment metadata, README, and script listing."""
    data = ctx.obj["client"].get(f"/experiments/{name}")
    output(ctx, data)


@experiments.command("update")
@click.argument("name")
@click.option("--description", help="New description.")
@click.option("--author", help="New author.")
@click.option("--tags", help="Replacement comma-separated tags.")
@click.pass_context
def update_experiment(ctx, name, description, author, tags):
    """Update experiment metadata."""
    body = {}
    if description is not None:
        body["description"] = description
    if author is not None:
        body["author"] = author
    if tags is not None:
        body["tags"] = _csv(tags)
    if not body:
        raise click.UsageError("Specify at least one field to update.")
    data = ctx.obj["client"].put(f"/experiments/{name}", json=body)
    if ctx.obj["format"] == "table":
        output_message(f"Updated experiment {name}")
    output(ctx, data)


@experiments.command("delete")
@click.argument("name")
@click.option("--force", is_flag=True, help="Skip confirmation.")
@click.pass_context
def delete_experiment(ctx, name, force):
    """Delete an experiment artifact."""
    if not force:
        click.confirm(f"Delete experiment '{name}'?", abort=True)
    data = ctx.obj["client"].delete(f"/experiments/{name}")
    if ctx.obj["format"] == "table":
        output_message(f"Deleted experiment {name}")
    output(ctx, data)


@experiments.group("readme")
def readme():
    """Read or replace an experiment README."""


@readme.command("get")
@click.argument("name")
@click.pass_context
def get_readme(ctx, name):
    """Show an experiment README."""
    data = ctx.obj["client"].get(f"/experiments/{name}/readme")
    if ctx.obj["format"] == "table":
        click.echo(data.get("content", ""))
        return
    output(ctx, data)


@readme.command("set")
@click.argument("name")
@click.option("--content", help="README content.")
@click.option("--file", "file_path", type=click.Path(),
              help="Read README content from a file, or '-' for stdin.")
@click.pass_context
def set_readme(ctx, name, content, file_path):
    """Replace an experiment README."""
    data = ctx.obj["client"].put(
        f"/experiments/{name}/readme",
        json={"content": _read_text_arg(content, file_path)},
    )
    if ctx.obj["format"] == "table":
        output_message(f"Saved README for {name}")
    output(ctx, data)


@experiments.group("scripts")
def scripts():
    """Read, replace, or delete experiment scripts."""


@scripts.command("get")
@click.argument("name")
@click.argument("filename")
@click.pass_context
def get_script(ctx, name, filename):
    """Show an experiment script."""
    data = ctx.obj["client"].get(f"/experiments/{name}/scripts/{filename}")
    if ctx.obj["format"] == "table":
        click.echo(data.get("content", ""))
        return
    output(ctx, data)


@scripts.command("set")
@click.argument("name")
@click.argument("filename")
@click.option("--content", help="Script content.")
@click.option("--file", "file_path", type=click.Path(),
              help="Read script content from a file, or '-' for stdin.")
@click.pass_context
def set_script(ctx, name, filename, content, file_path):
    """Create or replace an experiment script."""
    data = ctx.obj["client"].put(
        f"/experiments/{name}/scripts/{filename}",
        json={"content": _read_text_arg(content, file_path)},
    )
    if ctx.obj["format"] == "table":
        output_message(f"Saved script {filename} for {name}")
    output(ctx, data)


@scripts.command("delete")
@click.argument("name")
@click.argument("filename")
@click.option("--force", is_flag=True, help="Skip confirmation.")
@click.pass_context
def delete_script(ctx, name, filename, force):
    """Delete an experiment script."""
    if not force:
        click.confirm(f"Delete script '{filename}' from '{name}'?", abort=True)
    data = ctx.obj["client"].delete(f"/experiments/{name}/scripts/{filename}")
    if ctx.obj["format"] == "table":
        output_message(f"Deleted script {filename}")
    output(ctx, data)


@experiments.command("load")
@click.argument("name")
@click.option("--slice-name", default="", help="Name for the loaded draft slice.")
@click.pass_context
def load_experiment(ctx, name, slice_name):
    """Load an experiment's FABRIC template as a draft slice."""
    data = ctx.obj["client"].post(
        f"/experiments/{name}/load",
        json={"slice_name": slice_name} if slice_name else {},
    )
    if ctx.obj["format"] == "table":
        output_message(f"Loaded experiment {name}")
    output(ctx, data)


@experiments.command("save")
@click.argument("name")
@click.option("--description", default="", help="Short description.")
@click.option("--slice-name", default="", help="Slice to capture.")
@click.option("--author", default="", help="Author name.")
@click.option("--tags", default="cross-testbed", help="Comma-separated tags.")
@click.option("--variable", "variables", multiple=True,
              help="Variable default in NAME=VALUE form; repeatable.")
@click.pass_context
def save_experiment(ctx, name, description, slice_name, author, tags, variables):
    """Save the current federated slice as a cross-testbed experiment."""
    data = ctx.obj["client"].post("/experiments/save", json={
        "name": name,
        "description": description,
        "slice_name": slice_name,
        "variables": _variable_defs(variables),
        "author": author,
        "tags": _csv(tags),
    })
    if ctx.obj["format"] == "table":
        output_message(f"Saved experiment template {name}")
    output(ctx, data)


@experiments.command("template")
@click.argument("name")
@click.pass_context
def get_template(ctx, name):
    """Show a cross-testbed experiment template."""
    data = ctx.obj["client"].get(f"/experiments/{name}/template")
    output(ctx, data)


@experiments.command("load-experiment")
@click.argument("name")
@click.option("--var", "variables", multiple=True,
              help="Template variable in NAME=VALUE form; repeatable.")
@click.option("--variables-json", help="JSON object of template variables.")
@click.pass_context
def load_experiment_template(ctx, name, variables, variables_json):
    """Load a cross-testbed experiment template with variable substitutions."""
    body_variables = _parse_key_value(variables)
    if variables_json:
        try:
            body_variables.update(json.loads(variables_json))
        except json.JSONDecodeError as exc:
            raise click.UsageError(f"Invalid --variables-json: {exc}") from exc
    data = ctx.obj["client"].post(
        f"/experiments/{name}/load-experiment",
        json={"variables": body_variables},
    )
    if ctx.obj["format"] == "table":
        output_message(f"Loaded cross-testbed experiment {name}")
    output(ctx, data)
