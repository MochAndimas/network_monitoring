"""Define module logic for `backend/app/api/routes/auth.py`.

This module contains project-specific implementation details.
"""

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
    """Perform client IP from request.

    Args:
        request: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    remote_ip = request.client.host if request.client and request.client.host else ""
    forwarded_for = request.headers.get("x-forwarded-for", "")
    trusted_proxies = settings.normalized_trusted_proxy_ips
    if remote_ip and remote_ip in trusted_proxies and forwarded_for.strip():
        return forwarded_for.split(",", 1)[0].strip()
    if remote_ip:
        return remote_ip
    return ""


def _user_agent_from_request(request: Request) -> str:
    """Perform user agent from request.

    Args:
        request: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    return (request.headers.get("user-agent") or "").strip()[:255]


def _max_age_from_expiry(expires_at) -> int:
    """Perform max age from expiry.

    Args:
        expires_at: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    return max(int(as_wib_aware(expires_at).timestamp() - time()), 0)


def _set_auth_cookie(response: Response, token: str, *, expires_at) -> None:
    """Perform set auth cookie.

    Args:
        response: Parameter input untuk routine ini.
        token: Parameter input untuk routine ini.
        expires_at: Parameter input untuk routine ini.

    """
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
    """Perform clear auth cookie.

    Args:
        response: Parameter input untuk routine ini.

    """
    response.delete_cookie(
        key=settings.auth_cookie_name,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.normalized_auth_cookie_samesite,
        path="/",
    )


def _set_refresh_cookie(response: Response, token: str, *, expires_at) -> None:
    """Perform set refresh cookie.

    Args:
        response: Parameter input untuk routine ini.
        token: Parameter input untuk routine ini.
        expires_at: Parameter input untuk routine ini.

    """
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
    """Perform clear refresh cookie.

    Args:
        response: Parameter input untuk routine ini.

    """
    response.delete_cookie(
        key=settings.auth_refresh_cookie_name,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.normalized_auth_cookie_samesite,
        path="/",
    )


def _build_login_response(user, token: str, expiry) -> LoginResponse:
    """Build login response.

    Args:
        user: Parameter input untuk routine ini.
        token: Parameter input untuk routine ini.
        expiry: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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
    """Perform set no store headers.

    Args:
        response: Parameter input untuk routine ini.

    """
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def _client_metadata(request: Request) -> tuple[str, str]:
    """Perform client metadata.

    Args:
        request: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    return _client_ip_from_request(request), _user_agent_from_request(request)


def _normalize_origin(value: str | None) -> str | None:
    """Normalize origin/referer value into origin tuple string.

    Args:
        value: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    raw_value = str(value or "").strip()
    if not raw_value:
        return None
    parsed = urlparse(raw_value)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _trusted_cookie_origins() -> set[str]:
    """Build normalized trusted origins for cookie-bearing requests.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    return {origin.strip().lower() for origin in settings.normalized_cors_origins if origin.strip()}


def _trusted_cookie_hosts() -> set[str]:
    """Build normalized trusted hosts for cookie-bearing requests.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    return {host.strip().lower() for host in settings.normalized_trusted_hosts if host.strip()}


def _is_trusted_host_header(host_header: str | None) -> bool:
    """Validate request host against trusted host set.

    Args:
        host_header: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    raw_host = str(host_header or "").strip().lower()
    if not raw_host:
        return False
    if raw_host.startswith("[") and "]" in raw_host:
        normalized_host = raw_host.split("]", 1)[0].lstrip("[")
    else:
        normalized_host = raw_host.split(":", 1)[0]
    return normalized_host in _trusted_cookie_hosts()


def _enforce_cookie_request_origin(request: Request) -> None:
    """Reject cookie-bearing state changes from untrusted request origins.

    Args:
        request: Parameter input untuk routine ini.

    """
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
    """Authenticate credentials, issue session tokens, and set auth cookies.

    Args:
        payload: Parameter input untuk routine ini.
        request: Parameter input untuk routine ini.
        response: Parameter input untuk routine ini.
        db: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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
    session_cookie: str | None = Cookie(default=None, alias=settings.auth_cookie_name),
    refresh_cookie: str | None = Cookie(default=None, alias=settings.auth_refresh_cookie_name),
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """Restore an authenticated session using refresh token context.

    Args:
        request: Parameter input untuk routine ini.
        response: Parameter input untuk routine ini.
        session_cookie: Parameter input untuk routine ini.
        refresh_cookie: Parameter input untuk routine ini.
        db: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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
    """Return current authenticated user profile details.

    Args:
        actor: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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
    """List active sessions that belong to the current user.

    Args:
        actor: Parameter input untuk routine ini.
        db: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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
    """Revoke all other active sessions for the current user.

    Args:
        response: Parameter input untuk routine ini.
        actor: Parameter input untuk routine ini.
        db: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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
    """List sessions for a target user with admin privileges.

    Args:
        username: Parameter input untuk routine ini.
        include_revoked: Parameter input untuk routine ini.
        db: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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
    """Admin operation to revoke every active session for a target user.

    Args:
        user_id: Parameter input untuk routine ini.
        request: Parameter input untuk routine ini.
        actor: Parameter input untuk routine ini.
        db: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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
    """Return admin-facing paged list of user accounts.

    Args:
        db: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    return [UserAdminItem.model_validate(user) for user in await list_users_for_admin(db)]


@router.post("/admin/users", response_model=UserAdminItem, dependencies=[Depends(require_admin_access)])
async def admin_create_user(
    payload: UserAdminCreateRequest,
    request: Request,
    actor=Depends(require_admin_access),
    db: AsyncSession = Depends(get_db),
) -> UserAdminItem:
    """Create a new user account through admin controls.

    Args:
        payload: Parameter input untuk routine ini.
        request: Parameter input untuk routine ini.
        actor: Parameter input untuk routine ini.
        db: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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
    """Update role/profile/active-state fields for a target user.

    Args:
        user_id: Parameter input untuk routine ini.
        payload: Parameter input untuk routine ini.
        request: Parameter input untuk routine ini.
        actor: Parameter input untuk routine ini.
        db: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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
    """Reset password for a target user and optionally revoke sessions.

    Args:
        user_id: Parameter input untuk routine ini.
        payload: Parameter input untuk routine ini.
        request: Parameter input untuk routine ini.
        actor: Parameter input untuk routine ini.
        db: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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
    """Return admin audit-log entries with filtering and pagination.

    Args:
        limit: Parameter input untuk routine ini.
        db: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    return [AdminAuditLogItem.model_validate(item) for item in await list_admin_audit_logs(db, limit=limit)]


@router.post("/change-password", response_model=CurrentUserResponse)
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    actor=Depends(require_api_access),
    db: AsyncSession = Depends(get_db),
) -> CurrentUserResponse:
    """Change password for the current authenticated user.

    Args:
        payload: Parameter input untuk routine ini.
        request: Parameter input untuk routine ini.
        actor: Parameter input untuk routine ini.
        db: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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
    request: Request,
    response: Response,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=settings.auth_cookie_name),
    refresh_cookie: str | None = Cookie(default=None, alias=settings.auth_refresh_cookie_name),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Logout current session and clear authentication cookies.

    Args:
        request: Parameter input untuk routine ini.
        response: Parameter input untuk routine ini.
        authorization: Parameter input untuk routine ini.
        session_cookie: Parameter input untuk routine ini.
        refresh_cookie: Parameter input untuk routine ini.
        db: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    _set_no_store_headers(response)
    if refresh_cookie or session_cookie:
        _enforce_cookie_request_origin(request)
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
