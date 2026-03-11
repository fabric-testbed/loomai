"""Mock site availability data for testing."""

from __future__ import annotations

from typing import Any


def make_site(name: str, cores: int = 100, ram: int = 400, disk: int = 2000,
              state: str = "Active", components: dict | None = None,
              hosts: list[dict] | None = None) -> dict[str, Any]:
    """Create a mock site dict matching get_cached_sites() shape."""
    comp = components or {}
    return {
        "name": name,
        "state": state,
        "cores_available": cores,
        "ram_available": ram,
        "disk_available": disk,
        "components": comp,
        "hosts_detail": hosts or [],
        "location": {"lat": 35.0, "lon": -79.0},
    }


def make_host(name: str, cores: int = 32, ram: int = 128, disk: int = 500,
              components: dict | None = None) -> dict[str, Any]:
    """Create a mock host dict for hosts_detail."""
    return {
        "name": name,
        "cores_available": cores,
        "ram_available": ram,
        "disk_available": disk,
        "components": components or {},
    }


def make_gpu_components(rtx: int = 2, t4: int = 0) -> dict[str, Any]:
    """Create component availability dict with GPU counts."""
    return {
        "GPU-RTX6000": {"available": rtx},
        "GPU-Tesla T4": {"available": t4},
        "SmartNIC-ConnectX-5": {"available": 0},
        "SmartNIC-ConnectX-6": {"available": 0},
        "SmartNIC-ConnectX-7": {"available": 0},
        "FPGA-Xilinx-U280": {"available": 0},
        "NVME-P4510": {"available": 0},
    }


def default_sites() -> list[dict[str, Any]]:
    """Return a set of mock FABRIC sites for testing."""
    return [
        make_site("RENC", cores=200, ram=800, disk=4000, hosts=[
            make_host("renc-w1", cores=64, ram=256, disk=1000),
            make_host("renc-w2", cores=64, ram=256, disk=1000),
            make_host("renc-w3", cores=32, ram=128, disk=500),
        ]),
        make_site("UCSD", cores=150, ram=600, disk=3000,
                  components=make_gpu_components(rtx=2),
                  hosts=[
                      make_host("ucsd-w1", cores=48, ram=192, disk=800,
                                components={"GPU-RTX6000": {"available": 2}}),
                      make_host("ucsd-w2", cores=48, ram=192, disk=800),
                  ]),
        make_site("TACC", cores=100, ram=400, disk=2000,
                  components=make_gpu_components(rtx=1, t4=2),
                  hosts=[
                      make_host("tacc-w1", cores=32, ram=128, disk=500,
                                components={"GPU-RTX6000": {"available": 1},
                                            "GPU-Tesla T4": {"available": 2}}),
                      make_host("tacc-w2", cores=32, ram=128, disk=500),
                  ]),
        make_site("DALL", cores=80, ram=320, disk=1600, hosts=[
            make_host("dall-w1", cores=32, ram=128, disk=500),
            make_host("dall-w2", cores=32, ram=128, disk=500),
        ]),
        make_site("STAR", cores=60, ram=240, disk=1200, hosts=[
            make_host("star-w1", cores=32, ram=128, disk=500),
        ]),
        # Maintenance site — should be excluded by resolver
        make_site("MAINT", cores=100, ram=400, disk=2000, state="Maintenance"),
    ]


def minimal_sites() -> list[dict[str, Any]]:
    """Return a minimal set with just one site (for simple tests)."""
    return [
        make_site("RENC", cores=100, ram=400, disk=2000),
    ]


def constrained_sites() -> list[dict[str, Any]]:
    """Return sites with limited resources for constraint testing."""
    return [
        make_site("SMALL", cores=4, ram=16, disk=40, hosts=[
            make_host("small-w1", cores=4, ram=16, disk=40),
        ]),
        make_site("BIG", cores=64, ram=256, disk=1000, hosts=[
            make_host("big-w1", cores=64, ram=256, disk=1000),
        ]),
    ]


def gpu_only_sites() -> list[dict[str, Any]]:
    """Return sites where only one has GPUs."""
    return [
        make_site("NO-GPU", cores=100, ram=400, disk=2000, hosts=[
            make_host("nogpu-w1", cores=32, ram=128, disk=500),
        ]),
        make_site("HAS-GPU", cores=100, ram=400, disk=2000,
                  components=make_gpu_components(rtx=2),
                  hosts=[
                      make_host("hasgpu-w1", cores=32, ram=128, disk=500,
                                components={"GPU-RTX6000": {"available": 2}}),
                  ]),
    ]
