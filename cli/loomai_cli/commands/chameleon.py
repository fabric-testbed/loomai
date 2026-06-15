"""Chameleon Cloud commands — sites, leases, instances, IPs, security groups, slices, drafts."""

from __future__ import annotations

import json
from pathlib import Path

import click

from loomai_cli.output import output, output_message


def _is_table(ctx: click.Context) -> bool:
    return ctx.obj["format"] == "table"


def _table_message(ctx: click.Context, message: str) -> None:
    if _is_table(ctx):
        output_message(message)


@click.group()
@click.pass_context
def chameleon(ctx):
    """Manage Chameleon Cloud leases, instances, and resources.

    Requires Chameleon integration to be enabled in Settings.
    """
    client = ctx.obj["client"]
    try:
        status = client.get("/chameleon/status")
        if isinstance(status, dict) and status.get("enabled") is False:
            if ctx.invoked_subcommand == "status":
                return
            raise click.ClickException("Chameleon integration is disabled. Enable it in Settings.")
    except click.ClickException:
        raise
    except Exception:
        pass  # Let individual commands handle errors


@chameleon.command("status")
@click.pass_context
def status_cmd(ctx):
    """Show Chameleon integration status and configured sites."""
    data = ctx.obj["client"].get("/chameleon/status")
    output(ctx, data)


# ---------------------------------------------------------------------------
# Sites
# ---------------------------------------------------------------------------

@chameleon.command("sites")
@click.argument("site", required=False)
@click.pass_context
def sites_cmd(ctx, site):
    """List Chameleon sites or show details for a specific site.

    Examples:

      loomai chameleon sites

      loomai chameleon sites CHI@TACC
    """
    client = ctx.obj["client"]

    if site:
        # Show availability for a specific site
        data = client.get(f"/chameleon/sites/{site}/availability")
        if not _is_table(ctx):
            output(ctx, data)
            return
        click.echo(f"Site: {site}")
        hosts = data.get("hosts", [])
        flavors = data.get("flavors", [])
        if hosts:
            click.echo(f"\nHosts: {len(hosts)}")
            for h in hosts[:10]:
                name = h.get("hypervisor_hostname", h.get("id", "?"))
                click.echo(f"  {name}")
        if flavors:
            click.echo(f"\nFlavors: {len(flavors)}")
            for f in flavors[:10]:
                click.echo(f"  {f.get('name', '?')} — {f.get('vcpus', '?')} vCPUs, {f.get('ram', '?')} MB RAM, {f.get('disk', '?')} GB disk")
    else:
        # List all sites
        sites = client.get("/chameleon/sites")
        output(ctx, sites,
               columns=["name", "configured", lambda r: (r.get("location") or {}).get("city", "")],
               headers=["Name", "Configured", "City"])


@chameleon.command("images")
@click.argument("site", default="CHI@TACC")
@click.pass_context
def images_cmd(ctx, site):
    """List available OS images at a Chameleon site.

    Examples:

      loomai chameleon images

      loomai chameleon images CHI@UC
    """
    client = ctx.obj["client"]
    images = client.get(f"/chameleon/sites/{site}/images")
    if not _is_table(ctx):
        output(ctx, images)
        return
    click.echo(f"Images at {site}: ({len(images)} available)")
    for img in images[:30]:
        size = f" ({img['size_mb']} MB)" if img.get("size_mb") else ""
        click.echo(f"  {img['name']}{size}")
    if len(images) > 30:
        click.echo(f"  ... and {len(images) - 30} more")


@chameleon.group("node-types")
def node_types():
    """Inspect Chameleon bare-metal node types."""


@node_types.command("list")
@click.argument("site", default="CHI@TACC")
@click.option("--detail", is_flag=True, help="Include hardware detail when available.")
@click.pass_context
def node_types_list(ctx, site, detail):
    """List available node types at a Chameleon site."""
    data = ctx.obj["client"].get(f"/chameleon/sites/{site}/node-types", params={"detail": detail})
    if ctx.obj["format"] != "table":
        output(ctx, data)
        return
    rows = data.get("node_types", data) if isinstance(data, dict) else data
    output(ctx, rows,
           columns=["node_type", "total", "reservable", "cpu_arch", "ram_gb", "gpu", "gpu_count"],
           headers=["Node Type", "Total", "Reservable", "Arch", "RAM GB", "GPU", "GPUs"])


@node_types.command("detail")
@click.argument("site", default="CHI@TACC")
@click.pass_context
def node_types_detail(ctx, site):
    """List detailed hardware properties for node types at a site."""
    data = ctx.obj["client"].get(f"/chameleon/sites/{site}/node-types/detail")
    if ctx.obj["format"] != "table":
        output(ctx, data)
        return
    output(ctx, data.get("node_types", []),
           columns=["node_type", "total", "reservable", "cpu_count", "cpu_model", "ram_gb", "disk_gb", "gpu", "gpu_count"],
           headers=["Node Type", "Total", "Reservable", "CPUs", "CPU Model", "RAM", "Disk", "GPU", "GPUs"])


@chameleon.command("facility-ports")
@click.option("--site", help="Filter by Chameleon site.")
@click.pass_context
def facility_ports_cmd(ctx, site):
    """List Chameleon facility ports."""
    params = {"site": site} if site else {}
    data = ctx.obj["client"].get("/chameleon/facility-ports", params=params)
    output(ctx, data,
           columns=["name", "site", "vlan", "provider", "status"],
           headers=["Name", "Site", "VLAN", "Provider", "Status"])


@chameleon.command("find-availability")
@click.option("--site", default="CHI@TACC", help="Chameleon site.")
@click.option("--type", "node_type", required=True, help="Node type, e.g. compute_skylake.")
@click.option("--count", default=1, type=int, help="Number of nodes.")
@click.option("--hours", default=4, type=int, help="Duration in hours.")
@click.pass_context
def find_availability_cmd(ctx, site, node_type, count, hours):
    """Find approximate Chameleon node availability."""
    data = ctx.obj["client"].post("/chameleon/find-availability", json={
        "site": site,
        "node_type": node_type,
        "node_count": count,
        "duration_hours": hours,
    })
    output(ctx, data)


@chameleon.command("schedule-calendar")
@click.option("--days", default=14, type=click.IntRange(1, 90), help="Days to include.")
@click.pass_context
def schedule_calendar_cmd(ctx, days):
    """Show Chameleon lease/resource calendar data."""
    data = ctx.obj["client"].get("/chameleon/schedule/calendar", params={"days": days})
    if ctx.obj["format"] != "table":
        output(ctx, data)
        return
    rows = data.get("sites", data.get("data", [])) if isinstance(data, dict) else data
    output(ctx, rows,
           columns=["site", "leases", "node_types"],
           headers=["Site", "Leases", "Node Types"])


