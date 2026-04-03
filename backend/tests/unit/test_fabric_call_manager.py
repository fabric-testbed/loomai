"""Tests for app.fabric_call_manager — caching, coalescing, invalidation."""

import asyncio
import time
from unittest.mock import patch

import pytest

from app.fabric_call_manager import FabricCallManager, CacheEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fetcher(value, delay: float = 0):
    """Return a sync fetcher that optionally sleeps (simulating FABlib latency)."""
    call_count = {"n": 0}

    def fetcher():
        call_count["n"] += 1
        if delay:
            import time as _t
            _t.sleep(delay)
        return value

    fetcher.call_count = call_count
    return fetcher


def _make_failing_fetcher(exc: Exception):
    """Return a sync fetcher that always raises."""
    call_count = {"n": 0}

    def fetcher():
        call_count["n"] += 1
        raise exc

    fetcher.call_count = call_count
    return fetcher


# Patch run_in_fablib_pool to run synchronously in the event loop thread
# (no real thread pool needed for unit tests)
@pytest.fixture(autouse=True)
def _patch_executor():
    async def _run_inline(fn, *args):
        return fn(*args)

    with patch("app.fabric_call_manager.run_in_fablib_pool", side_effect=_run_inline):
        yield


@pytest.fixture()
def mgr():
    return FabricCallManager()


# ---------------------------------------------------------------------------
# Cache hit
# ---------------------------------------------------------------------------

class TestCacheHit:
    @pytest.mark.asyncio
    async def test_fresh_cache_returns_without_fetching(self, mgr):
        """If data is cached and within max_age, fetcher should NOT be called."""
        fetcher = _make_fetcher("first")
        # Prime the cache
        result1 = await mgr.get("k", fetcher, max_age=30)
        assert result1 == "first"
        assert fetcher.call_count["n"] == 1

        # Second call — should return cached
        fetcher2 = _make_fetcher("second")
        result2 = await mgr.get("k", fetcher2, max_age=30)
        assert result2 == "first"
        assert fetcher2.call_count["n"] == 0

    @pytest.mark.asyncio
    async def test_fast_path_no_lock(self, mgr):
        """Fresh cache is served via the fast path (no lock acquisition)."""
        fetcher = _make_fetcher("data")
        await mgr.get("k", fetcher, max_age=60)

        # Spy on the lock to verify fast path
        lock_acquired = {"n": 0}
        original_acquire = mgr._lock.acquire

        async def counting_acquire():
            lock_acquired["n"] += 1
            return await original_acquire()

        mgr._lock.acquire = counting_acquire
        result = await mgr.get("k", fetcher, max_age=60)
        assert result == "data"
        assert lock_acquired["n"] == 0


# ---------------------------------------------------------------------------
# Cache expiry
# ---------------------------------------------------------------------------

class TestCacheExpiry:
    @pytest.mark.asyncio
    async def test_expired_cache_triggers_fetch(self, mgr):
        """When cached data is older than max_age, a fresh fetch happens."""
        fetcher1 = _make_fetcher("old")
        await mgr.get("k", fetcher1, max_age=30)

        # Artificially age the cache
        mgr._cache["k"].timestamp = time.time() - 60

        fetcher2 = _make_fetcher("new")
        result = await mgr.get("k", fetcher2, max_age=30)
        assert result == "new"
        assert fetcher2.call_count["n"] == 1


# ---------------------------------------------------------------------------
# max_age=0 always fetches fresh
# ---------------------------------------------------------------------------

class TestMaxAgeZero:
    @pytest.mark.asyncio
    async def test_max_age_zero_bypasses_cache(self, mgr):
        """max_age=0 should always call the fetcher, even with fresh cache."""
        fetcher1 = _make_fetcher("v1")
        await mgr.get("k", fetcher1, max_age=30)

        fetcher2 = _make_fetcher("v2")
        result = await mgr.get("k", fetcher2, max_age=0)
        assert result == "v2"
        assert fetcher2.call_count["n"] == 1

    @pytest.mark.asyncio
    async def test_max_age_zero_updates_cache(self, mgr):
        """After max_age=0 fetch, subsequent reads see new data."""
        await mgr.get("k", _make_fetcher("v1"), max_age=30)
        await mgr.get("k", _make_fetcher("v2"), max_age=0)

        fetcher3 = _make_fetcher("v3")
        result = await mgr.get("k", fetcher3, max_age=30)
        # Should return v2 from cache (not call fetcher3)
        assert result == "v2"
        assert fetcher3.call_count["n"] == 0


