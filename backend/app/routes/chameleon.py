"""Chameleon Cloud routes — sites, leases, instances, and draft topologies.

All endpoints are gated by the ``chameleon.enabled`` setting. When disabled,
every route returns 404 so the frontend never sees Chameleon data.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.chameleon_executor import run_in_chi_pool
from app.chameleon_manager import (
    CHAMELEON_SITE_LOCATIONS,
    get_configured_sites,
    get_session,
    is_configured,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chameleon"])


def _chameleon_key_dir() -> str:
    return os.environ.get("FABRIC_CONFIG_DIR", "/home/fabric/work/fabric_config")


def get_chameleon_key_path(site: str) -> str:
    """Return the path to the Chameleon SSH private key for a site, if it exists.

    Checks per-site key first (``chameleon_key_CHI@TACC``), then generic
    (``chameleon_key``). Returns empty string if no key found.
    """
    config_dir = _chameleon_key_dir()
    # Per-site key: chameleon_key_CHI@TACC
    site_key = os.path.join(config_dir, f"chameleon_key_{site}")
    if os.path.isfile(site_key):
        return site_key
    # Generic fallback (legacy)
    generic = os.path.join(config_dir, "chameleon_key")
    if os.path.isfile(generic):
        return generic
    return ""


def ensure_routable_network(site: str) -> dict[str, str]:
    """Ensure a network with external routing exists at a Chameleon site.

    For floating IPs to work, the instance must be on a network that has a path
    to the external (public) network. Provider networks like ``sharednet1`` work
    automatically. Other networks need a router.

    Returns ``{"network_id": ..., "network_name": ..., "type": "provider"|"routed"}``.
    Prefers ``sharednet1`` if available. If only tenant networks exist, creates
    ``loomai-net`` + subnet + router to the public network.
    """
    session = get_session(site)
    nets = session.api_get("network", "/v2.0/networks")
    networks = nets.get("networks", [])

    # Prefer sharednet1 (provider network — floating IPs work without router)
    for n in networks:
        if n.get("shared") and "sharednet" in n.get("name", "").lower():
            return {"network_id": n["id"], "network_name": n["name"], "type": "provider"}

    # Check for our own loomai-net with a router
    for n in networks:
        if n.get("name") == "loomai-net":
            # Verify it has a router
            routers = session.api_get("network", "/v2.0/routers")
            for r in routers.get("routers", []):
                if r.get("name") == "loomai-router" and r.get("external_gateway_info"):
                    return {"network_id": n["id"], "network_name": "loomai-net", "type": "routed"}

    # No routable network found — create loomai-net + subnet + router
    logger.info("Creating routable network (loomai-net) at %s", site)

    # Find public network
    public_net_id = None
    for n in networks:
        if n.get("router:external") or n.get("name", "").lower() == "public":
            public_net_id = n["id"]
            break
    if not public_net_id:
        raise RuntimeError(f"No external network found at {site}")

    # Create network
    net_resp = session.api_post("network", "/v2.0/networks", {
        "network": {"name": "loomai-net"}
    })
    net = net_resp.get("network", net_resp)
    net_id = net["id"]

    # Create subnet
    sub_resp = session.api_post("network", "/v2.0/subnets", {
        "subnet": {
            "network_id": net_id,
            "name": "loomai-subnet",
            "cidr": "192.168.100.0/24",
            "ip_version": 4,
            "enable_dhcp": True,
            "gateway_ip": "192.168.100.1",
        }
    })
    sub = sub_resp.get("subnet", sub_resp)

    # Create router with public gateway
    router_resp = session.api_post("network", "/v2.0/routers", {
        "router": {
            "name": "loomai-router",
            "external_gateway_info": {"network_id": public_net_id},
        }
    })
    router = router_resp.get("router", router_resp)

    # Attach subnet to router
    session.api_put("network", f"/v2.0/routers/{router['id']}/add_router_interface", {
        "subnet_id": sub["id"],
    })

    logger.info("Created routable network at %s: net=%s router=%s", site, net_id[:12], router["id"][:12])
    return {"network_id": net_id, "network_name": "loomai-net", "type": "routed"}


def _save_chameleon_key(site: str, private_key: str) -> str:
    """Save a Chameleon SSH private key for a specific site. Returns the path."""
    config_dir = _chameleon_key_dir()
    os.makedirs(config_dir, exist_ok=True)
    key_path = os.path.join(config_dir, f"chameleon_key_{site}")
    with open(key_path, "w") as f:
        f.write(private_key)
    os.chmod(key_path, 0o600)
    logger.info("Saved Chameleon SSH key for %s to %s", site, key_path)
    return key_path

# ---------------------------------------------------------------------------
# In-memory Chameleon slices (composite resource groups, including drafts)
# ---------------------------------------------------------------------------
_chameleon_slices: dict[str, dict] = {}


def _slices_path() -> str:
    """Path to persisted Chameleon slices JSON file."""
    storage = os.environ.get("FABRIC_STORAGE_DIR", "/home/fabric/work")
    return os.path.join(storage, ".loomai", "chameleon_slices.json")


def _persist_slices() -> None:
    """Atomically write _chameleon_slices to disk."""
    path = _slices_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(_chameleon_slices, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def load_chameleon_slices() -> None:
    """Load persisted Chameleon slices from disk (called on startup)."""
    path = _slices_path()
    if os.path.isfile(path):
        try:
            with open(path) as f:
                data = json.load(f)
            _chameleon_slices.update(data)
            # Add defaults for new fields (backward compat)
            for s in _chameleon_slices.values():
                s.setdefault("nodes", [])
                s.setdefault("networks", [])
                s.setdefault("floating_ips", [])
                s.setdefault("resources", [])
                s.setdefault("state", "Active")  # Existing deployed slices default to Active
            logger.info("Loaded %d Chameleon slices from %s", len(data), path)
        except Exception:
            logger.warning("Failed to load Chameleon slices from %s", path, exc_info=True)


def _is_uuid(value: str) -> bool:
    """Check if a string looks like a UUID."""
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


# ---------------------------------------------------------------------------
# Middleware: check Chameleon is enabled
# ---------------------------------------------------------------------------

def _require_enabled() -> None:
    """Raise 404 if Chameleon integration is disabled."""
    from app import settings_manager
    if not settings_manager.is_chameleon_enabled():
        raise HTTPException(status_code=404, detail="Chameleon integration is disabled")


def _int_or(value: Any, default: int = 0) -> int:
    """Safely cast *value* to int, returning *default* on failure."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


async def _fetch_live_instances(sites: set[str]) -> list[dict]:
    """Fetch live instance data from Nova for the given sites."""
    def _fetch():
        all_instances: list[dict] = []
        for s in sites:
            try:
                session = get_session(s)
                result = session.api_get("compute", "/servers/detail")
                for srv in result.get("servers", []):
                    ips: list[str] = []
                    floating_ip = None
                    for net_name, addrs in srv.get("addresses", {}).items():
                        for addr in addrs:
                            ip = addr.get("addr", "")
                            if addr.get("OS-EXT-IPS:type") == "floating":
                                floating_ip = ip
                            else:
                                ips.append(ip)
                    all_instances.append({
                        "id": srv["id"],
                        "name": srv["name"],
                        "site": s,
                        "status": srv.get("status", "UNKNOWN"),
                        "ip_addresses": ips,
                        "floating_ip": floating_ip,
                    })
            except Exception as e:
                logger.warning("Live graph: could not fetch instances from %s: %s", s, e)
        return all_instances
    return await run_in_chi_pool(_fetch)


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

@router.get("/api/chameleon/status")
async def chameleon_status():
    """Return Chameleon integration status and configured sites."""
    from app import settings_manager
    enabled = settings_manager.is_chameleon_enabled()
    sites = {}
    if enabled:
        for name in settings_manager.get_chameleon_sites():
            configured = settings_manager.is_chameleon_site_configured(name)
            sites[name] = {"configured": configured}
    return {
        "enabled": enabled,
        "configured": is_configured() if enabled else False,
        "sites": sites,
    }


# ---------------------------------------------------------------------------
# Sites & Resources
# ---------------------------------------------------------------------------

@router.get("/api/chameleon/sites")
async def list_chameleon_sites():
    """List Chameleon sites with location and configuration status."""
    _require_enabled()
    from app import settings_manager

    result = []
    for name, cfg in settings_manager.get_chameleon_sites().items():
        loc = CHAMELEON_SITE_LOCATIONS.get(name, {})
        configured = settings_manager.is_chameleon_site_configured(name)
        result.append({
            "name": name,
            "auth_url": cfg.get("auth_url", ""),
            "configured": configured,
            "location": loc,
        })
    return result


@router.post("/api/chameleon/sites/{site}/ensure-network")
async def ensure_network(site: str):
    """Ensure a routable network exists at a site for floating IP access.

    Returns the network ID to use for instance creation.
    """
    _require_enabled()

    def _do():
        return ensure_routable_network(site)

    try:
        return await run_in_chi_pool(_do)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.get("/api/chameleon/sites/{site}/availability")
async def site_availability(site: str):
    """List available node types at a Chameleon site."""
    _require_enabled()

    def _fetch():
        session = get_session(site)
        # Query Blazar for host information
        try:
            hosts = session.api_get("reservation", "/os-hosts")
            host_list = hosts.get("hosts", [])
        except Exception as e:
            logger.warning("Chameleon %s: could not fetch hosts: %s", site, e)
            host_list = []

        # Query Nova for flavors as fallback/supplement
        try:
            flavors = session.api_get("compute", "/flavors/detail")
            flavor_list = flavors.get("flavors", [])
        except Exception as e:
            logger.warning("Chameleon %s: could not fetch flavors: %s", site, e)
            flavor_list = []

        return {"hosts": host_list, "flavors": flavor_list, "site": site}

    return await run_in_chi_pool(_fetch)


@router.get("/api/chameleon/sites/{site}/node-types")
async def site_node_types(site: str):
    """List available node types at a Chameleon site with counts."""
    _require_enabled()

    def _fetch():
        session = get_session(site)
        try:
            hosts = session.api_get("reservation", "/os-hosts")
            host_list = hosts.get("hosts", [])
        except Exception:
            host_list = []

        # Group by node_type
        type_counts: dict[str, dict] = {}
        for h in host_list:
            ntype = h.get("node_type", "unknown")
            if ntype not in type_counts:
                type_counts[ntype] = {
                    "node_type": ntype,
                    "total": 0,
                    "reservable": 0,
                    "cpu_arch": h.get("cpu_arch", ""),
                }
            type_counts[ntype]["total"] += 1
            if h.get("reservable"):
                type_counts[ntype]["reservable"] += 1

        # Sort by name
        result = sorted(type_counts.values(), key=lambda x: x["node_type"])
        return {"site": site, "node_types": result}

    return await run_in_chi_pool(_fetch)


@router.get("/api/chameleon/sites/{site}/images")
async def site_images(site: str):
    """List available OS images at a Chameleon site."""
    _require_enabled()

    def _fetch():
        session = get_session(site)
        # Paginate through all images (Glance uses marker-based pagination)
        all_images: list[dict] = []
        url = "/v2/images?limit=200&sort_key=name&sort_dir=asc"
        for _ in range(10):  # safety limit: max 2000 images
            result = session.api_get("image", url)
            page = result.get("images", [])
            if not page:
                break
            all_images.extend(page)
            # Check for next page link
            next_link = result.get("next")
            if next_link:
                # next_link is a relative URL like /v2/images?marker=...&limit=200
                url = next_link if next_link.startswith("/") else f"/v2/images?{next_link.split('?', 1)[-1]}"
            elif len(page) < 200:
                break
            else:
                # No next link but full page — use last image as marker
                url = f"/v2/images?limit=200&sort_key=name&sort_dir=asc&marker={page[-1]['id']}"

        return [
            {
                "id": img["id"],
                "name": img["name"],
                "status": img.get("status"),
                "size_mb": round(img.get("size", 0) / 1024 / 1024) if img.get("size") else None,
                "created": img.get("created_at"),
                "architecture": img.get("hw_architecture") or img.get("architecture") or img.get("cpu_arch") or "",
            }
            for img in all_images
            if img.get("visibility") in ("public", "shared", "community")
        ]

    return await run_in_chi_pool(_fetch)


# ---------------------------------------------------------------------------
# Leases (Blazar reservation API)
# ---------------------------------------------------------------------------

@router.get("/api/chameleon/leases")
async def list_leases(site: str | None = None):
    """List leases, optionally filtered by site. If no site, lists from all configured sites."""
    _require_enabled()

    def _fetch():
        sites_to_query = [site] if site else get_configured_sites()
        all_leases = []
        for s in sites_to_query:
            try:
                session = get_session(s)
                result = session.api_get("reservation", "/leases")
                for lease in result.get("leases", []):
                    lease["_site"] = s
                    all_leases.append(lease)
            except Exception as e:
                logger.warning("Chameleon %s: could not list leases: %s", s, e)
        return all_leases

    return await run_in_chi_pool(_fetch)


@router.get("/api/chameleon/leases/{lease_id}")
async def get_lease(lease_id: str, site: str = "CHI@TACC"):
    """Get details of a specific lease."""
    _require_enabled()

    def _fetch():
        session = get_session(site)
        result = session.api_get("reservation", f"/leases/{lease_id}")
        lease = result.get("lease", result)
        lease["_site"] = site
        return lease

    return await run_in_chi_pool(_fetch)


