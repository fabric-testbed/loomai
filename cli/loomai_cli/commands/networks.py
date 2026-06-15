"""Network management commands for draft slices."""

from __future__ import annotations

import click
from loomai_cli.completions import SLICE

from loomai_cli.output import output, output_message


@click.group()
def networks():
    """Manage networks in a draft slice."""


@networks.command("add")
@click.argument("slice_name", type=SLICE)
@click.argument("net_name")
@click.option("--type", "net_type", default="L2Bridge",
              type=click.Choice(["L2Bridge", "L2STS", "L2PTP", "FABNetv4", "FABNetv6"]),
              help="Network type (default: L2Bridge).")
@click.option("--interfaces", "-i", help="Comma-separated interface names (e.g. node1-nic1-p1,node2-nic1-p1).")
@click.pass_context
def add_network(ctx, slice_name, net_name, net_type, interfaces):
    """Add a network to a draft slice.

    Examples:

      loomai networks add my-slice my-net --type L2Bridge -i node1-nic1-p1,node2-nic1-p1

      loomai networks add my-slice internet --type FABNetv4
    """
    client = ctx.obj["client"]
    body: dict = {"name": net_name, "type": net_type}
    if interfaces:
        body["interfaces"] = [s.strip() for s in interfaces.split(",")]
    data = client.post(f"/slices/{slice_name}/networks", json=body)
    output_message(f"Added network '{net_name}' to slice '{slice_name}'")
    output(ctx, data)


@networks.command("update")
@click.argument("slice_name", type=SLICE)
@click.argument("net_name")
@click.option("--type", "net_type", help="Change network type.")
@click.pass_context
def update_network(ctx, slice_name, net_name, net_type):
    """Update a network in a draft slice.

    Examples:

      loomai networks update my-slice my-net --type L2STS
    """
    client = ctx.obj["client"]
    body = {}
    if net_type:
        body["type"] = net_type
    if not body:
        raise click.UsageError("Specify at least one property to update.")
    data = client.put(f"/slices/{slice_name}/networks/{net_name}", json=body)
    output_message(f"Updated network '{net_name}'")
    output(ctx, data)


@networks.command("remove")
@click.argument("slice_name", type=SLICE)
@click.argument("net_name")
@click.pass_context
def remove_network(ctx, slice_name, net_name):
    """Remove a network from a draft slice.

    Examples:

      loomai networks remove my-slice my-net
    """
    client = ctx.obj["client"]
    data = client.delete(f"/slices/{slice_name}/networks/{net_name}")
    output_message(f"Removed network '{net_name}' from slice '{slice_name}'")
    output(ctx, data)


@networks.command("add-fabnet")
@click.argument("slice_name", type=SLICE)
@click.argument("node_name")
@click.option("--type", "net_type", default="IPv4",
              type=click.Choice(["IPv4", "IPv6"]),
              help="FABNet type to attach.")
@click.pass_context
def add_fabnet(ctx, slice_name, node_name, net_type):
    """Attach a node to FABNet using FABlib's per-node helper."""
    data = ctx.obj["client"].post(
        f"/slices/{slice_name}/nodes/{node_name}/fabnet",
        json={"net_type": net_type},
    )
    if ctx.obj["format"] == "table":
        output_message(f"Attached '{node_name}' to FABNet {net_type}")
    output(ctx, data)


@networks.command("auto-configure")
@click.argument("slice_name", type=SLICE)
@click.pass_context
def auto_configure(ctx, slice_name):
    """Generate boot-config entries from assigned L3 network addresses."""
    data = ctx.obj["client"].post(f"/slices/{slice_name}/auto-configure-networks")
    if ctx.obj["format"] == "table":
        output_message(f"Auto-configured networks for '{slice_name}'")
    output(ctx, data)


@networks.group("ip-hints")
def ip_hints():
    """Manage IP hints for FABNet/L3 network interfaces."""


@ip_hints.command("get")
@click.argument("slice_name", type=SLICE)
@click.argument("net_name")
@click.pass_context
def get_ip_hints(ctx, slice_name, net_name):
    """Show saved IP hints for a network."""
    data = ctx.obj["client"].get(f"/slices/{slice_name}/networks/{net_name}/ip-hints")
    output(ctx, data)


