import secrets

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import internal_api_key_map, settings
from ..db.session import get_db
from ..services.auth_service import AuthenticatedActor, actor_has_permission, get_user_from_access_token


def _validate_internal_api_key(x_api_key: str | None) -> AuthenticatedActor | None:
    api_keys = internal_api_key_map()
    if not api_keys:
        if settings.allow_insecure_no_auth:
            return AuthenticatedActor(kind="insecure", role="admin", permissions=frozenset({"admin", "ops", "read", "write"}))
        return None
    if x_api_key and x_api_key in api_keys:
        for secret, spec in api_keys.items():
            if secrets.compare_digest(x_api_key, secret):
                scopes = frozenset(str(scope) for scope in spec.get("scopes", []))
                return AuthenticatedActor(
                    kind="api_key",
                    role="service",
                    permissions=scopes,
                    api_key_name=str(spec.get("name") or "unnamed"),
                )
    return None


async def _authenticate_api_access(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
    session_cookie: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> AuthenticatedActor:
    api_key_actor = _validate_internal_api_key(x_api_key)
    if api_key_actor is not None:
        return api_key_actor

    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        if token:
            return await get_user_from_access_token(db, token)

    if session_cookie:
        return await get_user_from_access_token(db, session_cookie)

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")


async def require_api_access(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> AuthenticatedActor:
    return await _authenticate_api_access(authorization=authorization, x_api_key=x_api_key, db=db)


async def require_api_access_with_session_cookie(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=settings.auth_cookie_name),
    db: AsyncSession = Depends(get_db),
) -> AuthenticatedActor:
    return await _authenticate_api_access(
        authorization=authorization,
        x_api_key=x_api_key,
        session_cookie=session_cookie,
        db=db,
    )


async def require_admin_access(actor: AuthenticatedActor = Depends(require_api_access)) -> AuthenticatedActor:
    if actor.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return actor


async def require_write_access(actor: AuthenticatedActor = Depends(require_api_access)) -> AuthenticatedActor:
    if actor.user is not None and actor.role == "admin":
        return actor
    if actor_has_permission(actor, "write"):
        return actor
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Write access required")


async def require_ops_access(actor: AuthenticatedActor = Depends(require_api_access)) -> AuthenticatedActor:
    if actor.user is not None and actor.role == "admin":
        return actor
    if actor_has_permission(actor, "ops"):
        return actor
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ops access required")
