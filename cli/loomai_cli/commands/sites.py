"""Site and resource discovery commands."""

from __future__ import annotations

import click
from loomai_cli.completions import SITE

from loomai_cli.output import output, output_message


@click.group()
def sites():
    """Query FABRIC sites and resource availability."""


@sites.command("list")
@click.option("--available", is_flag=True, help="Only show sites with state=Active.")
@click.option("--has-gpu", is_flag=True, help="Only show sites with GPU components.")
@click.option("--min-cores", type=int, help="Minimum available cores.")
@click.option("--min-ram", type=int, help="Minimum available RAM (GB).")
@click.pass_context
def list_sites(ctx, available, has_gpu, min_cores, min_ram):
    """List all FABRIC sites with resource availability.

    Examples:

      loomai sites list

      loomai sites list --available --min-cores 16

      loomai sites list --has-gpu

      loomai --format json sites list
    """
    client = ctx.obj["client"]
    data = client.get("/sites", params={"max_age": 0})

    # Client-side filters
    if available:
        data = [s for s in data if s.get("state") == "Active"]
    if has_gpu:
        data = [s for s in data
                if any("GPU" in k for k in (s.get("components") or {}).keys())]
    if min_cores:
        data = [s for s in data if (s.get("cores_available") or 0) >= min_cores]
    if min_ram:
        data = [s for s in data if (s.get("ram_available") or 0) >= min_ram]

    output(ctx, data,
           columns=["name", "state", "cores_available", "cores_capacity",
                     "ram_available", "disk_available", "hosts"],
           headers=["Site", "State", "Cores Avail", "Cores Total",
                     "RAM Avail", "Disk Avail", "Hosts"])


@sites.command("show")
@click.argument("name", type=SITE)
@click.pass_context
def show_site(ctx, name):
    """Show detailed information about a specific site.

    Examples:

      loomai sites show RENC

      loomai --format json sites show UCSD
    """
    client = ctx.obj["client"]
    data = client.get(f"/sites/{name}")
    output(ctx, data)


@sites.command("hosts")
@click.argument("name", type=SITE)
@click.pass_context
def site_hosts(ctx, name):
    """Show per-host resource availability for a site.

    Examples:

      loomai sites hosts RENC
    """
    client = ctx.obj["client"]
    data = client.get(f"/sites/{name}/hosts")
    output(ctx, data,
           columns=["name", "cores_available", "cores_capacity",
                     "ram_available", "ram_capacity", "disk_available"],
           headers=["Host", "Cores Avail", "Cores Total",
                     "RAM Avail", "RAM Total", "Disk Avail"])


@sites.command("find")
@click.option("--cores", type=int, default=0, help="Minimum available cores.")
@click.option("--ram", type=int, default=0, help="Minimum available RAM (GB).")
@click.option("--disk", type=int, default=0, help="Minimum available disk (GB).")
@click.option("--gpu", help="Required GPU model (e.g. GPU_RTX6000, GPU_A30).")
@click.pass_context
def find_sites(ctx, cores, ram, disk, gpu):
    """Find FABRIC sites that meet resource requirements.

    Examples:

      loomai sites find --cores 8 --ram 32

      loomai sites find --gpu GPU_RTX6000

      loomai sites find --cores 16 --ram 64 --disk 500 --gpu GPU_A30
    """
    client = ctx.obj["client"]
    all_sites = client.get("/sites", params={"max_age": 0})

    matching = []
    for s in all_sites:
        if s.get("state") != "Active":
            continue
        if cores and (s.get("cores_available") or 0) < cores:
            continue
        if ram and (s.get("ram_available") or 0) < ram:
            continue
        if disk and (s.get("disk_available") or 0) < disk:
            continue
        if gpu:
            comps = s.get("components") or {}
            if not any(gpu.lower() in k.lower() for k in comps.keys()):
                continue
            gpu_comp = next((v for k, v in comps.items() if gpu.lower() in k.lower()), None)
            if gpu_comp and (gpu_comp.get("available") or 0) < 1:
                continue
        matching.append(s)

    if not matching:
        output_message("No sites match the specified requirements.")
    output(ctx, matching,
           columns=["name", "cores_available", "ram_available", "disk_available"],
           headers=["Site", "Cores", "RAM", "Disk"])
