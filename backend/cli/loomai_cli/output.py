"""Output formatting — table, JSON, YAML."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Sequence, Union

import click
import yaml
from tabulate import tabulate


Column = Union[str, Callable[[dict], Any]]


def _format_cell(value: Any) -> str:
    """Render nested values compactly enough for a terminal table."""
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    if isinstance(value, list):
        if not value:
            return ""
        if all(isinstance(v, (str, int, float, bool)) or v is None for v in value):
            rendered = ", ".join("" if v is None else str(v) for v in value)
            return rendered if len(rendered) <= 80 else f"{len(value)} items"
        return f"{len(value)} item{'s' if len(value) != 1 else ''}"
    if isinstance(value, dict):
        if not value:
            return ""
        simple_items = [
            f"{k}={v}" for k, v in value.items()
            if isinstance(v, (str, int, float, bool)) or v is None
        ]
        if simple_items and len(simple_items) == len(value):
            rendered = ", ".join(simple_items)
            return rendered if len(rendered) <= 80 else f"{len(value)} fields"
        return f"{len(value)} fields"
    return str(value)


def _column_value(row: dict, column: Column) -> Any:
    if callable(column):
        return column(row)
    return row.get(column, "")


def _format_nested(value: Any, indent: int = 2) -> str:
    rendered = format_yaml(value).rstrip()
    prefix = " " * indent
    return "\n".join(f"{prefix}{line}" for line in rendered.splitlines())


def format_table(rows: Sequence[dict], columns: Sequence[Column], headers: Sequence[str] | None = None) -> str:
    """Format a list of dicts as an aligned table."""
    if not rows:
        return "(no results)"
    table_data = [[_format_cell(_column_value(row, c)) for c in columns] for row in rows]
    display_headers = headers or [
        c if isinstance(c, str) else getattr(c, "__name__", "value")
        for c in columns
    ]
    return tabulate(table_data, headers=display_headers, tablefmt="simple")


def format_json(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def format_yaml(data: Any) -> str:
    return yaml.dump(data, default_flow_style=False, sort_keys=False)


def output(ctx: click.Context, data: Any, columns: Sequence[Column] | None = None,
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
                    click.echo(f"{k}:")
                    click.echo(_format_nested(v))
                else:
                    click.echo(f"{k}: {v}")
        else:
            click.echo(data)


def output_message(msg: str) -> None:
    """Print a status message to stderr (doesn't interfere with piped output)."""
    click.echo(msg, err=True)