# ---------------------------------------------------------------------------
# Request coalescing
# ---------------------------------------------------------------------------

class TestCoalescing:
    @pytest.mark.asyncio
    async def test_concurrent_gets_coalesce(self, mgr):
        """Two concurrent get() calls for the same key should share one fetch."""
        call_count = {"n": 0}
        event = asyncio.Event()

        async def _slow_run(fn, *args):
            # First call waits; subsequent calls also wait
            call_count["n"] += 1
            await asyncio.sleep(0.05)
            return fn(*args)

        with patch("app.fabric_call_manager.run_in_fablib_pool", side_effect=_slow_run):
            fetcher = _make_fetcher("shared")
            results = await asyncio.gather(
                mgr.get("k", fetcher, max_age=0),
                mgr.get("k", fetcher, max_age=0),
            )

        assert results == ["shared", "shared"]
        # The fetcher itself should be called exactly once
        assert fetcher.call_count["n"] == 1

    @pytest.mark.asyncio
    async def test_different_keys_fetch_independently(self, mgr):
        """Different keys should not coalesce — each gets its own fetch."""
        f1 = _make_fetcher("a")
        f2 = _make_fetcher("b")

        r1, r2 = await asyncio.gather(
            mgr.get("k1", f1, max_age=0),
            mgr.get("k2", f2, max_age=0),
        )
        assert r1 == "a"
        assert r2 == "b"
        assert f1.call_count["n"] == 1
        assert f2.call_count["n"] == 1


# ---------------------------------------------------------------------------
# Mutation invalidation
# ---------------------------------------------------------------------------

class TestInvalidation:
    @pytest.mark.asyncio
    async def test_invalidate_causes_fresh_fetch(self, mgr):
        """After invalidate(), the next get() should fetch fresh data."""
        await mgr.get("k", _make_fetcher("old"), max_age=30)

        mgr.invalidate("k")

        fetcher2 = _make_fetcher("new")
        result = await mgr.get("k", fetcher2, max_age=30)
        assert result == "new"
        assert fetcher2.call_count["n"] == 1

    @pytest.mark.asyncio
    async def test_invalidate_nonexistent_key_is_noop(self, mgr):
        """Invalidating a key that doesn't exist should not raise."""
        mgr.invalidate("nonexistent")  # should not raise

    @pytest.mark.asyncio
    async def test_invalidate_prefix(self, mgr):
        """invalidate_prefix should expire all matching keys."""
        await mgr.get("slice:abc", _make_fetcher("s1"), max_age=30)
        await mgr.get("slice:abc:slivers", _make_fetcher("s2"), max_age=30)
        await mgr.get("sites", _make_fetcher("s3"), max_age=30)

        mgr.invalidate_prefix("slice:abc")

        # slice keys should be expired
        assert mgr._cache["slice:abc"].timestamp == 0
        assert mgr._cache["slice:abc:slivers"].timestamp == 0
        # sites key should still be valid
        assert mgr._cache["sites"].timestamp > 0


# ---------------------------------------------------------------------------
# Stale-on-error fallback
# ---------------------------------------------------------------------------

