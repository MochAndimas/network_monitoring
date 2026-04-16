import secrets

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..db.session import get_db
from ..services.auth_service import AuthenticatedActor, get_user_from_token


def _validate_internal_api_key(x_api_key: str | None) -> AuthenticatedActor | None:
    if not settings.internal_api_key:
        if settings.allow_insecure_no_auth:
            return AuthenticatedActor(kind="insecure", role="admin")
        return None
    if x_api_key and secrets.compare_digest(x_api_key, settings.internal_api_key):
        return AuthenticatedActor(kind="api_key", role="admin")
    return None


async def require_api_access(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> AuthenticatedActor:
    api_key_actor = _validate_internal_api_key(x_api_key)
    if api_key_actor is not None:
        return api_key_actor

    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        if token:
            return await get_user_from_token(db, token)

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")


async def require_admin_access(actor: AuthenticatedActor = Depends(require_api_access)) -> AuthenticatedActor:
    if actor.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return actor
