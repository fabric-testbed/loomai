"""Prometheus metrics proxy endpoints for FABRIC public metrics."""

from __future__ import annotations
from typing import Any

from fastapi import APIRouter, HTTPException
import httpx

router = APIRouter(tags=["metrics"])

PROMETHEUS_BASE = (
    "https://public-metrics.fabric-testbed.net"
    "/grafana/api/datasources/proxy/1/api/v1"
)
QUERY_URL = f"{PROMETHEUS_BASE}/query"


async def _prom_query(query: str) -> list[dict[str, Any]]:
    """Execute an instant Prometheus query and return the result vector."""
    async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
        resp = await client.get(QUERY_URL, params={"query": query})
        resp.raise_for_status()
        data = resp.json()
    if data.get("status") != "success":
        return []
    return data.get("data", {}).get("result", [])


@router.get("/metrics/site/{site_name}")
async def site_metrics(site_name: str) -> dict[str, Any]:
    """Get CPU load and dataplane traffic metrics for a FABRIC site."""
    rack = site_name.lower()
    try:
        load1, load5, load15, dp_in, dp_out = await _gather_queries(
            f'node_load1{{rack="{rack}"}}',
            f'node_load5{{rack="{rack}"}}',
            f'node_load15{{rack="{rack}"}}',
            f'dataplaneInBits{{rack="{rack}"}}',
            f'dataplaneOutBits{{rack="{rack}"}}',
        )
        return {
            "site": site_name,
            "node_load1": _simplify(load1),
            "node_load5": _simplify(load5),
            "node_load15": _simplify(load15),
            "dataplaneInBits": _simplify(dp_in),
            "dataplaneOutBits": _simplify(dp_out),
        }
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Prometheus query failed: {e}")


@router.get("/metrics/link/{site_a}/{site_b}")
async def link_metrics(site_a: str, site_b: str) -> dict[str, Any]:
    """Get dataplane traffic between two FABRIC sites in both directions."""
    rack_a = site_a.lower()
    rack_b = site_b.lower()
    try:
        in_a_to_b, out_a_to_b, in_b_to_a, out_b_to_a = await _gather_queries(
            f'dataplaneInBits{{src_rack="{rack_a}",dst_rack="{rack_b}"}}',
            f'dataplaneOutBits{{src_rack="{rack_a}",dst_rack="{rack_b}"}}',
            f'dataplaneInBits{{src_rack="{rack_b}",dst_rack="{rack_a}"}}',
            f'dataplaneOutBits{{src_rack="{rack_b}",dst_rack="{rack_a}"}}',
        )
        return {
            "site_a": site_a,
            "site_b": site_b,
            "a_to_b_in": _simplify(in_a_to_b),
            "a_to_b_out": _simplify(out_a_to_b),
            "b_to_a_in": _simplify(in_b_to_a),
            "b_to_a_out": _simplify(out_b_to_a),
        }
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Prometheus query failed: {e}")


async def _gather_queries(*queries: str) -> list[list[dict[str, Any]]]:
    """Run multiple Prometheus queries concurrently."""
    import asyncio
    return await asyncio.gather(*[_prom_query(q) for q in queries])


def _simplify(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Simplify Prometheus results to {metric, value} pairs."""
    out = []
    for r in results:
        metric = r.get("metric", {})
        value = r.get("value", [None, None])
        out.append({
            "metric": metric,
            "value": value,
        })
    return out
