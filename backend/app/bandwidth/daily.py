"""Exact integer allocation over half-open WIB calendar days.

Time within a flow is unmeasured: proportional allocation is an estimate.
Cumulative floors conserve bytes, including tiny flows spanning many days.
"""

from collections.abc import Iterator
from datetime import date, timedelta

DAY_NS = 86_400_000_000_000
WIB_NS = 7 * 3_600_000_000_000
EPOCH = date(1970, 1, 1)


def allocate_days(start_ns: int, end_ns: int, byte_count: int) -> Iterator[tuple[date, int, bool]]:
    if start_ns <= 0 or end_ns < start_ns or byte_count <= 0:
        raise ValueError("Invalid flow interval or bytes")
    first_day = (start_ns + WIB_NS) // DAY_NS
    if start_ns == end_ns:
        yield EPOCH + timedelta(days=first_day), byte_count, False
        return
    last_day = (end_ns - 1 + WIB_NS) // DAY_NS
    previous = 0
    for day in range(first_day, last_day + 1):
        boundary = min(end_ns, (day + 1) * DAY_NS - WIB_NS)
        cumulative = byte_count * (boundary - start_ns) // (end_ns - start_ns)
        yield EPOCH + timedelta(days=day), cumulative - previous, first_day != last_day
        previous = cumulative
