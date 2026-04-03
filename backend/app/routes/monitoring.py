"""Monitoring API routes — enable/disable scraping, retrieve metrics history.

Supports both FABRIC slices (via FABlib SSH) and Chameleon slices (via paramiko SSH).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.slice_registry import resolve_slice_name

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


def _mgr():
    from app.monitoring_manager import get_monitoring_manager
    return get_monitoring_manager()


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

@router.get("/{slice_name}/status")
async def monitoring_status(slice_name: str) -> Dict[str, Any]:
    """Get monitoring status for a slice."""
    slice_name = resolve_slice_name(slice_name)
    return _mgr().get_status(slice_name)


# ---------------------------------------------------------------------------
# Enable / Disable
# ---------------------------------------------------------------------------

@router.post("/{slice_name}/enable")
async def enable_monitoring(slice_name: str) -> Dict[str, Any]:
    """Enable monitoring for all nodes in a slice (installs exporters)."""
    slice_name = resolve_slice_name(slice_name)
    loop = asyncio.get_event_loop()
    try:
        results = await loop.run_in_executor(None, _mgr().enable_slice, slice_name)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # Start the scrape loop
    _mgr().start_scrape_loop(slice_name)
    return {"status": "enabled", "install_results": results}


@router.post("/{slice_name}/disable")
async def disable_monitoring(slice_name: str) -> Dict[str, Any]:
    """Disable monitoring for a slice."""
    slice_name = resolve_slice_name(slice_name)
    _mgr().disable_slice(slice_name)
    return {"status": "disabled"}


# ---------------------------------------------------------------------------
# Per-node enable / disable
# ---------------------------------------------------------------------------

@router.post("/{slice_name}/nodes/{node_name}/enable")
async def enable_node_monitoring(slice_name: str, node_name: str) -> Dict[str, Any]:
    """Enable monitoring for a single node."""
    slice_name = resolve_slice_name(slice_name)
    loop = asyncio.get_event_loop()
    try:
        msg = await loop.run_in_executor(None, _mgr().enable_node, slice_name, node_name)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "enabled", "message": msg}


@router.post("/{slice_name}/nodes/{node_name}/disable")
async def disable_node_monitoring(slice_name: str, node_name: str) -> Dict[str, Any]:
    """Disable monitoring for a single node."""
    slice_name = resolve_slice_name(slice_name)
    _mgr().disable_node(slice_name, node_name)
    return {"status": "disabled"}


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

@router.get("/{slice_name}/metrics")
async def latest_metrics(slice_name: str) -> Dict[str, Any]:
    """Get latest metric values for all monitored nodes."""
    slice_name = resolve_slice_name(slice_name)
    return _mgr().get_latest_metrics(slice_name)


@router.get("/{slice_name}/metrics/history")
async def metrics_history(
    slice_name: str, minutes: int = Query(default=30, ge=1, le=60)
) -> Dict[str, Any]:
    """Get time-series metric history for charting."""
    slice_name = resolve_slice_name(slice_name)
    return _mgr().get_history(slice_name, minutes)


# ---------------------------------------------------------------------------
# Infrastructure metrics (public FABRIC Prometheus)
# ---------------------------------------------------------------------------

@router.get("/{slice_name}/infrastructure")
async def infrastructure_metrics(slice_name: str) -> Dict[str, Any]:
    """Get public FABRIC site metrics filtered to slice's sites."""
    slice_name = resolve_slice_name(slice_name)
    from app.routes.metrics import _prom_query, _gather_queries

    # Get the slice's sites from monitoring state or FABlib
    mgr = _mgr()
    status = mgr.get_status(slice_name)
    sites = set()
    for node_info in status.get("nodes", []):
        site = node_info.get("site", "")
        if site:
            sites.add(site)

    # If no sites from monitoring state, try FABlib
    if not sites:
        try:
            from app.fablib_manager import get_fablib
            from app.slice_registry import get_slice_uuid
            fablib = get_fablib()
            uuid = get_slice_uuid(slice_name)
            if uuid:
                slice_obj = fablib.get_slice(slice_id=uuid)
            else:
                slice_obj = fablib.get_slice(slice_name)
            for node in slice_obj.get_nodes():
                try:
                    sites.add(node.get_site())
                except Exception:
                    pass
        except Exception:
            pass

    if not sites:
        return {"slice_name": slice_name, "sites": {}}

    result: Dict[str, Dict[str, Any]] = {}
    for site_name in sites:
        rack = site_name.lower()
        try:
            load1, load5, dp_in, dp_out = await _gather_queries(
                f'node_load1{{rack="{rack}"}}',
                f'node_load5{{rack="{rack}"}}',
                f'dataplaneInBits{{rack="{rack}"}}',
                f'dataplaneOutBits{{rack="{rack}"}}',
            )
            result[site_name] = {
                "node_load1": _simplify(load1),
                "node_load5": _simplify(load5),
                "dataplaneInBits": _simplify(dp_in),
                "dataplaneOutBits": _simplify(dp_out),
            }
        except Exception as e:
            logger.warning("Failed to get infrastructure metrics for %s: %s", site_name, e)
            result[site_name] = {"error": str(e)}

    return {"slice_name": slice_name, "sites": result}


def _simplify(results):
    """Simplify Prometheus results to {metric, value} pairs."""
    out = []
    for r in results:
        metric = r.get("metric", {})
        value = r.get("value", [None, None])
        out.append({"metric": metric, "value": value})
    return out


# ---------------------------------------------------------------------------
# Chameleon monitoring — cross-testbed support
# ---------------------------------------------------------------------------

class ChameleonNodeInfo(BaseModel):
    name: str
    ip: str
    site: str = ""
    key_path: str = ""
    username: str = "cc"


class ChameleonMonitorRequest(BaseModel):
    slice_name: str
    nodes: List[ChameleonNodeInfo]


@router.post("/chameleon/enable")
async def enable_chameleon_monitoring(req: ChameleonMonitorRequest) -> Dict[str, Any]:
    """Enable monitoring for Chameleon nodes (installs exporters via paramiko SSH)."""
    loop = asyncio.get_event_loop()
    nodes_dicts = [n.model_dump() for n in req.nodes]
    try:
        results = await loop.run_in_executor(
            None, _mgr().enable_chameleon_nodes, req.slice_name, nodes_dicts
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    _mgr().start_scrape_loop(req.slice_name)
    return {"status": "enabled", "install_results": results}
