"""Dynamic tab completion for the loomai CLI.

Provides shell_complete functions that query the backend API for
live data: slice names, node names, site names, weave names, etc.

Results are cached briefly (~5s) to avoid hammering the API on
rapid tab presses.
"""

from __future__ import annotations

import os
import time
from typing import Any

import click
from click.shell_completion import CompletionItem

# Brief cache to avoid repeated API calls on rapid tab presses
_cache: dict[str, tuple[float, list[str]]] = {}
_CACHE_TTL = 5  # seconds


def _get_base_url() -> str:
    return os.environ.get("LOOMAI_URL", "http://localhost:8000")


def _fetch_cached(key: str, path: str) -> list[str]:
    """Fetch a list of names from the backend API with brief caching."""
    cached = _cache.get(key)
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]

    try:
        import httpx
        resp = httpx.get(f"{_get_base_url()}/api{path}", timeout=5)
        if resp.status_code != 200:
            return []
        data = resp.json()
        if isinstance(data, list):
            names = [item.get("name") or item.get("id", "") for item in data if isinstance(item, dict)]
            if not names and data and isinstance(data[0], str):
                names = data
        else:
            names = []
        _cache[key] = (time.time(), names)
        return names
    except Exception:
        return _cache.get(key, (0, []))[1]  # Return stale cache on error


# ---------------------------------------------------------------------------
# Completion functions for Click arguments
# ---------------------------------------------------------------------------

class SliceNameComplete(click.ParamType):
    """Tab-complete slice names from the backend."""
    name = "slice"

    def shell_complete(self, ctx, param, incomplete):
        names = _fetch_cached("slices", "/slices?max_age=30")
        return [
            CompletionItem(n) for n in names
            if n.lower().startswith(incomplete.lower())
        ]


class NodeNameComplete(click.ParamType):
    """Tab-complete node names for a given slice."""
    name = "node"

    def shell_complete(self, ctx, param, incomplete):
        # Get slice name from previous argument
        slice_name = None
        if ctx and ctx.params:
            slice_name = ctx.params.get("slice_name") or ctx.params.get("slice")
        if not slice_name:
            return []

        try:
            import httpx
            resp = httpx.get(
                f"{_get_base_url()}/api/slices/{slice_name}",
                timeout=5,
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            nodes = [n["name"] for n in data.get("nodes", []) if isinstance(n, dict)]
            return [
                CompletionItem(n) for n in nodes
                if n.lower().startswith(incomplete.lower())
            ]
        except Exception:
            return []


class SiteNameComplete(click.ParamType):
    """Tab-complete FABRIC site names."""
    name = "site"

    def shell_complete(self, ctx, param, incomplete):
        names = _fetch_cached("sites", "/sites?max_age=300")
        return [
            CompletionItem(n) for n in names
            if n.lower().startswith(incomplete.lower())
        ]


class WeaveNameComplete(click.ParamType):
    """Tab-complete weave/template directory names."""
    name = "weave"

    def shell_complete(self, ctx, param, incomplete):
        names = _fetch_cached("templates", "/templates")
        # Templates return objects with dir_name or name
        if not names:
            try:
                import httpx
                resp = httpx.get(f"{_get_base_url()}/api/templates", timeout=5)
                data = resp.json()
                names = [t.get("dir_name") or t.get("name", "") for t in data if isinstance(t, dict)]
                _cache["templates"] = (time.time(), names)
            except Exception:
                pass
        return [
            CompletionItem(n) for n in names
            if n.lower().startswith(incomplete.lower())
        ]


class RunIdComplete(click.ParamType):
    """Tab-complete background run IDs."""
    name = "run_id"

    def shell_complete(self, ctx, param, incomplete):
        try:
            import httpx
            resp = httpx.get(f"{_get_base_url()}/api/templates/runs", timeout=5)
            data = resp.json()
            ids = [r.get("run_id", "") for r in data if isinstance(r, dict)]
            return [
                CompletionItem(i) for i in ids
                if i.lower().startswith(incomplete.lower())
            ]
        except Exception:
            return []


class ArtifactComplete(click.ParamType):
    """Tab-complete artifact names/UUIDs."""
    name = "artifact"

    def shell_complete(self, ctx, param, incomplete):
        names = _fetch_cached("artifacts_local", "/artifacts/local")
        if not names:
            try:
                import httpx
                resp = httpx.get(f"{_get_base_url()}/api/artifacts/local", timeout=5)
                data = resp.json()
                names = [a.get("dir_name") or a.get("name", "") for a in data if isinstance(a, dict)]
                _cache["artifacts_local"] = (time.time(), names)
            except Exception:
                pass
        return [
            CompletionItem(n) for n in names
            if n.lower().startswith(incomplete.lower())
        ]


class RecipeNameComplete(click.ParamType):
    """Tab-complete recipe names."""
    name = "recipe"

    def shell_complete(self, ctx, param, incomplete):
        names = _fetch_cached("recipes", "/recipes")
        return [
            CompletionItem(n) for n in names
            if n.lower().startswith(incomplete.lower())
        ]


# Convenience instances
SLICE = SliceNameComplete()
NODE = NodeNameComplete()
SITE = SiteNameComplete()
WEAVE = WeaveNameComplete()
RUN_ID = RunIdComplete()
ARTIFACT = ArtifactComplete()
RECIPE = RecipeNameComplete()
