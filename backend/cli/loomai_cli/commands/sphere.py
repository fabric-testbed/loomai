"""SPHERE / MergeTB commands — projects, experiments, realizations, materializations."""

from __future__ import annotations

import os

import click

from loomai_cli.output import output, output_message


def _is_table(ctx: click.Context) -> bool:
    return ctx.obj["format"] == "table"


def _table_message(ctx: click.Context, message: str) -> None:
    if _is_table(ctx):
        output_message(message)


@click.group()
@click.pass_context
def sphere(ctx):
    """Manage SPHERE (MergeTB) experiments, realizations, and materializations.

    Requires SPHERE integration to be enabled in Settings.
    """
    client = ctx.obj["client"]
    try:
        status = client.get("/sphere/status")
        if isinstance(status, dict) and status.get("enabled") is False:
            if ctx.invoked_subcommand == "status":
                return
            raise click.ClickException(
                "SPHERE integration is disabled. Enable it in Settings.")
    except click.ClickException:
        raise
    except Exception:
        pass  # Let individual commands handle errors


@sphere.command("status")
@click.pass_context
def status_cmd(ctx):
    """Show SPHERE integration status."""
    output(ctx, ctx.obj["client"].get("/sphere/status"))


@sphere.command("projects")
@click.pass_context
def projects_cmd(ctx):
    """List configured SPHERE projects.

    Examples:

      loomai sphere projects
    """
    data = ctx.obj["client"].get("/sphere/projects")
    output(ctx, [{"project": p} for p in data] if isinstance(data, list) else data,
           columns=["project"], headers=["Project"])


@sphere.command("experiments")
@click.option("--project", help="SPHERE project (defaults to configured default).")
@click.pass_context
def experiments_cmd(ctx, project):
    """List experiments in the project.

    Examples:

      loomai sphere experiments
    """
    params = {"project": project} if project else {}
    data = ctx.obj["client"].get("/sphere/experiments", params=params)
    rows = data if isinstance(data, list) else []
    output(ctx, rows, columns=["name", "description", "creator"],
           headers=["Experiment", "Description", "Creator"])


@sphere.command("create-experiment")
@click.argument("name")
@click.option("--description", default="", help="Experiment description.")
@click.option("--project", help="SPHERE project (defaults to configured default).")
@click.pass_context
def create_experiment_cmd(ctx, name, description, project):
    """Create an experiment.

    Names must match ^[a-z][a-z0-9]{0,62}$ (lowercase letter first, then
    lowercase letters/digits — no hyphens, underscores, spaces, or uppercase).

    Examples:

      loomai sphere create-experiment hello
    """
    body = {"experiment": name, "description": description}
    if project:
        body["project"] = project
    result = ctx.obj["client"].post("/sphere/experiments", json=body)
    _table_message(ctx, f"Experiment created: {name}")
    output(ctx, result)


@sphere.command("delete-experiment")
@click.argument("name")
@click.option("--project", help="SPHERE project (defaults to configured default).")
@click.pass_context
def delete_experiment_cmd(ctx, name, project):
    """Delete an experiment."""
    params = {"project": project} if project else {}
    result = ctx.obj["client"].delete(f"/sphere/experiments/{name}", params=params)
    _table_message(ctx, f"Experiment deleted: {name}")
    output(ctx, result)


@sphere.command("compile-model")
@click.argument("model_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--project", help="SPHERE project (defaults to configured default).")
@click.pass_context
def compile_model_cmd(ctx, model_file, project):
    """Compile (validate) a mergexp model file without pushing it.

    Examples:

      loomai sphere compile-model model.py
    """
    with open(model_file) as fh:
        model = fh.read()
    body = {"model": model}
    if project:
        body["project"] = project
    result = ctx.obj["client"].post("/sphere/models/compile", json=body)
    output(ctx, result)


@sphere.command("push-model")
@click.argument("experiment")
@click.argument("model_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--tag", help="Tag this model revision (e.g. v1).")
@click.option("--branch", help="Push to a branch.")
@click.option("--project", help="SPHERE project (defaults to configured default).")
@click.pass_context
def push_model_cmd(ctx, experiment, model_file, tag, branch, project):
    """Push a mergexp model file to an experiment.

    Examples:

      loomai sphere push-model hello model.py --tag v1
    """
    with open(model_file) as fh:
        model = fh.read()
    body = {"model": model, "experiment": experiment}
    for k, v in (("tag", tag), ("branch", branch), ("project", project)):
        if v:
            body[k] = v
    result = ctx.obj["client"].post("/sphere/models", json=body)
    _table_message(ctx, f"Model pushed to {experiment}"
                   + (f" (tag {tag})" if tag else ""))
    output(ctx, result)