@router.post("/api/chameleon/leases")
async def create_lease(request: Request):
    """Create a new Chameleon lease.

    Body: {
        "site": "CHI@TACC",
        "name": "my-lease",
        "node_type": "compute_haswell",
        "node_count": 1,
        "duration_hours": 4
    }
    """
    _require_enabled()
    body = await request.json()
    site = body.get("site", "CHI@TACC")
    name = body.get("name", "loomai-lease")
    node_type = body.get("node_type", "compute_haswell")
    node_count = body.get("node_count", 1)
    duration_hours = body.get("duration_hours", 4)
    start_date = body.get("start_date")  # ISO string or None for "now"
    resource_type = body.get("resource_type", "physical:host")

    def _create():
        from datetime import datetime, timedelta, timezone
        session = get_session(site)

        if start_date:
            # Future reservation
            try:
                start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            except Exception:
                start_dt = datetime.strptime(start_date, "%Y-%m-%dT%H:%M")
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            start_str = start_dt.strftime("%Y-%m-%d %H:%M")
            end_dt = start_dt + timedelta(hours=duration_hours)
        else:
            start_str = "now"
            end_dt = datetime.now(timezone.utc) + timedelta(hours=duration_hours)

        # Build reservation based on resource type
        if resource_type == "physical:host":
            reservation = {
                "resource_type": "physical:host",
                "resource_properties": json.dumps(["==", "$node_type", node_type]),
                "min": node_count,
                "max": node_count,
                "hypervisor_properties": "",
            }
        elif resource_type == "network":
            reservation = {
                "resource_type": "network",
                "network_name": body.get("network_name", f"{name}-net"),
                "network_properties": "",
                "resource_properties": json.dumps([]),
            }
        elif resource_type == "virtual:floatingip":
            reservation = {
                "resource_type": "virtual:floatingip",
                "network_id": body.get("network_id", ""),
                "amount": node_count,
            }
        else:
            reservation = {
                "resource_type": resource_type,
                "resource_properties": json.dumps(["==", "$node_type", node_type]) if node_type else "[]",
                "min": node_count,
                "max": node_count,
            }

        lease_body = {
            "name": name,
            "start_date": start_str,
            "end_date": end_dt.strftime("%Y-%m-%d %H:%M"),
            "reservations": [reservation],
            "events": [],
        }
        result = session.api_post("reservation", "/leases", lease_body)
        lease = result.get("lease", result)
        lease["_site"] = site
        return lease

    try:
        return await run_in_chi_pool(_create)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.put("/api/chameleon/leases/{lease_id}/extend")
async def extend_lease(lease_id: str, request: Request):
    """Extend a lease duration.

    Body: {"site": "CHI@TACC", "hours": 2}
    """
    _require_enabled()
    body = await request.json()
    site = body.get("site", "CHI@TACC")
    hours = body.get("hours", 1)

    def _extend():
        session = get_session(site)
        # Get current lease to find end_date
        current = session.api_get("reservation", f"/leases/{lease_id}")
        lease = current.get("lease", current)
        from datetime import datetime, timedelta, timezone
        end_date = lease.get("end_date", "")
        try:
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        except Exception:
            end_dt = datetime.now(timezone.utc)
        new_end = end_dt + timedelta(hours=hours)
        update_body = {"end_date": new_end.strftime("%Y-%m-%d %H:%M")}
        result = session.api_put("reservation", f"/leases/{lease_id}", update_body)
        return result.get("lease", result)

    try:
        return await run_in_chi_pool(_extend)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.delete("/api/chameleon/leases/{lease_id}")
async def delete_lease(lease_id: str, site: str = "CHI@TACC"):
    """Delete a lease."""
    _require_enabled()

    def _delete():
        session = get_session(site)
        session.api_delete("reservation", f"/leases/{lease_id}")
        return {"status": "deleted", "lease_id": lease_id}

    try:
        return await run_in_chi_pool(_delete)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# ---------------------------------------------------------------------------
# Instances (Nova compute API)
# ---------------------------------------------------------------------------

@router.get("/api/chameleon/instances")
async def list_instances(site: str | None = None):
    """List instances, optionally filtered by site."""
    _require_enabled()

    def _fetch():
        sites_to_query = [site] if site else get_configured_sites()
        all_instances = []
        for s in sites_to_query:
            try:
                session = get_session(s)
                result = session.api_get("compute", "/servers/detail")
                for srv in result.get("servers", []):
                    # Extract IPs
                    ips = []
                    floating_ip = None
                    for net_name, addrs in srv.get("addresses", {}).items():
                        for addr in addrs:
                            ip = addr.get("addr", "")
                            if addr.get("OS-EXT-IPS:type") == "floating":
                                floating_ip = ip
                            else:
                                ips.append(ip)
                    all_instances.append({
                        "id": srv["id"],
                        "name": srv["name"],
                        "site": s,
                        "status": srv.get("status", "UNKNOWN"),
                        "image": srv.get("image", {}).get("id", ""),
                        "created": srv.get("created"),
                        "ip_addresses": ips,
                        "floating_ip": floating_ip,
                    })
            except Exception as e:
                logger.warning("Chameleon %s: could not list instances: %s", s, e)
        return all_instances

    return await run_in_chi_pool(_fetch)


@router.get("/api/chameleon/instances/unaffiliated")
async def list_unaffiliated_instances():
    """List Chameleon instances not tracked in any slice's resources."""
    _require_enabled()

    # Collect all instance IDs tracked in any slice's resources
    tracked_ids: set[str] = set()
    for s in _chameleon_slices.values():
        for res in s.get("resources", []):
            if res.get("type") == "instance" and res.get("id"):
                tracked_ids.add(res["id"])

    def _fetch():
        sites_to_query = get_configured_sites()
        all_instances = []
        for site_name in sites_to_query:
            try:
                session = get_session(site_name)
                result = session.api_get("compute", "/servers/detail")
                for srv in result.get("servers", []):
                    if srv["id"] in tracked_ids:
                        continue
                    ips = []
                    floating_ip = None
                    for net_name, addrs in srv.get("addresses", {}).items():
                        for addr in addrs:
                            ip = addr.get("addr", "")
                            if addr.get("OS-EXT-IPS:type") == "floating":
                                floating_ip = ip
                            else:
                                ips.append(ip)
                    all_instances.append({
                        "id": srv["id"],
                        "name": srv["name"],
                        "site": site_name,
                        "status": srv.get("status", "UNKNOWN"),
                        "image": srv.get("image", {}).get("id", ""),
                        "created": srv.get("created"),
                        "ip_addresses": ips,
                        "floating_ip": floating_ip,
                    })
            except Exception as e:
                logger.warning("Chameleon %s: could not list instances: %s", site_name, e)
        return all_instances

    return await run_in_chi_pool(_fetch)


@router.get("/api/chameleon/instances/{instance_id}")
async def get_instance(instance_id: str, site: str = "CHI@TACC"):
    """Get details of a specific instance."""
    _require_enabled()

    def _fetch():
        session = get_session(site)
        result = session.api_get("compute", f"/servers/{instance_id}")
        srv = result.get("server", result)
        srv["_site"] = site
        return srv

    return await run_in_chi_pool(_fetch)


@router.post("/api/chameleon/instances")
async def create_instance(request: Request):
    """Launch a Chameleon instance on a lease.

    Body: {
        "site": "CHI@TACC",
        "name": "my-instance",
        "lease_id": "...",
        "reservation_id": "...",
        "image_id": "...",
        "key_name": "...",       (optional)
        "network_id": "..."      (optional)
    }
    """
    _require_enabled()
    body = await request.json()
    site = body.get("site", "CHI@TACC")

    def _create():
        session = get_session(site)

        # Look up baremetal flavor ID (some sites need UUID, not name)
        flavor_ref = "baremetal"
        try:
            flavors_resp = session.api_get("compute", "/flavors")
            for flv in flavors_resp.get("flavors", []):
                if flv.get("name") == "baremetal":
                    flavor_ref = flv["id"]
                    break
        except Exception:
            pass

        # Resolve image name to UUID if needed (Nova requires UUID, not name)
        image_ref = body.get("image_id", "")
        if image_ref and not _is_uuid(image_ref):
            from urllib.parse import quote
            try:
                images_resp = session.api_get("image", f"/v2/images?name={quote(image_ref)}&limit=5")
                for img in images_resp.get("images", []):
                    if img.get("name") == image_ref:
                        image_ref = img["id"]
                        break
            except Exception:
                logger.warning("Failed to resolve image name %r to UUID", image_ref)

        server_body: dict[str, Any] = {
            "server": {
                "name": body.get("name", "loomai-instance"),
                "imageRef": image_ref,
                "flavorRef": flavor_ref,
                "min_count": 1,
                "max_count": 1,
            }
        }

        # Add reservation scheduler hint (top-level, NOT inside "server")
        reservation_id = body.get("reservation_id", "")
        if reservation_id:
            server_body["os:scheduler_hints"] = {
                "reservation": reservation_id,
            }

        # Add key pair
        if body.get("key_name"):
            server_body["server"]["key_name"] = body["key_name"]

        # Add network(s) — supports single or multiple
        if body.get("network_ids"):
            server_body["server"]["networks"] = [{"uuid": nid} for nid in body["network_ids"]]
        elif body.get("network_id"):
            server_body["server"]["networks"] = [{"uuid": body["network_id"]}]

        # Add security groups
        if body.get("security_groups"):
            server_body["server"]["security_groups"] = [{"name": sg} for sg in body["security_groups"]]

        result = session.api_post("compute", "/servers", server_body)
        srv = result.get("server", result)
        srv["_site"] = site
        return srv

    try:
        return await run_in_chi_pool(_create)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.delete("/api/chameleon/instances/{instance_id}")
async def delete_instance(instance_id: str, site: str = "CHI@TACC"):
    """Terminate an instance."""
    _require_enabled()

    def _delete():
        session = get_session(site)
        session.api_delete("compute", f"/servers/{instance_id}")
        return {"status": "deleted", "instance_id": instance_id}

    try:
        return await run_in_chi_pool(_delete)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post("/api/chameleon/instances/{instance_id}/associate-ip")
async def associate_floating_ip(instance_id: str, request: Request):
    """Allocate and associate a floating IP with an instance via Neutron.

    Body: {"site": "CHI@TACC"}
    Finds the external network, gets the instance port, allocates a floating IP,
    and associates it to the port in one Neutron call.
    """
    _require_enabled()
    body = await request.json()
    site = body.get("site", "CHI@TACC")

    def _associate():
        session = get_session(site)

        # Find external (public) network
        nets = session.api_get("network", "/v2.0/networks")
        ext_net_id = None
        for net in nets.get("networks", []):
            if net.get("router:external") or net.get("name", "").lower() == "public":
                ext_net_id = net["id"]
                break
        if not ext_net_id:
            raise RuntimeError("No external network found for floating IP allocation")

        # Find instance port
        ports = session.api_get("network", f"/v2.0/ports?device_id={instance_id}")
        port_id = None
        for p in ports.get("ports", []):
            port_id = p["id"]
            break
        if not port_id:
            raise RuntimeError(f"No port found for instance {instance_id}")

        # Allocate and associate in one call
        fip_resp = session.api_post("network", "/v2.0/floatingips", {
            "floatingip": {
                "floating_network_id": ext_net_id,
                "port_id": port_id,
            }
        })
        fip_data = fip_resp.get("floatingip", fip_resp)
        floating_ip = fip_data.get("floating_ip_address", "")

        return {"instance_id": instance_id, "floating_ip": floating_ip, "fip_id": fip_data.get("id", "")}

    try:
        return await run_in_chi_pool(_associate)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post("/api/chameleon/instances/{instance_id}/disassociate-ip")
async def disassociate_floating_ip(instance_id: str, request: Request):
    """Disassociate a floating IP from an instance.

    Body: {"site": "CHI@TACC", "floating_ip": "129.114.x.x"}
    """
    _require_enabled()
    body = await request.json()
    site = body.get("site", "CHI@TACC")
    floating_ip = body.get("floating_ip", "")

    def _disassociate():
        session = get_session(site)
        session.api_post("compute", f"/servers/{instance_id}/action", {
            "removeFloatingIp": {"address": floating_ip}
        })
        return {"instance_id": instance_id, "floating_ip": floating_ip, "status": "disassociated"}

    try:
        return await run_in_chi_pool(_disassociate)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post("/api/chameleon/instances/{instance_id}/reboot")
async def reboot_instance(instance_id: str, request: Request):
    """Reboot an instance.

    Body: {"site": "CHI@TACC", "type": "SOFT"|"HARD"}
    """
    _require_enabled()
    body = await request.json()
    site = body.get("site", "CHI@TACC")
    reboot_type = body.get("type", "SOFT")

    def _do():
        session = get_session(site)
        session.api_post("compute", f"/servers/{instance_id}/action", {
            "reboot": {"type": reboot_type}
        })
        return {"status": "rebooting", "instance_id": instance_id}

    try:
        return await run_in_chi_pool(_do)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post("/api/chameleon/instances/{instance_id}/stop")
async def stop_instance(instance_id: str, request: Request):
    """Stop an instance.

    Body: {"site": "CHI@TACC"}
    """
    _require_enabled()
    body = await request.json()
    site = body.get("site", "CHI@TACC")

    def _do():
        session = get_session(site)
        session.api_post("compute", f"/servers/{instance_id}/action", {
            "os-stop": None
        })
        return {"status": "stopping", "instance_id": instance_id}

    try:
        return await run_in_chi_pool(_do)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post("/api/chameleon/instances/{instance_id}/start")
async def start_instance(instance_id: str, request: Request):
    """Start a stopped instance.

    Body: {"site": "CHI@TACC"}
    """
    _require_enabled()
    body = await request.json()
    site = body.get("site", "CHI@TACC")

    def _do():
        session = get_session(site)
        session.api_post("compute", f"/servers/{instance_id}/action", {
            "os-start": None
        })
        return {"status": "starting", "instance_id": instance_id}

    try:
        return await run_in_chi_pool(_do)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# ---------------------------------------------------------------------------
# Networks (Neutron API)
# ---------------------------------------------------------------------------

@router.get("/api/chameleon/networks")
async def list_networks(site: str | None = None):
    """List networks, optionally filtered by site.

    Returns project-owned and shared networks with subnet details.
    """
    _require_enabled()

    def _fetch():
        sites_to_query = [site] if site else get_configured_sites()
        all_networks = []
        for s in sites_to_query:
            try:
                session = get_session(s)

                # Fetch networks and subnets in parallel-safe manner
                nets_data = session.api_get("network", "/v2.0/networks")
                net_list = nets_data.get("networks", [])

                subnets_data = session.api_get("network", "/v2.0/subnets")
                subnet_list = subnets_data.get("subnets", [])

                # Index subnets by ID for fast lookup
                subnet_index: dict[str, dict] = {
                    sub["id"]: sub for sub in subnet_list
                }

                project_id = session.project_id
                for net in net_list:
                    # Filter: project-owned or shared
                    if net.get("project_id") != project_id and not net.get("shared", False):
                        continue
                    subnet_details = []
                    for sid in net.get("subnets", []):
                        sub = subnet_index.get(sid)
                        if sub:
                            subnet_details.append({
                                "id": sid,
                                "cidr": sub.get("cidr", ""),
                                "name": sub.get("name", ""),
                            })
                    all_networks.append({
                        "id": net["id"],
                        "name": net.get("name", ""),
                        "site": s,
                        "status": net.get("status"),
                        "shared": net.get("shared", False),
                        "subnet_details": subnet_details,
                    })
            except Exception as e:
                logger.warning("Chameleon %s: could not list networks: %s", s, e)
        return all_networks

    return await run_in_chi_pool(_fetch)


