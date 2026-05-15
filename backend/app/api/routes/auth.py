"""FastAPI routes for auth endpoints."""

from time import time
from urllib.parse import urlparse

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import require_admin_access, require_api_access, require_api_access_with_session_cookie
from ...api.schemas import (
    AdminAuditLogItem,
    AuthAdminSessionItem,
    AuthSessionItem,
    ChangePasswordRequest,
    CurrentUserResponse,
    LoginRequest,
    LoginResponse,
    LogoutAllResponse,
    UserAdminCreateRequest,
    UserAdminItem,
    UserAdminUpdateRequest,
    UserPasswordResetRequest,
    UserSessionInfo,
)
from ...core.config import settings
from ...core.time import as_wib_aware
from ...db.session import get_db
from ...services.audit_service import list_admin_audit_logs, record_admin_audit_log
from ...services.auth_service import (
    authenticate_user_with_options,
    change_password_for_user,
    create_user_for_admin,
    list_users_for_admin,
    list_active_sessions_for_user,
    list_sessions_for_admin,
    refresh_user_session,
    revoke_all_sessions_for_user,
    revoke_other_sessions_for_user,
    revoke_token,
    reset_user_password_for_admin,
    update_user_for_admin,
)

router = APIRouter()


def _client_ip_from_request(request: Request) -> str:
    """Handle the client ip from request endpoint."""
    remote_ip = request.client.host if request.client and request.client.host else ""
    forwarded_for = request.headers.get("x-forwarded-for", "")
    trusted_proxies = settings.normalized_trusted_proxy_ips
    if remote_ip and remote_ip in trusted_proxies and forwarded_for.strip():
        return forwarded_for.split(",", 1)[0].strip()
    if remote_ip:
        return remote_ip
    return ""


def _user_agent_from_request(request: Request) -> str:
    """Handle the user agent from request endpoint."""
    return (request.headers.get("user-agent") or "").strip()[:255]


def _max_age_from_expiry(expires_at) -> int:
    """Handle the max age from expiry endpoint."""
    return max(int(as_wib_aware(expires_at).timestamp() - time()), 0)


def _set_auth_cookie(response: Response, token: str, *, expires_at) -> None:
    """Handle the auth cookie endpoint."""
    max_age = _max_age_from_expiry(expires_at)
    auth_settings = settings.auth
    response.set_cookie(
        key=auth_settings.cookie_name,
        value=token,
        httponly=True,
        secure=auth_settings.cookie_secure,
        samesite=settings.normalized_auth_cookie_samesite,
        max_age=max_age,
        expires=max_age,
        path="/",
    )


def _clear_auth_cookie(response: Response) -> None:
    """Handle the auth cookie endpoint."""
    auth_settings = settings.auth
    response.delete_cookie(
        key=auth_settings.cookie_name,
        httponly=True,
        secure=auth_settings.cookie_secure,
        samesite=settings.normalized_auth_cookie_samesite,
        path="/",
    )


def _set_refresh_cookie(response: Response, token: str, *, expires_at) -> None:
    """Handle the refresh cookie endpoint."""
    max_age = _max_age_from_expiry(expires_at)
    auth_settings = settings.auth
    response.set_cookie(
        key=auth_settings.refresh_cookie_name,
        value=token,
        httponly=True,
        secure=auth_settings.cookie_secure,
        samesite=settings.normalized_auth_cookie_samesite,
        max_age=max_age,
        expires=max_age,
        path="/",
    )


def _clear_refresh_cookie(response: Response) -> None:
    """Handle the refresh cookie endpoint."""
    auth_settings = settings.auth
    response.delete_cookie(
        key=auth_settings.refresh_cookie_name,
        httponly=True,
        secure=auth_settings.cookie_secure,
        samesite=settings.normalized_auth_cookie_samesite,
        path="/",
    )


def _build_login_response(user, token: str, expiry) -> LoginResponse:
    """Handle the login response endpoint."""
    return LoginResponse(
        access_token=token,
        user=UserSessionInfo(
            id=user.id,
            username=user.username,
            full_name=user.full_name,
            role=user.role,
            expires_at=expiry,
        ),
    )


