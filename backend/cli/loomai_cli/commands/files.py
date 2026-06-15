"""File transfer commands — upload/download to VMs."""

from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import click
from loomai_cli.completions import SLICE

from loomai_cli.client import Client, CliError
from loomai_cli.commands.ssh import _get_node_names
from loomai_cli.output import output, output_message


def _read_text_arg(content: str | None, file_path: str | None) -> str:
    if content is not None and file_path:
        raise click.UsageError("Use either --content or --file, not both.")
    if file_path:
        if file_path == "-":
            return sys.stdin.read()
        with open(file_path) as f:
            return f.read()
    if content is not None:
        return content
    raise click.UsageError("Provide --content, --file PATH, or --file -.")


def _raise_for_raw_response(resp, action: str) -> None:
    if resp.status_code < 400:
        return
    try:
        detail = resp.json().get("detail", resp.text)
    except Exception:
        detail = resp.text
    raise CliError(f"{action} failed: {detail}", resp.status_code)


def _filename_from_response(resp, fallback: str) -> str:
    header = resp.headers.get("content-disposition", "")
    marker = 'filename="'
    if marker in header:
        return header.split(marker, 1)[1].split('"', 1)[0]
    return os.path.basename(fallback.rstrip("/")) or "download"


def _save_raw_response(resp, dest: str, fallback_name: str) -> str:
    if os.path.isdir(dest):
        path = os.path.join(dest, _filename_from_response(resp, fallback_name))
    else:
        path = dest
    with open(path, "wb") as f:
        f.write(resp.content)
    return path


@click.group("files")
def files_group():
    """Browse storage and operate on FABRIC VM or Chameleon instance files."""


@files_group.command("list")
@click.argument("path", required=False, default="")
@click.pass_context
def list_storage_files(ctx, path):
    """List container storage files."""
    data = ctx.obj["client"].get("/files", params={"path": path})
    output(ctx, data,
           columns=["name", "type", "size", "modified"],
           headers=["Name", "Type", "Size", "Modified"])


@files_group.command("read")
@click.argument("path")
@click.pass_context
def read_storage_file(ctx, path):
    """Read a text file from container storage."""
    data = ctx.obj["client"].get("/files/content", params={"path": path})
    if ctx.obj["format"] == "table":
        click.echo(data.get("content", ""))
        return
    output(ctx, data)


@files_group.command("write")
@click.argument("path")
@click.option("--content", help="Text content to write.")
@click.option("--file", "file_path", type=click.Path(),
              help="Read content from a file, or '-' for stdin.")
@click.pass_context
def write_storage_file(ctx, path, content, file_path):
    """Write a text file in container storage."""
    data = ctx.obj["client"].put("/files/content", json={
        "path": path,
        "content": _read_text_arg(content, file_path),
    })
    if ctx.obj["format"] == "table":
        output_message(f"Wrote {path}")
    output(ctx, data)


@files_group.command("mkdir")
@click.argument("path")
@click.pass_context
def mkdir_storage(ctx, path):
    """Create a directory in container storage."""
    parent = os.path.dirname(path)
    name = os.path.basename(path.rstrip("/"))
    data = ctx.obj["client"].post("/files/mkdir", params={"path": parent}, json={"name": name})
    if ctx.obj["format"] == "table":
        output_message(f"Created directory {path}")
    output(ctx, data)


@files_group.command("delete")
@click.argument("path")
@click.option("--force", is_flag=True, help="Skip confirmation.")
@click.pass_context
def delete_storage_path(ctx, path, force):
    """Delete a file or directory from container storage."""
    if not force:
        click.confirm(f"Delete storage path '{path}'?", abort=True)
    data = ctx.obj["client"].delete("/files", params={"path": path})
    if ctx.obj["format"] == "table":
        output_message(f"Deleted {path}")
    output(ctx, data)


