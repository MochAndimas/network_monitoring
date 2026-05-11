"""Compatibility facade for live monitoring dashboard helpers.

The implementation is split under ``dashboard.pages.live_monitoring.modules``.
This module keeps the historical import path stable for dashboard pages and tests.
"""

from .modules import impl as _impl

for _name in dir(_impl):
    if _name.startswith("__"):
        continue
    globals()[_name] = getattr(_impl, _name)

__all__ = [_name for _name in globals() if not _name.startswith("__")]
