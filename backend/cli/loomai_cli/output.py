"""Output formatting — table, JSON, YAML."""

from __future__ import annotations

import json
import sys
from typing import Any, Sequence

import click
import yaml
from tabulate import tabulate


def format_table(rows: Sequence[dict], columns: Sequence[str], headers: Sequence[str] | None = None) -> str:
    """Format a list of dicts as an aligned table."""
    if not rows:
        return "(no results)"
    table_data = [[row.get(c, "") for c in columns] for row in rows]
    return tabulate(table_data, headers=headers or columns, tablefmt="simple")


def format_json(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def format_yaml(data: Any) -> str:
    return yaml.dump(data, default_flow_style=False, sort_keys=False)


def output(ctx: click.Context, data: Any, columns: Sequence[str] | None = None,
           headers: Sequence[str] | None = None) -> None:
    """Print data in the format specified by --format."""
    fmt = ctx.obj["format"]

    if fmt == "json":
        click.echo(format_json(data))
    elif fmt == "yaml":
        click.echo(format_yaml(data))
    else:
        # Table format
        if isinstance(data, list) and columns:
            click.echo(format_table(data, columns, headers))
        elif isinstance(data, dict):
            # Single object — key: value pairs
            for k, v in data.items():
                if isinstance(v, (list, dict)):
                    v = json.dumps(v, default=str)
                click.echo(f"{k}: {v}")
        else:
            click.echo(data)


def output_message(msg: str) -> None:
    """Print a status message to stderr (doesn't interfere with piped output)."""
    click.echo(msg, err=True)