@files_group.command("upload")
@click.argument("dest_dir")
@click.argument("local_files", nargs=-1, type=click.Path(exists=True, dir_okay=False))
@click.pass_context
def upload_storage_files(ctx, dest_dir, local_files):
    """Upload one or more local files into container storage."""
    if not local_files:
        raise click.UsageError("Specify at least one local file.")
    opened = []
    try:
        multipart = []
        for path in local_files:
            fh = open(path, "rb")
            opened.append(fh)
            multipart.append(("files", (os.path.basename(path), fh)))
        resp = ctx.obj["client"]._http.post(
            "/files/upload",
            params={"path": dest_dir},
            files=multipart,
        )
        _raise_for_raw_response(resp, "Upload")
        data = resp.json()
    finally:
        for fh in opened:
            fh.close()
    if ctx.obj["format"] == "table":
        output_message(f"Uploaded {len(local_files)} file(s) to {dest_dir}")
    output(ctx, data)


@files_group.command("download")
@click.argument("storage_path")
@click.argument("dest", type=click.Path(), default=".", required=False)
@click.pass_context
def download_storage_file(ctx, storage_path, dest):
    """Download a container-storage file to a local path or directory."""
    resp = ctx.obj["client"]._http.get("/files/download", params={"path": storage_path})
    _raise_for_raw_response(resp, "Download")
    saved = _save_raw_response(resp, dest, storage_path)
    data = {"status": "downloaded", "source": storage_path, "path": saved, "bytes": len(resp.content)}
    if ctx.obj["format"] == "table":
        output_message(f"Downloaded {storage_path} to {saved}")
    output(ctx, data)


@files_group.command("download-folder")
@click.argument("storage_path")
@click.argument("dest", type=click.Path(), default=".", required=False)
@click.pass_context
def download_storage_folder(ctx, storage_path, dest):
    """Download a container-storage directory as a zip archive."""
    resp = ctx.obj["client"]._http.get("/files/download-folder", params={"path": storage_path})
    _raise_for_raw_response(resp, "Folder download")
    saved = _save_raw_response(resp, dest, f"{storage_path.rstrip('/')}.zip")
    data = {"status": "downloaded", "source": storage_path, "path": saved, "bytes": len(resp.content)}
    if ctx.obj["format"] == "table":
        output_message(f"Downloaded {storage_path} to {saved}")
    output(ctx, data)


@files_group.group("vm")
def vm_files():
    """Operate on files in FABRIC VMs."""


@vm_files.command("list")
@click.argument("slice_name", type=SLICE)
@click.argument("node_name")
@click.option("--path", default="/home", help="Remote directory path.")
@click.pass_context
def list_vm_files_cmd(ctx, slice_name, node_name, path):
    """List files on a FABRIC VM."""
    data = ctx.obj["client"].get(f"/files/vm/{slice_name}/{node_name}", params={"path": path})
    output(ctx, data,
           columns=["name", "type", "size", "modified"],
           headers=["Name", "Type", "Size", "Modified"])


@vm_files.command("read")
@click.argument("slice_name", type=SLICE)
@click.argument("node_name")
@click.argument("remote_path")
@click.pass_context
def read_vm_file_cmd(ctx, slice_name, node_name, remote_path):
    """Read a text file from a FABRIC VM."""
    data = ctx.obj["client"].post(
        f"/files/vm/{slice_name}/{node_name}/read-content",
        json={"path": remote_path},
    )
    if ctx.obj["format"] == "table":
        click.echo(data.get("content", ""))
        return
    output(ctx, data)


@vm_files.command("write")
@click.argument("slice_name", type=SLICE)
@click.argument("node_name")
@click.argument("remote_path")
@click.option("--content", help="Text content to write.")
@click.option("--file", "file_path", type=click.Path(),
              help="Read content from a file, or '-' for stdin.")
@click.pass_context
def write_vm_file_cmd(ctx, slice_name, node_name, remote_path, content, file_path):
    """Write a text file on a FABRIC VM."""
    data = ctx.obj["client"].post(
        f"/files/vm/{slice_name}/{node_name}/write-content",
        json={"path": remote_path, "content": _read_text_arg(content, file_path)},
    )
    if ctx.obj["format"] == "table":
        output_message(f"Wrote {remote_path} on {node_name}")
    output(ctx, data)