@router.post("/api/chameleon/networks")
async def create_network(request: Request):
    """Create a Chameleon network (and optionally a subnet).

    Body: {"site": "CHI@TACC", "name": "my-net", "cidr": "192.168.1.0/24"}
    If cidr is provided, a subnet is also created.
    """
    _require_enabled()
    body = await request.json()
    site = body.get("site", "CHI@TACC")
    name = body.get("name", "loomai-net")
    cidr = body.get("cidr", "")

    def _create():
        session = get_session(site)

        # Create the network
        net_result = session.api_post("network", "/v2.0/networks", {
            "network": {"name": name, "admin_state_up": True}
        })
        net = net_result.get("network", net_result)
        net_id = net["id"]

        subnet_details = []
        if cidr:
            # Create a subnet on the new network
            sub_result = session.api_post("network", "/v2.0/subnets", {
                "subnet": {
                    "network_id": net_id,
                    "ip_version": 4,
                    "cidr": cidr,
                    "name": f"{name}-subnet",
                }
            })
            sub = sub_result.get("subnet", sub_result)
            subnet_details.append({
                "id": sub["id"],
                "cidr": sub.get("cidr", cidr),
                "name": sub.get("name", ""),
            })

        return {
            "id": net_id,
            "name": net.get("name", name),
            "site": site,
            "status": net.get("status"),
            "shared": net.get("shared", False),
            "subnet_details": subnet_details,
        }

    try:
        return await run_in_chi_pool(_create)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.delete("/api/chameleon/networks/{network_id}")
async def delete_network(network_id: str, site: str = "CHI@TACC"):
    """Delete a network."""
    _require_enabled()

    def _delete():
        session = get_session(site)
        session.api_delete("network", f"/v2.0/networks/{network_id}")
        return {"status": "deleted", "network_id": network_id}

    try:
        return await run_in_chi_pool(_delete)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# ---------------------------------------------------------------------------
# Key Pairs (Nova)
# ---------------------------------------------------------------------------

@router.get("/api/chameleon/keypairs")
async def list_keypairs(site: str = Query(None)):
    """List Nova key pairs, optionally filtered by site."""
    _require_enabled()

    def _do():
        results = []
        sites_to_check = [site] if site else list(get_configured_sites())
        for s in sites_to_check:
            try:
                session = get_session(s)
                resp = session.api_get("compute", "/os-keypairs")
                for kp in resp.get("keypairs", []):
                    k = kp.get("keypair", kp)
                    k["_site"] = s
                    results.append(k)
            except Exception:
                pass
        return results

    return await run_in_chi_pool(_do)


@router.post("/api/chameleon/keypairs")
async def create_keypair(request: Request):
    """Create a Nova key pair.

    Body: {"site": "CHI@TACC", "name": "my-key", "public_key": "ssh-rsa ..."}
    If public_key is omitted, Nova generates one and returns the private key.
    When a private key is returned (no public_key provided), it is automatically
    saved to {config_dir}/chameleon_key and registered in settings.
    """
    _require_enabled()
    body = await request.json()
    site = body.get("site", "CHI@TACC")

    def _do():
        session = get_session(site)
        kp_body: dict[str, Any] = {"keypair": {"name": body["name"]}}
        if body.get("public_key"):
            kp_body["keypair"]["public_key"] = body["public_key"]
        result = session.api_post("compute", "/os-keypairs", kp_body)
        kp_data = result.get("keypair", result)

        # If Nova generated a private key, save it per-site
        private_key = kp_data.get("private_key", "")
        if private_key:
            _save_chameleon_key(site, private_key)
            try:
                from app.settings_manager import load_settings, save_settings, invalidate_settings_cache
                settings = load_settings()
                settings.setdefault("chameleon", {})["ssh_key_file"] = key_path
                save_settings(settings)
                invalidate_settings_cache()
            except Exception as e:
                logger.warning("Failed to update settings with key path: %s", e)

        return kp_data

    try:
        return await run_in_chi_pool(_do)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post("/api/chameleon/keypairs/ensure")
async def ensure_keypair(request: Request):
    """Ensure 'loomai-key' keypair exists AND we have the matching private key.

    Body: {"site": "CHI@TACC"}
    If the keypair exists but we don't have the private key locally,
    deletes and recreates it so we get a new private key.
    Returns: {"name": "loomai-key", "status": "exists"|"created"|"recreated", "key_path": "..."}
    """
    _require_enabled()
    body = await request.json()
    site = body.get("site", "CHI@TACC")
    kp_name = "loomai-key"

    def _do():
        session = get_session(site)

        # Check if private key exists locally (per-site key)
        local_key_path = get_chameleon_key_path(site)
        has_local_key = bool(local_key_path)

        # Check if keypair exists on Chameleon
        kps = session.api_get("compute", "/os-keypairs")
        remote_exists = any(
            kp.get("keypair", kp).get("name") == kp_name
            for kp in kps.get("keypairs", [])
        )

        if remote_exists and has_local_key:
            return {"name": kp_name, "status": "exists", "key_path": local_key_path}

        if remote_exists and not has_local_key:
            # Delete the remote keypair — we can't use it without the private key
            logger.info("Deleting orphaned keypair '%s' at %s (no local private key)", kp_name, site)
            session.api_delete("compute", f"/os-keypairs/{kp_name}")

        # Create new keypair
        result = session.api_post("compute", "/os-keypairs", {
            "keypair": {"name": kp_name}
        })
        kp_data = result.get("keypair", result)
        private_key = kp_data.get("private_key", "")
        if not private_key:
            raise RuntimeError("Nova did not return a private key")

        # Save private key per-site
        key_path = _save_chameleon_key(site, private_key)

        try:
            from app.settings_manager import load_settings, save_settings, invalidate_settings_cache
            settings = load_settings()
            settings.setdefault("chameleon", {})["ssh_key_file"] = key_path
            save_settings(settings)
            invalidate_settings_cache()
        except Exception as e:
            logger.warning("Failed to update settings with key path: %s", e)

        status = "recreated" if remote_exists else "created"
        return {"name": kp_name, "status": status, "key_path": key_path}

    try:
        return await run_in_chi_pool(_do)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


def _ensure_keypair_at_site(site: str, kp_name: str = "loomai-key") -> dict:
    """Ensure keypair exists at a Chameleon site (callable from non-HTTP context).

    Same logic as the ensure_keypair endpoint but as a plain function
    for use in the full_deploy flow.
    """
    session = get_session(site)
    local_key_path = get_chameleon_key_path(site)
    has_local_key = bool(local_key_path)
    kps = session.api_get("compute", "/os-keypairs")
    remote_exists = any(
        kp.get("keypair", kp).get("name") == kp_name
        for kp in kps.get("keypairs", [])
    )
    if remote_exists and has_local_key:
        return {"name": kp_name, "status": "exists"}
    if remote_exists and not has_local_key:
        logger.info("Deleting orphaned keypair '%s' at %s (no local private key)", kp_name, site)
        session.api_delete("compute", f"/os-keypairs/{kp_name}")
    result = session.api_post("compute", "/os-keypairs", {"keypair": {"name": kp_name}})
    kp_data = result.get("keypair", result)
    private_key = kp_data.get("private_key", "")
    if not private_key:
        raise RuntimeError("Nova did not return a private key")
    key_path = _save_chameleon_key(site, private_key)
    try:
        from app.settings_manager import load_settings, save_settings, invalidate_settings_cache
        settings = load_settings()
        settings.setdefault("chameleon", {})["ssh_key_file"] = key_path
        save_settings(settings)
        invalidate_settings_cache()
    except Exception as e:
        logger.warning("Failed to update settings with key path: %s", e)
    return {"name": kp_name, "status": "recreated" if remote_exists else "created"}


@router.delete("/api/chameleon/keypairs/{name}")
async def delete_keypair(name: str, site: str = Query(None)):
    """Delete a Nova key pair by name."""
    _require_enabled()
    site = site or "CHI@TACC"

    def _do():
        session = get_session(site)
        session.api_delete("compute", f"/os-keypairs/{name}")
        return {"status": "deleted", "name": name}

    try:
        return await run_in_chi_pool(_do)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# ---------------------------------------------------------------------------
# Chameleon Boot Config + Recipe Execution
# ---------------------------------------------------------------------------


def _chi_boot_config_dir(slice_id: str) -> str:
    """Return boot config directory for a Chameleon slice."""
    storage = os.environ.get("FABRIC_STORAGE_DIR", "/home/fabric/work")
    d = os.path.join(storage, ".boot-config", "chameleon", slice_id)
    os.makedirs(d, exist_ok=True)
    return d


@router.get("/api/chameleon/boot-config/{slice_id}/{node_name}")
async def get_chameleon_boot_config(slice_id: str, node_name: str):
    """Load boot config for a Chameleon node."""
    path = os.path.join(_chi_boot_config_dir(slice_id), f"{node_name}.json")
    if os.path.isfile(path):
        with open(path) as f:
            return json.load(f)
    return {"uploads": [], "commands": [], "network": []}


@router.put("/api/chameleon/boot-config/{slice_id}/{node_name}")
async def save_chameleon_boot_config(slice_id: str, node_name: str, request: Request):
    """Save boot config for a Chameleon node."""
    config = await request.json()
    path = os.path.join(_chi_boot_config_dir(slice_id), f"{node_name}.json")
    with open(path, "w") as f:
        json.dump(config, f, indent=2)
    return {"status": "saved"}


@router.post("/api/chameleon/boot-config/{slice_id}/{node_name}/execute")
async def execute_chameleon_boot_config(slice_id: str, node_name: str):
    """Execute boot config on a single Chameleon node via SSH."""
    _require_enabled()

    def _do():
        import paramiko

        # Load boot config
        path = os.path.join(_chi_boot_config_dir(slice_id), f"{node_name}.json")
        if not os.path.isfile(path):
            return {"status": "skip", "message": "No boot config defined"}
        with open(path) as f:
            config = json.load(f)

        uploads = config.get("uploads", [])
        commands = config.get("commands", [])
        if not commands and not uploads:
            return {"status": "skip", "message": "No commands or uploads in boot config"}

        # Find the instance to get its IP and site
        slice_obj = _chameleon_slices.get(slice_id)
        if not slice_obj:
            raise HTTPException(404, "Slice not found")

        instance_res = None
        for res in slice_obj.get("resources", []):
            if res.get("type") == "instance" and res.get("name") == node_name:
                instance_res = res
                break
        if not instance_res:
            raise HTTPException(404, f"Instance '{node_name}' not found in slice resources")

        site = instance_res.get("site", "CHI@TACC")
        ip = instance_res.get("floating_ip") or instance_res.get("ip", "")
        if not ip:
            raise HTTPException(400, "Instance has no IP address")

        # Connect via SSH
        key_path = get_chameleon_key_path(site)
        if not key_path:
            raise HTTPException(400, f"No SSH key for site {site}")

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            pkey = paramiko.RSAKey.from_private_key_file(key_path)
        except Exception:
            try:
                pkey = paramiko.Ed25519Key.from_private_key_file(key_path)
            except Exception:
                pkey = paramiko.ECDSAKey.from_private_key_file(key_path)

        client.connect(hostname=ip, port=22, username="cc", pkey=pkey,
                       timeout=15, allow_agent=False, look_for_keys=False)

        results = []

        # Process file uploads via SFTP
        if uploads:
            sftp = client.open_sftp()
            storage = os.environ.get("FABRIC_STORAGE_DIR", "/home/fabric/work")
            for upload in sorted(uploads, key=lambda u: u.get("order", 0)):
                src = upload.get("source", "")
                dest = upload.get("dest", "")
                if not src or not dest:
                    continue
                local_path = os.path.join(storage, src) if not os.path.isabs(src) else src
                try:
                    sftp.put(local_path, dest)
                    results.append({"type": "upload", "source": src, "dest": dest, "status": "ok"})
                except Exception as e:
                    results.append({"type": "upload", "source": src, "dest": dest, "status": "error", "message": str(e)})
            sftp.close()

        for cmd_entry in sorted(commands, key=lambda c: c.get("order", 0)):
            cmd = cmd_entry.get("command", "")
            if not cmd:
                continue
            try:
                stdin, stdout, stderr = client.exec_command(cmd, timeout=60)
                out = stdout.read().decode().strip()
                err = stderr.read().decode().strip()
                exit_code = stdout.channel.recv_exit_status()
                results.append({"command": cmd, "status": "ok" if exit_code == 0 else "error",
                                "output": out, "stderr": err, "exit_code": exit_code})
            except Exception as e:
                results.append({"command": cmd, "status": "error", "message": str(e)})

        client.close()
        return {"status": "done", "results": results}

    try:
        return await run_in_chi_pool(_do)
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post("/api/chameleon/instances/{instance_id}/execute-recipe")
async def execute_chameleon_recipe(instance_id: str, request: Request):
    """Execute a recipe on a Chameleon instance via SSH.

    Body: {"site": "CHI@TACC", "recipe_dir": "my-recipe"}
    """
    _require_enabled()
    body = await request.json()
    site = body.get("site", "CHI@TACC")
    recipe_dir = body.get("recipe_dir", "")

    def _do():
        import paramiko

        # Load recipe
        storage = os.environ.get("FABRIC_STORAGE_DIR", "/home/fabric/work")
        recipe_path = os.path.join(storage, "my_artifacts", recipe_dir, "recipe.json")
        if not os.path.isfile(recipe_path):
            raise HTTPException(404, f"Recipe '{recipe_dir}' not found")
        with open(recipe_path) as f:
            recipe = json.load(f)

        commands = recipe.get("commands", recipe.get("steps", []))
        if not commands:
            return {"status": "skip", "message": "No commands in recipe"}

        # Get instance IP
        session = get_session(site)
        srv_resp = session.api_get("compute", f"/servers/{instance_id}")
        srv = srv_resp.get("server", srv_resp)
        ip = None
        for net_name, addrs in srv.get("addresses", {}).items():
            for addr in addrs:
                if addr.get("OS-EXT-IPS:type") == "floating":
                    ip = addr["addr"]
                    break
            if ip:
                break
        if not ip:
            for net_name, addrs in srv.get("addresses", {}).items():
                for addr in addrs:
                    ip = addr["addr"]
                    break
                if ip:
                    break
        if not ip:
            raise HTTPException(400, "Instance has no IP address")

        # Connect via SSH
        key_path = get_chameleon_key_path(site)
        if not key_path:
            raise HTTPException(400, f"No SSH key for site {site}")

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            pkey = paramiko.RSAKey.from_private_key_file(key_path)
        except Exception:
            try:
                pkey = paramiko.Ed25519Key.from_private_key_file(key_path)
            except Exception:
                pkey = paramiko.ECDSAKey.from_private_key_file(key_path)

        client.connect(hostname=ip, port=22, username="cc", pkey=pkey,
                       timeout=15, allow_agent=False, look_for_keys=False)

        results = []
        for step in commands:
            cmd = step if isinstance(step, str) else step.get("command", step.get("run", ""))
            if not cmd:
                continue
            try:
                stdin, stdout, stderr = client.exec_command(cmd, timeout=120)
                out = stdout.read().decode().strip()
                err = stderr.read().decode().strip()
                exit_code = stdout.channel.recv_exit_status()
                results.append({"command": cmd, "status": "ok" if exit_code == 0 else "error",
                                "output": out, "stderr": err, "exit_code": exit_code})
            except Exception as e:
                results.append({"command": cmd, "status": "error", "message": str(e)})

        client.close()
        return {"status": "done", "results": results}

    try:
        return await run_in_chi_pool(_do)
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# ---------------------------------------------------------------------------
# Floating IPs (Neutron)
# ---------------------------------------------------------------------------

