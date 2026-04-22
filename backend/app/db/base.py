"""Provide database engine, session, and initialization helpers for the network monitoring project."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Represent base behavior and data for database engine, session, and initialization helpers.

    Inherits from `DeclarativeBase` to match the surrounding framework or persistence model.
    """
    pass