@sphere.command("realizations")
@click.option("--project", help="SPHERE project (defaults to configured default).")
@click.option("--all", "all_", is_flag=True, help="List all visible realizations.")
@click.option("--summary", is_flag=True, help="Return compact summaries only.")
@click.pass_context
def realizations_cmd(ctx, project, all_, summary):
    """List SPHERE realizations.

    Examples:

      loomai sphere realizations

      loomai sphere realizations --project fabricsphere --summary
    """
    params = {"all": all_, "summary": summary}
    if project:
        params["project"] = project
    data = ctx.obj["client"].get("/sphere/realizations", params=params)
    rows = data if isinstance(data, list) else []
    # Realization full or summary both carry id/eid/pid.
    output(ctx, rows,
           columns=["id", "eid", "pid",
                    lambda r: "yes" if r.get("complete") else "no"],
           headers=["Realization", "Experiment", "Project", "Complete"])


@sphere.command("realization")
@click.argument("experiment")
@click.argument("realization")
@click.option("--project", help="SPHERE project (defaults to configured default).")
@click.pass_context
def realization_cmd(ctx, experiment, realization, project):
    """Show a single SPHERE realization.

    Examples:

      loomai sphere realization hello world
    """
    params = {"project": project} if project else {}
    data = ctx.obj["client"].get(
        f"/sphere/realizations/{experiment}/{realization}", params=params)
    output(ctx, data)


@sphere.command("graph")
@click.argument("experiment")
@click.argument("realization")
@click.option("--project", help="SPHERE project (defaults to configured default).")
@click.pass_context
def graph_cmd(ctx, experiment, realization, project):
    """Show the Cytoscape topology graph for a SPHERE realization.

    Examples:

      loomai sphere graph hello world --format json
    """
    params = {"project": project} if project else {}
    data = ctx.obj["client"].get(
        f"/sphere/realizations/{experiment}/{realization}/graph", params=params)
    if not _is_table(ctx):
        output(ctx, data)
        return
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])
    click.echo(f"Nodes: {len(nodes)}  Edges: {len(edges)}")
    for n in nodes:
        d = n.get("data", {})
        click.echo(f"  [{d.get('element_type','?')}] {d.get('label','?')}")


@sphere.command("realize")
@click.argument("experiment")
@click.argument("realization")
@click.option("--tag", help="Realize a tagged model revision.")
@click.option("--branch", help="Realize a branch.")
@click.option("--revision", help="Realize a specific revision.")
@click.option("--duration", help="Reservation duration (e.g. 24h).")
@click.option("--project", help="SPHERE project (defaults to configured default).")
@click.pass_context
def realize_cmd(ctx, experiment, realization, tag, branch, revision, duration, project):
    """Realize (reserve resources for) a SPHERE experiment.

    Examples:

      loomai sphere realize hello world --tag v1
    """
    body = {"experiment": experiment, "realization": realization}
    for k, v in (("tag", tag), ("branch", branch), ("revision", revision),
                 ("duration", duration), ("project", project)):
        if v:
            body[k] = v
    result = ctx.obj["client"].post("/sphere/realizations", json=body)
    _table_message(ctx, f"Realize requested: {realization}.{experiment}")
    output(ctx, result)


@sphere.command("relinquish")
@click.argument("experiment")
@click.argument("realization")
@click.option("--project", help="SPHERE project (defaults to configured default).")
@click.pass_context
def relinquish_cmd(ctx, experiment, realization, project):
    """Relinquish (release) a SPHERE realization."""
    params = {"project": project} if project else {}
    result = ctx.obj["client"].delete(
        f"/sphere/realizations/{experiment}/{realization}", params=params)
    _table_message(ctx, f"Relinquished: {realization}.{experiment}")
    output(ctx, result)