@router.get("/api/chameleon/floating-ips")
async def list_floating_ips(site: str = Query(None)):
    """List floating IPs, optionally filtered by site."""
    _require_enabled()

    def _do():
        results = []
        sites_to_check = [site] if site else list(get_configured_sites())
        for s in sites_to_check:
            try:
                session = get_session(s)
                resp = session.api_get("network", "/v2.0/floatingips")
                for fip in resp.get("floatingips", []):
                    fip["_site"] = s
                    results.append(fip)
            except Exception:
                pass
        return results

    return await run_in_chi_pool(_do)


@router.post("/api/chameleon/floating-ips")
async def allocate_floating_ip(request: Request):
    """Allocate a floating IP from the external network.

    Body: {"site": "CHI@TACC", "network": "public"}
    """
    _require_enabled()
    body = await request.json()
    fip_site = body.get("site", "CHI@TACC")
    network_name = body.get("network", "public")

    def _do():
        session = get_session(fip_site)
        # Discover external network UUID
        nets = session.api_get("network", f"/v2.0/networks?name={network_name}&router:external=true")
        ext_nets = nets.get("networks", [])
        if not ext_nets:
            # Fallback: try without router:external filter
            nets = session.api_get("network", f"/v2.0/networks?name={network_name}")
            ext_nets = nets.get("networks", [])
        if not ext_nets:
            raise ValueError(f"External network '{network_name}' not found at {fip_site}")
        ext_net_id = ext_nets[0]["id"]
        result = session.api_post("network", "/v2.0/floatingips", {
            "floatingip": {"floating_network_id": ext_net_id}
        })
        fip = result.get("floatingip", result)
        fip["_site"] = fip_site
        return fip

    try:
        return await run_in_chi_pool(_do)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.delete("/api/chameleon/floating-ips/{ip_id}")
async def release_floating_ip(ip_id: str, site: str = Query(None)):
    """Release (deallocate) a floating IP."""
    _require_enabled()
    site = site or "CHI@TACC"

    def _do():
        session = get_session(site)
        session.api_delete("network", f"/v2.0/floatingips/{ip_id}")
        return {"status": "released", "floating_ip_id": ip_id}

    try:
        return await run_in_chi_pool(_do)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post("/api/chameleon/floating-ips/{ip_id}/associate")
async def associate_floating_ip_to_port(ip_id: str, request: Request):
    """Associate a floating IP with a port.

    Body: {"site": "CHI@TACC", "port_id": "..."}
    """
    _require_enabled()
    body = await request.json()
    fip_site = body.get("site", "CHI@TACC")
    port_id = body.get("port_id", "")

    def _do():
        session = get_session(fip_site)
        result = session.api_put("network", f"/v2.0/floatingips/{ip_id}", {
            "floatingip": {"port_id": port_id or None}
        })
        fip = result.get("floatingip", result)
        fip["_site"] = fip_site
        return fip

    try:
        return await run_in_chi_pool(_do)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# ---------------------------------------------------------------------------
# Security Groups (Neutron)
# ---------------------------------------------------------------------------

@router.get("/api/chameleon/security-groups")
async def list_security_groups(site: str = Query(None)):
    """List security groups, optionally filtered by site."""
    _require_enabled()

    def _do():
        results = []
        sites_to_check = [site] if site else list(get_configured_sites())
        for s in sites_to_check:
            try:
                session = get_session(s)
                resp = session.api_get("network", "/v2.0/security-groups")
                for sg in resp.get("security_groups", []):
                    sg["_site"] = s
                    results.append(sg)
            except Exception:
                pass
        return results

    return await run_in_chi_pool(_do)


@router.delete("/api/chameleon/security-groups/{sg_id}")
async def delete_security_group(sg_id: str, site: str = Query(None)):
    """Delete a security group by ID."""
    _require_enabled()
    site = site or "CHI@TACC"

    def _do():
        session = get_session(site)
        session.api_delete("network", f"/v2.0/security-groups/{sg_id}")
        return {"status": "deleted", "security_group_id": sg_id}

    try:
        return await run_in_chi_pool(_do)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post("/api/chameleon/security-groups")
async def create_security_group(request: Request):
    """Create a new security group.

    Body: {"site": "CHI@TACC", "name": "my-sg", "description": "..."}
    """
    _require_enabled()
    body = await request.json()
    sg_site = body.get("site", "CHI@TACC")
    sg_name = body.get("name", "new-sg")
    sg_desc = body.get("description", "")

    def _do():
        session = get_session(sg_site)
        result = session.api_post("network", "/v2.0/security-groups", {
            "security_group": {"name": sg_name, "description": sg_desc}
        })
        sg = result.get("security_group", result)
        sg["_site"] = sg_site
        return sg

    try:
        return await run_in_chi_pool(_do)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post("/api/chameleon/security-groups/{sg_id}/rules")
async def add_security_group_rule(sg_id: str, request: Request):
    """Add a rule to a security group.

    Body: {"site": "CHI@TACC", "direction": "ingress", "protocol": "tcp",
           "port_range_min": 22, "port_range_max": 22,
           "remote_ip_prefix": "0.0.0.0/0", "ethertype": "IPv4"}
    """
    _require_enabled()
    body = await request.json()
    sg_site = body.get("site", "CHI@TACC")

    def _do():
        session = get_session(sg_site)
        rule_body = {
            "security_group_rule": {
                "security_group_id": sg_id,
                "direction": body.get("direction", "ingress"),
                "ethertype": body.get("ethertype", "IPv4"),
            }
        }
        # Optional fields — only include if provided
        for field in ("protocol", "port_range_min", "port_range_max", "remote_ip_prefix"):
            if body.get(field) is not None:
                rule_body["security_group_rule"][field] = body[field]
        result = session.api_post("network", "/v2.0/security-group-rules", rule_body)
        return result.get("security_group_rule", result)

    try:
        return await run_in_chi_pool(_do)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.delete("/api/chameleon/security-groups/{sg_id}/rules/{rule_id}")
async def delete_security_group_rule(sg_id: str, rule_id: str, site: str = Query(None)):
    """Delete a security group rule."""
    _require_enabled()
    site = site or "CHI@TACC"

    def _do():
        session = get_session(site)
        session.api_delete("network", f"/v2.0/security-group-rules/{rule_id}")
        return {"status": "deleted", "rule_id": rule_id}

    try:
        return await run_in_chi_pool(_do)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# ---------------------------------------------------------------------------
# Chameleon Slices (composite resource groups)
# ---------------------------------------------------------------------------


@router.get("/api/chameleon/slices")
async def list_chameleon_slices():
    """List all Chameleon slices with computed real state."""
    _require_enabled()
    result = []
    for s in _chameleon_slices.values():
        entry = {**s}
        entry["state"] = _compute_chi_real_state(s)
        result.append(entry)
    return result


def _compute_chi_real_state(chi: dict) -> str:
    """Compute real state from resource statuses (Deploying while BUILD)."""
    resources = chi.get("resources", [])
    if not resources:
        return chi.get("state", "Configuring") or "Configuring"
    instances = [r for r in resources if r.get("type") == "instance"]
    if instances:
        statuses = [i.get("status", "") for i in instances]
        if all(s == "ACTIVE" for s in statuses):
            return "Active"
        if any(s == "ERROR" for s in statuses):
            return "Error"
        if any(s in ("BUILD", "PENDING", "SPAWNING") for s in statuses):
            return "Deploying"
    leases = [r for r in resources if r.get("type") == "lease"]
    if leases and not instances:
        return "Deploying"
    return chi.get("state", "Unknown")


@router.get("/api/chameleon/slices/all")
async def list_all_chameleon_slices():
    """List ALL Chameleon slices (both Draft and Active) for unified selector."""
    _require_enabled()
    return list(_chameleon_slices.values())


@router.post("/api/chameleon/slices")
async def create_chameleon_slice(request: Request):
    """Create a new Chameleon slice.

    Body: {"name": "my-slice", "site": "CHI@TACC"}
    """
    _require_enabled()
    body = await request.json()
    slice_id = f"chi-slice-{uuid.uuid4()}"
    chi_slice = {
        "id": slice_id,
        "name": body.get("name", "untitled"),
        "site": body.get("site", "CHI@TACC"),
        "resources": [],
        "state": "Configuring",
        "created": datetime.now(timezone.utc).isoformat(),
        "nodes": [],
        "networks": [],
        "floating_ips": [],
    }
    _chameleon_slices[slice_id] = chi_slice
    _persist_slices()
    return chi_slice


@router.delete("/api/chameleon/slices/{slice_id}")
async def delete_chameleon_slice(slice_id: str, delete_resources: bool = Query(False)):
    """Delete a Chameleon slice.

    When ``delete_resources=True``, first deletes all tracked instances (Nova)
    and leases (Blazar) before removing the slice from the store.
    """
    _require_enabled()
    chi_slice = _chameleon_slices.get(slice_id)
    if not chi_slice:
        raise HTTPException(404, "Chameleon slice not found")

    cleanup_errors: list[str] = []

    if delete_resources:
        resources = chi_slice.get("resources", [])

        # Delete instances first
        for res in resources:
            if res.get("type") == "instance" and res.get("id"):
                site = res.get("site", "CHI@TACC")
                instance_id = res["id"]
                try:
                    def _del_instance(s=site, iid=instance_id):
                        session = get_session(s)
                        session.api_delete("compute", f"/servers/{iid}")
                    await run_in_chi_pool(_del_instance)
                except Exception as e:
                    cleanup_errors.append(f"instance {instance_id}: {e}")

        # Then delete leases
        for res in resources:
            if res.get("type") == "lease" and res.get("id"):
                site = res.get("site", "CHI@TACC")
                lease_id = res["id"]
                try:
                    def _del_lease(s=site, lid=lease_id):
                        session = get_session(s)
                        session.api_delete("reservation", f"/leases/{lid}")
                    await run_in_chi_pool(_del_lease)
                except Exception as e:
                    cleanup_errors.append(f"lease {lease_id}: {e}")

    del _chameleon_slices[slice_id]
    _persist_slices()

    result: dict[str, Any] = {"status": "deleted", "slice_id": slice_id}
    if cleanup_errors:
        result["cleanup_errors"] = cleanup_errors
    return result


@router.post("/api/chameleon/slices/{slice_id}/add-resource")
async def add_chameleon_slice_resource(slice_id: str, request: Request):
    """Add a resource to a Chameleon slice.

    Body: {"type": "instance"|"lease"|"network"|"floating_ip", "id": "...",
           "name": "...", "site": "CHI@TACC", ...extra}
    """
    _require_enabled()
    chi_slice = _chameleon_slices.get(slice_id)
    if not chi_slice:
        raise HTTPException(404, "Chameleon slice not found")
    body = await request.json()
    resource = {
        "resource_id": f"res-{uuid.uuid4()}",
        "type": body.get("type", "instance"),
        "id": body.get("id", ""),
        "name": body.get("name", ""),
        "site": body.get("site", chi_slice["site"]),
    }
    # Copy any extra fields
    for key in ("node_type", "image", "lease_id", "cidr", "status"):
        if key in body:
            resource[key] = body[key]
    chi_slice["resources"].append(resource)
    _persist_slices()
    return chi_slice


@router.post("/api/chameleon/slices/{slice_id}/remove-resource")
async def remove_chameleon_slice_resource(slice_id: str, request: Request):
    """Remove a resource from a Chameleon slice.

    Body: {"resource_id": "res-..."}
    """
    _require_enabled()
    chi_slice = _chameleon_slices.get(slice_id)
    if not chi_slice:
        raise HTTPException(404, "Chameleon slice not found")
    body = await request.json()
    rid = body.get("resource_id", "")
    chi_slice["resources"] = [r for r in chi_slice["resources"] if r.get("resource_id") != rid]
    _persist_slices()
    return chi_slice


_VALID_SLICE_STATES = {"Draft", "Deploying", "Active", "Error", "Terminated"}


@router.put("/api/chameleon/slices/{slice_id}/state")
async def update_chameleon_slice_state(slice_id: str, request: Request):
    """Update the state of a Chameleon slice.

    Body: {"state": "Draft"|"Deploying"|"Active"|"Error"|"Terminated"}
    """
    _require_enabled()
    chi_slice = _chameleon_slices.get(slice_id)
    if not chi_slice:
        raise HTTPException(404, "Chameleon slice not found")
    body = await request.json()
    new_state = body.get("state", "")
    if new_state not in _VALID_SLICE_STATES:
        raise HTTPException(400, f"Invalid state '{new_state}'. Must be one of: {', '.join(sorted(_VALID_SLICE_STATES))}")
    chi_slice["state"] = new_state
    _persist_slices()
    return chi_slice


