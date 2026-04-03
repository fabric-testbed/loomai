"""Dedicated thread pool for Chameleon (OpenStack) blocking calls.

Same pattern as fablib_executor.py — isolates blocking Keystone/Nova/Blazar
calls from the async event loop.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, TypeVar

T = TypeVar("T")

_chi_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="chameleon")


async def run_in_chi_pool(fn: Callable[..., T], *args: Any) -> T:
    """Run a blocking Chameleon/OpenStack call in the dedicated thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_chi_pool, fn, *args)
