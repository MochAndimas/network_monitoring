"""Client inventory is separate from monitored infrastructure targets.

All inventory timestamps are UTC epoch nanoseconds (signed BIGINT), avoiding the
legacy naive WIB metric timestamps. No inferred DHCP assignment times are stored.
"""

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base


class BandwidthClient(Base):
    __tablename__ = "bandwidth_clients"
    __table_args__ = (UniqueConstraint("router_id", "mac_address", name="uq_bw_client_router_mac"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    router_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False)
    mac_address: Mapped[str] = mapped_column(String(17), nullable=False)
    hostname: Mapped[str | None] = mapped_column(String(255))
    custom_name: Mapped[str | None] = mapped_column(String(255))
    first_seen_ns: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_seen_ns: Mapped[int] = mapped_column(BigInteger, nullable=False)


class BandwidthIPHistory(Base):
    __tablename__ = "bandwidth_client_ip_history"
    __table_args__ = (
        UniqueConstraint("router_id", "ip_address", "active_slot", name="uq_bw_ip_active"),
        Index("ix_bw_ip_router_time", "router_id", "ip_address", "first_observed_ns"),
        Index("ix_bw_ip_router_active", "router_id", "active_slot"),
        CheckConstraint("last_observed_ns >= first_observed_ns", name="ck_bw_ip_observation_order"),
        CheckConstraint(
            "(active_slot IS NOT NULL AND active_slot = 1 AND ended_ns IS NULL) "
            "OR (active_slot IS NULL AND ended_ns IS NOT NULL)",
            name="ck_bw_ip_active_state",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    router_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False)
    client_id: Mapped[int] = mapped_column(ForeignKey("bandwidth_clients.id"), nullable=False)
    ip_address: Mapped[str] = mapped_column(String(15), nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False)
    first_observed_ns: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_observed_ns: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ended_ns: Mapped[int | None] = mapped_column(BigInteger)
    # NULL on historical rows allows multiple closed intervals on MySQL/SQLite.
    active_slot: Mapped[int | None] = mapped_column(nullable=True)


class BandwidthInventoryState(Base):
    __tablename__ = "bandwidth_inventory_states"

    router_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), primary_key=True)
    observed_ns: Mapped[int] = mapped_column(BigInteger, nullable=False)
    client_count: Mapped[int] = mapped_column(nullable=False)
    ambiguous_ip_count: Mapped[int] = mapped_column(nullable=False)
    invalid_row_count: Mapped[int] = mapped_column(nullable=False)
