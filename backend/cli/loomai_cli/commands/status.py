"""Health/status commands."""

from __future__ import annotations

import click

from loomai_cli.output import output


@click.command("status")
@click.pass_context
def status(ctx):
    """Show LoomAI backend and subsystem health.

    Examples:

      loomai status

      loomai status --format json
    """
    client = ctx.obj["client"]
    data = client.get("/health/detailed")

    if ctx.obj["format"] != "table":
        output(ctx, data)
        return

    click.echo(f"Status: {data.get('status', '?')}")
    checks = data.get("checks", {})
    if checks:
        rows = []
        for name, check in checks.items():
            if isinstance(check, dict):
                rows.append({
                    "name": name,
                    "ok": check.get("ok", ""),
                    "detail": check.get("error") or check.get("status") or check.get("message") or "",
                })
            else:
                rows.append({"name": name, "ok": bool(check), "detail": ""})
        output(ctx, rows, columns=["name", "ok", "detail"], headers=["Check", "OK", "Detail"])