@vm_files.command("mkdir")
@click.argument("slice_name", type=SLICE)
@click.argument("node_name")
@click.argument("remote_path")
@click.pass_context
def mkdir_vm_cmd(ctx, slice_name, node_name, remote_path):
    """Create a directory on a FABRIC VM."""
    data = ctx.obj["client"].post(
        f"/files/vm/{slice_name}/{node_name}/mkdir",
        json={"path": remote_path},
    )
    if ctx.obj["format"] == "table":
        output_message(f"Created {remote_path} on {node_name}")
    output(ctx, data)


@vm_files.command("delete")
@click.argument("slice_name", type=SLICE)
@click.argument("node_name")
@click.argument("remote_path")
@click.option("--force", is_flag=True, help="Skip confirmation.")
@click.pass_context
def delete_vm_cmd(ctx, slice_name, node_name, remote_path, force):
    """Delete a file or directory on a FABRIC VM."""
    if not force:
        click.confirm(f"Delete '{remote_path}' on {slice_name}/{node_name}?", abort=True)
    data = ctx.obj["client"].post(
        f"/files/vm/{slice_name}/{node_name}/delete",
        json={"path": remote_path},
    )
    if ctx.obj["format"] == "table":
        output_message(f"Deleted {remote_path} on {node_name}")
    output(ctx, data)


@vm_files.command("upload")
@click.argument("slice_name", type=SLICE)
@click.argument("node_name")
@click.argument("source")
@click.argument("dest")
@click.pass_context
def upload_vm_cmd(ctx, slice_name, node_name, source, dest):
    """Upload a file or directory from container storage to a FABRIC VM."""
    data = ctx.obj["client"].post(
        f"/files/vm/{slice_name}/{node_name}/upload",
        json={"source": source, "dest": dest},
    )
    if ctx.obj["format"] == "table":
        output_message(f"Uploaded {source} to {node_name}:{dest}")
    output(ctx, data)


@vm_files.command("download")
@click.argument("slice_name", type=SLICE)
@click.argument("node_name")
@click.argument("remote_path")
@click.option("--dest-dir", default="", help="Container storage directory to save into.")
@click.pass_context
def download_vm_cmd(ctx, slice_name, node_name, remote_path, dest_dir):
    """Download a FABRIC VM file into container storage."""
    data = ctx.obj["client"].post(
        f"/files/vm/{slice_name}/{node_name}/download",
        json={"remote_path": remote_path, "dest_dir": dest_dir},
    )
    if ctx.obj["format"] == "table":
        output_message(f"Downloaded {remote_path} from {node_name}")
    output(ctx, data)


@vm_files.command("download-direct")
@click.argument("slice_name", type=SLICE)
@click.argument("node_name")
@click.argument("remote_path")
@click.argument("dest", type=click.Path(), default=".", required=False)
@click.pass_context
def download_vm_direct_cmd(ctx, slice_name, node_name, remote_path, dest):
    """Download a FABRIC VM file to a local path or directory."""
    resp = ctx.obj["client"]._http.get(
        f"/files/vm/{slice_name}/{node_name}/download-direct",
        params={"remote_path": remote_path},
    )
    _raise_for_raw_response(resp, "VM download")
    saved = _save_raw_response(resp, dest, remote_path)
    data = {"status": "downloaded", "source": remote_path, "path": saved, "bytes": len(resp.content)}
    if ctx.obj["format"] == "table":
        output_message(f"Downloaded {remote_path} to {saved}")
    output(ctx, data)


