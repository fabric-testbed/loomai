"""Project details API route — fetches project info from UIS API."""

from __future__ import annotations

import json
import logging
import os

import httpx
from fastapi import APIRouter, HTTPException, Query

from app.http_pool import fabric_client

from app.slice_registry import get_all_entries

logger = logging.getLogger(__name__)

router = APIRouter(tags=["projects"])

UIS_BASE = "https://uis.fabric-testbed.net"


def _config_dir() -> str:
    return os.environ.get("FABRIC_CONFIG_DIR", "/home/fabric/work/fabric_config")


def _read_id_token() -> str | None:
    from app.user_context import get_token_path
    path = get_token_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        return data.get("id_token")
    except Exception:
        return None


@router.get("/api/people/search")
async def search_people(q: str = Query(..., min_length=3)):
    """Search FABRIC users by name, email, or UUID."""
    token = _read_id_token()
    if not token:
        raise HTTPException(status_code=400, detail="No token available")

    try:
        resp = await fabric_client.get(
            f"{UIS_BASE}/people?search={q}&limit=10",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        logger.warning("UIS people search failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"UIS API error: {exc}")

    results = []
    for person in data.get("results", []):
        results.append({
            "uuid": person.get("uuid", ""),
            "name": person.get("name", ""),
            "email": person.get("email", ""),
            "affiliation": person.get("affiliation", ""),
        })

    return {"results": results}


@router.get("/api/projects/{uuid}/details")
async def get_project_details(uuid: str):
    token = _read_id_token()
    if not token:
        raise HTTPException(status_code=400, detail="No token available")

    try:
        resp = await fabric_client.get(
            f"{UIS_BASE}/projects/{uuid}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        logger.warning("UIS project query failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"UIS API error: {exc}")

    # The UIS response wraps results; extract the first project
    results = data.get("results", [data])
    proj = results[0] if results else data

    # Count slices from local registry
    all_slices = get_all_entries(include_archived=False, project_id=uuid)
    active_count = sum(1 for v in all_slices.values() if v.get("state") not in {"Dead", "Closing"})
    total_count = len(all_slices)

    return {
        "uuid": proj.get("uuid", uuid),
        "name": proj.get("name", ""),
        "description": proj.get("description", ""),
        "project_type": proj.get("project_type", ""),
        "active": proj.get("active", True),
        "created": proj.get("created", ""),
        "communities": proj.get("communities", []),
        "tags": proj.get("tags", []),
        "project_lead": proj.get("project_lead"),
        "project_owners": proj.get("project_owners", []),
        "project_members": proj.get("project_members", []),
        "project_creators": proj.get("project_creators", []),
        "project_funding": proj.get("project_funding", []),
        "slice_counts": {
            "active": active_count,
            "total": total_count,
        },
    }