@router.get("/api/chameleon/slices/{slice_id}/graph")
async def get_chameleon_slice_graph(slice_id: str):
    """Return Cytoscape.js graph elements for a Chameleon slice.

    Delegates to ``get_draft_graph`` which now handles both draft and
    deployed topologies with live instance state overlay.
    """
    return await get_draft_graph(slice_id)


# ---------------------------------------------------------------------------
# Detailed node types (Blazar with hardware properties)
# ---------------------------------------------------------------------------

@router.get("/api/chameleon/sites/{site}/node-types/detail")
async def site_node_types_detail(site: str):
    """List node types at a Chameleon site with detailed hardware properties."""
    _require_enabled()

    def _fetch():
        session = get_session(site)
        try:
            hosts = session.api_get("reservation", "/os-hosts")
            host_list = hosts.get("hosts", [])
        except Exception:
            host_list = []

        # Group by node_type and aggregate hardware properties
        type_info: dict[str, dict] = {}
        for h in host_list:
            ntype = h.get("node_type", "unknown")
            if ntype not in type_info:
                type_info[ntype] = {
                    "node_type": ntype,
                    "total": 0,
                    "reservable": 0,
                    "cpu_arch": h.get("cpu_arch", ""),
                    "cpu_count": _int_or(h.get("vcpus"), 0),
                    "cpu_model": h.get("cpu_model", ""),
                    "ram_gb": _int_or(h.get("memory_mb"), 0) // 1024 if _int_or(h.get("memory_mb"), 0) else 0,
                    "disk_gb": _int_or(h.get("local_gb"), 0),
                    "gpu": h.get("gpu.gpu_model") or h.get("gpu_model") or None,
                    "gpu_count": _int_or(h.get("gpu.gpu_count") or h.get("gpu_count"), 0),
                }
            type_info[ntype]["total"] += 1
            if h.get("reservable"):
                type_info[ntype]["reservable"] += 1

        result = sorted(type_info.values(), key=lambda x: x["node_type"])
        return {"site": site, "node_types": result}

    return await run_in_chi_pool(_fetch)


# ---------------------------------------------------------------------------
# Chameleon nodes in slice drafts
# ---------------------------------------------------------------------------

# In-memory store for Chameleon nodes attached to slice drafts
# Key: slice_name, Value: list of chameleon node dicts
_chameleon_slice_nodes: dict[str, list[dict]] = {}


@router.get("/api/chameleon/slice-nodes/{slice_name}")
async def get_chameleon_slice_nodes(slice_name: str):
    """Get Chameleon nodes attached to a slice draft."""
    return _chameleon_slice_nodes.get(slice_name, [])


@router.post("/api/chameleon/slice-nodes/{slice_name}")
async def add_chameleon_slice_node(slice_name: str, request: Request):
    """Add a Chameleon node to a slice draft.

    Body: {"name": "chi-node1", "site": "CHI@TACC", "node_type": "compute_skylake",
           "image_id": "...", "connection_type": "fabnet_v4"|"l2_stitch"}
    """
    body = await request.json()
    nodes = _chameleon_slice_nodes.setdefault(slice_name, [])
    node = {
        "name": body.get("name", f"chi-{len(nodes) + 1}"),
        "site": body.get("site", "CHI@TACC"),
        "node_type": body.get("node_type", "compute_haswell"),
        "image_id": body.get("image_id", ""),
        "connection_type": body.get("connection_type", "fabnet_v4"),
        "status": "draft",
    }
    nodes.append(node)
    return {"chameleon_nodes": nodes}


@router.delete("/api/chameleon/slice-nodes/{slice_name}/{node_name}")
async def remove_chameleon_slice_node(slice_name: str, node_name: str):
    """Remove a Chameleon node from a slice draft."""
    nodes = _chameleon_slice_nodes.get(slice_name, [])
    _chameleon_slice_nodes[slice_name] = [n for n in nodes if n.get("name") != node_name]
    return {"chameleon_nodes": _chameleon_slice_nodes.get(slice_name, [])}


# ---------------------------------------------------------------------------
# Availability finder
# ---------------------------------------------------------------------------

@router.post("/api/chameleon/find-availability")
async def find_availability(request: Request):
    """Find the earliest time a resource request can be satisfied.

    Body: {"site": "CHI@TACC", "node_type": "compute_skylake", "node_count": 2, "duration_hours": 4}
    Returns: {"earliest_start": "2026-03-27T10:00", "available_now": int, "total": int}
    """
    _require_enabled()
    body = await request.json()
    site = body.get("site", "CHI@TACC")
    node_type = body.get("node_type", "")
    node_count = body.get("node_count", 1)
    duration_hours = body.get("duration_hours", 4)

    def _find():
        from datetime import datetime, timedelta, timezone
        session = get_session(site)

        # Get total hosts of this type
        try:
            hosts_data = session.api_get("reservation", "/os-hosts")
            all_hosts = hosts_data.get("hosts", [])
        except Exception:
            all_hosts = []

        matching_hosts = [h for h in all_hosts if h.get("node_type") == node_type and h.get("reservable")]
        total = len(matching_hosts)

        if total < node_count:
            return {
                "earliest_start": None,
                "available_now": total,
                "total": total,
                "error": f"Only {total} {node_type} nodes exist (need {node_count})",
            }

        # Get active/pending leases for this node type
        try:
            leases_data = session.api_get("reservation", "/leases")
            all_leases = leases_data.get("leases", [])
        except Exception:
            all_leases = []

        # Find leases that use this node type and are active/pending
        active_reservations = []
        for lease in all_leases:
            if lease.get("status") not in ("ACTIVE", "PENDING"):
                continue
            for res in lease.get("reservations", []):
                if res.get("resource_type") != "physical:host":
                    continue
                props = res.get("resource_properties", "")
                if node_type in props:
                    count = res.get("max", res.get("min", 1))
                    end_date = lease.get("end_date", "")
                    active_reservations.append({
                        "count": count,
                        "end_date": end_date,
                    })

        # Count currently reserved nodes
        reserved_now = sum(r["count"] for r in active_reservations)
        available_now = max(0, total - reserved_now)

        if available_now >= node_count:
            return {
                "earliest_start": "now",
                "available_now": available_now,
                "total": total,
                "error": "",
                "approximate": True,
                "warning": "Availability is approximate \u2014 Blazar may reject due to scheduling conflicts.",
            }

        # Find earliest time enough nodes free up
        # Sort reservations by end_date
        end_times = []
        for r in active_reservations:
            try:
                end_dt = datetime.fromisoformat(r["end_date"].replace("Z", "+00:00"))
                end_times.extend([end_dt] * r["count"])
            except Exception:
                pass

        end_times.sort()

        # Walk through end times, counting freed nodes
        freed = 0
        for end_dt in end_times:
            freed += 1
            if available_now + freed >= node_count:
                return {
                    "earliest_start": end_dt.strftime("%Y-%m-%dT%H:%M"),
                    "available_now": available_now,
                    "total": total,
                    "error": "",
                }

        return {
            "earliest_start": None,
            "available_now": available_now,
            "total": total,
            "error": f"Cannot determine availability — {available_now + freed} of {node_count} needed",
        }

    try:
        return await run_in_chi_pool(_find)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# ---------------------------------------------------------------------------
# Schedule calendar
# ---------------------------------------------------------------------------

def _parse_iso(val: str) -> datetime | None:
    """Parse an ISO-format timestamp string, returning None on failure."""
    if not val:
        return None
    try:
        dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


@router.get("/api/chameleon/schedule/calendar")
async def chameleon_schedule_calendar(days: int = Query(14, ge=1, le=90)):
    """Combine Chameleon lease data with site node-type availability.

    Returns per-site lease information and node-type capacity for a calendar
    view, mirroring the FABRIC ``/api/schedule/calendar`` pattern.
    """
    _require_enabled()

    now = datetime.now(timezone.utc)
    end_time = now + timedelta(days=days)

    configured_sites = get_configured_sites()

    def _fetch_site(site_name: str) -> dict[str, Any]:
        """Fetch leases and node types for a single site (blocking)."""
        session = get_session(site_name)

        # --- leases ---
        try:
            raw = session.api_get("reservation", "/leases")
            all_leases = raw.get("leases", [])
        except Exception as exc:
            logger.warning("Chameleon %s: could not fetch leases for calendar: %s", site_name, exc)
            all_leases = []

        # Filter to leases that overlap the calendar window
        filtered_leases: list[dict[str, Any]] = []
        for lease in all_leases:
            lease_end_dt = _parse_iso(lease.get("end_date", ""))
            lease_start_dt = _parse_iso(lease.get("start_date", ""))

            # Keep the lease if its end is within the window or it is currently
            # active (started before now and ends within range), or spans the
            # whole window.
            if lease_end_dt and lease_end_dt < now:
                # Already expired — skip
                continue
            if lease_start_dt and lease_start_dt > end_time:
                # Starts after our window — skip
                continue

            reservations = []
            for res in lease.get("reservations", []):
                reservations.append({
                    "id": res.get("id", ""),
                    "resource_type": res.get("resource_type", ""),
                    "min": _int_or(res.get("min"), 0),
                    "max": _int_or(res.get("max"), 0),
                    "status": res.get("status", ""),
                })

            filtered_leases.append({
                "id": lease.get("id", ""),
                "name": lease.get("name", ""),
                "status": lease.get("status", ""),
                "start_date": lease.get("start_date", ""),
                "end_date": lease.get("end_date", ""),
                "reservations": reservations,
            })

        # --- node types ---
        try:
            hosts_raw = session.api_get("reservation", "/os-hosts")
            host_list = hosts_raw.get("hosts", [])
        except Exception as exc:
            logger.warning("Chameleon %s: could not fetch hosts for calendar: %s", site_name, exc)
            host_list = []

        type_counts: dict[str, dict[str, Any]] = {}
        for h in host_list:
            ntype = h.get("node_type", "unknown")
            if ntype not in type_counts:
                type_counts[ntype] = {"node_type": ntype, "total": 0, "reservable": 0}
            type_counts[ntype]["total"] += 1
            if h.get("reservable"):
                type_counts[ntype]["reservable"] += 1

        node_types = sorted(type_counts.values(), key=lambda x: x["node_type"])

        return {
            "name": site_name,
            "node_types": node_types,
            "leases": filtered_leases,
        }

    def _fetch_all() -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for s in configured_sites:
            try:
                results.append(_fetch_site(s))
            except Exception as exc:
                logger.warning("Chameleon %s: skipping in calendar: %s", s, exc)
                # Include the site with empty data so the frontend knows it exists
                results.append({"name": s, "node_types": [], "leases": []})
        return results

    sites = await run_in_chi_pool(_fetch_all)

    return {
        "time_range": {
            "start": now.isoformat(),
            "end": end_time.isoformat(),
        },
        "sites": sites,
    }


# ---------------------------------------------------------------------------
# Connection test
# ---------------------------------------------------------------------------

@router.post("/api/chameleon/test")
async def test_connection(request: Request):
    """Test connection to a Chameleon site.

    Body: {"site": "CHI@TACC"} or {"site": "all"}
    """
    body = await request.json()
    site = body.get("site", "")

    from app import settings_manager
    if site == "all":
        sites_to_test = list(settings_manager.get_chameleon_sites().keys())
    else:
        sites_to_test = [site]

    def _test():
        import time
        results = {}
        for s in sites_to_test:
            if not settings_manager.is_chameleon_site_configured(s):
                results[s] = {"ok": False, "error": "Not configured", "latency_ms": 0}
                continue
            start = time.time()
            try:
                session = get_session(s)
                session.get_token()  # Force auth
                latency = int((time.time() - start) * 1000)
                # Try listing leases as a deeper test
                try:
                    session.api_get("reservation", "/leases")
                    results[s] = {"ok": True, "error": "", "latency_ms": latency}
                except Exception as e:
                    results[s] = {"ok": True, "error": f"Auth OK, Blazar: {e}", "latency_ms": latency}
            except Exception as e:
                latency = int((time.time() - start) * 1000)
                results[s] = {"ok": False, "error": str(e), "latency_ms": latency}
        return results

    return await run_in_chi_pool(_test)


# ---------------------------------------------------------------------------
# Draft topology management
# ---------------------------------------------------------------------------


def _draft_sites(draft: dict) -> list[str]:
    """Return sorted unique sites from a draft's nodes."""
    return sorted(set(n.get("site", "") for n in draft.get("nodes", []) if n.get("site")))


@router.post("/api/chameleon/drafts")
async def create_draft(request: Request):
    """Create a new Chameleon draft topology (stored as a slice with state=Draft).

    Body: {"name": "my-exp"}
    Site is per-node, not per-draft.  Legacy "site" field accepted but ignored.
    """
    _require_enabled()
    body = await request.json()
    slice_id = f"chi-slice-{uuid.uuid4()}"
    draft: dict = {
        "id": slice_id,
        "name": body.get("name", "untitled"),
        "state": "Draft",
        "created": datetime.now(timezone.utc).isoformat(),
        "nodes": [],
        "networks": [],
        "floating_ips": [],
        "resources": [],
    }
    # Keep legacy site if provided (backward compat for old clients)
    if body.get("site"):
        draft["site"] = body["site"]
    _chameleon_slices[slice_id] = draft
    _persist_slices()
    return draft


@router.get("/api/chameleon/drafts")
async def list_drafts():
    """List all Chameleon slices (returns all for unified view; frontend filters)."""
    _require_enabled()
    return list(_chameleon_slices.values())


@router.get("/api/chameleon/drafts/{draft_id}")
async def get_draft(draft_id: str):
    """Get a Chameleon draft/slice topology."""
    _require_enabled()
    draft = _chameleon_slices.get(draft_id)
    if not draft:
        raise HTTPException(404, "Draft not found")
    return draft


