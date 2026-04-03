"""Artifact marketplace commands."""

from __future__ import annotations

import click

from loomai_cli.output import output, output_message


@click.group()
def artifacts():
    """Browse, get, and publish FABRIC artifacts."""


@artifacts.command("list")
@click.option("--local", "source", flag_value="local", help="Show local artifacts only.")
@click.option("--remote", "source", flag_value="remote", help="Show marketplace artifacts only.")
@click.option("--mine", "source", flag_value="mine", help="Show your published artifacts.")
@click.pass_context
def list_artifacts(ctx, source):
    """List artifacts.

    Examples:

      loomai artifacts list --local

      loomai artifacts list --remote

      loomai artifacts list --mine
    """
    client = ctx.obj["client"]
    if source == "local":
        data = client.get("/artifacts/local")
    elif source == "mine":
        data = client.get("/artifacts/my")
    else:
        data = client.get("/artifacts/remote")

    if isinstance(data, list):
        output(ctx, data,
               columns=["name", "category", "description"],
               headers=["Name", "Category", "Description"])
    else:
        output(ctx, data)


@artifacts.command("search")
@click.argument("query")
@click.option("--tags", help="Comma-separated tags to filter by.")
@click.pass_context
def search_artifacts(ctx, query, tags):
    """Search the artifact marketplace.

    Examples:

      loomai artifacts search "hello fabric"

      loomai artifacts search "gpu" --tags networking,gpu
    """
    client = ctx.obj["client"]
    data = client.get("/artifacts/remote")
    # Client-side search (backend doesn't have search endpoint)
    q = query.lower()
    results = [a for a in data if q in (a.get("title", "") + a.get("description", "")).lower()]
    if tags:
        tag_set = {t.strip().lower() for t in tags.split(",")}
        results = [a for a in results
                   if tag_set & {t.lower() for t in (a.get("tags") or [])}]
    output(ctx, results,
           columns=["title", "uuid", "description"],
           headers=["Title", "UUID", "Description"])


@artifacts.command("show")
@click.argument("uuid")
@click.pass_context
def show_artifact(ctx, uuid):
    """Show detailed artifact information.

    Examples:

      loomai artifacts show abc-123-def-456
    """
    client = ctx.obj["client"]
    data = client.get(f"/artifacts/remote/{uuid}")
    output(ctx, data)


@artifacts.command("get")
@click.argument("uuid")
@click.option("--name", "local_name", help="Local name for the downloaded artifact.")
@click.pass_context
def get_artifact(ctx, uuid, local_name):
    """Download an artifact from the marketplace.

    Examples:

      loomai artifacts get abc-123 --name My_Weave
    """
    client = ctx.obj["client"]
    body = {"uuid": uuid}
    if local_name:
        body["local_name"] = local_name
    data = client.post("/artifacts/download", json=body)
    output_message(f"Downloaded artifact {uuid}")
    output(ctx, data)


@artifacts.command("publish")
@click.argument("dir_name")
@click.option("--title", required=True, help="Artifact title.")
@click.option("--description", required=True, help="Short description.")
@click.option("--tags", help="Comma-separated tags.")
@click.option("--category", default="weave", type=click.Choice(["weave", "vm", "recipe", "notebook"]),
              help="Artifact category (default: weave).")
@click.option("--visibility", default="author", type=click.Choice(["author", "project", "public"]),
              help="Visibility (default: author).")
@click.pass_context
def publish_artifact(ctx, dir_name, title, description, tags, category, visibility):
    """Publish a local artifact to the marketplace.

    Examples:

      loomai artifacts publish My_Weave --title "My Experiment" --description "A cool weave" --tags networking

      loomai artifacts publish GPU_Template --title "GPU VM" --description "RTX6000 template" --category vm
    """
    client = ctx.obj["client"]
    body = {
        "dir_name": dir_name,
        "title": title,
        "description": description,
        "category": category,
        "visibility": visibility,
    }
    if tags:
        body["tags"] = [t.strip() for t in tags.split(",")]
    data = client.post("/artifacts/publish", json=body)
    output_message(f"Published '{title}'")
    output(ctx, data)