class TestStaleOnError:
    @pytest.mark.asyncio
    async def test_returns_stale_data_on_fetch_failure(self, mgr):
        """If a fresh fetch fails but stale data exists, return stale data."""
        await mgr.get("k", _make_fetcher("stale"), max_age=30)

        # Expire the cache
        mgr._cache["k"].timestamp = 0

        failing = _make_failing_fetcher(RuntimeError("FABRIC down"))
        result = await mgr.get("k", failing, max_age=30)
        assert result == "stale"
        assert failing.call_count["n"] == 1

    @pytest.mark.asyncio
    async def test_raises_when_no_stale_data(self, mgr):
        """If fetch fails and there's no stale data, the error propagates."""
        failing = _make_failing_fetcher(RuntimeError("no connection"))
        with pytest.raises(RuntimeError, match="no connection"):
            await mgr.get("k", failing, max_age=30)

    @pytest.mark.asyncio
    async def test_coalesced_waiters_get_stale_on_error(self, mgr):
        """When a coalesced fetch fails, waiters should get stale data if available."""
        await mgr.get("k", _make_fetcher("stale"), max_age=30)
        mgr._cache["k"].timestamp = 0

        async def _slow_fail(fn, *args):
            await asyncio.sleep(0.05)
            raise RuntimeError("network error")

        with patch("app.fabric_call_manager.run_in_fablib_pool", side_effect=_slow_fail):
            # Both requests should get the stale data back
            results = await asyncio.gather(
                mgr.get("k", _make_fetcher("unused"), max_age=0),
                mgr.get("k", _make_fetcher("unused"), max_age=0),
                return_exceptions=True,
            )
        # At least one should get stale data, none should get RuntimeError
        # The owner gets stale fallback; the waiter may also get stale or re-fetch
        for r in results:
            if isinstance(r, Exception):
                pytest.fail(f"Expected stale fallback, got exception: {r}")
            assert r == "stale"


# ---------------------------------------------------------------------------
# Stale-while-revalidate (SWR)
# ---------------------------------------------------------------------------

class TestSWR:
    @pytest.mark.asyncio
    async def test_swr_returns_stale_immediately(self, mgr):
        """SWR mode should return stale data without waiting for refresh."""
        await mgr.get("k", _make_fetcher("original"), max_age=30)
        mgr._cache["k"].timestamp = time.time() - 60  # expire

        bg_started = asyncio.Event()
        bg_complete = asyncio.Event()

        async def _slow_run(fn, *args):
            bg_started.set()
            await asyncio.sleep(0.1)
            result = fn(*args)
            bg_complete.set()
            return result

        with patch("app.fabric_call_manager.run_in_fablib_pool", side_effect=_slow_run):
            # Should return stale immediately, not block
            result = await mgr.get(
                "k", _make_fetcher("refreshed"), max_age=30,
                stale_while_revalidate=True,
            )
            assert result == "original"  # stale data returned immediately

            # Wait for background refresh to complete
            await asyncio.wait_for(bg_complete.wait(), timeout=2.0)

        # Now cache should have refreshed data
        result2 = await mgr.get("k", _make_fetcher("unused"), max_age=30)
        assert result2 == "refreshed"

    @pytest.mark.asyncio
    async def test_swr_not_triggered_when_fresh(self, mgr):
        """SWR flag should have no effect when cache is fresh."""
        fetcher = _make_fetcher("data")
        await mgr.get("k", fetcher, max_age=30)

        fetcher2 = _make_fetcher("new")
        result = await mgr.get(
            "k", fetcher2, max_age=30, stale_while_revalidate=True,
        )
        assert result == "data"
        assert fetcher2.call_count["n"] == 0

    @pytest.mark.asyncio
    async def test_swr_does_not_start_duplicate_bg_fetch(self, mgr):
        """If a background fetch is already running, SWR should not start another."""
        await mgr.get("k", _make_fetcher("original"), max_age=30)
        mgr._cache["k"].timestamp = time.time() - 60

        fetch_count = {"n": 0}

        async def _counting_run(fn, *args):
            fetch_count["n"] += 1
            await asyncio.sleep(0.1)
            return fn(*args)

        with patch("app.fabric_call_manager.run_in_fablib_pool", side_effect=_counting_run):
            # Two SWR calls in quick succession
            r1 = await mgr.get("k", _make_fetcher("r1"), max_age=30, stale_while_revalidate=True)
            r2 = await mgr.get("k", _make_fetcher("r2"), max_age=30, stale_while_revalidate=True)

            # Both should return stale immediately
            assert r1 == "original"
            assert r2 == "original"

            # Let background complete
            await asyncio.sleep(0.2)

        # Only one background fetch should have started
        assert fetch_count["n"] == 1
