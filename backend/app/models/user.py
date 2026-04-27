"""Define module logic for `backend/app/models/user.py`.

This module contains project-specific implementation details.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base
from ..core.time import utcnow


class User(Base):
    """Perform User.

    This class encapsulates related behavior and data for this domain area.
    """
    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_username_active", "username", "is_active"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="viewer")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=utcnow)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    disabled_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    sessions: Mapped[list["AuthSession"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class AuthSession(Base):
    """Perform AuthSession.

    This class encapsulates related behavior and data for this domain area.
    """
    __tablename__ = "auth_sessions"
    __table_args__ = (
        Index("ix_auth_sessions_user_active", "user_id", "expires_at", "revoked_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    jwt_id: Mapped[str | None] = mapped_column(String(36), nullable=True, unique=True, index=True)
    token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    client_ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    user_agent: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship(back_populates="sessions")


class AuthLoginAttempt(Base):
    """Perform AuthLoginAttempt.

    This class encapsulates related behavior and data for this domain area.
    """
    __tablename__ = "auth_login_attempts"
    __table_args__ = (
        Index("ix_auth_login_attempts_lookup", "username", "client_ip", "attempted_at"),
        Index("ix_auth_login_attempts_cleanup", "attempted_at", "was_successful"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    client_ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    was_successful: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    was_rate_limited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attempted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)
