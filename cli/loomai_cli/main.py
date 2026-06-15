"""LoomAI CLI — root command group and global options."""

from __future__ import annotations

import click

from loomai_cli.client import Client


_FORMAT_CHOICE = click.Choice(["table", "json", "yaml"])


def _set_local_format(ctx: click.Context, _param: click.Parameter, value: str | None) -> None:
    """Allow --format at the command level, not only before subcommands."""
    if value:
        ctx.ensure_object(dict)
        ctx.obj["format"] = value


def _has_format_option(command: click.Command) -> bool:
    return any(
        isinstance(param, click.Option) and "--format" in param.opts
        for param in command.params
    )


def _attach_format_options(command: click.Command) -> None:
    """Add --format to all subcommands so placement is natural for users."""
    if command is not cli and not _has_format_option(command):
        command.params.append(click.Option(
            ["--format", "fmt"],
            type=_FORMAT_CHOICE,
            expose_value=False,
            callback=_set_local_format,
            help="Output format.",
        ))

    if isinstance(command, click.Group):
        for subcommand in command.commands.values():
            _attach_format_options(subcommand)


@click.group(invoke_without_command=True)
@click.option("--url", envvar="LOOMAI_URL", default="http://localhost:8000",
              help="LoomAI backend URL (env: LOOMAI_URL).")
@click.option("--format", "fmt", type=_FORMAT_CHOICE,
              default="table", help="Output format.")
@click.pass_context
def cli(ctx: click.Context, url: str, fmt: str) -> None:
    """LoomAI CLI — manage FABRIC testbed slices, resources, and artifacts.

    Run with no command to enter the interactive shell.
    Use `/ask <question>` or `? <question>` for AI assistance.
    Use `/model` to select a model.
    """
    ctx.ensure_object(dict)
    ctx.obj["client"] = Client(url)
    ctx.obj["format"] = fmt

    # No subcommand → enter interactive shell
    if ctx.invoked_subcommand is None:
        from loomai_cli.shell import run_shell
        run_shell(url, fmt)


# Register command groups — Phases 1-2
from loomai_cli.commands.slices import slices  # noqa: E402
from loomai_cli.commands.nodes import nodes  # noqa: E402
from loomai_cli.commands.networks import networks  # noqa: E402
from loomai_cli.commands.components import components  # noqa: E402
from loomai_cli.commands.sites import sites  # noqa: E402
from loomai_cli.commands.resources import images, component_models  # noqa: E402
from loomai_cli.commands.portmirrors import port_mirrors  # noqa: E402

# Phase 3: SSH & exec
from loomai_cli.commands.ssh import ssh, exec_cmd  # noqa: E402

# Phase 4: File transfer
from loomai_cli.commands.files import files_group, scp, rsync  # noqa: E402
from loomai_cli.commands.facilityports import facility_ports  # noqa: E402

# Phase 5: Weaves & boot config
from loomai_cli.commands.weaves import weaves  # noqa: E402
from loomai_cli.commands.bootconfig import boot_config  # noqa: E402

# Phase 6: Artifacts
from loomai_cli.commands.artifacts import artifacts  # noqa: E402

# Phase 7: Recipes, VM templates, monitoring
from loomai_cli.commands.recipes import recipes  # noqa: E402
from loomai_cli.commands.vmtemplates import vm_templates  # noqa: E402
from loomai_cli.commands.monitor import monitor  # noqa: E402

# Phase 8: Config, projects, keys, AI
from loomai_cli.commands.config import config, projects, keys, settings  # noqa: E402
from loomai_cli.commands.ai import ai  # noqa: E402
from loomai_cli.commands.chameleon import chameleon  # noqa: E402
from loomai_cli.commands.composite import composite  # noqa: E402
from loomai_cli.commands.federated import federated  # noqa: E402
from loomai_cli.commands.schedule import schedule  # noqa: E402
from loomai_cli.commands.status import status  # noqa: E402
from loomai_cli.commands.tunnels import tunnels  # noqa: E402
from loomai_cli.commands.jupyter import jupyter, notebooks  # noqa: E402
from loomai_cli.commands.experiments import experiments  # noqa: E402
from loomai_cli.commands.users import users  # noqa: E402
from loomai_cli.commands.trovi import trovi  # noqa: E402

