"""Provide FastAPI route handlers and HTTP helpers for the network monitoring project."""

from time import time

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
    remote_ip = request.client.host if request.client and request.client.host else ""
    forwarded_for = request.headers.get("x-forwarded-for", "")
    trusted_proxies = settings.normalized_trusted_proxy_ips
    if remote_ip and remote_ip in trusted_proxies and forwarded_for.strip():
        return forwarded_for.split(",", 1)[0].strip()
    if remote_ip:
        return remote_ip
    return ""


def _user_agent_from_request(request: Request) -> str:
    return (request.headers.get("user-agent") or "").strip()[:255]


def _max_age_from_expiry(expires_at) -> int:
    return max(int(as_wib_aware(expires_at).timestamp() - time()), 0)


def _set_auth_cookie(response: Response, token: str, *, expires_at) -> None:
    max_age = _max_age_from_expiry(expires_at)
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.normalized_auth_cookie_samesite,
        max_age=max_age,
        expires=max_age,
        path="/",
    )


def _clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.auth_cookie_name,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.normalized_auth_cookie_samesite,
        path="/",
    )


def _set_refresh_cookie(response: Response, token: str, *, expires_at) -> None:
    max_age = _max_age_from_expiry(expires_at)
    response.set_cookie(
        key=settings.auth_refresh_cookie_name,
        value=token,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.normalized_auth_cookie_samesite,
        max_age=max_age,
        expires=max_age,
        path="/",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.auth_refresh_cookie_name,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.normalized_auth_cookie_samesite,
        path="/",
    )


def _build_login_response(user, token: str, expiry) -> LoginResponse:
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
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def _client_metadata(request: Request) -> tuple[str, str]:
    return _client_ip_from_request(request), _user_agent_from_request(request)


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
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
    response: Response,
    session_cookie: str | None = Cookie(default=None, alias=settings.auth_cookie_name),
    refresh_cookie: str | None = Cookie(default=None, alias=settings.auth_refresh_cookie_name),
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    _set_no_store_headers(response)
    refresh_token = refresh_cookie or session_cookie
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    user, tokens = await refresh_user_session(db, refresh_token)
    _set_auth_cookie(response, tokens.access_token, expires_at=tokens.access_expires_at)
    _set_refresh_cookie(response, tokens.refresh_token, expires_at=tokens.refresh_expires_at)
    return _build_login_response(user, tokens.access_token, tokens.access_expires_at)


@router.get("/me", response_model=CurrentUserResponse)
async def me(actor=Depends(require_api_access_with_session_cookie)) -> CurrentUserResponse:
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
    revoked_sessions = await revoke_all_sessions_for_user(db, user_id=user_id)
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
    )
    return LogoutAllResponse(revoked_sessions=revoked_sessions)


@router.get("/admin/users", response_model=list[UserAdminItem], dependencies=[Depends(require_admin_access)])
async def admin_list_users(db: AsyncSession = Depends(get_db)) -> list[UserAdminItem]:
    return [UserAdminItem.model_validate(user) for user in await list_users_for_admin(db)]


@router.post("/admin/users", response_model=UserAdminItem, dependencies=[Depends(require_admin_access)])
async def admin_create_user(
    payload: UserAdminCreateRequest,
    request: Request,
    actor=Depends(require_admin_access),
    db: AsyncSession = Depends(get_db),
) -> UserAdminItem:
    user = await create_user_for_admin(
        db,
        username=payload.username,
        full_name=payload.full_name,
        password=payload.password,
        role=payload.role,
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
    )
    return UserAdminItem.model_validate(user)


@router.put("/admin/users/{user_id}", response_model=UserAdminItem, dependencies=[Depends(require_admin_access)])
async def admin_update_user(
    user_id: int,
    payload: UserAdminUpdateRequest,
    request: Request,
    actor=Depends(require_admin_access),
    db: AsyncSession = Depends(get_db),
) -> UserAdminItem:
    user = await update_user_for_admin(
        db,
        user_id=user_id,
        full_name=payload.full_name,
        role=payload.role,
        is_active=payload.is_active,
        disabled_reason=payload.disabled_reason,
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
    )
    return UserAdminItem.model_validate(user)


@router.post("/admin/users/{user_id}/reset-password", response_model=UserAdminItem, dependencies=[Depends(require_admin_access)])
async def admin_reset_password(
    user_id: int,
    payload: UserPasswordResetRequest,
    request: Request,
    actor=Depends(require_admin_access),
    db: AsyncSession = Depends(get_db),
) -> UserAdminItem:
    user = await reset_user_password_for_admin(db, user_id=user_id, new_password=payload.new_password)
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
    )
    return UserAdminItem.model_validate(user)


@router.get("/admin/audit-logs", response_model=list[AdminAuditLogItem], dependencies=[Depends(require_admin_access)])
async def admin_list_audit_logs(
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[AdminAuditLogItem]:
    return [AdminAuditLogItem.model_validate(item) for item in await list_admin_audit_logs(db, limit=limit)]


@router.post("/change-password", response_model=CurrentUserResponse)
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    actor=Depends(require_api_access),
    db: AsyncSession = Depends(get_db),
) -> CurrentUserResponse:
    if actor.user is None or actor.session is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User session required")
    user = await change_password_for_user(
        db,
        user_id=actor.user.id,
        current_password=payload.current_password,
        new_password=payload.new_password,
        current_jwt_id=actor.session.jwt_id,
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


@router.post("/logout")
async def logout(
    response: Response,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=settings.auth_cookie_name),
    refresh_cookie: str | None = Cookie(default=None, alias=settings.auth_refresh_cookie_name),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _set_no_store_headers(response)
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        if token:
            await revoke_token(db, token)
    if refresh_cookie:
        await revoke_token(db, refresh_cookie)
    elif session_cookie:
        await revoke_token(db, session_cookie)
    _clear_auth_cookie(response)
    _clear_refresh_cookie(response)
    return {"success": True}