@vm_files.command("execute")
@click.argument("slice_name", type=SLICE)
@click.argument("node_name")
@click.argument("command")
@click.option("--timeout", default=None, type=int, help="Timeout in seconds.")
@click.pass_context
def execute_vm_cmd(ctx, slice_name, node_name, command, timeout):
    """Execute an ad-hoc command on a FABRIC VM."""
    body = {"command": command}
    if timeout is not None:
        body["timeout"] = timeout
    data = ctx.obj["client"].post(f"/files/vm/{slice_name}/{node_name}/execute", json=body)
    if ctx.obj["format"] == "table":
        click.echo(data.get("stdout", ""), nl=False)
        if data.get("stderr"):
            click.echo(data["stderr"], err=True, nl=False)
        return
    output(ctx, data)


@vm_files.command("reboot")
@click.argument("slice_name", type=SLICE)
@click.argument("node_name")
@click.option("--timeout", default=300, type=int, help="Wait timeout in seconds.")
@click.option("--force", is_flag=True, help="Skip confirmation.")
@click.pass_context
def reboot_vm_cmd(ctx, slice_name, node_name, timeout, force):
    """Reboot a FABRIC VM and wait for SSH to return."""
    if not force:
        click.confirm(f"Reboot VM '{slice_name}/{node_name}'?", abort=True)
    data = ctx.obj["client"].post(
        f"/files/vm/{slice_name}/{node_name}/reboot",
        json={"timeout": timeout},
    )
    output(ctx, data)


@files_group.group("chameleon")
def chameleon_files():
    """Operate on files in Chameleon instances."""


@chameleon_files.command("list")
@click.argument("instance_id")
@click.option("--site", required=True, help="Chameleon site, e.g. CHI@TACC.")
@click.option("--path", default="/home", help="Remote directory path.")
@click.pass_context
def list_chameleon_files_cmd(ctx, instance_id, site, path):
    """List files on a Chameleon instance."""
    data = ctx.obj["client"].get(
        f"/files/chameleon/{instance_id}",
        params={"site": site, "path": path},
    )
    output(ctx, data,
           columns=["name", "type", "size", "modified"],
           headers=["Name", "Type", "Size", "Modified"])


@chameleon_files.command("read")
@click.argument("instance_id")
@click.argument("remote_path")
@click.option("--site", required=True, help="Chameleon site, e.g. CHI@TACC.")
@click.pass_context
def read_chameleon_file_cmd(ctx, instance_id, remote_path, site):
    """Read a text file from a Chameleon instance."""
    data = ctx.obj["client"].post(
        f"/files/chameleon/{instance_id}/read-content",
        params={"site": site},
        json={"path": remote_path},
    )
    if ctx.obj["format"] == "table":
        click.echo(data.get("content", ""))
        return
    output(ctx, data)


@chameleon_files.command("write")
@click.argument("instance_id")
@click.argument("remote_path")
@click.option("--site", required=True, help="Chameleon site, e.g. CHI@TACC.")
@click.option("--content", help="Text content to write.")
@click.option("--file", "file_path", type=click.Path(),
              help="Read content from a file, or '-' for stdin.")
@click.pass_context
def write_chameleon_file_cmd(ctx, instance_id, remote_path, site, content, file_path):
    """Write a text file on a Chameleon instance."""
    data = ctx.obj["client"].post(
        f"/files/chameleon/{instance_id}/write-content",
        params={"site": site},
        json={"path": remote_path, "content": _read_text_arg(content, file_path)},
    )
    if ctx.obj["format"] == "table":
        output_message(f"Wrote {remote_path} on {instance_id}")
    output(ctx, data)


@chameleon_files.command("mkdir")
@click.argument("instance_id")
@click.argument("remote_path")
@click.option("--site", required=True, help="Chameleon site, e.g. CHI@TACC.")
@click.pass_context
def mkdir_chameleon_cmd(ctx, instance_id, remote_path, site):
    """Create a directory on a Chameleon instance."""
    data = ctx.obj["client"].post(
        f"/files/chameleon/{instance_id}/mkdir",
        params={"site": site},
        json={"path": remote_path},
    )
    if ctx.obj["format"] == "table":
        output_message(f"Created {remote_path} on {instance_id}")
    output(ctx, data)