@sphere.command("materialize")
@click.argument("experiment")
@click.argument("realization")
@click.option("--project", help="SPHERE project (defaults to configured default).")
@click.pass_context
def materialize_cmd(ctx, experiment, realization, project):
    """Materialize a SPHERE realization (power on, image, wire network).

    Examples:

      loomai sphere materialize hello world
    """
    body = {"experiment": experiment, "realization": realization}
    if project:
        body["project"] = project
    result = ctx.obj["client"].post("/sphere/materializations", json=body)
    _table_message(ctx, f"Materialize requested: {realization}.{experiment}")
    output(ctx, result)


@sphere.command("materialization")
@click.argument("experiment")
@click.argument("realization")
@click.option("--project", help="SPHERE project (defaults to configured default).")
@click.pass_context
def materialization_cmd(ctx, experiment, realization, project):
    """Show materialization status for a SPHERE realization."""
    params = {"project": project} if project else {}
    data = ctx.obj["client"].get(
        f"/sphere/materializations/{experiment}/{realization}", params=params)
    if not _is_table(ctx):
        output(ctx, data)
        return
    ts = (data.get("taskSummary") or {})
    summary = (data.get("summary") or {})
    click.echo(f"Status: {ts.get('HighestStatus', '?')}")
    if summary:
        click.echo(f"  rid={summary.get('rid')} virtual={summary.get('numVirtual')} "
                   f"links={summary.get('numLinks')}")


@sphere.command("dematerialize")
@click.argument("experiment")
@click.argument("realization")
@click.option("--project", help="SPHERE project (defaults to configured default).")
@click.pass_context
def dematerialize_cmd(ctx, experiment, realization, project):
    """Dematerialize (tear down) a SPHERE realization."""
    params = {"project": project} if project else {}
    result = ctx.obj["client"].delete(
        f"/sphere/materializations/{experiment}/{realization}", params=params)
    _table_message(ctx, f"Dematerialize requested: {realization}.{experiment}")
    output(ctx, result)


@sphere.command("package")
@click.argument("experiment")
@click.option("--name", required=True, help="Weave name (e.g. netsec1-detector).")
@click.option("--realization", default="r0", help="Realization to package (default r0).")
@click.option("--description", default="", help="Short description of the experiment.")
@click.option("--script", "scripts", multiple=True, metavar="TARGET:FILE",
              help="Per-node setup script as TARGET:FILE (e.g. gateway:detector.py). "
                   "TARGET is a node name or 'all'. Repeatable.")
@click.option("--no-notebook", "no_notebook", is_flag=True,
              help="Skip the starter analysis notebook.")
@click.option("--notebook", "notebook_file", type=click.Path(exists=True, dir_okay=False),
              help="Use this .ipynb as the analysis notebook instead of the auto-generated one.")
@click.option("--project", help="SPHERE project (defaults to configured default).")
@click.pass_context
def package_cmd(ctx, experiment, name, realization, description, scripts, no_notebook,
                notebook_file, project):
    """Package a SPHERE experiment + realization into a reproducible weave.

    Produces a ``sphere-experiment-v1`` weave (model + starter notebook +
    per-node setup scripts) under My Artifacts. Requires the experiment to have
    a realization (preferred) or a pushed model. Use this — NOT ``loomai weaves``
    — for SPHERE, so the weave can be sent to an XDC.

    Examples:

      loomai sphere package netsec1 --name netsec1-detector --realization r0 \\
        --script gateway:detector.py
    """
    script_list = []
    for spec in scripts:
        if ":" not in spec:
            raise click.BadParameter(
                f"--script must be TARGET:FILE (e.g. gateway:detector.py), got '{spec}'")
        target, path = spec.split(":", 1)
        with open(path) as fh:
            content = fh.read()
        script_list.append({"name": os.path.basename(path), "target": target, "content": content})
    body = {
        "name": name,
        "realization": realization,
        "description": description,
        "scripts": script_list,
        "include_notebook": not no_notebook,
    }
    if notebook_file:
        import json as _json
        with open(notebook_file) as fh:
            body["notebook"] = _json.load(fh)
    if project:
        body["project"] = project
    result = ctx.obj["client"].post(f"/sphere/experiments/{experiment}/package", json=body)
    _table_message(ctx, f"Packaged '{name}' from {experiment}/{realization}")
    output(ctx, result)