def _parse_json_object(value: str, label: str):
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise click.UsageError(f"Invalid {label}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise click.UsageError(f"{label} must be a JSON object.")
    return parsed


@chameleon.command("openstack-request")
@click.option("--site", default="CHI@TACC", help="Chameleon site.")
@click.option("--service", "service_type", required=True,
              type=click.Choice(["compute", "reservation", "network", "image"]),
              help="OpenStack service type.")
@click.option("--method", default="GET",
              type=click.Choice(["GET", "POST", "PUT", "DELETE"]),
              help="HTTP method.")
@click.option("--path", required=True, help="Service-relative OpenStack API path.")
@click.option("--params-json", default="", help="JSON object of query parameters.")
@click.option("--body-json", default="", help="JSON object request body.")
@click.option("--timeout", default=120, type=int, help="Request timeout in seconds.")
@click.pass_context
def openstack_request_cmd(ctx, site, service_type, method, path, params_json,
                          body_json, timeout):
    """Proxy an advanced OpenStack API request through LoomAI's Chameleon auth."""
    body = {
        "site": site,
        "service_type": service_type,
        "method": method,
        "path": path,
        "timeout": timeout,
    }
    params = _parse_json_object(params_json, "--params-json")
    request_body = _parse_json_object(body_json, "--body-json")
    if params is not None:
        body["params"] = params
    if request_body is not None:
        body["body"] = request_body
    data = ctx.obj["client"].post("/chameleon/openstack/request", json=body)
    output(ctx, data)


@chameleon.command("password-projects")
@click.option("--username", required=True, help="Chameleon username.")
@click.option("--password", prompt=True, hide_input=True,
              help="Chameleon password. Prefer prompt/env handling over shell history.")
@click.option("--site", "sites", multiple=True,
              help="Site to query; repeatable. Defaults to configured sites.")
@click.pass_context
def password_projects_cmd(ctx, username, password, sites):
    """List projects visible to password-auth Chameleon credentials."""
    data = ctx.obj["client"].post("/chameleon/password-auth/projects", json={
        "username": username,
        "password": password,
        "sites": list(sites),
    })
    if ctx.obj["format"] != "table":
        output(ctx, data)
        return
    rows = data.get("projects", [])
    output(ctx, rows,
           columns=["name", "site_count", "sites"],
           headers=["Project", "Sites", "Project IDs By Site"])


# ---------------------------------------------------------------------------
# Leases
# ---------------------------------------------------------------------------

@chameleon.group("leases")
def leases():
    """Manage Chameleon leases (reservations)."""


@leases.command("list")
@click.option("--site", help="Filter by site (e.g. CHI@TACC).")
@click.pass_context
def leases_list(ctx, site):
    """List Chameleon leases.

    Examples:

      loomai chameleon leases list

      loomai chameleon leases list --site CHI@TACC
    """
    client = ctx.obj["client"]
    params = {"site": site} if site else {}
    data = client.get("/chameleon/leases", params=params)
    output(ctx, data,
           columns=["name", "id", "status", "_site", "start_date", "end_date"],
           headers=["Name", "ID", "Status", "Site", "Start", "End"])


@leases.command("create")
@click.option("--site", default="CHI@TACC", help="Chameleon site.")
@click.option("--name", default="loomai-lease", help="Lease name.")
@click.option("--type", "node_type", default="compute_haswell", help="Node type.")
@click.option("--count", default=1, help="Number of nodes.")
@click.option("--hours", default=4, help="Duration in hours.")
@click.pass_context
def leases_create(ctx, site, name, node_type, count, hours):
    """Create a new Chameleon lease.

    Examples:

      loomai chameleon leases create --site CHI@TACC --type compute_haswell --count 2 --hours 4
    """
    client = ctx.obj["client"]

    result = client.post("/chameleon/leases", json={
        "site": site,
        "name": name,
        "node_type": node_type,
        "node_count": count,
        "duration_hours": hours,
    })
    lease_id = result.get("id", "?")
    status = result.get("status", "?")
    _table_message(ctx, f"Lease created: {name} ({lease_id}) — {status}")
    output(ctx, result)


@leases.command("delete")
@click.argument("lease_id")
@click.option("--site", default="CHI@TACC", help="Chameleon site.")
@click.pass_context
def leases_delete(ctx, lease_id, site):
    """Delete a Chameleon lease.

    Examples:

      loomai chameleon leases delete <lease-id> --site CHI@TACC
    """
    client = ctx.obj["client"]

    data = client.delete(f"/chameleon/leases/{lease_id}", params={"site": site})
    _table_message(ctx, f"Lease {lease_id} deleted.")
    if not _is_table(ctx):
        output(ctx, data)


@leases.command("extend")
@click.argument("lease_id")
@click.option("--site", default="CHI@TACC", help="Chameleon site.")
@click.option("--hours", default=1, help="Hours to extend.")
@click.pass_context
def leases_extend(ctx, lease_id, site, hours):
    """Extend a Chameleon lease.

    Examples:

      loomai chameleon leases extend <lease-id> --hours 2
    """
    client = ctx.obj["client"]

    data = client.put(f"/chameleon/leases/{lease_id}/extend", json={"site": site, "hours": hours})
    _table_message(ctx, f"Lease {lease_id} extended by {hours} hour(s).")
    output(ctx, data)


# ---------------------------------------------------------------------------
# Instances
# ---------------------------------------------------------------------------

@chameleon.group("instances")
def instances():
    """Manage Chameleon instances (servers)."""


@instances.command("list")
@click.option("--site", help="Filter by site.")
@click.pass_context
def instances_list(ctx, site):
    """List Chameleon instances.

    Examples:

      loomai chameleon instances list

      loomai chameleon instances list --site CHI@UC
    """
    client = ctx.obj["client"]
    params = {"site": site} if site else {}
    data = client.get("/chameleon/instances", params=params)
    output(ctx, data,
           columns=["name", "id", "status", "site", lambda r: r.get("floating_ip") or ", ".join(r.get("ip_addresses", []))],
           headers=["Name", "ID", "Status", "Site", "IP"])


@instances.command("show")
@click.argument("instance_id")
@click.option("--site", default="CHI@TACC", help="Chameleon site.")
@click.pass_context
def instances_show(ctx, instance_id, site):
    """Show details for one Chameleon instance."""
    data = ctx.obj["client"].get(f"/chameleon/instances/{instance_id}", params={"site": site})
    output(ctx, data)


@instances.command("unaffiliated")
@click.option("--site", default="CHI@TACC", help="Chameleon site.")
@click.pass_context
def instances_unaffiliated(ctx, site):
    """List Chameleon instances not attached to a LoomAI Chameleon slice."""
    data = ctx.obj["client"].get("/chameleon/instances/unaffiliated", params={"site": site})
    output(ctx, data,
           columns=["id", "name", "status", "site", "floating_ip"],
           headers=["ID", "Name", "Status", "Site", "Floating IP"])


@instances.command("create")
@click.option("--site", default="CHI@TACC", help="Chameleon site.")
@click.option("--name", default="loomai-instance", help="Instance name.")
@click.option("--lease", "lease_id", required=True, help="Lease ID.")
@click.option("--reservation", "reservation_id", help="Reservation ID (from lease).")
@click.option("--image", "image_id", required=True, help="Image ID or name.")
@click.option("--key", "key_name", help="SSH key pair name.")
@click.option("--network", "network_id", help="Network ID.")
@click.pass_context
def instances_create(ctx, site, name, lease_id, reservation_id, image_id, key_name, network_id):
    """Launch a Chameleon instance on a lease.

    Examples:

      loomai chameleon instances create --lease <id> --image CC-Ubuntu22.04
    """
    client = ctx.obj["client"]

    body = {
        "site": site,
        "name": name,
        "lease_id": lease_id,
        "image_id": image_id,
    }
    if reservation_id:
        body["reservation_id"] = reservation_id
    if key_name:
        body["key_name"] = key_name
    if network_id:
        body["network_id"] = network_id

    result = client.post("/chameleon/instances", json=body)
    instance_id = result.get("id", "?")
    _table_message(ctx, f"Instance created: {name} ({instance_id})")
    output(ctx, result)


@instances.command("associate-ip")
@click.argument("instance_id")
@click.option("--site", default="CHI@TACC", help="Chameleon site.")
@click.pass_context
def instances_associate_ip(ctx, instance_id, site):
    """Allocate and associate a floating IP with an instance."""
    data = ctx.obj["client"].post(f"/chameleon/instances/{instance_id}/associate-ip", json={"site": site})
    if ctx.obj["format"] == "table":
        output_message(f"Associated floating IP with {instance_id[:12]}...")
    output(ctx, data)


@instances.command("execute-recipe")
@click.argument("instance_id")
@click.argument("recipe_dir")
@click.option("--site", default="CHI@TACC", help="Chameleon site.")
@click.pass_context
def instances_execute_recipe(ctx, instance_id, recipe_dir, site):
    """Execute a LoomAI recipe on a Chameleon instance."""
    data = ctx.obj["client"].post(f"/chameleon/instances/{instance_id}/execute-recipe", json={
        "site": site,
        "recipe_dir": recipe_dir,
    })
    output(ctx, data)


@instances.command("delete")
@click.argument("instance_id")
@click.option("--site", default="CHI@TACC", help="Chameleon site.")
@click.pass_context
def instances_delete(ctx, instance_id, site):
    """Terminate a Chameleon instance.

    Examples:

      loomai chameleon instances delete <instance-id>
    """
    client = ctx.obj["client"]

    data = client.delete(f"/chameleon/instances/{instance_id}", params={"site": site})
    _table_message(ctx, f"Instance {instance_id} deleted.")
    if not _is_table(ctx):
        output(ctx, data)


@instances.command("reboot")
@click.argument("instance_id")
@click.option("--site", default="CHI@TACC", help="Chameleon site.")
@click.option("--type", "reboot_type", default="SOFT", type=click.Choice(["SOFT", "HARD"]), help="Reboot type.")
@click.pass_context
def instances_reboot(ctx, instance_id, site, reboot_type):
    """Reboot a Chameleon instance.

    Examples:

      loomai chameleon instances reboot <instance-id>

      loomai chameleon instances reboot <instance-id> --type HARD
    """
    client = ctx.obj["client"]

    data = client.post(f"/chameleon/instances/{instance_id}/reboot", json={"site": site, "type": reboot_type})
    _table_message(ctx, f"Instance {instance_id} rebooting ({reboot_type}).")
    output(ctx, data)


@instances.command("stop")
@click.argument("instance_id")
@click.option("--site", default="CHI@TACC", help="Chameleon site.")
@click.pass_context
def instances_stop(ctx, instance_id, site):
    """Stop a Chameleon instance.

    Examples:

      loomai chameleon instances stop <instance-id>
    """
    client = ctx.obj["client"]

    data = client.post(f"/chameleon/instances/{instance_id}/stop", json={"site": site})
    _table_message(ctx, f"Instance {instance_id} stopping.")
    output(ctx, data)


@instances.command("start")
@click.argument("instance_id")
@click.option("--site", default="CHI@TACC", help="Chameleon site.")
@click.pass_context
def instances_start(ctx, instance_id, site):
    """Start a stopped Chameleon instance.

    Examples:

      loomai chameleon instances start <instance-id>
    """
    client = ctx.obj["client"]

    data = client.post(f"/chameleon/instances/{instance_id}/start", json={"site": site})
    _table_message(ctx, f"Instance {instance_id} starting.")
    output(ctx, data)


# ---------------------------------------------------------------------------
# Networks
# ---------------------------------------------------------------------------

@chameleon.group("networks")
def networks():
    """Manage Chameleon networks."""


@networks.command("list")
@click.option("--site", help="Filter by site.")
@click.pass_context
def networks_list(ctx, site):
    """List Chameleon networks.

    Examples:

      loomai chameleon networks list

      loomai chameleon networks list --site CHI@TACC
    """
    client = ctx.obj["client"]
    params = {"site": site} if site else {}
    data = client.get("/chameleon/networks", params=params)
    output(ctx, data,
           columns=["name", "id", "status", "site", "shared",
                    lambda r: ", ".join(s.get("cidr", s.get("name", "?")) for s in r.get("subnet_details", []))],
           headers=["Name", "ID", "Status", "Site", "Shared", "Subnets"])


@networks.command("create")
@click.option("--site", default="CHI@TACC", help="Chameleon site.")
@click.option("--name", required=True, help="Network name.")
@click.option("--cidr", default="", help="Subnet CIDR (e.g. 192.168.1.0/24).")
@click.pass_context
def networks_create(ctx, site, name, cidr):
    """Create a Chameleon network.

    Examples:

      loomai chameleon networks create --name my-net --cidr 192.168.1.0/24
    """
    client = ctx.obj["client"]

    body = {"site": site, "name": name}
    if cidr:
        body["cidr"] = cidr
    result = client.post("/chameleon/networks", json=body)
    net_id = result.get("id", "?")
    _table_message(ctx, f"Network created: {name} ({net_id})")
    output(ctx, result)


@networks.command("delete")
@click.argument("network_id")
@click.option("--site", default="CHI@TACC", help="Chameleon site.")
@click.pass_context
def networks_delete(ctx, network_id, site):
    """Delete a Chameleon network.

    Examples:

      loomai chameleon networks delete <network-id> --site CHI@TACC
    """
    client = ctx.obj["client"]

    data = client.delete(f"/chameleon/networks/{network_id}", params={"site": site})
    _table_message(ctx, f"Network {network_id} deleted.")
    if not _is_table(ctx):
        output(ctx, data)


# ---------------------------------------------------------------------------
# Key Pairs
# ---------------------------------------------------------------------------

@chameleon.group("keypairs")
def keypairs():
    """Manage Chameleon key pairs."""


@keypairs.command("list")
@click.option("--site", help="Filter by site.")
@click.pass_context
def keypairs_list(ctx, site):
    """List Chameleon key pairs.

    Examples:

      loomai chameleon keypairs list

      loomai chameleon keypairs list --site CHI@TACC
    """
    client = ctx.obj["client"]
    params = {"site": site} if site else {}
    data = client.get("/chameleon/keypairs", params=params)
    output(ctx, data,
           columns=["name", "_site", "type", "fingerprint", "has_private_key"],
           headers=["Name", "Site", "Type", "Fingerprint", "Private Key"])


@keypairs.command("create")
@click.option("--site", default="CHI@TACC", help="Chameleon site.")
@click.option("--name", required=True, help="Key pair name.")
@click.option("--public-key", default="", help="Public key string (optional; Nova generates if omitted).")
@click.pass_context
def keypairs_create(ctx, site, name, public_key):
    """Create a Chameleon key pair.

    Examples:

      loomai chameleon keypairs create --name my-key

      loomai chameleon keypairs create --name my-key --public-key "ssh-rsa AAAA..."
    """
    client = ctx.obj["client"]

    body = {"site": site, "name": name}
    if public_key:
        body["public_key"] = public_key
    result = client.post("/chameleon/keypairs", json=body)
    if _is_table(ctx):
        click.echo(f"Key pair created: {name}")
        if result.get("private_key"):
            click.echo("Private key (save this — it won't be shown again):")
            click.echo(result["private_key"])
    else:
        output(ctx, result)


@keypairs.command("delete")
@click.argument("name")
@click.option("--site", default="CHI@TACC", help="Chameleon site.")
@click.pass_context
def keypairs_delete(ctx, name, site):
    """Delete a Chameleon key pair.

    Examples:

      loomai chameleon keypairs delete my-key --site CHI@TACC
    """
    client = ctx.obj["client"]

    data = client.delete(f"/chameleon/keypairs/{name}", params={"site": site})
    _table_message(ctx, f"Key pair '{name}' deleted.")
    if not _is_table(ctx):
        output(ctx, data)


@keypairs.command("upload-private-key")
@click.argument("name")
@click.option("--site", default="CHI@TACC", help="Chameleon site.")
@click.option("--file", "key_file", required=True,
              type=click.Path(exists=True, dir_okay=False, readable=True),
              help="Private key file to store for SSH/terminal access.")
@click.pass_context
def keypairs_upload_private_key(ctx, name, site, key_file):
    """Upload the private key for an existing Chameleon key pair."""
    client = ctx.obj["client"]
    path = Path(key_file)
    with path.open("rb") as fh:
        data = client.post_file(
            f"/chameleon/keypairs/{name}/private-key",
            files={"private_key": (path.name, fh, "application/octet-stream")},
            params={"site": site},
        )
    _table_message(ctx, f"Stored private key for key pair '{name}' at {site}")
    output(ctx, data)


@keypairs.command("ensure")
@click.option("--site", default="CHI@TACC", help="Chameleon site.")
@click.pass_context
def keypairs_ensure(ctx, site):
    """Ensure the managed loomai-key keypair exists for a site."""
    data = ctx.obj["client"].post("/chameleon/keypairs/ensure", json={"site": site})
    output(ctx, data)


# ---------------------------------------------------------------------------
# Boot config
# ---------------------------------------------------------------------------

@chameleon.group("boot-config")
def boot_config():
    """Manage Chameleon node boot configuration."""


@boot_config.command("show")
@click.argument("slice_id")
@click.argument("node_name")
@click.pass_context
def boot_config_show(ctx, slice_id, node_name):
    """Show boot config for a Chameleon node."""
    data = ctx.obj["client"].get(f"/chameleon/boot-config/{slice_id}/{node_name}")
    output(ctx, data)


@boot_config.command("set")
@click.argument("slice_id")
@click.argument("node_name")
@click.option("--from-file", "config_file", type=click.Path(exists=True),
              help="JSON file containing full boot config.")
@click.option("--command", "commands", multiple=True,
              help="Shell command to add to boot config. Repeatable.")
@click.pass_context
def boot_config_set(ctx, slice_id, node_name, config_file, commands):
    """Save boot config for a Chameleon node."""
    if config_file:
        with open(config_file) as f:
            data = json.load(f)
    elif commands:
        data = {
            "uploads": [],
            "commands": [
                {"id": f"cmd-{idx}", "command": command, "order": idx}
                for idx, command in enumerate(commands)
            ],
            "network": [],
        }
    else:
        raise click.UsageError("Use --from-file or at least one --command.")
    result = ctx.obj["client"].put(f"/chameleon/boot-config/{slice_id}/{node_name}", json=data)
    output(ctx, result)


@boot_config.command("run")
@click.argument("slice_id")
@click.argument("node_name")
@click.pass_context
def boot_config_run(ctx, slice_id, node_name):
    """Execute boot config for a Chameleon node."""
    data = ctx.obj["client"].post(f"/chameleon/boot-config/{slice_id}/{node_name}/execute")
    output(ctx, data)


# ---------------------------------------------------------------------------
# Test connection
# ---------------------------------------------------------------------------

@chameleon.command("test")
@click.argument("site", default="all")
@click.pass_context
def test_cmd(ctx, site):
    """Test connection to Chameleon site(s).

    Examples:

      loomai chameleon test

      loomai chameleon test CHI@TACC
    """
    client = ctx.obj["client"]

    results = client.post("/chameleon/test", json={"site": site})
    if not _is_table(ctx):
        output(ctx, results)
        return
    for site_name, r in results.items():
        status = "OK" if r.get("ok") else "FAILED"
        latency = f" ({r['latency_ms']}ms)" if r.get("latency_ms") else ""
        error = f" — {r['error']}" if r.get("error") else ""
        click.echo(f"  {site_name}: {status}{latency}{error}")


# ---------------------------------------------------------------------------
# Floating IPs
# ---------------------------------------------------------------------------

@chameleon.group("ips")
def ips():
    """Manage Chameleon floating IP addresses."""


@ips.command("list")
@click.option("--site", help="Filter by site.")
@click.pass_context
def ips_list(ctx, site):
    """List floating IPs.

    Examples:

      loomai chameleon ips list

      loomai chameleon ips list --site CHI@TACC
    """
    client = ctx.obj["client"]
    params = {"site": site} if site else {}
    data = client.get("/chameleon/floating-ips", params=params)
    output(ctx, data,
           columns=["floating_ip_address", "id", "status", "_site", "port_id"],
           headers=["IP", "ID", "Status", "Site", "Port"])


@ips.command("allocate")
@click.option("--site", default="CHI@TACC", help="Chameleon site.")
@click.option("--network", default="public", help="External network name.")
@click.pass_context
def ips_allocate(ctx, site, network):
    """Allocate a floating IP from the external network.

    Examples:

      loomai chameleon ips allocate --site CHI@TACC
    """
    client = ctx.obj["client"]

    result = client.post("/chameleon/floating-ips", json={"site": site, "network": network})
    ip = result.get("floating_ip_address", "?")
    fip_id = result.get("id", "?")
    _table_message(ctx, f"Allocated: {ip} ({fip_id})")
    output(ctx, result)


@ips.command("associate")
@click.argument("ip_id")
@click.option("--port", "port_id", required=True, help="Port ID to associate with.")
@click.option("--site", default="CHI@TACC", help="Chameleon site.")
@click.pass_context
def ips_associate(ctx, ip_id, port_id, site):
    """Associate a floating IP with a port.

    Examples:

      loomai chameleon ips associate <ip-id> --port <port-id> --site CHI@TACC
    """
    client = ctx.obj["client"]

    result = client.post(f"/chameleon/floating-ips/{ip_id}/associate", json={"site": site, "port_id": port_id})
    ip = result.get("floating_ip_address", "?")
    _table_message(ctx, f"Associated {ip} with port {port_id[:12]}...")
    output(ctx, result)


@ips.command("disassociate")
@click.argument("instance_id")
@click.option("--ip", "floating_ip", required=True, help="Floating IP address.")
@click.option("--site", default="CHI@TACC", help="Chameleon site.")
@click.pass_context
def ips_disassociate(ctx, instance_id, floating_ip, site):
    """Disassociate a floating IP from an instance.

    Examples:

      loomai chameleon ips disassociate <instance-id> --ip 192.5.87.100 --site CHI@TACC
    """
    client = ctx.obj["client"]

    data = client.post(f"/chameleon/instances/{instance_id}/disassociate-ip", json={"site": site, "floating_ip": floating_ip})
    _table_message(ctx, f"Disassociated {floating_ip} from instance {instance_id[:12]}...")
    output(ctx, data)


@ips.command("release")
@click.argument("ip_id")
@click.option("--site", default="CHI@TACC", help="Chameleon site.")
@click.pass_context
def ips_release(ctx, ip_id, site):
    """Release (deallocate) a floating IP.

    Examples:

      loomai chameleon ips release <ip-id> --site CHI@TACC
    """
    client = ctx.obj["client"]

    data = client.delete(f"/chameleon/floating-ips/{ip_id}", params={"site": site})
    _table_message(ctx, f"Floating IP {ip_id} released.")
    if not _is_table(ctx):
        output(ctx, data)


# ---------------------------------------------------------------------------
# Security Groups
# ---------------------------------------------------------------------------

@chameleon.group("security-groups")
def security_groups():
    """Manage Chameleon security groups and rules."""


@security_groups.command("list")
@click.option("--site", help="Filter by site.")
@click.pass_context
def sg_list(ctx, site):
    """List security groups.

    Examples:

      loomai chameleon security-groups list

      loomai chameleon security-groups list --site CHI@TACC
    """
    client = ctx.obj["client"]
    params = {"site": site} if site else {}
    data = client.get("/chameleon/security-groups", params=params)
    output(ctx, data,
           columns=["name", "id", "_site", lambda r: len(r.get("security_group_rules", [])), "description"],
           headers=["Name", "ID", "Site", "Rules", "Description"])


@security_groups.command("create")
@click.option("--name", required=True, help="Security group name.")
@click.option("--site", default="CHI@TACC", help="Chameleon site.")
@click.option("--description", default="", help="Description.")
@click.pass_context
def sg_create(ctx, name, site, description):
    """Create a security group.

    Examples:

      loomai chameleon security-groups create --name my-sg --site CHI@TACC
    """
    client = ctx.obj["client"]

    result = client.post("/chameleon/security-groups", json={"site": site, "name": name, "description": description})
    sg_id = result.get("id", "?")
    _table_message(ctx, f"Security group created: {name} ({sg_id})")
    output(ctx, result)


@security_groups.command("delete")
@click.argument("sg_id")
@click.option("--site", default="CHI@TACC", help="Chameleon site.")
@click.pass_context
def sg_delete(ctx, sg_id, site):
    """Delete a security group.

    Examples:

      loomai chameleon security-groups delete <sg-id> --site CHI@TACC
    """
    client = ctx.obj["client"]

    data = client.delete(f"/chameleon/security-groups/{sg_id}", params={"site": site})
    _table_message(ctx, f"Security group {sg_id} deleted.")
    if not _is_table(ctx):
        output(ctx, data)


@security_groups.command("add-rule")
@click.argument("sg_id")
@click.option("--direction", required=True, type=click.Choice(["ingress", "egress"]), help="Rule direction.")
@click.option("--protocol", default=None, help="Protocol (tcp, udp, icmp).")
@click.option("--port-min", default=None, type=int, help="Min port.")
@click.option("--port-max", default=None, type=int, help="Max port.")
@click.option("--remote-ip", default=None, help="Remote IP prefix (e.g. 0.0.0.0/0).")
@click.option("--ethertype", default="IPv4", help="Ethertype (IPv4 or IPv6).")
@click.option("--site", default="CHI@TACC", help="Chameleon site.")
@click.pass_context
def sg_add_rule(ctx, sg_id, direction, protocol, port_min, port_max, remote_ip, ethertype, site):
    """Add a rule to a security group.

    Examples:

      loomai chameleon security-groups add-rule <sg-id> --direction ingress --protocol tcp --port-min 22 --port-max 22 --remote-ip 0.0.0.0/0

      loomai chameleon security-groups add-rule <sg-id> --direction ingress --protocol icmp
    """
    client = ctx.obj["client"]

    body = {"site": site, "direction": direction, "ethertype": ethertype}
    if protocol:
        body["protocol"] = protocol
    if port_min is not None:
        body["port_range_min"] = port_min
    if port_max is not None:
        body["port_range_max"] = port_max
    if remote_ip:
        body["remote_ip_prefix"] = remote_ip

    result = client.post(f"/chameleon/security-groups/{sg_id}/rules", json=body)
    rule_id = result.get("id", "?")
    _table_message(ctx, f"Rule added: {direction} {protocol or 'any'} {port_min or ''}-{port_max or ''} ({rule_id})")
    output(ctx, result)


@security_groups.command("remove-rule")
@click.argument("sg_id")
@click.argument("rule_id")
@click.option("--site", default="CHI@TACC", help="Chameleon site.")
@click.pass_context
def sg_remove_rule(ctx, sg_id, rule_id, site):
    """Remove a rule from a security group.

    Examples:

      loomai chameleon security-groups remove-rule <sg-id> <rule-id> --site CHI@TACC
    """
    client = ctx.obj["client"]

    data = client.delete(f"/chameleon/security-groups/{sg_id}/rules/{rule_id}", params={"site": site})
    _table_message(ctx, f"Rule {rule_id} deleted.")
    if not _is_table(ctx):
        output(ctx, data)


# ---------------------------------------------------------------------------
# Slices (resource groups)
# ---------------------------------------------------------------------------

@chameleon.group("slices")
def slices():
    """Manage Chameleon slices (resource groups)."""


@slices.command("list")
@click.pass_context
def slices_list(ctx):
    """List Chameleon slices.

    Examples:

      loomai chameleon slices list
    """
    client = ctx.obj["client"]
    data = client.get("/chameleon/slices")
    output(ctx, data,
           columns=["name", "id", "state", "site", lambda r: len(r.get("resources", []))],
           headers=["Name", "ID", "State", "Site", "Resources"])


@slices.command("all")
@click.pass_context
def slices_all(ctx):
    """List all Chameleon slice records, including compatibility records."""
    data = ctx.obj["client"].get("/chameleon/slices/all")
    output(ctx, data,
           columns=["id", "name", "state", "site"],
           headers=["ID", "Name", "State", "Site"])


@slices.command("show")
@click.argument("slice_id")
@click.pass_context
def slices_show(ctx, slice_id):
    """Show one Chameleon slice/draft record."""
    data = ctx.obj["client"].get(f"/chameleon/drafts/{slice_id}")
    output(ctx, data)


@slices.command("create")
@click.option("--name", required=True, help="Slice name.")
@click.option("--site", default="CHI@TACC", help="Chameleon site.")
@click.pass_context
def slices_create(ctx, name, site):
    """Create a Chameleon slice.

    Examples:

      loomai chameleon slices create --name my-slice --site CHI@TACC
    """
    client = ctx.obj["client"]

    result = client.post("/chameleon/slices", json={"name": name, "site": site})
    slice_id = result.get("id", "?")
    _table_message(ctx, f"Slice created: {name} ({slice_id})")
    output(ctx, result)


@slices.command("state")
@click.argument("slice_id")
@click.option("--state", "new_state", help="Set slice state instead of only showing it.")
@click.pass_context
def slices_state(ctx, slice_id, new_state):
    """Show or update a Chameleon slice state."""
    if new_state:
        data = ctx.obj["client"].put(f"/chameleon/slices/{slice_id}/state", json={"state": new_state})
    else:
        data = ctx.obj["client"].get(f"/chameleon/drafts/{slice_id}")
        data = {"id": slice_id, "state": data.get("state", ""), "name": data.get("name", "")}
    output(ctx, data)


@slices.command("graph")
@click.argument("slice_id")
@click.pass_context
def slices_graph(ctx, slice_id):
    """Show the topology graph for a Chameleon slice."""
    data = ctx.obj["client"].get(f"/chameleon/slices/{slice_id}/graph")
    output(ctx, data)


@slices.command("auto-network-setup")
@click.argument("slice_id")
@click.pass_context
def slices_auto_network_setup(ctx, slice_id):
    """Ensure SSH security groups and floating IPs for slice instances."""
    data = ctx.obj["client"].post(f"/chameleon/slices/{slice_id}/auto-network-setup")
    output(ctx, data)


@slices.command("import-reservation")
@click.argument("slice_id")
@click.option("--site", default="CHI@TACC", help="Chameleon site.")
@click.option("--lease-id", default="", help="Blazar lease ID.")
@click.option("--instance-id", "instance_ids", multiple=True,
              help="Explicit instance ID to import. Repeatable.")
@click.option("--instance-name", "instance_names", multiple=True,
              help="Explicit instance name to import. Repeatable.")
@click.option("--include-lease/--no-include-lease", default=True,
              help="Track the lease resource in the slice.")
@click.pass_context
def slices_import_reservation(ctx, slice_id, site, lease_id, instance_ids, instance_names, include_lease):
    """Import lease-associated instances into a Chameleon slice."""
    data = ctx.obj["client"].post(f"/chameleon/slices/{slice_id}/import-reservation", json={
        "site": site,
        "lease_id": lease_id,
        "instance_ids": list(instance_ids),
        "instance_names": list(instance_names),
        "include_lease": include_lease,
    })
    output(ctx, data)


@slices.command("ensure-bastion")
@click.argument("slice_id")
@click.option("--site", default="CHI@TACC", help="Chameleon site.")
@click.option("--experiment-net-id", default="", help="Experiment/private network ID.")
@click.option("--reservation-id", default="", help="Reservation ID for the bastion.")
@click.pass_context
def slices_ensure_bastion(ctx, slice_id, site, experiment_net_id, reservation_id):
    """Ensure a bastion exists for private Chameleon worker access."""
    data = ctx.obj["client"].post(f"/chameleon/slices/{slice_id}/ensure-bastion", json={
        "site": site,
        "experiment_net_id": experiment_net_id,
        "reservation_id": reservation_id,
    })
    output(ctx, data)


@slices.command("check-readiness")
@click.argument("slice_id")
@click.pass_context
def slices_check_readiness(ctx, slice_id):
    """Probe SSH readiness for Chameleon slice instances."""
    data = ctx.obj["client"].post(f"/chameleon/slices/{slice_id}/check-readiness")
    output(ctx, data)


@slices.command("delete")
@click.argument("slice_id")
@click.pass_context
def slices_delete(ctx, slice_id):
    """Delete a Chameleon slice.

    Examples:

      loomai chameleon slices delete <slice-id>
    """
    client = ctx.obj["client"]

    data = client.delete(f"/chameleon/slices/{slice_id}")
    _table_message(ctx, f"Slice {slice_id} deleted.")
    if not _is_table(ctx):
        output(ctx, data)


@slices.command("add-resource")
@click.argument("slice_id")
@click.option("--type", "res_type", required=True, type=click.Choice(["instance", "lease", "network", "floating_ip"]), help="Resource type.")
@click.option("--id", "res_id", required=True, help="Resource ID.")
@click.option("--name", "res_name", default="", help="Resource name (display label).")
@click.option("--site", default=None, help="Resource site.")
@click.pass_context
def slices_add_resource(ctx, slice_id, res_type, res_id, res_name, site):
    """Add a resource to a Chameleon slice.

    Examples:

      loomai chameleon slices add-resource <slice-id> --type instance --id <instance-id> --name my-vm
    """
    client = ctx.obj["client"]

    body = {"type": res_type, "id": res_id, "name": res_name}
    if site:
        body["site"] = site

    result = client.post(f"/chameleon/slices/{slice_id}/add-resource", json=body)
    count = len(result.get("resources", []))
    _table_message(ctx, f"Resource added to slice. Total resources: {count}")
    output(ctx, result)


@slices.command("remove-resource")
@click.argument("slice_id")
@click.argument("resource_id")
@click.pass_context
def slices_remove_resource(ctx, slice_id, resource_id):
    """Remove a resource from a Chameleon slice.

    Examples:

      loomai chameleon slices remove-resource <slice-id> <resource-id>
    """
    client = ctx.obj["client"]

    result = client.post(f"/chameleon/slices/{slice_id}/remove-resource", json={"resource_id": resource_id})
    count = len(result.get("resources", []))
    _table_message(ctx, f"Resource removed. Remaining resources: {count}")
    output(ctx, result)


# ---------------------------------------------------------------------------
# Drafts (topology designs)
# ---------------------------------------------------------------------------

@chameleon.group("drafts")
def drafts():
    """Manage Chameleon draft topologies."""


@drafts.command("list")
@click.pass_context
def drafts_list(ctx):
    """List Chameleon draft topologies.

    Examples:

      loomai chameleon drafts list
    """
    client = ctx.obj["client"]
    data = client.get("/chameleon/drafts")
    output(ctx, data,
           columns=["name", "id", "site", lambda r: len(r.get("nodes", [])), lambda r: len(r.get("networks", []))],
           headers=["Name", "ID", "Site", "Nodes", "Networks"])


@drafts.command("show")
@click.argument("draft_id")
@click.pass_context
def drafts_show(ctx, draft_id):
    """Show a Chameleon draft/slice topology."""
    data = ctx.obj["client"].get(f"/chameleon/drafts/{draft_id}")
    output(ctx, data)


@drafts.command("create")
@click.option("--name", required=True, help="Draft name.")
@click.option("--site", default="CHI@TACC", help="Chameleon site.")
@click.pass_context
def drafts_create(ctx, name, site):
    """Create a new Chameleon draft topology.

    Examples:

      loomai chameleon drafts create --name my-draft --site CHI@TACC
    """
    client = ctx.obj["client"]

    result = client.post("/chameleon/drafts", json={"name": name, "site": site})
    draft_id = result.get("id", "?")
    _table_message(ctx, f"Draft created: {name} ({draft_id})")
    output(ctx, result)


@drafts.command("delete")
@click.argument("draft_id")
@click.pass_context
def drafts_delete(ctx, draft_id):
    """Delete a Chameleon draft.

    Examples:

      loomai chameleon drafts delete <draft-id>
    """
    client = ctx.obj["client"]

    data = client.delete(f"/chameleon/drafts/{draft_id}")
    _table_message(ctx, f"Draft {draft_id} deleted.")
    if not _is_table(ctx):
        output(ctx, data)


@drafts.command("add-node")
@click.argument("draft_id")
@click.option("--name", required=True, help="Node name.")
@click.option("--type", "node_type", default="compute_haswell", help="Node type.")
@click.option("--image", default="CC-Ubuntu22.04", help="Image name or ID.")
@click.pass_context
def drafts_add_node(ctx, draft_id, name, node_type, image):
    """Add a node to a Chameleon draft.

    Examples:

      loomai chameleon drafts add-node <draft-id> --name node1 --type compute_haswell --image CC-Ubuntu22.04
    """
    client = ctx.obj["client"]

    result = client.post(f"/chameleon/drafts/{draft_id}/nodes", json={
        "name": name, "node_type": node_type, "image": image,
    })
    nodes = result.get("nodes", [])
    _table_message(ctx, f"Node '{name}' added. Total nodes: {len(nodes)}")
    output(ctx, result)


@drafts.command("update-node")
@click.argument("draft_id")
@click.argument("node_id")
@click.option("--name", help="Node display name.")
@click.option("--type", "node_type", help="Node type.")
@click.option("--image", help="Image name or ID.")
@click.option("--count", type=int, help="Replica count.")
@click.option("--site", help="Chameleon site.")
@click.option("--key-name", help="Nova keypair name.")
@click.pass_context
def drafts_update_node(ctx, draft_id, node_id, name, node_type, image, count, site, key_name):
    """Update a planned node in a Chameleon draft."""
    body = {}
    for key, value in {
        "name": name,
        "node_type": node_type,
        "image": image,
        "count": count,
        "site": site,
        "key_name": key_name,
    }.items():
        if value is not None:
            body[key] = value
    if not body:
        raise click.UsageError("Specify at least one node property.")
    data = ctx.obj["client"].put(f"/chameleon/drafts/{draft_id}/nodes/{node_id}", json=body)
    output(ctx, data)


@drafts.command("remove-node")
@click.argument("draft_id")
@click.argument("node_id")
@click.pass_context
def drafts_remove_node(ctx, draft_id, node_id):
    """Remove a node from a Chameleon draft.

    Examples:

      loomai chameleon drafts remove-node <draft-id> <node-id>
    """
    client = ctx.obj["client"]

    data = client.delete(f"/chameleon/drafts/{draft_id}/nodes/{node_id}")
    _table_message(ctx, f"Node {node_id} removed.")
    if not _is_table(ctx):
        output(ctx, data)


@drafts.command("set-node-network")
@click.argument("draft_id")
@click.argument("node_id")
@click.option("--network-id", default="", help="Network ID, or empty to disconnect.")
@click.option("--network-name", default="", help="Network display name.")
@click.pass_context
def drafts_set_node_network(ctx, draft_id, node_id, network_id, network_name):
    """Set the primary network for a planned node."""
    body = None if not network_id and not network_name else {
        "id": network_id,
        "name": network_name or network_id,
    }
    data = ctx.obj["client"].put(f"/chameleon/drafts/{draft_id}/nodes/{node_id}/network", json=body)
    output(ctx, data)


@drafts.command("set-interfaces")
@click.argument("draft_id")
@click.argument("node_id")
@click.option("--interface", "interfaces", multiple=True,
              help="NIC assignment as NIC=NETWORK_ID[:NETWORK_NAME]. Repeatable.")
@click.pass_context
def drafts_set_interfaces(ctx, draft_id, node_id, interfaces):
    """Set all NIC network assignments for a planned node."""
    body = []
    for raw in interfaces:
        if "=" not in raw:
            raise click.UsageError(f"Invalid interface '{raw}' (expected NIC=NETWORK_ID[:NETWORK_NAME])")
        nic_raw, network_raw = raw.split("=", 1)
        try:
            nic = int(nic_raw)
        except ValueError as exc:
            raise click.UsageError(f"Invalid NIC index '{nic_raw}'") from exc
        network_id, _, network_name = network_raw.partition(":")
        network = None if not network_id else {"id": network_id, "name": network_name or network_id}
        body.append({"nic": nic, "network": network})
    data = ctx.obj["client"].put(f"/chameleon/drafts/{draft_id}/nodes/{node_id}/interfaces", json=body)
    output(ctx, data)


@drafts.command("add-network")
@click.argument("draft_id")
@click.option("--name", required=True, help="Network name.")
@click.option("--nodes", default="", help="Comma-separated node IDs to connect.")
@click.pass_context
def drafts_add_network(ctx, draft_id, name, nodes):
    """Add a network to a Chameleon draft.

    Examples:

      loomai chameleon drafts add-network <draft-id> --name my-net

      loomai chameleon drafts add-network <draft-id> --name my-net --nodes node1-id,node2-id
    """
    client = ctx.obj["client"]

    body = {"name": name}
    if nodes:
        body["connected_nodes"] = [n.strip() for n in nodes.split(",") if n.strip()]

    result = client.post(f"/chameleon/drafts/{draft_id}/networks", json=body)
    nets = result.get("networks", [])
    _table_message(ctx, f"Network '{name}' added. Total networks: {len(nets)}")
    output(ctx, result)


@drafts.command("remove-network")
@click.argument("draft_id")
@click.argument("network_id")
@click.pass_context
def drafts_remove_network(ctx, draft_id, network_id):
    """Remove a network from a Chameleon draft.

    Examples:

      loomai chameleon drafts remove-network <draft-id> <network-id>
    """
    client = ctx.obj["client"]

    data = client.delete(f"/chameleon/drafts/{draft_id}/networks/{network_id}")
    _table_message(ctx, f"Network {network_id} removed.")
    if not _is_table(ctx):
        output(ctx, data)


@drafts.command("floating-ips")
@click.argument("draft_id")
@click.option("--entry", "entries", multiple=True,
              help="Floating IP intent as NODE_ID[:NIC]. Repeatable.")
@click.pass_context
def drafts_floating_ips(ctx, draft_id, entries):
    """Set which planned nodes should get floating IPs."""
    parsed = []
    for raw in entries:
        node_id, _, nic_raw = raw.partition(":")
        if not node_id:
            raise click.UsageError("NODE_ID cannot be empty")
        nic = int(nic_raw) if nic_raw else 0
        parsed.append({"node_id": node_id, "nic": nic})
    data = ctx.obj["client"].put(f"/chameleon/drafts/{draft_id}/floating-ips", json={"entries": parsed})
    output(ctx, data)


@drafts.command("graph")
@click.argument("draft_id")
@click.pass_context
def drafts_graph(ctx, draft_id):
    """Show a Chameleon draft topology graph."""
    data = ctx.obj["client"].get(f"/chameleon/drafts/{draft_id}/graph")
    output(ctx, data)


@drafts.command("precreate-leases")
@click.argument("draft_id")
@click.option("--lease-name", default=None, help="Lease name prefix.")
@click.option("--hours", default=24, type=int, help="Lease duration in hours.")
@click.option("--start-date", default=None, help="Start date (ISO format, or now).")
@click.pass_context
def drafts_precreate_leases(ctx, draft_id, lease_name, hours, start_date):
    """Create Blazar leases for a draft without deploying instances."""
    body = {"duration_hours": hours}
    if lease_name:
        body["lease_name"] = lease_name
    if start_date:
        body["start_date"] = start_date
    data = ctx.obj["client"].post(f"/chameleon/drafts/{draft_id}/precreate-leases", json=body)
    output(ctx, data)


@drafts.command("deploy")
@click.argument("draft_id")
@click.option("--lease-name", default=None, help="Lease name (auto-generated if omitted).")
@click.option("--hours", default=4, help="Lease duration in hours.")
@click.option("--start-date", default=None, help="Start date (ISO format, or 'now').")
@click.pass_context
def drafts_deploy(ctx, draft_id, lease_name, hours, start_date):
    """Deploy a Chameleon draft topology (create lease + instances).

    Examples:

      loomai chameleon drafts deploy <draft-id>

      loomai chameleon drafts deploy <draft-id> --lease-name my-lease --hours 8
    """
    client = ctx.obj["client"]

    body = {"duration_hours": hours}
    if lease_name:
        body["lease_name"] = lease_name
    if start_date:
        body["start_date"] = start_date

    result = client.post(f"/chameleon/drafts/{draft_id}/deploy", json=body)
    if _is_table(ctx):
        click.echo("Deployment started.")
        if result.get("lease_id"):
            click.echo(f"  Lease: {result['lease_id']}")
        if result.get("instances"):
            for inst in result["instances"]:
                click.echo(f"  Instance: {inst.get('name', '?')} ({inst.get('id', '?')[:12]}...)")
        if result.get("error"):
            click.echo(f"  Warning: {result['error']}")
    else:
        output(ctx, result)
