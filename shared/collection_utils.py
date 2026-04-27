"""Define module logic for `shared/collection_utils.py`.

This module contains project-specific implementation details.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import TypeVar


T = TypeVar("T")


def chunked(items: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    """Yield fixed-size contiguous slices from a sequence.

    Args:
        items: Source sequence to split into smaller batches.
        size: Maximum number of items per yielded chunk; callers should pass
            a positive integer.

    Yields:
        Consecutive ``Sequence[T]`` slices that preserve input ordering.
    """
    for index in range(0, len(items), size):
        yield items[index : index + size]

