"""Provide database engine, session, and initialization helpers for the network monitoring project."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