@router.delete("/api/chameleon/drafts/{draft_id}")
async def delete_draft(draft_id: str, delete_resources: bool = Query(False)):
    """Delete a Chameleon draft/slice topology.

    When ``delete_resources=True``, first deletes all tracked instances (Nova)
    and leases (Blazar) before removing the slice from the store.
    """
    _require_enabled()
    draft = _chameleon_slices.get(draft_id)
    if not draft:
        raise HTTPException(404, "Draft not found")

    cleanup_errors: list[str] = []

    if delete_resources:
        resources = draft.get("resources", [])

        # Delete instances first
        for res in resources:
            if res.get("type") == "instance" and res.get("id"):
                site = res.get("site", "CHI@TACC")
                instance_id = res["id"]
                try:
                    def _del_instance(s=site, iid=instance_id):
                        session = get_session(s)
                        session.api_delete("compute", f"/servers/{iid}")
                    await run_in_chi_pool(_del_instance)
                except Exception as e:
                    cleanup_errors.append(f"instance {instance_id}: {e}")

        # Then delete leases
        for res in resources:
            if res.get("type") == "lease" and res.get("id"):
                site = res.get("site", "CHI@TACC")
                lease_id = res["id"]
                try:
                    def _del_lease(s=site, lid=lease_id):
                        session = get_session(s)
                        session.api_delete("reservation", f"/leases/{lid}")
                    await run_in_chi_pool(_del_lease)
                except Exception as e:
                    cleanup_errors.append(f"lease {lease_id}: {e}")

    del _chameleon_slices[draft_id]
    _persist_slices()

    result: dict[str, Any] = {"status": "deleted", "draft_id": draft_id}
    if cleanup_errors:
        result["cleanup_errors"] = cleanup_errors
    return result


@router.post("/api/chameleon/drafts/{draft_id}/nodes")
async def add_draft_node(draft_id: str, request: Request):
    """Add a node to a Chameleon draft/slice topology.

    Body: {"name": "node1", "node_type": "compute_skylake", "image": "CC-Ubuntu22.04", "count": 1, "site": "CHI@TACC"}
    """
    _require_enabled()
    draft = _chameleon_slices.get(draft_id)
    if not draft:
        raise HTTPException(404, "Draft not found")
    body = await request.json()
    node = {
        "id": f"node-{uuid.uuid4()}",
        "name": body.get("name", f"node{len(draft['nodes']) + 1}"),
        "node_type": body.get("node_type", "compute_haswell"),
        "image": body.get("image", "CC-Ubuntu22.04"),
        "count": body.get("count", 1),
        "site": body.get("site") or draft.get("site") or "",
        "interfaces": body.get("interfaces", [
            {"nic": 0, "network": None},
            {"nic": 1, "network": None},
        ]),
    }
    if not node["site"]:
        raise HTTPException(400, "Node site is required")
    draft["nodes"].append(node)
    _persist_slices()
    return draft


@router.delete("/api/chameleon/drafts/{draft_id}/nodes/{node_id}")
async def remove_draft_node(draft_id: str, node_id: str):
    """Remove a node from a Chameleon draft/slice topology."""
    _require_enabled()
    draft = _chameleon_slices.get(draft_id)
    if not draft:
        raise HTTPException(404, "Draft not found")
    original_len = len(draft["nodes"])
    draft["nodes"] = [n for n in draft["nodes"] if n["id"] != node_id]
    if len(draft["nodes"]) == original_len:
        raise HTTPException(404, "Node not found")
    # Also remove from floating_ips and network connected_nodes
    draft["floating_ips"] = [nid for nid in draft["floating_ips"] if nid != node_id]
    for net in draft["networks"]:
        net["connected_nodes"] = [nid for nid in net["connected_nodes"] if nid != node_id]
    _persist_slices()
    return draft


@router.put("/api/chameleon/drafts/{draft_id}/nodes/{node_id}/network")
async def update_draft_node_network(draft_id: str, node_id: str, request: Request):
    """Update the network assignment for a node's primary interface (backward compat).

    Body: {"id": "neutron-net-uuid", "name": "sharednet1"} or null to disconnect.
    """
    _require_enabled()
    draft = _chameleon_slices.get(draft_id)
    if not draft:
        raise HTTPException(404, "Draft not found")
    node = next((n for n in draft["nodes"] if n["id"] == node_id), None)
    if not node:
        raise HTTPException(404, "Node not found")
    body = await request.json()
    # Update interfaces array if present, else set legacy network field
    if "interfaces" in node:
        if node["interfaces"]:
            node["interfaces"][0]["network"] = body
    else:
        node["network"] = body
    _persist_slices()


@router.put("/api/chameleon/drafts/{draft_id}/nodes/{node_id}/interfaces")
async def update_draft_node_interfaces(draft_id: str, node_id: str, request: Request):
    """Update all interface network assignments for a node.

    Body: [{"nic": 0, "network": {"id": "...", "name": "sharednet1"}},
           {"nic": 1, "network": {"id": "...", "name": "fabnetv4"}}]
    """
    _require_enabled()
    draft = _chameleon_slices.get(draft_id)
    if not draft:
        raise HTTPException(404, "Draft not found")
    node = next((n for n in draft["nodes"] if n["id"] == node_id), None)
    if not node:
        raise HTTPException(404, "Node not found")
    body = await request.json()
    node["interfaces"] = body
    _persist_slices()
    return draft


@router.post("/api/chameleon/drafts/{draft_id}/networks")
async def add_draft_network(draft_id: str, request: Request):
    """Add a network to a Chameleon draft/slice topology.

    Body: {"name": "my-net", "connected_nodes": ["node-id-1", "node-id-2"]}
    """
    _require_enabled()
    draft = _chameleon_slices.get(draft_id)
    if not draft:
        raise HTTPException(404, "Draft not found")
    body = await request.json()
    network = {
        "id": f"net-{uuid.uuid4()}",
        "name": body.get("name", f"net{len(draft['networks']) + 1}"),
        "connected_nodes": body.get("connected_nodes", []),
    }
    draft["networks"].append(network)
    _persist_slices()
    return draft


@router.delete("/api/chameleon/drafts/{draft_id}/networks/{network_id}")
async def remove_draft_network(draft_id: str, network_id: str):
    """Remove a network from a Chameleon draft/slice topology."""
    _require_enabled()
    draft = _chameleon_slices.get(draft_id)
    if not draft:
        raise HTTPException(404, "Draft not found")
    original_len = len(draft["networks"])
    draft["networks"] = [n for n in draft["networks"] if n["id"] != network_id]
    if len(draft["networks"]) == original_len:
        raise HTTPException(404, "Network not found")
    _persist_slices()
    return draft


@router.put("/api/chameleon/drafts/{draft_id}/floating-ips")
async def set_draft_floating_ips(draft_id: str, body: dict = Body(...)):
    """Set which nodes get floating IPs (and on which NIC) in a Chameleon draft.

    Supports two formats:

    Old (backward compatible):
      Body: {"node_ids": ["node-id-1"]}
      → All specified nodes get a floating IP on NIC 0

    New (NIC-specific):
      Body: {"entries": [{"node_id": "node-id-1", "nic": 1}]}
      → Each entry specifies which NIC gets the floating IP

    Only one NIC per node can have a floating IP.
    """
    _require_enabled()
    draft = _chameleon_slices.get(draft_id)
    if not draft:
        raise HTTPException(404, "Draft not found")

    # Support both old (node_ids) and new (entries) format
    entries = body.get("entries")
    if entries is not None:
        # New format: [{node_id, nic}, ...]
        # Validate: only one entry per node
        seen_nodes: set[str] = set()
        validated: list[dict] = []
        for e in entries:
            nid = e.get("node_id", "")
            nic = e.get("nic", 0)
            if nid and nid not in seen_nodes:
                seen_nodes.add(nid)
                validated.append({"node_id": nid, "nic": nic})
        draft["floating_ips"] = validated
    else:
        # Old format: node_ids list (default to NIC 0)
        node_ids = body.get("node_ids", [])
        draft["floating_ips"] = [{"node_id": nid, "nic": 0} for nid in node_ids]

    _persist_slices()
    return draft


@router.get("/api/chameleon/drafts/{draft_id}/graph")
async def get_draft_graph(draft_id: str):
    """Get Cytoscape.js graph elements for a Chameleon draft/slice topology.

    If the draft has deployed instances (resources with an ``id``), fetches
    live status from Nova and overlays ACTIVE/BUILD/ERROR/etc. state onto the
    topology graph nodes.  Persisted statuses are opportunistically updated
    when live data differs.
    """
    _require_enabled()
    draft = _chameleon_slices.get(draft_id)
    if not draft:
        raise HTTPException(404, "Draft not found")

    # Fetch live instance statuses if slice has deployed instances
    live_instances = None
    instance_resources = [
        r for r in draft.get("resources", [])
        if r.get("type") == "instance" and r.get("id")
    ]
    if instance_resources:
        sites_needed = set(
            r.get("site", "") for r in instance_resources if r.get("site")
        )
        if sites_needed:
            live_instances = await _fetch_live_instances(sites_needed)
            # Opportunistically update persisted statuses
            if live_instances:
                inst_status_map = {inst["id"]: inst for inst in live_instances}
                changed = False
                for res in draft.get("resources", []):
                    if res.get("type") == "instance" and res.get("id") in inst_status_map:
                        live = inst_status_map[res["id"]]
                        if res.get("status") != live.get("status"):
                            res["status"] = live["status"]
                            changed = True
                if changed:
                    # Also update slice-level state from resource statuses
                    all_inst = [r for r in draft.get("resources", []) if r.get("type") == "instance"]
                    if all_inst:
                        inst_statuses = [r.get("status", "") for r in all_inst]
                        if all(s == "ACTIVE" for s in inst_statuses):
                            draft["state"] = "Active"
                        elif any(s == "ERROR" for s in inst_statuses):
                            draft["state"] = "Error"
                        elif any(s in ("BUILD", "PENDING", "SPAWNING") for s in inst_statuses):
                            draft["state"] = "Deploying"
                    _persist_slices()

    from app.graph_builder import build_chameleon_slice_graph
    return build_chameleon_slice_graph(draft, live_instances=live_instances)


# ---------------------------------------------------------------------------
# Deploy draft → Chameleon lease
# ---------------------------------------------------------------------------


