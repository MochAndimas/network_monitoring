"""Log elapsed time for a bounded operation without recording its payload."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter


@contextmanager
def timed_phase(logger: logging.Logger, phase: str, scope: str) -> Iterator[None]:
    started_at = perf_counter()
    outcome = "interrupted"
    try:
        yield
        outcome = "ok"
    except Exception:
        outcome = "error"
        raise
    finally:
        logger.info(
            "scheduler_phase phase=%s scope=%s outcome=%s duration_ms=%.2f",
            phase, scope, outcome, (perf_counter() - started_at) * 1000,
        )