@artifacts.command("update")
@click.argument("uuid")
@click.option("--title", help="New title.")
@click.option("--description", help="New description.")
@click.option("--tags", help="New comma-separated tags.")
@click.pass_context
def update_artifact(ctx, uuid, title, description, tags):
    """Update a published artifact's metadata.

    Examples:

      loomai artifacts update abc-123 --title "New Title" --description "Updated"
    """
    client = ctx.obj["client"]
    body = {}
    if title:
        body["title"] = title
    if description:
        body["description"] = description
    if tags:
        body["tags"] = [t.strip() for t in tags.split(",")]
    if not body:
        raise click.UsageError("Specify at least one field to update.")
    data = client.put(f"/artifacts/remote/{uuid}", json=body)
    output_message(f"Updated artifact {uuid}")
    output(ctx, data)


@artifacts.command("delete")
@click.argument("uuid")
@click.option("--force", is_flag=True, help="Skip confirmation.")
@click.pass_context
def delete_artifact(ctx, uuid, force):
    """Delete a published artifact.

    Examples:

      loomai artifacts delete abc-123 --force
    """
    if not force:
        click.confirm(f"Delete artifact {uuid}?", abort=True)
    client = ctx.obj["client"]
    data = client.delete(f"/artifacts/remote/{uuid}")
    output_message(f"Deleted artifact {uuid}")


@artifacts.command("tags")
@click.pass_context
def list_tags(ctx):
    """List valid artifact tags.

    Examples:

      loomai artifacts tags
    """
    client = ctx.obj["client"]
    data = client.get("/artifacts/valid-tags")
    if ctx.obj["format"] == "table":
        for tag in data:
            click.echo(tag)
    else:
        output(ctx, data)


@artifacts.command("versions")
@click.argument("uuid")
@click.pass_context
def list_versions(ctx, uuid):
    """List versions of a published artifact.

    Examples:

      loomai artifacts versions abc-123-def-456
    """
    client = ctx.obj["client"]
    data = client.get(f"/artifacts/remote/{uuid}")
    versions = data.get("versions", [])
    if not versions:
        click.echo("(no versions)")
        return
    if isinstance(versions, list) and versions and isinstance(versions[0], dict):
        output(ctx, versions,
               columns=["uuid", "version", "active", "created_at"],
               headers=["UUID", "Version", "Active", "Created"])
    else:
        output(ctx, versions)


@artifacts.command("push-version")
@click.argument("uuid")
@click.argument("dir_name")
@click.option("--category", default="weave",
              type=click.Choice(["weave", "vm", "recipe", "notebook"]),
              help="Artifact category (default: weave).")
@click.pass_context
def push_version(ctx, uuid, dir_name, category):
    """Push a new version of a published artifact.

    Examples:

      loomai artifacts push-version abc-123 My_Weave

      loomai artifacts push-version abc-123 GPU_Template --category vm
    """
    client = ctx.obj["client"]
    body = {"artifact_uuid": uuid, "dir_name": dir_name, "category": category}
    data = client.post(f"/artifacts/remote/{uuid}/version", json=body)
    output_message(f"Pushed new version for artifact {uuid}")
    output(ctx, data)


@artifacts.command("delete-version")
@click.argument("uuid")
@click.argument("version_uuid")
@click.option("--force", is_flag=True, help="Skip confirmation.")
@click.pass_context
def delete_version(ctx, uuid, version_uuid, force):
    """Delete a specific version of a published artifact.

    Examples:

      loomai artifacts delete-version abc-123 ver-456 --force
    """
    if not force:
        click.confirm(f"Delete version {version_uuid} of artifact {uuid}?", abort=True)
    client = ctx.obj["client"]
    data = client.delete(f"/artifacts/remote/{uuid}/version/{version_uuid}")
    output_message(f"Deleted version {version_uuid}")
