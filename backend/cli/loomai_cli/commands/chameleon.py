"""Chameleon Cloud commands — sites, leases, instances, IPs, security groups, slices, drafts."""

from __future__ import annotations

import json

import click

from loomai_cli.output import output, output_message


@click.group()
@click.pass_context
def chameleon(ctx):
    """Manage Chameleon Cloud leases, instances, and resources.

    Requires Chameleon integration to be enabled in Settings.
    """
    client = ctx.obj["client"]
    try:
        status = client.get("/chameleon/status")
        if not status.get("enabled"):
            click.echo("Chameleon integration is disabled. Enable it in Settings.")
            ctx.abort()
    except Exception:
        pass  # Let individual commands handle errors


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
    fmt = ctx.obj["format"]

    if site:
        # Show availability for a specific site
        try:
            data = client.get(f"/chameleon/sites/{site}/availability")
            if fmt == "json":
                click.echo(json.dumps(data, indent=2))
            else:
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
        except Exception as e:
            click.echo(f"Error: {e}", err=True)
    else:
        # List all sites
        try:
            sites = client.get("/chameleon/sites")
            if fmt == "json":
                click.echo(json.dumps(sites, indent=2))
            else:
                click.echo("Chameleon Sites:")
                for s in sites:
                    status = "configured" if s.get("configured") else "not configured"
                    loc = s.get("location", {})
                    city = loc.get("city", "")
                    click.echo(f"  {s['name']} ({status}){' — ' + city if city else ''}")
        except Exception as e:
            click.echo(f"Error: {e}", err=True)


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
    fmt = ctx.obj["format"]

    try:
        images = client.get(f"/chameleon/sites/{site}/images")
        if fmt == "json":
            click.echo(json.dumps(images, indent=2))
        else:
            click.echo(f"Images at {site}: ({len(images)} available)")
            for img in images[:30]:
                size = f" ({img['size_mb']} MB)" if img.get("size_mb") else ""
                click.echo(f"  {img['name']}{size}")
            if len(images) > 30:
                click.echo(f"  ... and {len(images) - 30} more")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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
    fmt = ctx.obj["format"]

    try:
        params = {"site": site} if site else {}
        data = client.get("/chameleon/leases", params=params)
        if fmt == "json":
            click.echo(json.dumps(data, indent=2))
        else:
            if not data:
                click.echo("No leases found.")
                return
            click.echo(f"Leases ({len(data)}):")
            for l in data:
                status = l.get("status", "?")
                name = l.get("name", "?")
                site_name = l.get("_site", "?")
                start = l.get("start_date", "")[:16]
                end = l.get("end_date", "")[:16]
                click.echo(f"  {name} ({status}) @ {site_name}  [{start} → {end}]")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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

    try:
        result = client.post("/chameleon/leases", json={
            "site": site,
            "name": name,
            "node_type": node_type,
            "node_count": count,
            "duration_hours": hours,
        })
        lease_id = result.get("id", "?")
        status = result.get("status", "?")
        click.echo(f"Lease created: {name} ({lease_id}) — {status}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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

    try:
        client.delete(f"/chameleon/leases/{lease_id}", params={"site": site})
        click.echo(f"Lease {lease_id} deleted.")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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

    try:
        client.put(f"/chameleon/leases/{lease_id}/extend", json={"site": site, "hours": hours})
        click.echo(f"Lease {lease_id} extended by {hours} hour(s).")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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
    fmt = ctx.obj["format"]

    try:
        params = {"site": site} if site else {}
        data = client.get("/chameleon/instances", params=params)
        if fmt == "json":
            click.echo(json.dumps(data, indent=2))
        else:
            if not data:
                click.echo("No instances found.")
                return
            click.echo(f"Instances ({len(data)}):")
            for i in data:
                name = i.get("name", "?")
                status = i.get("status", "?")
                site_name = i.get("site", "?")
                ip = i.get("floating_ip") or ", ".join(i.get("ip_addresses", []))
                click.echo(f"  {name} ({status}) @ {site_name}  IP: {ip or 'none'}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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

    try:
        result = client.post("/chameleon/instances", json=body)
        instance_id = result.get("id", "?")
        click.echo(f"Instance created: {name} ({instance_id})")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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

    try:
        client.delete(f"/chameleon/instances/{instance_id}", params={"site": site})
        click.echo(f"Instance {instance_id} deleted.")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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

    try:
        client.post(f"/chameleon/instances/{instance_id}/reboot", json={"site": site, "type": reboot_type})
        click.echo(f"Instance {instance_id} rebooting ({reboot_type}).")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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

    try:
        client.post(f"/chameleon/instances/{instance_id}/stop", json={"site": site})
        click.echo(f"Instance {instance_id} stopping.")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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

    try:
        client.post(f"/chameleon/instances/{instance_id}/start", json={"site": site})
        click.echo(f"Instance {instance_id} starting.")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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
    fmt = ctx.obj["format"]

    try:
        params = {"site": site} if site else {}
        data = client.get("/chameleon/networks", params=params)
        if fmt == "json":
            click.echo(json.dumps(data, indent=2))
        else:
            if not data:
                click.echo("No networks found.")
                return
            click.echo(f"Networks ({len(data)}):")
            for n in data:
                name = n.get("name", "?")
                site_name = n.get("site", "?")
                status = n.get("status", "?")
                shared = "shared" if n.get("shared") else "private"
                subnets = ", ".join(
                    s.get("cidr", s.get("name", "?"))
                    for s in n.get("subnet_details", [])
                ) or "none"
                click.echo(f"  {name} ({status}, {shared}) @ {site_name}  subnets: {subnets}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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

    try:
        body = {"site": site, "name": name}
        if cidr:
            body["cidr"] = cidr
        result = client.post("/chameleon/networks", json=body)
        net_id = result.get("id", "?")
        click.echo(f"Network created: {name} ({net_id})")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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

    try:
        client.delete(f"/chameleon/networks/{network_id}", params={"site": site})
        click.echo(f"Network {network_id} deleted.")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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
    fmt = ctx.obj["format"]

    try:
        params = {"site": site} if site else {}
        data = client.get("/chameleon/keypairs", params=params)
        if fmt == "json":
            click.echo(json.dumps(data, indent=2))
        else:
            if not data:
                click.echo("No key pairs found.")
                return
            click.echo(f"Key Pairs ({len(data)}):")
            for kp in data:
                name = kp.get("name", "?")
                site_name = kp.get("_site", "?")
                fp = kp.get("fingerprint", "")
                ktype = kp.get("type", "")
                click.echo(f"  {name} @ {site_name}  {ktype}  {fp}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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

    try:
        body = {"site": site, "name": name}
        if public_key:
            body["public_key"] = public_key
        result = client.post("/chameleon/keypairs", json=body)
        click.echo(f"Key pair created: {name}")
        if result.get("private_key"):
            click.echo("Private key (save this — it won't be shown again):")
            click.echo(result["private_key"])
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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

    try:
        client.delete(f"/chameleon/keypairs/{name}", params={"site": site})
        click.echo(f"Key pair '{name}' deleted.")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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

    try:
        results = client.post("/chameleon/test", json={"site": site})
        for site_name, r in results.items():
            status = "OK" if r.get("ok") else "FAILED"
            latency = f" ({r['latency_ms']}ms)" if r.get("latency_ms") else ""
            error = f" — {r['error']}" if r.get("error") else ""
            click.echo(f"  {site_name}: {status}{latency}{error}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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
    fmt = ctx.obj["format"]

    try:
        params = {"site": site} if site else {}
        data = client.get("/chameleon/floating-ips", params=params)
        if fmt == "json":
            click.echo(json.dumps(data, indent=2))
        else:
            if not data:
                click.echo("No floating IPs found.")
                return
            click.echo(f"Floating IPs ({len(data)}):")
            for fip in data:
                ip = fip.get("floating_ip_address", "?")
                status = fip.get("status", "?")
                site_name = fip.get("_site", "?")
                port = fip.get("port_id") or "unassociated"
                click.echo(f"  {ip} ({status}) @ {site_name}  port: {port[:12]}{'...' if len(str(port)) > 12 else ''}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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

    try:
        result = client.post("/chameleon/floating-ips", json={"site": site, "network": network})
        ip = result.get("floating_ip_address", "?")
        fip_id = result.get("id", "?")
        click.echo(f"Allocated: {ip} ({fip_id})")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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

    try:
        result = client.post(f"/chameleon/floating-ips/{ip_id}/associate", json={"site": site, "port_id": port_id})
        ip = result.get("floating_ip_address", "?")
        click.echo(f"Associated {ip} with port {port_id[:12]}...")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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

    try:
        client.post(f"/chameleon/instances/{instance_id}/disassociate-ip", json={"site": site, "floating_ip": floating_ip})
        click.echo(f"Disassociated {floating_ip} from instance {instance_id[:12]}...")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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

    try:
        client.delete(f"/chameleon/floating-ips/{ip_id}", params={"site": site})
        click.echo(f"Floating IP {ip_id} released.")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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
    fmt = ctx.obj["format"]

    try:
        params = {"site": site} if site else {}
        data = client.get("/chameleon/security-groups", params=params)
        if fmt == "json":
            click.echo(json.dumps(data, indent=2))
        else:
            if not data:
                click.echo("No security groups found.")
                return
            click.echo(f"Security Groups ({len(data)}):")
            for sg in data:
                name = sg.get("name", "?")
                site_name = sg.get("_site", "?")
                desc = sg.get("description", "")
                rules = len(sg.get("security_group_rules", []))
                click.echo(f"  {name} @ {site_name}  {rules} rules  {desc[:40]}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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

    try:
        result = client.post("/chameleon/security-groups", json={"site": site, "name": name, "description": description})
        sg_id = result.get("id", "?")
        click.echo(f"Security group created: {name} ({sg_id})")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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

    try:
        client.delete(f"/chameleon/security-groups/{sg_id}", params={"site": site})
        click.echo(f"Security group {sg_id} deleted.")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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

    try:
        result = client.post(f"/chameleon/security-groups/{sg_id}/rules", json=body)
        rule_id = result.get("id", "?")
        click.echo(f"Rule added: {direction} {protocol or 'any'} {port_min or ''}-{port_max or ''} ({rule_id})")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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

    try:
        client.delete(f"/chameleon/security-groups/{sg_id}/rules/{rule_id}", params={"site": site})
        click.echo(f"Rule {rule_id} deleted.")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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
    fmt = ctx.obj["format"]

    try:
        data = client.get("/chameleon/slices")
        if fmt == "json":
            click.echo(json.dumps(data, indent=2))
        else:
            if not data:
                click.echo("No slices found.")
                return
            click.echo(f"Chameleon Slices ({len(data)}):")
            for s in data:
                name = s.get("name", "?")
                site_name = s.get("site", "?")
                res_count = len(s.get("resources", []))
                state = s.get("state", "?")
                click.echo(f"  {name} ({state}) @ {site_name}  {res_count} resources  id: {s.get('id', '?')[:16]}...")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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

    try:
        result = client.post("/chameleon/slices", json={"name": name, "site": site})
        slice_id = result.get("id", "?")
        click.echo(f"Slice created: {name} ({slice_id})")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


@slices.command("delete")
@click.argument("slice_id")
@click.pass_context
def slices_delete(ctx, slice_id):
    """Delete a Chameleon slice.

    Examples:

      loomai chameleon slices delete <slice-id>
    """
    client = ctx.obj["client"]

    try:
        client.delete(f"/chameleon/slices/{slice_id}")
        click.echo(f"Slice {slice_id} deleted.")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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

    try:
        result = client.post(f"/chameleon/slices/{slice_id}/add-resource", json=body)
        count = len(result.get("resources", []))
        click.echo(f"Resource added to slice. Total resources: {count}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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

    try:
        result = client.post(f"/chameleon/slices/{slice_id}/remove-resource", json={"resource_id": resource_id})
        count = len(result.get("resources", []))
        click.echo(f"Resource removed. Remaining resources: {count}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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
    fmt = ctx.obj["format"]

    try:
        data = client.get("/chameleon/drafts")
        if fmt == "json":
            click.echo(json.dumps(data, indent=2))
        else:
            if not data:
                click.echo("No drafts found.")
                return
            click.echo(f"Drafts ({len(data)}):")
            for d in data:
                name = d.get("name", "?")
                site_name = d.get("site", "?")
                nodes = len(d.get("nodes", []))
                nets = len(d.get("networks", []))
                click.echo(f"  {name} @ {site_name}  {nodes} nodes, {nets} networks  id: {d.get('id', '?')[:16]}...")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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

    try:
        result = client.post("/chameleon/drafts", json={"name": name, "site": site})
        draft_id = result.get("id", "?")
        click.echo(f"Draft created: {name} ({draft_id})")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


@drafts.command("delete")
@click.argument("draft_id")
@click.pass_context
def drafts_delete(ctx, draft_id):
    """Delete a Chameleon draft.

    Examples:

      loomai chameleon drafts delete <draft-id>
    """
    client = ctx.obj["client"]

    try:
        client.delete(f"/chameleon/drafts/{draft_id}")
        click.echo(f"Draft {draft_id} deleted.")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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

    try:
        result = client.post(f"/chameleon/drafts/{draft_id}/nodes", json={
            "name": name, "node_type": node_type, "image": image,
        })
        nodes = result.get("nodes", [])
        click.echo(f"Node '{name}' added. Total nodes: {len(nodes)}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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

    try:
        client.delete(f"/chameleon/drafts/{draft_id}/nodes/{node_id}")
        click.echo(f"Node {node_id} removed.")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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

    try:
        result = client.post(f"/chameleon/drafts/{draft_id}/networks", json=body)
        nets = result.get("networks", [])
        click.echo(f"Network '{name}' added. Total networks: {len(nets)}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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

    try:
        client.delete(f"/chameleon/drafts/{draft_id}/networks/{network_id}")
        click.echo(f"Network {network_id} removed.")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


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

    try:
        result = client.post(f"/chameleon/drafts/{draft_id}/deploy", json=body)
        click.echo(f"Deployment started.")
        if result.get("lease_id"):
            click.echo(f"  Lease: {result['lease_id']}")
        if result.get("instances"):
            for inst in result["instances"]:
                click.echo(f"  Instance: {inst.get('name', '?')} ({inst.get('id', '?')[:12]}...)")
        if result.get("error"):
            click.echo(f"  Warning: {result['error']}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
