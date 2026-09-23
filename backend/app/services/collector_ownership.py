"""One device-collector ownership policy for scheduler and manual cycles."""

from dataclasses import dataclass
import hashlib

from ..core.config import settings


@dataclass(frozen=True)
class DeviceCollectorOwnership:
    site: str | None
    excluded_sites: frozenset[str]

    @property
    def lock_scope(self) -> str:
        """Keep site names separate from the reserved central owner."""
        if self.site is None:
            return "device:central"
        digest = hashlib.sha256(self.site.encode("utf-8")).hexdigest()[:32]
        return f"device:site:{digest}"


def device_collector_ownership() -> DeviceCollectorOwnership:
    """Central excludes delegated sites; an agent collects only its own site."""
    site = settings.monitor.collector_agent_site.strip() or None
    delegated = frozenset(item.strip() for item in settings.monitor.collector_agent_sites.split(",") if item.strip())
    return DeviceCollectorOwnership(site=site, excluded_sites=frozenset() if site else delegated)