@router.post("/api/chameleon/drafts/{draft_id}/deploy")
async def deploy_draft(draft_id: str, body: dict = Body(...)):
    """Create Chameleon leases from a draft topology (one lease per site).

    Body: {"lease_name": "my-exp-lease", "duration_hours": 24, "start_date": "2026-04-01T10:00"}

    Groups nodes by site and creates one Blazar lease per site.
    Returns ``{ draft_id, leases: [{ site, lease_id, status, reservations }, ...] }``.
    If ``start_date`` is provided (ISO datetime string), leases are
    scheduled for the future; otherwise they start immediately ("now").
    """
    _require_enabled()
    slice_obj = _chameleon_slices.get(draft_id)
    if not slice_obj:
        raise HTTPException(404, "Draft not found")

    if not slice_obj["nodes"]:
        raise HTTPException(400, "Draft has no nodes")

    base_lease_name = body.get("lease_name", slice_obj["name"])
    duration_hours = body.get("duration_hours", 24)
    start_date = body.get("start_date")  # ISO datetime string or None

    # Group nodes by site
    sites_nodes: dict[str, list[dict]] = {}
    for node in slice_obj["nodes"]:
        s = node.get("site") or slice_obj.get("site", "")
        if not s:
            continue
        sites_nodes.setdefault(s, []).append(node)

    if not sites_nodes:
        raise HTTPException(400, "No nodes with valid sites in draft")

    # Determine start/end dates (shared across all leases)
    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        except Exception:
            start_dt = datetime.strptime(start_date, "%Y-%m-%dT%H:%M")
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        start_str = start_dt.strftime("%Y-%m-%d %H:%M")
        end_dt = start_dt + timedelta(hours=duration_hours)
    else:
        start_str = "now"
        end_dt = datetime.now(timezone.utc) + timedelta(hours=duration_hours)

    end_str = end_dt.strftime("%Y-%m-%d %H:%M")

    def _create_lease_for_site(site: str, nodes: list[dict]) -> dict:
        session = get_session(site)

        # Build reservations — group by node_type
        node_type_counts: dict[str, int] = {}
        for node in nodes:
            nt = node["node_type"]
            node_type_counts[nt] = node_type_counts.get(nt, 0) + node.get("count", 1)

        reservations: list[dict[str, Any]] = []
        for nt, count in node_type_counts.items():
            reservations.append({
                "resource_type": "physical:host",
                "resource_properties": json.dumps(["==", "$node_type", nt]),
                "min": count,
                "max": count,
                "hypervisor_properties": "",
            })

        # Use site-suffixed name if multi-site to avoid Blazar name collisions
        lease_name = f"{base_lease_name}-{site}" if len(sites_nodes) > 1 else base_lease_name

        lease_body = {
            "name": lease_name,
            "start_date": start_str,
            "end_date": end_str,
            "reservations": reservations,
            "events": [],
        }
        logger.info("Deploy draft %s at %s: lease_body=%s", draft_id, site, json.dumps(lease_body))
        result = session.api_post("reservation", "/leases", lease_body)
        lease = result.get("lease", result)
        lease["_site"] = site
        return lease

    # Create leases — one per site (concurrently if multiple)
    created_leases: list[dict] = []
    errors: list[str] = []

    if len(sites_nodes) == 1:
        site, nodes = next(iter(sites_nodes.items()))
        try:
            lease = await run_in_chi_pool(lambda: _create_lease_for_site(site, nodes))
            created_leases.append({"site": site, "lease_id": lease.get("id", ""), "lease_name": lease.get("name", ""), "status": lease.get("status", "PENDING"), "reservations": lease.get("reservations", [])})
        except Exception as e:
            errors.append(f"{site}: {e}")
    else:
        import asyncio
        tasks = []
        site_order = []
        for site, nodes in sites_nodes.items():
            site_order.append(site)
            tasks.append(run_in_chi_pool(lambda s=site, n=nodes: _create_lease_for_site(s, n)))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for site, result in zip(site_order, results):
            if isinstance(result, Exception):
                errors.append(f"{site}: {result}")
            else:
                created_leases.append({"site": site, "lease_id": result.get("id", ""), "lease_name": result.get("name", ""), "status": result.get("status", "PENDING"), "reservations": result.get("reservations", [])})

    if not created_leases and errors:
        return JSONResponse({"error": "; ".join(errors)}, status_code=400)

    # Add lease resources to the slice and update state
    for lease_info in created_leases:
        slice_obj.setdefault("resources", []).append({
            "resource_id": f"res-{uuid.uuid4()}",
            "type": "lease",
            "id": lease_info["lease_id"],
            "name": lease_info.get("lease_name", ""),
            "site": lease_info["site"],
            "status": lease_info.get("status", "PENDING"),
        })
    slice_obj["state"] = "Deploying"
    _persist_slices()

    # If full_deploy requested, wait for leases ACTIVE then launch instances
    if body.get("full_deploy"):
        import asyncio as _asyncio
        # Wait for leases to become ACTIVE (up to 5 min)
        for lease_info in created_leases:
            lease_id = lease_info["lease_id"]
            site = lease_info["site"]
            for attempt in range(60):
                await _asyncio.sleep(5)
                try:
                    session = get_session(site)
                    lease_data = await run_in_chi_pool(lambda s=session, lid=lease_id: s.api_get("reservation", f"/leases/{lid}"))
                    lease_obj = lease_data.get("lease", lease_data)
                    status = lease_obj.get("status", "UNKNOWN")
                    if status == "ACTIVE":
                        lease_info["status"] = "ACTIVE"
                        lease_info["reservations"] = lease_obj.get("reservations", [])
                        break
                    if status == "ERROR":
                        errors.append(f"Lease at {site} entered ERROR state")
                        break
                except Exception:
                    pass

        # Launch instances for each node using their lease's reservation
        instances_launched = 0
        for site, nodes in sites_nodes.items():
            lease_info = next((l for l in created_leases if l["site"] == site), None)
            if not lease_info or lease_info.get("status") != "ACTIVE":
                continue
            # Get reservation ID
            host_res = next((r for r in lease_info.get("reservations", []) if r.get("resource_type") == "physical:host" or (not r.get("resource_type") and r.get("id"))), None)
            reservation_id = host_res["id"] if host_res else ""
            # Ensure keypair exists at this site
            keypair_name = "loomai-key"
            try:
                await run_in_chi_pool(lambda s=site: _ensure_keypair_at_site(s, keypair_name))
            except Exception as e:
                logger.warning("Full deploy: keypair setup at %s: %s", site, e)
            # Find routable network as fallback for nodes without explicit interface networks
            network_id = ""
            try:
                net_info = await run_in_chi_pool(lambda s=site: ensure_routable_network(s))
                network_id = net_info.get("network_id", "")
            except Exception:
                pass
            # Launch each node
            for node in nodes:
                # Use per-node interface networks if available (multi-NIC)
                ifaces = node.get("interfaces", [])
                node_nets = [ifc["network"]["id"] for ifc in ifaces if ifc.get("network") and ifc["network"].get("id")]
                if not node_nets and network_id:
                    node_nets = [network_id]
                try:
                    def _launch(site_name=site, n=node, rid=reservation_id, nets=node_nets, kp=keypair_name):
                        s = get_session(site_name)
                        # Resolve image name → UUID if needed (Nova requires UUID)
                        image_ref = n.get("image", "CC-Ubuntu22.04")
                        if image_ref and not _is_uuid(image_ref):
                            from urllib.parse import quote
                            try:
                                images_resp = s.api_get("image", f"/v2/images?name={quote(image_ref)}&limit=5")
                                for img in images_resp.get("images", []):
                                    if img.get("name") == image_ref:
                                        image_ref = img["id"]
                                        break
                            except Exception:
                                logger.warning("Failed to resolve image name %r to UUID at %s", image_ref, site_name)
                        net_list = [{"uuid": nid} for nid in nets] if nets else []
                        server_body: dict = {
                            "server": {
                                "name": n["name"],
                                "imageRef": image_ref,
                                "flavorRef": "baremetal",
                                "min_count": 1, "max_count": 1,
                                **({"key_name": kp} if kp else {}),
                                **({"networks": net_list} if net_list else {}),
                            },
                            **({"os:scheduler_hints": {"reservation": rid}} if rid else {}),
                        }
                        return s.api_post("compute", "/servers", server_body)
                    result = await run_in_chi_pool(_launch)
                    server = result.get("server", result)
                    # Track instance in slice
                    slice_obj.setdefault("resources", []).append({
                        "resource_id": f"res-{uuid.uuid4()}",
                        "type": "instance",
                        "id": server.get("id", ""),
                        "name": node["name"],
                        "site": site,
                        "image": node.get("image", ""),
                        "lease_id": lease_info["lease_id"],
                        "status": "BUILD",
                    })
                    instances_launched += 1
                except Exception as e:
                    errors.append(f"Launch {node['name']}: {e}")

        if instances_launched > 0:
            slice_obj["state"] = "Deploying"
        _persist_slices()

    return {
        "draft_id": draft_id,
        "leases": created_leases,
        **({"errors": errors} if errors else {}),
    }


# ---------------------------------------------------------------------------
# Auto-network-setup (security groups + floating IPs for slice instances)
# ---------------------------------------------------------------------------


@router.post("/api/chameleon/slices/{slice_id}/auto-network-setup")
async def auto_network_setup(slice_id: str):
    """Ensure SSH security group and floating IPs for all instances in a slice.

    For each unique site referenced by instance resources:
      1. Ensure a ``loomai-ssh`` security group exists (SSH + ICMP ingress)
      2. Wait for each instance to reach ACTIVE state (up to ~5 min)
      3. Assign the ``loomai-ssh`` security group to the instance
      4. Allocate and associate a floating IP for nodes flagged in ``floating_ips``

    Returns ``{"results": [...]}}`` with per-instance status.
    """
    _require_enabled()

    def _setup():
        import time as _time

        slice_obj = _chameleon_slices.get(slice_id)
        if not slice_obj:
            raise HTTPException(404, "Slice not found")

        instance_resources = [
            r for r in slice_obj.get("resources", []) if r.get("type") == "instance"
        ]
        if not instance_resources:
            return {"results": [], "message": "No instances to configure"}

        # Determine which node IDs should get floating IPs and on which NIC.
        # floating_ips supports two formats:
        #   Old: ["node-id-1", "node-id-2"]  (defaults to NIC 0)
        #   New: [{"node_id": "node-id-1", "nic": 1}, ...]  (specific NIC)
        floating_ip_node_ids: set[str] = set()
        floating_ip_nic_map: dict[str, int] = {}  # node_id → NIC index
        for entry in slice_obj.get("floating_ips", []):
            if isinstance(entry, str):
                floating_ip_node_ids.add(entry)
                floating_ip_nic_map[entry] = 0  # default NIC 0
            elif isinstance(entry, dict):
                nid = entry.get("node_id", "")
                if nid:
                    floating_ip_node_ids.add(nid)
                    floating_ip_nic_map[nid] = entry.get("nic", 0)

        # Map node names to their dict so we can look up node id from instance name
        nodes_by_name: dict[str, dict] = {
            n["name"]: n for n in slice_obj.get("nodes", [])
        }

        # --- Step 1: Ensure loomai-ssh security group per site ----------------
        sites = set(
            r.get("site", "") for r in instance_resources if r.get("site")
        )
        sg_ids: dict[str, str] = {}
        for site in sites:
            session = get_session(site)
            existing = session.api_get("network", "/v2.0/security-groups")
            loomai_sg = None
            for sg in existing.get("security_groups", []):
                if sg.get("name") == "loomai-ssh":
                    loomai_sg = sg
                    break

            if not loomai_sg:
                sg_body = {
                    "security_group": {
                        "name": "loomai-ssh",
                        "description": "LoomAI SSH + ICMP access",
                    }
                }
                result = session.api_post("network", "/v2.0/security-groups", sg_body)
                loomai_sg = result.get("security_group", result)

                # Add SSH rule (TCP port 22 ingress)
                rule_body = {
                    "security_group_rule": {
                        "security_group_id": loomai_sg["id"],
                        "direction": "ingress",
                        "protocol": "tcp",
                        "port_range_min": 22,
                        "port_range_max": 22,
                        "remote_ip_prefix": "0.0.0.0/0",
                        "ethertype": "IPv4",
                    }
                }
                session.api_post("network", "/v2.0/security-group-rules", rule_body)

                # Add ICMP rule
                icmp_body = {
                    "security_group_rule": {
                        "security_group_id": loomai_sg["id"],
                        "direction": "ingress",
                        "protocol": "icmp",
                        "remote_ip_prefix": "0.0.0.0/0",
                        "ethertype": "IPv4",
                    }
                }
                session.api_post("network", "/v2.0/security-group-rules", icmp_body)

            sg_ids[site] = loomai_sg["id"]

        # --- Step 2-4: Wait for ACTIVE, assign SG, allocate floating IPs -----
        results: list[dict[str, Any]] = []
        for res in instance_resources:
            instance_id = res.get("id", "")
            instance_name = res.get("name", "")
            site = res.get("site", "")
            if not instance_id or not site:
                continue

            # Check if this node needs a floating IP
            node = nodes_by_name.get(instance_name)
            needs_fip = node is not None and node.get("id") in floating_ip_node_ids

            session = get_session(site)

            # Wait for instance to be ACTIVE (up to ~15 min: 90 x 10s)
            # Bare-metal provisioning can take 10-15 minutes
            active = False
            for _attempt in range(90):
                try:
                    srv = session.api_get("compute", f"/servers/{instance_id}")
                    status = srv.get("server", srv).get("status", "")
                    if status == "ACTIVE":
                        active = True
                        break
                    if status == "ERROR":
                        break
                except Exception:
                    pass
                _time.sleep(10)

            if not active:
                results.append({"name": instance_name, "site": site, "error": "Instance not ACTIVE"})
                continue

            # Assign loomai-ssh security group to the instance
            try:
                sg_action = {"addSecurityGroup": {"name": "loomai-ssh"}}
                session.api_post("compute", f"/servers/{instance_id}/action", sg_action)
            except Exception:
                # May already be assigned — ignore
                pass

            # Allocate and associate floating IP via Neutron API
            floating_ip = None
            if needs_fip:
                try:
                    # Find external (public) network for floating IPs
                    nets = session.api_get("network", "/v2.0/networks")
                    ext_net_id = None
                    for net in nets.get("networks", []):
                        if net.get("router:external") or net.get("name", "").lower() == "public":
                            ext_net_id = net["id"]
                            break

                    if ext_net_id:
                        # Find the correct instance port based on NIC selection.
                        # The user specifies which NIC (0, 1, 2, ...) gets the floating IP.
                        # OpenStack ports are ordered by creation (matching network list order).
                        target_nic = floating_ip_nic_map.get(node.get("id", ""), 0) if node else 0
                        ports = session.api_get("network", f"/v2.0/ports?device_id={instance_id}")
                        port_list = ports.get("ports", [])
                        port_id = None
                        if target_nic < len(port_list):
                            port_id = port_list[target_nic]["id"]
                        elif port_list:
                            port_id = port_list[0]["id"]  # fallback to first port

                        if port_id:
                            # Allocate and associate in one call via Neutron
                            fip_resp = session.api_post("network", "/v2.0/floatingips", {
                                "floatingip": {
                                    "floating_network_id": ext_net_id,
                                    "port_id": port_id,
                                }
                            })
                            fip_data = fip_resp.get("floatingip", fip_resp)
                            floating_ip = fip_data.get("floating_ip_address", "")
                except Exception as e:
                    results.append({"name": instance_name, "site": site, "error": f"Floating IP failed: {e}"})
                    continue

            # Persist floating IP back to the resource entry
            if floating_ip:
                for res in slice_obj.get("resources", []):
                    if res.get("id") == instance_id and res.get("type") == "instance":
                        res["floating_ip"] = floating_ip
                        break

            entry: dict[str, Any] = {"name": instance_name, "site": site, "status": "configured"}
            if floating_ip:
                entry["floating_ip"] = floating_ip
            results.append(entry)

        # Update slice state based on actual instance statuses
        all_instances = [r for r in slice_obj.get("resources", []) if r.get("type") == "instance"]
        if all_instances:
            statuses = [r.get("status", "") for r in all_instances]
            if all(s == "ACTIVE" for s in statuses):
                slice_obj["state"] = "Active"
            elif any(s == "ERROR" for s in statuses):
                slice_obj["state"] = "Error"
            elif any(s in ("BUILD", "PENDING", "SPAWNING") for s in statuses):
                slice_obj["state"] = "Deploying"

        _persist_slices()
        return {"results": results}

    return await run_in_chi_pool(_setup)


# ---------------------------------------------------------------------------
# Import from reservation
# ---------------------------------------------------------------------------


@router.post("/api/chameleon/slices/{slice_id}/import-reservation")
async def import_reservation(slice_id: str, request: Request):
    """Import instances from a Blazar lease/reservation into a slice.

    Body: {"site": "CHI@TACC", "lease_id": "..."}
    Finds instances associated with the lease and adds them as slice resources.
    """
    _require_enabled()
    body = await request.json()
    site = body.get("site", "CHI@TACC")
    lease_id = body.get("lease_id", "")

    def _do():
        slice_obj = _chameleon_slices.get(slice_id)
        if not slice_obj:
            raise HTTPException(404, "Slice not found")

        session = get_session(site)

        # Get all instances at the site
        servers = session.api_get("compute", "/servers/detail")
        existing_ids = {r.get("id") for r in slice_obj.get("resources", []) if r.get("type") == "instance"}

        imported = []
        for srv in servers.get("servers", []):
            # Check if instance metadata references this lease
            metadata = srv.get("metadata", {})
            reservation_id = metadata.get("reservation_id", "")
            # Also check if instance was created with a scheduler hint for this lease's reservation
            if not reservation_id:
                continue

            # Check lease association: get the lease and see if this reservation belongs to it
            try:
                lease = session.api_get("reservation", f"/leases/{lease_id}")
                lease_data = lease if "id" in lease else lease.get("lease", lease)
                lease_res_ids = {r["id"] for r in lease_data.get("reservations", [])}
                if reservation_id not in lease_res_ids:
                    continue
            except Exception:
                continue

            if srv["id"] in existing_ids:
                continue  # Already in slice

            # Extract IP info
            ips = []
            floating_ip = None
            for net_name, addrs in srv.get("addresses", {}).items():
                for addr in addrs:
                    if addr.get("OS-EXT-IPS:type") == "floating":
                        floating_ip = addr["addr"]
                    else:
                        ips.append(addr["addr"])

            resource = {
                "type": "instance",
                "id": srv["id"],
                "name": srv.get("name", ""),
                "site": site,
                "status": srv.get("status", "UNKNOWN"),
                "image": srv.get("image", {}).get("id", "") if isinstance(srv.get("image"), dict) else "",
                "ip_addresses": ips,
                "floating_ip": floating_ip,
                "lease_id": lease_id,
            }
            slice_obj.setdefault("resources", []).append(resource)
            imported.append(resource)

        _persist_slices()
        return {"imported": len(imported), "instances": [r["name"] for r in imported]}

    try:
        return await run_in_chi_pool(_do)
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# ---------------------------------------------------------------------------
# Auto-bastion management
# ---------------------------------------------------------------------------