# --------------------------------------------------------------------------- #
# XDCs (Experiment Data Conduits) — jump containers used to reach nodes
# --------------------------------------------------------------------------- #
@sphere.group("xdc")
def xdc():
    """Manage XDCs — the jump containers used to SSH into experiment nodes."""


@xdc.command("list")
@click.option("--project", help="SPHERE project (defaults to configured default).")
@click.pass_context
def xdc_list_cmd(ctx, project):
    """List XDCs.

    Examples:

      loomai sphere xdc list
    """
    params = {"project": project} if project else {}
    data = ctx.obj["client"].get("/sphere/xdcs", params=params)
    rows = data if isinstance(data, list) else []
    output(ctx, rows,
           columns=["name", "type", "fqdn", "materialization", "creator"],
           headers=["XDC", "Type", "FQDN", "Attached To", "Creator"])


@xdc.command("create")
@click.argument("name")
@click.option("--type", "xdc_type", type=click.Choice(["shared", "personal"]),
              default="shared", show_default=True, help="XDC type.")
@click.option("--project", help="SPHERE project (defaults to configured default).")
@click.pass_context
def xdc_create_cmd(ctx, name, xdc_type, project):
    """Create an XDC.

    Examples:

      loomai sphere xdc create x0

      loomai sphere xdc create x0 --type shared
    """
    body = {"xdc": name, "type": xdc_type}
    if project:
        body["project"] = project
    result = ctx.obj["client"].post("/sphere/xdcs", json=body)
    _table_message(ctx, f"XDC created: {name}")
    output(ctx, result)


@xdc.command("delete")
@click.argument("name")
@click.option("--project", help="SPHERE project (defaults to configured default).")
@click.pass_context
def xdc_delete_cmd(ctx, name, project):
    """Delete an XDC."""
    params = {"project": project} if project else {}
    result = ctx.obj["client"].delete(f"/sphere/xdcs/{name}", params=params)
    _table_message(ctx, f"XDC deleted: {name}")
    output(ctx, result)


@xdc.command("attach")
@click.argument("name")
@click.argument("experiment")
@click.argument("realization")
@click.option("--project", help="SPHERE project (defaults to configured default).")
@click.pass_context
def xdc_attach_cmd(ctx, name, experiment, realization, project):
    """Attach an XDC to a realization so its nodes become reachable.

    Examples:

      loomai sphere xdc attach x0 hello world
    """
    body = {"experiment": experiment, "realization": realization}
    if project:
        body["project"] = project
    result = ctx.obj["client"].post(f"/sphere/xdcs/{name}/attach", json=body)
    _table_message(ctx, f"XDC {name} attached to {realization}.{experiment}")
    output(ctx, result)


@xdc.command("detach")
@click.argument("name")
@click.argument("experiment")
@click.argument("realization")
@click.option("--project", help="SPHERE project (defaults to configured default).")
@click.pass_context
def xdc_detach_cmd(ctx, name, experiment, realization, project):
    """Detach an XDC from a realization."""
    body = {"experiment": experiment, "realization": realization}
    if project:
        body["project"] = project
    result = ctx.obj["client"].post(f"/sphere/xdcs/{name}/detach", json=body)
    _table_message(ctx, f"XDC {name} detached from {realization}.{experiment}")
    output(ctx, result)


@sphere.command("ssh")
@click.argument("experiment")
@click.argument("realization")
@click.argument("node")
@click.option("--xdc", "xdc_name", required=True, help="XDC to jump through (must be attached).")
@click.option("--project", help="SPHERE project (defaults to configured default).")
@click.pass_context
def ssh_cmd(ctx, experiment, realization, node, xdc_name, project):
    """Print the command to SSH into a node through an XDC.

    The LoomAI WebUI opens this connection in-browser; from a shell, use the
    printed ``mrg`` command.

    Examples:

      loomai sphere ssh hello world a --xdc x0
    """
    proj = project or ""
    if not proj:
        try:
            status = ctx.obj["client"].get("/sphere/status")
            proj = (status or {}).get("default_project", "")
        except Exception:
            proj = ""
    ref = f"{xdc_name}.{proj}" if proj else f"{xdc_name}.<project>"
    cmd = f"mrg xdc ssh -x {ref} {node}"
    if _is_table(ctx):
        output_message(cmd)
    else:
        output(ctx, {"command": cmd, "experiment": experiment,
                     "realization": realization, "node": node, "xdc": xdc_name})