cli.add_command(slices)
cli.add_command(nodes)
cli.add_command(networks)
cli.add_command(components)
cli.add_command(sites)
cli.add_command(images)
cli.add_command(component_models)
cli.add_command(ssh)
cli.add_command(exec_cmd)
cli.add_command(files_group)
cli.add_command(scp)
cli.add_command(rsync)
cli.add_command(facility_ports)
cli.add_command(port_mirrors)
cli.add_command(weaves)
cli.add_command(boot_config)
cli.add_command(artifacts)
cli.add_command(recipes)
cli.add_command(vm_templates)
cli.add_command(monitor)
cli.add_command(config)
cli.add_command(settings)
cli.add_command(projects)
cli.add_command(keys)
cli.add_command(ai)
cli.add_command(chameleon)
composite.hidden = True
cli.add_command(composite)
cli.add_command(federated)
cli.add_command(schedule)
cli.add_command(status)
cli.add_command(tunnels)
cli.add_command(jupyter)
cli.add_command(notebooks)
cli.add_command(experiments)
cli.add_command(users)
cli.add_command(trovi)


# Shell completion helper
@cli.command("completions")
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish"]))
def completions_cmd(shell):
    """Print shell completion activation command.

    Install tab completion for your shell:

      eval "$(loomai completions bash)"

      eval "$(loomai completions zsh)"

      loomai completions fish | source
    """
    prog = "loomai"
    env_var = f"_{prog.upper()}_COMPLETE"
    if shell == "fish":
        click.echo(f"set -x {env_var} fish_source; {prog} | source; set -e {env_var}")
    else:
        click.echo(f'eval "$({env_var}={shell}_source {prog})"')


@cli.command("version")
def version_cmd():
    """Show the LoomAI version."""
    try:
        import importlib.resources as pkg_resources
        version_text = pkg_resources.read_text("loomai_cli", "VERSION") if hasattr(pkg_resources, "read_text") else ""
    except Exception:
        version_text = ""
    if not version_text:
        try:
            import os
            # Try reading from backend/VERSION or the package directory
            here = os.path.dirname(os.path.abspath(__file__))
            for candidate in [
                os.path.join(here, "..", "..", "VERSION"),
                os.path.join(here, "VERSION"),
                "/app/VERSION",
            ]:
                if os.path.isfile(candidate):
                    with open(candidate) as f:
                        version_text = f.read().strip()
                    break
        except Exception:
            pass
    if version_text:
        # Parse version from TypeScript format: export const VERSION = "X.Y.Z-beta";
        import re
        m = re.search(r'"([^"]+)"', version_text)
        click.echo(f"loomai {m.group(1) if m else version_text}")
    else:
        click.echo("loomai (version unknown)")


@cli.command("help")
@click.argument("command", nargs=-1)
@click.pass_context
def help_cmd(ctx, command):
    """Show help for a command or subcommand.

    Examples:

      loomai help

      loomai help slices

      loomai help slices list
    """
    root = ctx.parent
    if not command:
        # Show root help
        click.echo(root.get_help())
        return

    # Walk the command tree
    cmd_obj = cli
    for part in command:
        if isinstance(cmd_obj, click.Group):
            sub = cmd_obj.get_command(ctx, part)
            if sub is None:
                click.echo(f"Unknown command: {' '.join(command)}")
                return
            cmd_obj = sub
        else:
            click.echo(f"'{cmd_obj.name}' is not a group — no subcommand '{part}'")
            return

    # Build a context for the target command and print its help
    with click.Context(cmd_obj, info_name=' '.join(['loomai'] + list(command))) as sub_ctx:
        click.echo(cmd_obj.get_help(sub_ctx))


_attach_format_options(cli)