@router.post("/api/chameleon/slices/{slice_id}/ensure-bastion")
async def ensure_bastion_endpoint(slice_id: str, request: Request):
    """Ensure a bastion instance exists for SSH access to private-network workers.

    Body: {"site": "CHI@TACC", "experiment_net_id": "...", "reservation_id": "..."}
    Creates a dual-NIC bastion on sharednet1 + experiment network with a floating IP.
    Returns bastion info: instance_id, floating_ip, site.
    """
    _require_enabled()
    body = await request.json()
    site = body.get("site", "CHI@TACC")
    experiment_net_id = body.get("experiment_net_id", "")
    reservation_id = body.get("reservation_id", "")

    def _do():
        import time as _time

        slice_obj = _chameleon_slices.get(slice_id)
        if not slice_obj:
            raise HTTPException(404, "Slice not found")

        # Check if bastion already exists
        bastion = slice_obj.get("bastion")
        if bastion and bastion.get("instance_id"):
            session = get_session(site)
            try:
                srv = session.api_get("compute", f"/servers/{bastion['instance_id']}")
                status = srv.get("server", srv).get("status", "")
                if status == "ACTIVE":
                    return {"status": "exists", **bastion}
            except Exception:
                pass  # Bastion gone — recreate

        session = get_session(site)

        # Find sharednet1
        routable = ensure_routable_network(site)
        sharednet_id = routable["network_id"]

        # Build networks list: sharednet1 + experiment network
        networks = [{"uuid": sharednet_id}]
        if experiment_net_id and experiment_net_id != sharednet_id:
            networks.append({"uuid": experiment_net_id})

        # Find image (CC-Ubuntu22.04 preferred)
        images = session.api_get("image", "/v2/images?limit=20&sort_key=name&sort_dir=desc")
        img_id = ""
        for img in images.get("images", []):
            if "CC-Ubuntu22" in img.get("name", ""):
                img_id = img["id"]
                break
        if not img_id:
            for img in images.get("images", []):
                if img.get("visibility") in ("public", "community"):
                    img_id = img["id"]
                    break

        # Find flavor
        flavors = session.api_get("compute", "/flavors/detail")
        flavor_ref = "baremetal"
        for f in flavors.get("flavors", []):
            if f.get("name") == "baremetal":
                flavor_ref = f["id"]
                break

        # Ensure keypair
        key_path = get_chameleon_key_path(site)
        key_name = "loomai-key" if key_path else ""

        # Create bastion instance
        server_body: dict[str, Any] = {
            "server": {
                "name": f"loomai-bastion-{slice_id[:8]}",
                "imageRef": img_id,
                "flavorRef": flavor_ref,
                "networks": networks,
                "security_groups": [{"name": "loomai-ssh"}],
                "min_count": 1,
                "max_count": 1,
            },
        }
        if key_name:
            server_body["server"]["key_name"] = key_name
        if reservation_id:
            server_body["os:scheduler_hints"] = {"reservation": reservation_id}

        result = session.api_post("compute", "/servers", server_body)
        srv = result.get("server", result)
        bastion_id = srv["id"]

        # Wait for ACTIVE (up to 15 min)
        logger.info("Waiting for bastion %s to become ACTIVE at %s", bastion_id[:12], site)
        for _attempt in range(90):
            try:
                check = session.api_get("compute", f"/servers/{bastion_id}")
                status = check.get("server", check).get("status", "")
                if status == "ACTIVE":
                    break
                if status == "ERROR":
                    raise RuntimeError(f"Bastion instance ERROR: {check.get('server', check).get('fault', {})}")
            except RuntimeError:
                raise
            except Exception:
                pass
            _time.sleep(10)

        # Assign security group + floating IP
        try:
            session.api_post("compute", f"/servers/{bastion_id}/action", {"addSecurityGroup": {"name": "loomai-ssh"}})
        except Exception:
            pass

        # Allocate floating IP via Neutron
        nets = session.api_get("network", "/v2.0/networks")
        ext_net_id = None
        for net in nets.get("networks", []):
            if net.get("router:external") or net.get("name", "").lower() == "public":
                ext_net_id = net["id"]
                break

        floating_ip = ""
        if ext_net_id:
            ports = session.api_get("network", f"/v2.0/ports?device_id={bastion_id}")
            port_id = ports["ports"][0]["id"] if ports.get("ports") else None
            if port_id:
                fip_resp = session.api_post("network", "/v2.0/floatingips", {
                    "floatingip": {"floating_network_id": ext_net_id, "port_id": port_id}
                })
                floating_ip = fip_resp.get("floatingip", fip_resp).get("floating_ip_address", "")

        # Store bastion info in slice
        bastion_info = {
            "instance_id": bastion_id,
            "floating_ip": floating_ip,
            "site": site,
        }
        slice_obj["bastion"] = bastion_info
        _persist_slices()

        logger.info("Bastion ready: %s at %s (FIP: %s)", bastion_id[:12], site, floating_ip)
        return {"status": "created", **bastion_info}

    try:
        return await run_in_chi_pool(_do)
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# ---------------------------------------------------------------------------
# SSH readiness probe
# ---------------------------------------------------------------------------


def _check_ssh_reachable(ip: str, timeout: float = 3.0) -> bool:
    """Return True if TCP port 22 is reachable on *ip*."""
    import socket

    try:
        with socket.create_connection((ip, 22), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


@router.post("/api/chameleon/slices/{slice_id}/check-readiness")
async def check_slice_readiness(slice_id: str):
    """Probe SSH (port 22) reachability for each instance in a slice.

    Updates each resource entry with ``ssh_ready`` flag and persists.
    """
    _require_enabled()

    def _check():
        slice_obj = _chameleon_slices.get(slice_id)
        if not slice_obj:
            raise HTTPException(404, "Slice not found")

        instance_resources = [
            r for r in slice_obj.get("resources", []) if r.get("type") == "instance"
        ]
        results: list[dict[str, Any]] = []
        changed = False

        for res in instance_resources:
            ip = res.get("floating_ip", "")
            name = res.get("name", "")
            site = res.get("site", "")
            instance_id = res.get("id", "")

            if not ip:
                results.append({"name": name, "site": site, "instance_id": instance_id, "ip": "", "ssh_ready": False})
                continue

            ready = _check_ssh_reachable(ip)
            if ready != res.get("ssh_ready", False):
                res["ssh_ready"] = ready
                changed = True

            results.append({"name": name, "site": site, "instance_id": instance_id, "ip": ip, "ssh_ready": ready})

        if changed:
            _persist_slices()

        return {"results": results}

    return await run_in_chi_pool(_check)


# ---------------------------------------------------------------------------
# Graph elements for cross-testbed topology
# ---------------------------------------------------------------------------

@router.get("/api/chameleon/graph")
async def chameleon_graph(connections: str | None = None):
    """Return Cytoscape.js graph elements for Chameleon instances.

    Optional query param ``connections`` is a JSON array of cross-testbed
    connection specs: [{"chameleon_instance_id": "...", "fabric_node": "...", "type": "l2_stitch"|"fabnet_v4"}]
    """
    _require_enabled()

    def _build():
        sites_to_query = get_configured_sites()
        all_instances = []
        for s in sites_to_query:
            try:
                session = get_session(s)
                result = session.api_get("compute", "/servers/detail")
                for srv in result.get("servers", []):
                    ips = []
                    floating_ip = None
                    for net_name, addrs in srv.get("addresses", {}).items():
                        for addr in addrs:
                            ip = addr.get("addr", "")
                            if addr.get("OS-EXT-IPS:type") == "floating":
                                floating_ip = ip
                            else:
                                ips.append(ip)
                    all_instances.append({
                        "id": srv["id"],
                        "name": srv["name"],
                        "site": s,
                        "status": srv.get("status", "UNKNOWN"),
                        "ip_addresses": ips,
                        "floating_ip": floating_ip,
                    })
            except Exception as e:
                logger.warning("Chameleon %s: could not list instances for graph: %s", s, e)

        conn_list = None
        if connections:
            try:
                conn_list = json.loads(connections)
            except Exception:
                pass

        from app.graph_builder import build_chameleon_elements
        return build_chameleon_elements(all_instances, conn_list)

    return await run_in_chi_pool(_build)


# ---------------------------------------------------------------------------
# VLAN Negotiation (FABRIC facility port <-> Chameleon network)
# ---------------------------------------------------------------------------

# Map of Chameleon sites to their FABRIC peering sites (facility port locations)
_CHI_TO_FABRIC_SITE: dict[str, str] = {
    "CHI@TACC": "TACC",
    "CHI@UC": "STAR",
    "CHI@Edge": "STAR",
    "KVM@TACC": "TACC",
}


def _parse_vlan_ranges(vlan_range: list) -> set[int]:
    """Parse a FABRIC VLAN range list into a set of individual VLAN IDs.

    VLAN ranges come from FABlib as strings like "200-300" or individual
    integers/strings. Returns a flat set of all VLAN IDs in the range.
    """
    result: set[int] = set()
    for entry in vlan_range:
        s = str(entry).strip()
        if not s:
            continue
        if "-" in s:
            try:
                parts = s.split("-", 1)
                lo, hi = int(parts[0].strip()), int(parts[1].strip())
                result.update(range(lo, hi + 1))
            except (ValueError, IndexError):
                continue
        else:
            try:
                result.add(int(s))
            except ValueError:
                continue
    return result


@router.post("/api/chameleon/negotiate-vlan")
async def negotiate_vlan(request: Request):
    """Negotiate a common VLAN between a FABRIC facility port and a Chameleon site.

    Body: {"fabric_site": "STAR", "chameleon_site": "CHI@TACC"}

    Queries FABRIC facility port VLAN ranges at the specified site and
    Chameleon existing network VLANs at the specified Chameleon site, then
    finds VLANs available on FABRIC that are not in use on Chameleon.
    """
    _require_enabled()
    body = await request.json()
    fabric_site = body.get("fabric_site", "")
    chameleon_site = body.get("chameleon_site", "CHI@TACC")

    if not fabric_site:
        # Auto-detect FABRIC site from Chameleon site mapping
        fabric_site = _CHI_TO_FABRIC_SITE.get(chameleon_site, "")
        if not fabric_site:
            return JSONResponse({
                "error": f"No known FABRIC peering site for Chameleon site '{chameleon_site}'"
            }, status_code=400)

    def _negotiate():
        # --- FABRIC side: query facility port VLANs at the site ---
        fabric_vlans: set[int] = set()
        try:
            from app.routes.resources import _fetch_facility_ports_locked
            facility_ports = _fetch_facility_ports_locked()
            for fp in facility_ports:
                fp_site = fp.get("site", "")
                if fp_site.upper() != fabric_site.upper():
                    continue
                for iface in fp.get("interfaces", []):
                    vlan_range = iface.get("vlan_range", [])
                    fabric_vlans.update(_parse_vlan_ranges(vlan_range))
        except Exception as e:
            logger.warning("VLAN negotiation: could not fetch FABRIC facility ports: %s", e)

        # --- Chameleon side: query existing networks to find used VLANs ---
        chameleon_used_vlans: set[int] = set()
        chameleon_available_vlans: set[int] = set()
        try:
            session = get_session(chameleon_site)

            # Try to get VLAN-backed networks to find used VLANs
            nets_data = session.api_get("network", "/v2.0/networks")
            net_list = nets_data.get("networks", [])

            for net in net_list:
                # Check provider:segmentation_id for VLAN tag
                seg_id = net.get("provider:segmentation_id")
                if seg_id is not None:
                    try:
                        chameleon_used_vlans.add(int(seg_id))
                    except (ValueError, TypeError):
                        pass

            # If we have FABRIC VLANs, find Chameleon-available VLANs
            # as those in the FABRIC range that are not used on Chameleon.
            # If no FABRIC VLANs, use a reasonable default range (200-4094).
            if fabric_vlans:
                chameleon_available_vlans = fabric_vlans - chameleon_used_vlans
            else:
                # Use a default range and subtract used VLANs
                default_range = set(range(200, 4095))
                chameleon_available_vlans = default_range - chameleon_used_vlans

        except Exception as e:
            logger.warning("VLAN negotiation: could not query Chameleon networks at %s: %s",
                           chameleon_site, e)
            # If Chameleon query fails, treat all FABRIC VLANs as available
            chameleon_available_vlans = fabric_vlans.copy() if fabric_vlans else set()

        # --- Find intersection ---
        if fabric_vlans:
            common_vlans = sorted(fabric_vlans & chameleon_available_vlans)
        else:
            # No FABRIC facility ports found — common set is just Chameleon available
            common_vlans = sorted(chameleon_available_vlans)

        fabric_vlans_sorted = sorted(fabric_vlans)
        chameleon_vlans_sorted = sorted(chameleon_available_vlans)

        result: dict[str, Any] = {
            "fabric_site": fabric_site,
            "chameleon_site": chameleon_site,
            "fabric_vlans": fabric_vlans_sorted[:100],  # Truncate for response size
            "chameleon_vlans": chameleon_vlans_sorted[:100],
            "common_vlans": common_vlans[:50],
            "suggested_vlan": common_vlans[0] if common_vlans else None,
        }

        if not common_vlans:
            result["error"] = "No common VLANs available"
            if not fabric_vlans:
                result["error"] = f"No facility ports found at FABRIC site '{fabric_site}'"

        return result

    try:
        return await run_in_chi_pool(_negotiate)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
