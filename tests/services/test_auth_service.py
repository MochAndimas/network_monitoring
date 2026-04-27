"""Define test module behavior for `tests/services/test_auth_service.py`.

This module contains automated regression and validation scenarios.
"""

from datetime import timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.app.core.config import settings
from backend.app.core.security import hash_password
from backend.app.core.time import utcnow
from backend.app.db.base import Base
from backend.app.models.user import AuthLoginAttempt, AuthSession, User
from backend.app.services.auth_service import cleanup_auth_data
from tests.test_utils import run

def test_cleanup_auth_data_removes_old_sessions_and_attempts():
    """Validate that cleanup auth data removes old sessions and attempts.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    original_password_secret = settings.auth_password_secret
    original_jwt_secret = settings.auth_jwt_secret
    settings.auth_password_secret = "test-password-secret"
    settings.auth_jwt_secret = "test-jwt-secret"

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    async def scenario():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with session_factory() as db:
            user = User(
                username="viewer",
                full_name="Viewer",
                password_hash=hash_password("StrongPass123!"),
                role="viewer",
                is_active=True,
            )
            db.add(user)
            await db.flush()

            old_timestamp = utcnow() - timedelta(days=45)
            recent_timestamp = utcnow() - timedelta(days=1)
            db.add_all(
                [
                    AuthSession(
                        user_id=user.id,
                        jwt_id="old-session",
                        token_hash="old-token-hash",
                        expires_at=old_timestamp,
                        created_at=old_timestamp,
                        last_seen_at=old_timestamp,
                    ),
                    AuthSession(
                        user_id=user.id,
                        jwt_id="recent-session",
                        token_hash="recent-token-hash",
                        expires_at=recent_timestamp,
                        created_at=recent_timestamp,
                        last_seen_at=recent_timestamp,
                    ),
                    AuthLoginAttempt(
                        username="viewer",
                        client_ip="127.0.0.1",
                        was_successful=False,
                        attempted_at=utcnow() - timedelta(days=10),
                    ),
                    AuthLoginAttempt(
                        username="viewer",
                        client_ip="127.0.0.1",
                        was_successful=False,
                        attempted_at=utcnow() - timedelta(hours=1),
                    ),
                ]
            )
            await db.commit()

        async with session_factory() as db:
            result = await cleanup_auth_data(db)
            remaining_sessions = (await db.execute(Base.metadata.tables["auth_sessions"].select())).all()
            remaining_attempts = (await db.execute(Base.metadata.tables["auth_login_attempts"].select())).all()
            return result, remaining_sessions, remaining_attempts

    try:
        result, remaining_sessions, remaining_attempts = run(scenario())
        run(engine.dispose())

        assert result["auth_sessions_deleted"] == 1
        assert result["auth_login_attempts_deleted"] == 1
        assert len(remaining_sessions) == 1
        assert len(remaining_attempts) == 1
    finally:
        settings.auth_password_secret = original_password_secret
        settings.auth_jwt_secret = original_jwt_secret