@chameleon_files.command("delete")
@click.argument("instance_id")
@click.argument("remote_path")
@click.option("--site", required=True, help="Chameleon site, e.g. CHI@TACC.")
@click.option("--force", is_flag=True, help="Skip confirmation.")
@click.pass_context
def delete_chameleon_cmd(ctx, instance_id, remote_path, site, force):
    """Delete a file or directory on a Chameleon instance."""
    if not force:
        click.confirm(f"Delete '{remote_path}' on Chameleon instance {instance_id}?", abort=True)
    data = ctx.obj["client"].post(
        f"/files/chameleon/{instance_id}/delete",
        params={"site": site},
        json={"path": remote_path},
    )
    if ctx.obj["format"] == "table":
        output_message(f"Deleted {remote_path} on {instance_id}")
    output(ctx, data)


@chameleon_files.command("upload")
@click.argument("instance_id")
@click.argument("dest_path")
@click.argument("local_files", nargs=-1, type=click.Path(exists=True, dir_okay=False))
@click.option("--site", required=True, help="Chameleon site, e.g. CHI@TACC.")
@click.pass_context
def upload_chameleon_cmd(ctx, instance_id, dest_path, local_files, site):
    """Upload local files directly to a Chameleon instance."""
    if not local_files:
        raise click.UsageError("Specify at least one local file.")
    opened = []
    try:
        multipart = []
        for path in local_files:
            fh = open(path, "rb")
            opened.append(fh)
            multipart.append(("files", (os.path.basename(path), fh)))
        resp = ctx.obj["client"]._http.post(
            f"/files/chameleon/{instance_id}/upload-direct",
            params={"site": site, "dest_path": dest_path},
            files=multipart,
        )
        _raise_for_raw_response(resp, "Chameleon upload")
        data = resp.json()
    finally:
        for fh in opened:
            fh.close()
    if ctx.obj["format"] == "table":
        output_message(f"Uploaded {len(local_files)} file(s) to {instance_id}:{dest_path}")
    output(ctx, data)


@chameleon_files.command("download")
@click.argument("instance_id")
@click.argument("remote_path")
@click.argument("dest", type=click.Path(), default=".", required=False)
@click.option("--site", required=True, help="Chameleon site, e.g. CHI@TACC.")
@click.pass_context
def download_chameleon_cmd(ctx, instance_id, remote_path, dest, site):
    """Download a Chameleon instance file to a local path or directory."""
    resp = ctx.obj["client"]._http.get(
        f"/files/chameleon/{instance_id}/download-direct",
        params={"site": site, "remote_path": remote_path},
    )
    _raise_for_raw_response(resp, "Chameleon download")
    saved = _save_raw_response(resp, dest, remote_path)
    data = {"status": "downloaded", "source": remote_path, "path": saved, "bytes": len(resp.content)}
    if ctx.obj["format"] == "table":
        output_message(f"Downloaded {remote_path} to {saved}")
    output(ctx, data)


@chameleon_files.command("download-folder")
@click.argument("instance_id")
@click.argument("remote_path")
@click.argument("dest", type=click.Path(), default=".", required=False)
@click.option("--site", required=True, help="Chameleon site, e.g. CHI@TACC.")
@click.pass_context
def download_chameleon_folder_cmd(ctx, instance_id, remote_path, dest, site):
    """Download a Chameleon instance directory as a tar.gz archive."""
    resp = ctx.obj["client"]._http.get(
        f"/files/chameleon/{instance_id}/download-folder",
        params={"site": site, "remote_path": remote_path},
    )
    _raise_for_raw_response(resp, "Chameleon folder download")
    saved = _save_raw_response(resp, dest, f"{remote_path.rstrip('/')}.tar.gz")
    data = {"status": "downloaded", "source": remote_path, "path": saved, "bytes": len(resp.content)}
    if ctx.obj["format"] == "table":
        output_message(f"Downloaded {remote_path} to {saved}")
    output(ctx, data)


