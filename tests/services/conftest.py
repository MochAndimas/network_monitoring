"""Reusable isolated databases for notification and bandwidth integration tests."""

import os

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from backend.app.models.device import Device
from tests.test_utils import create_all, drop_all, run


@pytest.fixture
def outbox_sessions(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'outbox.db'}")
    run(create_all(engine))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    run(drop_all(engine))


@pytest.fixture
def inventory_sessions(tmp_path):
    url = os.environ.get("BANDWIDTH_TEST_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'inventory.db'}")
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite" and not (parsed.database or "").endswith("_test"):
        raise ValueError("Bandwidth fixtures require a disposable database name ending in _test")
    engine = create_async_engine(url, poolclass=NullPool)
    run(create_all(engine))
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    async def seed():
        async with factory.begin() as db:
            db.add_all(
                [
                    Device(id=1, name="Router A", ip_address="192.0.2.1", device_type="mikrotik"),
                    Device(id=2, name="Router B", ip_address="192.0.2.2", device_type="mikrotik"),
                ]
            )

    run(seed())
    yield factory
    run(drop_all(engine))