def _set_no_store_headers(response: Response) -> None:
    """Handle the no store headers endpoint."""
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def _client_metadata(request: Request) -> tuple[str, str]:
    """Handle the client metadata endpoint."""
    return _client_ip_from_request(request), _user_agent_from_request(request)


def _normalize_origin(value: str | None) -> str | None:
    """Handle the origin endpoint."""
    raw_value = str(value or "").strip()
    if not raw_value:
        return None
    parsed = urlparse(raw_value)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _trusted_cookie_origins() -> set[str]:
    """Handle the trusted cookie origins endpoint."""
    return {origin.strip().lower() for origin in settings.normalized_cors_origins if origin.strip()}


def _trusted_cookie_hosts() -> set[str]:
    """Handle the trusted cookie hosts endpoint."""
    return {host.strip().lower() for host in settings.normalized_trusted_hosts if host.strip()}


def _is_trusted_host_header(host_header: str | None) -> bool:
    """Return whether is trusted host header applies in API routes."""
    raw_host = str(host_header or "").strip().lower()
    if not raw_host:
        return False
    if raw_host.startswith("[") and "]" in raw_host:
        normalized_host = raw_host.split("]", 1)[0].lstrip("[")
    else:
        normalized_host = raw_host.split(":", 1)[0]
    return normalized_host in _trusted_cookie_hosts()


