from sqlalchemy import Float, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base


class Threshold(Base):
    __tablename__ = "thresholds"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
