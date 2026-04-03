"""SSH and remote execution commands."""

from __future__ import annotations

import sys
from loomai_cli.completions import SLICE, NODE
from concurrent.futures import ThreadPoolExecutor, as_completed

import click

from loomai_cli.client import Client, CliError
from loomai_cli.output import output, output_message


def _get_node_names(client: Client, slice_name: str) -> list[str]:
    """Get all node names from a slice."""
    data = client.get(f"/slices/{slice_name}")
    return [n["name"] for n in data.get("nodes", [])]


def _exec_on_node(client: Client, slice_name: str, node_name: str, command: str) -> dict:
    """Execute a command on a single node, return result dict."""
    try:
        resp = client.post(
            f"/files/vm/{slice_name}/{node_name}/execute",
            json={"command": command},
        )
        return {"node": node_name, "stdout": resp.get("stdout", ""), "stderr": resp.get("stderr", ""), "error": ""}
    except CliError as e:
        return {"node": node_name, "stdout": "", "stderr": "", "error": str(e)}


@click.command("ssh")
@click.argument("slice_name", type=SLICE)
@click.argument("node_name", type=NODE)
@click.argument("command", nargs=-1)
@click.pass_context
def ssh(ctx, slice_name, node_name, command):
    """Execute a command on a VM via SSH.

    If COMMAND is provided, runs it and prints output. Without a command,
    prints the SSH connection info (interactive SSH requires the web terminal).

    Examples:

      loomai ssh my-slice node1 -- hostname

      loomai ssh my-slice node1 -- "cat /etc/os-release"

      loomai ssh my-slice node1   # Show SSH connection info
    """
    client = ctx.obj["client"]
    if command:
        cmd_str = " ".join(command)
        result = _exec_on_node(client, slice_name, node_name, cmd_str)
        if result["error"]:
            raise CliError(f"[{node_name}] {result['error']}")
        if result["stdout"]:
            click.echo(result["stdout"], nl=False)
        if result["stderr"]:
            click.echo(result["stderr"], err=True, nl=False)
    else:
        # No command — show slice info for this node
        data = client.get(f"/slices/{slice_name}")
        for node in data.get("nodes", []):
            if node["name"] == node_name:
                ip = node.get("management_ip", "")
                user = node.get("username", "ubuntu")
                click.echo(f"Node: {node_name}")
                click.echo(f"IP:   {ip}")
                click.echo(f"User: {user}")
                click.echo(f"SSH:  ssh {user}@{ip}")
                return
        raise CliError(f"Node '{node_name}' not found in slice '{slice_name}'")


@click.command("exec")
@click.argument("slice_name", type=SLICE)
@click.argument("command")
@click.option("--nodes", help="Comma-separated node names (default: all).")
@click.option("--all", "all_nodes", is_flag=True, help="Run on all nodes.")
@click.option("--parallel", is_flag=True, help="Run on nodes in parallel (default: serial).")
@click.pass_context
def exec_cmd(ctx, slice_name, command, nodes, all_nodes, parallel):
    """Execute a command on one or more VMs.

    Examples:

      loomai exec my-slice "hostname" --all

      loomai exec my-slice "apt update" --all --parallel

      loomai exec my-slice "df -h" --nodes node1,node2
    """
    client = ctx.obj["client"]

    if nodes:
        node_list = [n.strip() for n in nodes.split(",")]
    elif all_nodes:
        node_list = _get_node_names(client, slice_name)
        if not node_list:
            raise CliError(f"No nodes found in slice '{slice_name}'")
    else:
        raise click.UsageError("Specify --nodes or --all")

    output_message(f"Running on {len(node_list)} node(s): {', '.join(node_list)}")

    if parallel and len(node_list) > 1:
        results = []
        with ThreadPoolExecutor(max_workers=min(len(node_list), 10)) as pool:
            futures = {
                pool.submit(_exec_on_node, client, slice_name, n, command): n
                for n in node_list
            }
            for future in as_completed(futures):
                results.append(future.result())
    else:
        results = [_exec_on_node(client, slice_name, n, command) for n in node_list]

    # Print results
    has_errors = False
    for r in sorted(results, key=lambda x: x["node"]):
        click.echo(f"--- {r['node']} ---")
        if r["error"]:
            click.echo(f"ERROR: {r['error']}", err=True)
            has_errors = True
        else:
            if r["stdout"]:
                click.echo(r["stdout"], nl=False)
            if r["stderr"]:
                click.echo(r["stderr"], err=True, nl=False)

    if has_errors:
        sys.exit(1)
