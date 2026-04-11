"""HTTP API for the LoomAI RAG layer: status, search, rebuild."""
from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai/rag", tags=["rag"])


class RagSearchRequest(BaseModel):
    query: str
    k: int = 5
    min_score: float = 0.25
    weave_bias: bool = False
    source_types: list[str] | None = None


@router.get("/status")
async def rag_status() -> dict:
    """Return index diagnostics: chunk count, embedder, last build time, sources."""
    from app.rag import get_index

    idx = get_index()
    if idx is None:
        return {
            "status": "uninitialized",
            "chunk_count": 0,
            "embedder": None,
            "sources": {},
        }
    return {"status": "ready", **idx.status()}


@router.post("/search")
async def rag_search(req: RagSearchRequest) -> dict:
    """Manual retrieval — useful for debugging and UI preview."""
    from app.rag import get_index

    idx = get_index()
    if idx is None:
        raise HTTPException(503, "RAG index not ready")
    try:
        filter_set = set(req.source_types) if req.source_types else None
        hits = idx.retrieve(
            req.query,
            k=req.k,
            min_score=req.min_score,
            source_type_filter=filter_set,
        )
        if req.weave_bias:
            for h in hits:
                if h.chunk.source_type in ("weave", "example"):
                    h.score += 0.1
            hits.sort(key=lambda h: -h.score)
    except Exception as e:
        logger.warning("RAG search failed: %s", e, exc_info=True)
        raise HTTPException(500, f"search failed: {e}")
    return {
        "query": req.query,
        "count": len(hits),
        "hits": [
            {
                "chunk_id": h.chunk.chunk_id,
                "source_type": h.chunk.source_type,
                "source_path": h.chunk.source_path,
                "section": h.chunk.section,
                "score": round(h.score, 3),
                "semantic_score": round(h.semantic_score, 3),
                "bm25_score": round(h.bm25_score, 3),
                "preview": h.chunk.text[:500],
                "metadata": h.chunk.metadata,
            }
            for h in hits
        ],
    }


@router.post("/rebuild")
async def rag_rebuild(full: bool = False) -> dict:
    """Rebuild the RAG index.

    - ``full=False`` (default): incremental refresh — only re-embed changed files.
    - ``full=True``: drop the existing index and rebuild from scratch.
    """
    import asyncio
    from app.rag import (
        get_index,
        startup_build_index,
        _gather_corpus_chunks,
    )
    import os

    if full:
        # Drop current index and rebuild from scratch
        import app.rag as _rag
        async with _rag._INDEX_LOCK:
            _rag._INDEX = None
        try:
            await startup_build_index()
        except Exception as e:
            logger.warning("RAG full rebuild failed: %s", e, exc_info=True)
            raise HTTPException(500, f"rebuild failed: {e}")
    else:
        idx = get_index()
        if idx is None:
            # Nothing to incrementally refresh — do a full build
            try:
                await startup_build_index()
            except Exception as e:
                raise HTTPException(500, f"initial build failed: {e}")
        else:
            ai_tools_dir = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "..", "ai-tools"
            )
            ai_tools_dir = os.path.normpath(ai_tools_dir)
            try:
                fresh = await asyncio.to_thread(_gather_corpus_chunks, ai_tools_dir)
                changed = await asyncio.to_thread(idx.incremental_refresh, fresh)
            except Exception as e:
                logger.warning("RAG incremental rebuild failed: %s", e, exc_info=True)
                raise HTTPException(500, f"incremental rebuild failed: {e}")
            return {"status": "refreshed", "changed_chunks": changed, **idx.status()}

    from app.rag import get_index as _get_index
    idx = _get_index()
    if idx is None:
        raise HTTPException(500, "index not available after rebuild")
    return {"status": "rebuilt", **idx.status()}
