"""Unified FABlib API call manager with caching, coalescing, and freshness control.

Centralizes all FABlib read calls through a single path that provides:
- Caller-specified ``max_age`` (acceptable data staleness in seconds)
- Request coalescing (concurrent duplicate calls share one FABlib fetch)
- Stale-while-revalidate (return stale data immediately, refresh in background)
- Mutation invalidation (submit/delete/modify mark cache entries as expired)
- Stale-on-error fallback (return stale data when a fresh fetch fails)

Usage::

    from app.fabric_call_manager import get_call_manager

    mgr = get_call_manager()

    # Fetch with 30s acceptable staleness
    result = await mgr.get("slices:list", fetcher=my_sync_fn, max_age=30)

    # Force fresh (max_age=0)
    result = await mgr.get("slices:list", fetcher=my_sync_fn, max_age=0)

    # Invalidate after a mutation
    mgr.invalidate("slices:list")
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, TypeVar

from app.fablib_executor import run_in_fablib_pool

logger = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass
class CacheEntry:
    """A single cached FABlib call result."""

    data: Any = None
    timestamp: float = 0.0
    error: Optional[Exception] = None
    # In-flight coordination: waiters attach to this event
    inflight_event: Optional[asyncio.Event] = None
    # Disambiguate stale events after invalidation during a fetch
    inflight_id: int = 0


class FabricCallManager:
    """Centralized manager for all FABlib read calls.

    All read operations go through :meth:`get`, which checks the cache,
    coalesces concurrent requests, and delegates to the FABlib thread pool
    only when fresh data is actually needed.
    """

    def __init__(self) -> None:
        self._cache: dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()
        self._id_counter = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get(
        self,
        key: str,
        fetcher: Callable[[], T],
        max_age: float = 30.0,
        stale_while_revalidate: bool = False,
    ) -> T:
        """Get data for *key*, fetching via *fetcher* if stale.

        Parameters
        ----------
        key:
            Cache key (e.g. ``"slices:list"``, ``"slice:{uuid}"``).
        fetcher:
            **Synchronous** callable that returns fresh data.  Runs in the
            dedicated FABlib thread pool via ``run_in_fablib_pool``.
        max_age:
            Maximum acceptable age of cached data in seconds.
            ``0`` means always fetch fresh.
        stale_while_revalidate:
            If ``True`` and the cache is stale, return stale data immediately
            and kick off a background refresh.  If ``False``, block until
            fresh data is available.

        Returns
        -------
        The cached or freshly-fetched data.

        Raises
        ------
        Exception
            If the fetcher fails and no stale data is available.
        """
        # Fast path (no lock): check for fresh cache hit
        entry = self._cache.get(key)
        if entry is not None and entry.data is not None and max_age > 0:
            age = time.time() - entry.timestamp
            if age < max_age:
                return entry.data

        # Slow path: need the lock to inspect/modify entry state
        coalesce_event: Optional[asyncio.Event] = None
        coalesce_id: int = 0

        async with self._lock:
            entry = self._cache.get(key)

            # Case 1: fresh cache hit (re-check under lock)
            if entry is not None and entry.data is not None and max_age > 0:
                age = time.time() - entry.timestamp
                if age < max_age:
                    return entry.data

            # Case 2: stale cache + SWR requested → return stale, refresh bg
            if (
                entry is not None
                and entry.data is not None
                and stale_while_revalidate
            ):
                # Kick off bg refresh only if one isn't already running
                if entry.inflight_event is None:
                    self._start_background_fetch(key, entry, fetcher)
                return entry.data

            # Case 3: a fetch is already in-flight → coalesce
            if entry is not None and entry.inflight_event is not None:
                coalesce_event = entry.inflight_event
                coalesce_id = entry.inflight_id
                # Lock released on exit — we'll wait outside

        # If coalescing (Case 3), wait for the in-flight fetch
        if coalesce_event is not None:
            await coalesce_event.wait()
            entry = self._cache.get(key)
            if entry is not None:
                if entry.error is not None and entry.inflight_id == coalesce_id:
                    # The fetch we were waiting on failed
                    if entry.data is not None:
                        return entry.data  # stale fallback
                    raise entry.error
                if entry.data is not None:
                    return entry.data
            # Edge case: entry invalidated while waiting — fall through to fetch

        # Case 4: no usable cache, no in-flight fetch → start one
        return await self._do_fetch(key, fetcher)

    def invalidate(self, key: str) -> None:
        """Mark a cache entry as expired so the next ``get()`` fetches fresh.

        Safe to call from sync or async context (does not acquire the async lock).
        """
        entry = self._cache.get(key)
        if entry is not None:
            entry.timestamp = 0

    def invalidate_prefix(self, prefix: str) -> None:
        """Invalidate all entries whose key starts with *prefix*."""
        for k, entry in self._cache.items():
            if k.startswith(prefix):
                entry.timestamp = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _do_fetch(self, key: str, fetcher: Callable[[], T]) -> T:
        """Start a fetch, store result, and wake any coalesced waiters."""
        async with self._lock:
            entry = self._cache.get(key)

            # Check if another fetch is now in-flight
            if entry is not None and entry.inflight_event is not None:
                event = entry.inflight_event
                fetch_id = entry.inflight_id

            else:
                # We are the fetch owner
                event = asyncio.Event()
                self._id_counter += 1
                fetch_id = self._id_counter

                if entry is None:
                    entry = CacheEntry()
                    self._cache[key] = entry
                entry.inflight_event = event
                entry.inflight_id = fetch_id
                event = None  # signal that we own the fetch

        if event is not None:
            # Another fetch started while we waited for the lock — coalesce
            await event.wait()
            entry = self._cache.get(key)
            if entry is not None and entry.data is not None:
                return entry.data
            if entry is not None and entry.error is not None:
                if entry.data is not None:
                    return entry.data
                raise entry.error
            # Shouldn't happen, but fall through to try our own fetch
            return await self._do_fetch(key, fetcher)

        # We own the fetch — execute outside the lock
        entry = self._cache[key]
        owned_event = entry.inflight_event
        try:
            result = await run_in_fablib_pool(fetcher)
            async with self._lock:
                entry.data = result
                entry.timestamp = time.time()
                entry.error = None
                entry.inflight_event = None
            if owned_event is not None:
                owned_event.set()
            return result
        except Exception as exc:
            async with self._lock:
                entry.error = exc
                entry.inflight_event = None
            if owned_event is not None:
                owned_event.set()
            # Stale-on-error fallback
            if entry.data is not None:
                logger.warning(
                    "Fetch failed for '%s', returning stale data: %s", key, exc
                )
                return entry.data
            raise

    def _start_background_fetch(
        self, key: str, entry: CacheEntry, fetcher: Callable
    ) -> None:
        """Kick off a background refresh (called while holding ``_lock``)."""
        event = asyncio.Event()
        self._id_counter += 1
        fetch_id = self._id_counter
        entry.inflight_event = event
        entry.inflight_id = fetch_id

        async def _bg() -> None:
            try:
                result = await run_in_fablib_pool(fetcher)
                async with self._lock:
                    entry.data = result
                    entry.timestamp = time.time()
                    entry.error = None
                    entry.inflight_event = None
                event.set()
            except Exception as exc:
                logger.warning(
                    "Background refresh failed for '%s': %s", key, exc
                )
                async with self._lock:
                    entry.error = exc
                    entry.inflight_event = None
                event.set()

        asyncio.get_event_loop().create_task(_bg())


# ------------------------------------------------------------------
# Module-level singleton
# ------------------------------------------------------------------

_manager: Optional[FabricCallManager] = None


def get_call_manager() -> FabricCallManager:
    """Return the singleton :class:`FabricCallManager` instance."""
    global _manager
    if _manager is None:
        _manager = FabricCallManager()
    return _manager


def reset_call_manager() -> None:
    """Reset the singleton (for tests)."""
    global _manager
    _manager = None
