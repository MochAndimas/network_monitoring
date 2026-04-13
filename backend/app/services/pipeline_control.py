from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator


_monitoring_pipeline_lock = asyncio.Lock()


@asynccontextmanager
async def monitoring_pipeline_guard(*, wait: bool) -> AsyncIterator[bool]:
    acquired = False
    if wait:
        await _monitoring_pipeline_lock.acquire()
        acquired = True
    else:
        try:
            await asyncio.wait_for(_monitoring_pipeline_lock.acquire(), timeout=0.001)
            acquired = True
        except TimeoutError:
            acquired = False

    try:
        yield acquired
    finally:
        if acquired:
            _monitoring_pipeline_lock.release()
