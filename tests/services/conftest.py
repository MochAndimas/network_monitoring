"""Reusable isolated database for notification tests only."""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from tests.test_utils import create_all, drop_all, run


@pytest.fixture
def outbox_sessions(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'outbox.db'}")
    run(create_all(engine))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    run(drop_all(engine))