@ip_hints.command("set")
@click.argument("slice_name", type=SLICE)
@click.argument("net_name")
@click.option("--ip", "ips", multiple=True,
              help="Set full IP for an interface, e.g. iface=10.128.1.10. Repeatable.")
@click.option("--last-octet", "last_octets", multiple=True,
              help="Set last IPv4 octet, e.g. iface=10. Repeatable.")
@click.option("--range", "ranges", multiple=True,
              help="Set last-octet range, e.g. iface=100-120. Repeatable.")
@click.pass_context
def set_ip_hints(ctx, slice_name, net_name, ips, last_octets, ranges):
    """Save IP assignment hints for a network."""
    hints = {}

    def ensure_iface(raw: str) -> tuple[str, str]:
        if "=" not in raw:
            raise click.UsageError(f"Invalid hint '{raw}' (expected iface=value)")
        iface, value = raw.split("=", 1)
        iface = iface.strip()
        if not iface:
            raise click.UsageError("Interface name cannot be empty")
        hints.setdefault(iface, {})
        return iface, value.strip()

    for raw in ips:
        iface, value = ensure_iface(raw)
        hints[iface]["ip"] = value
    for raw in last_octets:
        iface, value = ensure_iface(raw)
        try:
            hints[iface]["last_octet"] = int(value)
        except ValueError as exc:
            raise click.UsageError(f"Invalid last octet '{value}'") from exc
    for raw in ranges:
        iface, value = ensure_iface(raw)
        hints[iface]["last_octet_range"] = value

    if not hints:
        raise click.UsageError("Specify at least one --ip, --last-octet, or --range hint.")

    data = ctx.obj["client"].put(
        f"/slices/{slice_name}/networks/{net_name}/ip-hints",
        json={"hints": hints},
    )
    if ctx.obj["format"] == "table":
        output_message(f"Saved {len(hints)} IP hint(s) for '{net_name}'")
    output(ctx, data)


@ip_hints.command("apply")
@click.argument("slice_name", type=SLICE)
@click.argument("net_name")
@click.pass_context
def apply_ip_hints(ctx, slice_name, net_name):
    """Apply saved IP hints to node boot configuration."""
    data = ctx.obj["client"].post(f"/slices/{slice_name}/networks/{net_name}/apply-ip-hints")
    if ctx.obj["format"] == "table":
        output_message(f"Applied IP hints for '{net_name}'")
    output(ctx, data)


@networks.group("l3-config")
def l3_config():
    """Manage FABNet/L3 network configuration."""


@l3_config.command("get")
@click.argument("slice_name", type=SLICE)
@click.argument("net_name")
@click.pass_context
def get_l3_config(ctx, slice_name, net_name):
    """Show L3 config for a network."""
    data = ctx.obj["client"].get(f"/slices/{slice_name}/networks/{net_name}/l3-config")
    output(ctx, data)


@l3_config.command("set")
@click.argument("slice_name", type=SLICE)
@click.argument("net_name")
@click.option("--mode", default="auto", type=click.Choice(["auto", "manual", "user_octet"]),
              help="Addressing mode.")
@click.option("--route-mode", default="default_fabnet",
              type=click.Choice(["default_fabnet", "custom"]),
              help="Route generation mode.")
@click.option("--custom-route", "custom_routes", multiple=True,
              help="Custom route subnet. Repeatable.")
@click.option("--default-fabnet-subnet", default="10.128.0.0/10",
              help="Default FABNet aggregate route.")
@click.pass_context
def set_l3_config(ctx, slice_name, net_name, mode, route_mode, custom_routes, default_fabnet_subnet):
    """Save L3 config for a FABNet network."""
    data = ctx.obj["client"].put(
        f"/slices/{slice_name}/networks/{net_name}/l3-config",
        json={
            "mode": mode,
            "route_mode": route_mode,
            "custom_routes": list(custom_routes),
            "default_fabnet_subnet": default_fabnet_subnet,
        },
    )
    if ctx.obj["format"] == "table":
        output_message(f"Saved L3 config for '{net_name}'")
    output(ctx, data)
