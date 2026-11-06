"""Materialized WIB usage; delayed identity attribution preserves byte totals."""

from datetime import date
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, Date, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base


class BandwidthDailyUsage(Base):
    __tablename__ = "bandwidth_daily_usage"
    __table_args__ = (
        CheckConstraint(
            "upload_bytes >= 0 AND download_bytes >= 0 AND estimated_bytes >= 0",
            name="ck_bw_daily_bytes",
        ),
    )

    router_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    # c:<client id> merges that client's IP changes; ip:<address> stays unresolved.
    subject: Mapped[str] = mapped_column(String(32), primary_key=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("bandwidth_clients.id"))
    unresolved_ip: Mapped[str | None] = mapped_column(String(15))
    upload_bytes: Mapped[Decimal] = mapped_column(Numeric(38, 0).with_variant(BigInteger(), "sqlite"), nullable=False)
    download_bytes: Mapped[Decimal] = mapped_column(Numeric(38, 0).with_variant(BigInteger(), "sqlite"), nullable=False)
    estimated_bytes: Mapped[Decimal] = mapped_column(
        Numeric(38, 0).with_variant(BigInteger(), "sqlite"), nullable=False
    )
    updated_ns: Mapped[int] = mapped_column(BigInteger, nullable=False)
