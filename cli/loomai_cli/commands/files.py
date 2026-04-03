"""File transfer commands — upload/download to VMs."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import click
from loomai_cli.completions import SLICE

from loomai_cli.client import Client, CliError
from loomai_cli.commands.ssh import _get_node_names
from loomai_cli.output import output_message


def _upload_to_node(client: Client, slice_name: str, node: str, local: str, remote: str) -> dict:
    """Upload a file to a VM node."""
    try:
        with open(local, "r") as f:
            content = f.read()
        client.post(f"/files/vm/{slice_name}/{node}/write-content",
                    json={"path": remote, "content": content})
        return {"node": node, "status": "ok", "error": ""}
    except UnicodeDecodeError:
        # Binary file — use container-to-VM upload (file must be in container)
        try:
            client.post(f"/files/vm/{slice_name}/{node}/upload-direct",
                        json={"source_path": local, "dest_path": remote})
            return {"node": node, "status": "ok", "error": ""}
        except CliError as e:
            return {"node": node, "status": "error", "error": str(e)}
    except CliError as e:
        return {"node": node, "status": "error", "error": str(e)}
    except FileNotFoundError:
        return {"node": node, "status": "error", "error": f"Local file not found: {local}"}


@click.command("scp")
@click.argument("slice_name", type=SLICE)
@click.argument("node_name", required=False)
@click.argument("source")
@click.argument("dest")
@click.option("--download", is_flag=True, help="Download from VM (source=remote, dest=local).")
@click.option("--all", "all_nodes", is_flag=True, help="Transfer to/from all nodes.")
@click.option("--nodes", help="Comma-separated node names.")
@click.option("--parallel", is_flag=True, help="Transfer in parallel.")
@click.pass_context
def scp(ctx, slice_name, node_name, source, dest, download, all_nodes, nodes, parallel):
    """Copy files to/from VMs.

    Examples:

      loomai scp my-slice node1 ./setup.sh /tmp/setup.sh

      loomai scp my-slice node1 --download /tmp/results.csv ./results.csv

      loomai scp my-slice ./config.sh /tmp/config.sh --all --parallel
    """
    client = ctx.obj["client"]

    if all_nodes or nodes:
        # Multi-node transfer
        node_list = [n.strip() for n in nodes.split(",")] if nodes else _get_node_names(client, slice_name)
        if not node_list:
            raise CliError(f"No nodes found in slice '{slice_name}'")

        if download:
            raise CliError("--download with --all/--nodes is not supported (files would overwrite each other)")

        output_message(f"Uploading to {len(node_list)} node(s)...")

        if parallel and len(node_list) > 1:
            with ThreadPoolExecutor(max_workers=min(len(node_list), 10)) as pool:
                futures = {pool.submit(_upload_to_node, client, slice_name, n, source, dest): n for n in node_list}
                results = [f.result() for f in as_completed(futures)]
        else:
            results = [_upload_to_node(client, slice_name, n, source, dest) for n in node_list]

        for r in sorted(results, key=lambda x: x["node"]):
            if r["error"]:
                click.echo(f"  {r['node']}: ERROR — {r['error']}", err=True)
            else:
                click.echo(f"  {r['node']}: ok")
    else:
        # Single node transfer
        if not node_name:
            raise click.UsageError("Specify NODE_NAME or use --all/--nodes")

        if download:
            output_message(f"Downloading {source} from {node_name}...")
            resp = client._http.get(f"/files/vm/{slice_name}/{node_name}/download-direct",
                                     params={"path": source})
            if resp.status_code >= 400:
                raise CliError(f"Download failed: {resp.text}")
            with open(dest, "wb") as f:
                f.write(resp.content)
            output_message(f"Downloaded to {dest} ({len(resp.content)} bytes)")
        else:
            output_message(f"Uploading {source} to {node_name}:{dest}...")
            result = _upload_to_node(client, slice_name, node_name, source, dest)
            if result["error"]:
                raise CliError(result["error"])
            output_message("Upload complete")


def _rsync_to_node(client: Client, slice_name: str, node: str,
                   source: str, dest: str) -> dict:
    """Upload a directory tree to a VM node."""
    uploaded = 0
    errors = []
    src = Path(source)
    for path in src.rglob("*"):
        if path.is_dir():
            continue
        rel = path.relative_to(src)
        remote_path = f"{dest.rstrip('/')}/{rel}"
        result = _upload_to_node(client, slice_name, node, str(path), remote_path)
        if result["error"]:
            errors.append(f"{rel}: {result['error']}")
        else:
            uploaded += 1
    return {"node": node, "uploaded": uploaded, "errors": errors}


@click.command("rsync")
@click.argument("slice_name", type=SLICE)
@click.argument("node_name", required=False)
@click.argument("source", type=click.Path(exists=True))
@click.argument("dest")
@click.option("--all", "all_nodes", is_flag=True, help="Sync to all nodes.")
@click.option("--nodes", help="Comma-separated node names.")
@click.option("--parallel", is_flag=True, help="Sync in parallel.")
@click.pass_context
def rsync(ctx, slice_name, node_name, source, dest, all_nodes, nodes, parallel):
    """Sync a local directory to VMs.

    Recursively uploads all files from SOURCE to DEST on the target VM(s).

    Examples:

      loomai rsync my-slice node1 ./project /home/ubuntu/project

      loomai rsync my-slice ./config /tmp/config --all --parallel
    """
    client = ctx.obj["client"]

    if all_nodes or nodes:
        node_list = ([n.strip() for n in nodes.split(",")]
                     if nodes else _get_node_names(client, slice_name))
        if not node_list:
            raise CliError(f"No nodes found in slice '{slice_name}'")

        output_message(f"Syncing to {len(node_list)} node(s)...")
        if parallel and len(node_list) > 1:
            with ThreadPoolExecutor(max_workers=min(len(node_list), 10)) as pool:
                futures = {pool.submit(_rsync_to_node, client, slice_name, n,
                                       source, dest): n for n in node_list}
                results = [f.result() for f in as_completed(futures)]
        else:
            results = [_rsync_to_node(client, slice_name, n, source, dest)
                       for n in node_list]

        for r in sorted(results, key=lambda x: x["node"]):
            errs = r["errors"]
            if errs:
                click.echo(f"  {r['node']}: {r['uploaded']} files, {len(errs)} error(s)",
                           err=True)
                for e in errs:
                    click.echo(f"    {e}", err=True)
            else:
                click.echo(f"  {r['node']}: {r['uploaded']} files synced")
    else:
        if not node_name:
            raise click.UsageError("Specify NODE_NAME or use --all/--nodes")

        output_message(f"Syncing {source} to {node_name}:{dest}...")
        result = _rsync_to_node(client, slice_name, node_name, source, dest)
        if result["errors"]:
            for e in result["errors"]:
                click.echo(f"  ERROR: {e}", err=True)
        output_message(f"Synced {result['uploaded']} file(s)")
