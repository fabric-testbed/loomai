"""Dedicated thread pool for FABlib blocking calls.

FABlib calls are blocking and can take 2-15 seconds each. Using a dedicated
pool prevents them from starving WebSocket terminals, SSE streams, file ops,
and other async operations that share Python's default thread pool.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, TypeVar

T = TypeVar("T")

# Dedicated pool for FABlib calls — limits concurrency so we don't overwhelm
# FABlib's internal state (which is not fully thread-safe) while still
# allowing some parallelism for independent slice operations.
_fablib_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="fablib")


async def run_in_fablib_pool(fn: Callable[..., T], *args: Any) -> T:
    """Run a blocking FABlib call in the dedicated thread pool.

    Usage:
        result = await run_in_fablib_pool(fablib.get_slices)
        result = await run_in_fablib_pool(lambda: fablib.get_slice(name="foo"))
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_fablib_pool, fn, *args)