@chameleon_files.command("execute")
@click.argument("instance_id")
@click.argument("command")
@click.option("--site", required=True, help="Chameleon site, e.g. CHI@TACC.")
@click.pass_context
def execute_chameleon_cmd(ctx, instance_id, command, site):
    """Execute an ad-hoc command on a Chameleon instance."""
    data = ctx.obj["client"].post(
        f"/files/chameleon/{instance_id}/execute",
        params={"site": site},
        json={"command": command},
    )
    if ctx.obj["format"] == "table":
        click.echo(data.get("stdout", ""), nl=False)
        if data.get("stderr"):
            click.echo(data["stderr"], err=True, nl=False)
        return
    output(ctx, data)


@files_group.group("provisions")
def provisions():
    """Manage storage-to-VM provisioning rules."""


@provisions.command("list")
@click.argument("slice_name", type=SLICE)
@click.pass_context
def list_provisions_cmd(ctx, slice_name):
    """List provisioning rules for a slice."""
    data = ctx.obj["client"].get(f"/files/provisions/{slice_name}")
    output(ctx, data,
           columns=["id", "source", "node_name", "dest"],
           headers=["ID", "Source", "Node", "Destination"])


@provisions.command("add")
@click.argument("source")
@click.argument("slice_name", type=SLICE)
@click.argument("node_name")
@click.argument("dest")
@click.pass_context
def add_provision_cmd(ctx, source, slice_name, node_name, dest):
    """Add a provisioning rule from storage to a VM."""
    data = ctx.obj["client"].post("/files/provisions", json={
        "source": source,
        "slice_name": slice_name,
        "node_name": node_name,
        "dest": dest,
    })
    if ctx.obj["format"] == "table":
        output_message(f"Added provision rule for {slice_name}/{node_name}")
    output(ctx, data)


@provisions.command("delete")
@click.argument("slice_name", type=SLICE)
@click.argument("rule_id")
@click.pass_context
def delete_provision_cmd(ctx, slice_name, rule_id):
    """Delete a provisioning rule."""
    data = ctx.obj["client"].delete(f"/files/provisions/{slice_name}/{rule_id}")
    if ctx.obj["format"] == "table":
        output_message(f"Deleted provision rule {rule_id}")
    output(ctx, data)


@provisions.command("execute")
@click.argument("slice_name", type=SLICE)
@click.option("--node", "node_name", help="Only execute rules for one node.")
@click.pass_context
def execute_provisions_cmd(ctx, slice_name, node_name):
    """Execute provisioning rules for a slice."""
    params = {"node_name": node_name} if node_name else {}
    data = ctx.obj["client"].post(f"/files/provisions/{slice_name}/execute", params=params)
    output(ctx, data,
           columns=["id", "status", "detail"],
           headers=["ID", "Status", "Detail"])


@files_group.group("boot")
def boot_files():
    """Inspect boot-config execution status and logs."""


@boot_files.command("running")
@click.pass_context
def boot_running_cmd(ctx):
    """List slices with boot config currently running."""
    data = ctx.obj["client"].get("/files/boot-config/running")
    output(ctx, data)


@boot_files.command("log")
@click.argument("slice_name", type=SLICE)
@click.pass_context
def boot_log_cmd(ctx, slice_name):
    """Show stored boot config log events for a slice."""
    data = ctx.obj["client"].get(f"/files/boot-config/{slice_name}/log")
    if ctx.obj["format"] == "table":
        for item in data.get("lines", []):
            if isinstance(item, dict):
                click.echo(item.get("message") or item)
            else:
                click.echo(item)
        return
    output(ctx, data)


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
            remote_dir = os.path.dirname(remote) or "/home"
            remote_name = os.path.basename(remote) or os.path.basename(local)
            with open(local, "rb") as f:
                resp = client._http.post(
                    f"/files/vm/{slice_name}/{node}/upload-direct",
                    params={"dest_path": remote_dir},
                    files=[("files", (remote_name, f))],
                )
            _raise_for_raw_response(resp, "Upload")
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
                                     params={"remote_path": source})
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
