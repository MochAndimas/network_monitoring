"""db support code for base."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Helper object used by database setup."""
    pass