def _enforce_cookie_request_origin(request: Request) -> None:
    """Handle the enforce cookie request origin endpoint."""
    origin = _normalize_origin(request.headers.get("origin"))
    referer_origin = _normalize_origin(request.headers.get("referer"))
    trusted_origins = _trusted_cookie_origins()

    if origin is not None:
        if origin not in trusted_origins:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Untrusted request origin")
        return

    if referer_origin is not None:
        if referer_origin not in trusted_origins:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Untrusted request origin")
        return

    if not _is_trusted_host_header(request.headers.get("host")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Untrusted request origin")


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """Handle the login endpoint."""
    _set_no_store_headers(response)
    user, tokens = await authenticate_user_with_options(
        db,
        payload.username,
        payload.password,
        remember=payload.remember,
        client_ip=_client_ip_from_request(request),
        user_agent=_user_agent_from_request(request),
    )
    _set_auth_cookie(response, tokens.access_token, expires_at=tokens.access_expires_at)
    _set_refresh_cookie(response, tokens.refresh_token, expires_at=tokens.refresh_expires_at)
    return _build_login_response(user, tokens.access_token, tokens.access_expires_at)


@router.post("/restore", response_model=LoginResponse)
async def restore_session(
    request: Request,
    response: Response,
    session_cookie: str | None = Cookie(default=None, alias=settings.auth.cookie_name),
    refresh_cookie: str | None = Cookie(default=None, alias=settings.auth.refresh_cookie_name),
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """Handle the session endpoint."""
    _set_no_store_headers(response)
    refresh_token = refresh_cookie or session_cookie
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    _enforce_cookie_request_origin(request)
    user, tokens = await refresh_user_session(db, refresh_token)
    _set_auth_cookie(response, tokens.access_token, expires_at=tokens.access_expires_at)
    _set_refresh_cookie(response, tokens.refresh_token, expires_at=tokens.refresh_expires_at)
    return _build_login_response(user, tokens.access_token, tokens.access_expires_at)


@router.get("/me", response_model=CurrentUserResponse)
async def me(actor=Depends(require_api_access_with_session_cookie)) -> CurrentUserResponse:
    """Handle the me endpoint."""
    user = actor.user
    if user is None:
        return CurrentUserResponse(
            id=0,
            username=actor.api_key_name or "system",
            full_name="System API Key",
            role=actor.role,
            auth_kind=actor.kind,
            scopes=sorted(actor.permissions),
        )
    return CurrentUserResponse(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        role=user.role,
        auth_kind=actor.kind,
        scopes=sorted(actor.permissions),
        expires_at=actor.session.expires_at if actor.session is not None else None,
    )


@router.get("/sessions", response_model=list[AuthSessionItem])
async def list_my_sessions(actor=Depends(require_api_access), db: AsyncSession = Depends(get_db)) -> list[AuthSessionItem]:
    """Handle the my sessions endpoint."""
    if actor.user is None or actor.session is None:
        return []
    sessions = await list_active_sessions_for_user(db, user_id=actor.user.id, current_jwt_id=actor.session.jwt_id)
    return [
        AuthSessionItem(
            session_id=session.id,
            client_ip=session.client_ip,
            user_agent=session.user_agent,
            created_at=session.created_at,
            last_seen_at=session.last_seen_at,
            expires_at=session.expires_at,
            is_current=session.jwt_id == actor.session.jwt_id,
        )
        for session in sessions
    ]


@router.post("/logout-all", response_model=LogoutAllResponse)
async def logout_all_sessions(
    response: Response,
    actor=Depends(require_api_access),
    db: AsyncSession = Depends(get_db),
) -> LogoutAllResponse:
    """Handle the logout all sessions endpoint."""
    _set_no_store_headers(response)
    if actor.user is None or actor.session is None:
        _clear_auth_cookie(response)
        _clear_refresh_cookie(response)
        return LogoutAllResponse(revoked_sessions=0)
    revoked_sessions = await revoke_other_sessions_for_user(
        db,
        user_id=actor.user.id,
        current_jwt_id=actor.session.jwt_id,
    )
    return LogoutAllResponse(revoked_sessions=revoked_sessions)


@router.get("/admin/sessions", response_model=list[AuthAdminSessionItem], dependencies=[Depends(require_admin_access)])
async def admin_list_sessions(
    username: str | None = Query(default=None),
    include_revoked: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
) -> list[AuthAdminSessionItem]:
    """Handle the admin list sessions endpoint."""
    rows = await list_sessions_for_admin(db, username=username, include_revoked=include_revoked)
    return [
        AuthAdminSessionItem(
            session_id=session.id,
            user_id=user.id,
            username=user.username,
            full_name=user.full_name,
            role=user.role,
            client_ip=session.client_ip,
            user_agent=session.user_agent,
            created_at=session.created_at,
            last_seen_at=session.last_seen_at,
            expires_at=session.expires_at,
            revoked_at=session.revoked_at,
            is_current=False,
        )
        for session, user in rows
    ]


@router.post("/admin/users/{user_id}/logout-all", response_model=LogoutAllResponse, dependencies=[Depends(require_admin_access)])
async def admin_logout_all_user_sessions(
    user_id: int,
    request: Request,
    actor=Depends(require_admin_access),
    db: AsyncSession = Depends(get_db),
) -> LogoutAllResponse:
    """Handle the admin logout all user sessions endpoint."""
    try:
        revoked_sessions = await revoke_all_sessions_for_user(db, user_id=user_id, commit=False)
        client_ip, user_agent = _client_metadata(request)
        await record_admin_audit_log(
            db,
            actor=actor,
            action="auth.admin.logout_all_sessions",
            target_type="user",
            target_id=str(user_id),
            ip_address=client_ip,
            user_agent=user_agent,
            details={"revoked_sessions": revoked_sessions},
            commit=False,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return LogoutAllResponse(revoked_sessions=revoked_sessions)


@router.get("/admin/users", response_model=list[UserAdminItem], dependencies=[Depends(require_admin_access)])
async def admin_list_users(db: AsyncSession = Depends(get_db)) -> list[UserAdminItem]:
    """Handle the admin list users endpoint."""
    return [UserAdminItem.model_validate(user) for user in await list_users_for_admin(db)]


@router.post("/admin/users", response_model=UserAdminItem, dependencies=[Depends(require_admin_access)])
async def admin_create_user(
    payload: UserAdminCreateRequest,
    request: Request,
    actor=Depends(require_admin_access),
    db: AsyncSession = Depends(get_db),
) -> UserAdminItem:
    """Handle the admin create user endpoint."""
    try:
        user = await create_user_for_admin(
            db,
            username=payload.username,
            full_name=payload.full_name,
            password=payload.password,
            role=payload.role,
            commit=False,
        )
        client_ip, user_agent = _client_metadata(request)
        await record_admin_audit_log(
            db,
            actor=actor,
            action="auth.admin.create_user",
            target_type="user",
            target_id=str(user.id),
            ip_address=client_ip,
            user_agent=user_agent,
            details={"username": user.username, "role": user.role},
            commit=False,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return UserAdminItem.model_validate(user)


@router.put("/admin/users/{user_id}", response_model=UserAdminItem, dependencies=[Depends(require_admin_access)])
async def admin_update_user(
    user_id: int,
    payload: UserAdminUpdateRequest,
    request: Request,
    actor=Depends(require_admin_access),
    db: AsyncSession = Depends(get_db),
) -> UserAdminItem:
    """Handle the admin update user endpoint."""
    try:
        user = await update_user_for_admin(
            db,
            user_id=user_id,
            full_name=payload.full_name,
            role=payload.role,
            is_active=payload.is_active,
            disabled_reason=payload.disabled_reason,
            commit=False,
        )
        client_ip, user_agent = _client_metadata(request)
        await record_admin_audit_log(
            db,
            actor=actor,
            action="auth.admin.update_user",
            target_type="user",
            target_id=str(user_id),
            ip_address=client_ip,
            user_agent=user_agent,
            details=payload.model_dump(exclude_unset=True),
            commit=False,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return UserAdminItem.model_validate(user)


@router.post("/admin/users/{user_id}/reset-password", response_model=UserAdminItem, dependencies=[Depends(require_admin_access)])
async def admin_reset_password(
    user_id: int,
    payload: UserPasswordResetRequest,
    request: Request,
    actor=Depends(require_admin_access),
    db: AsyncSession = Depends(get_db),
) -> UserAdminItem:
    """Handle the admin reset password endpoint."""
    try:
        user = await reset_user_password_for_admin(
            db,
            user_id=user_id,
            new_password=payload.new_password,
            commit=False,
        )
        client_ip, user_agent = _client_metadata(request)
        await record_admin_audit_log(
            db,
            actor=actor,
            action="auth.admin.reset_password",
            target_type="user",
            target_id=str(user_id),
            ip_address=client_ip,
            user_agent=user_agent,
            details={"username": user.username},
            commit=False,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return UserAdminItem.model_validate(user)


@router.get("/admin/audit-logs", response_model=list[AdminAuditLogItem], dependencies=[Depends(require_admin_access)])
async def admin_list_audit_logs(
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[AdminAuditLogItem]:
    """Handle the admin list audit logs endpoint."""
    return [AdminAuditLogItem.model_validate(item) for item in await list_admin_audit_logs(db, limit=limit)]


@router.post("/change-password", response_model=CurrentUserResponse)
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    actor=Depends(require_api_access),
    db: AsyncSession = Depends(get_db),
) -> CurrentUserResponse:
    """Handle the change password endpoint."""
    if actor.user is None or actor.session is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User session required")
    try:
        user = await change_password_for_user(
            db,
            user_id=actor.user.id,
            current_password=payload.current_password,
            new_password=payload.new_password,
            current_jwt_id=actor.session.jwt_id,
            commit=False,
        )
        client_ip, user_agent = _client_metadata(request)
        await record_admin_audit_log(
            db,
            actor=actor,
            action="auth.user.change_password",
            target_type="user",
            target_id=str(user.id),
            ip_address=client_ip,
            user_agent=user_agent,
            details={"username": user.username},
            commit=False,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return CurrentUserResponse(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        role=user.role,
        auth_kind=actor.kind,
        scopes=sorted(actor.permissions),
        expires_at=actor.session.expires_at if actor.session is not None else None,
    )


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=settings.auth.cookie_name),
    refresh_cookie: str | None = Cookie(default=None, alias=settings.auth.refresh_cookie_name),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Handle the logout endpoint."""
    _set_no_store_headers(response)
    if refresh_cookie or session_cookie:
        _enforce_cookie_request_origin(request)
    try:
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization.split(" ", 1)[1].strip()
            if token:
                await revoke_token(db, token, commit=False)
        if refresh_cookie:
            await revoke_token(db, refresh_cookie, commit=False)
        elif session_cookie:
            await revoke_token(db, session_cookie, commit=False)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    _clear_auth_cookie(response)
    _clear_refresh_cookie(response)
    return {"success": True}
