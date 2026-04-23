"""Collection helpers shared across application layers."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import TypeVar


T = TypeVar("T")


def chunked(items: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    """Yield contiguous chunks from an input sequence."""
    for index in range(0, len(items), size):
        yield items[index : index + size]

