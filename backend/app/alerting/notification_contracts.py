"""Transaction-owned notification persistence contract for alert evaluation."""

from collections.abc import Awaitable, Callable
from sqlalchemy.ext.asyncio import AsyncSession

# A writer only persists jobs using this session. It must neither commit nor
# perform network I/O; the engine/calling transaction owns the commit boundary.
# The adapter must preserve ACTIVE/RESOLVED stream identity and serialize
# producers until commit. It must snapshot routing/grouping and use stable
# idempotency keys; injecting a writer alone does not provide those guarantees.
NotificationBatchWriter = Callable[[AsyncSession, list[dict]], Awaitable[None]]
