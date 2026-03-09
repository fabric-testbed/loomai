"""API endpoints for SSH tunnel management."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.tunnel_manager import get_tunnel_manager

router = APIRouter()


class TunnelCreateRequest(BaseModel):
    slice_name: str
    node_name: str
    port: int


@router.post("/api/tunnels")
def create_tunnel(req: TunnelCreateRequest):
    """Create (or reuse) an SSH tunnel to a VM service."""
    mgr = get_tunnel_manager()
    try:
        info = mgr.create_tunnel(req.slice_name, req.node_name, req.port)
        return info.to_dict()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/tunnels")
def list_tunnels():
    """List all active tunnels."""
    return get_tunnel_manager().list_tunnels()


@router.delete("/api/tunnels/{tunnel_id}")
def close_tunnel(tunnel_id: str):
    """Close a tunnel and free its port."""
    if not get_tunnel_manager().close_tunnel(tunnel_id):
        raise HTTPException(status_code=404, detail="Tunnel not found")
    return {"status": "closed", "id": tunnel_id}
