from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import require_api_access
from ...api.schemas import CurrentUserResponse, LoginRequest, LoginResponse, UserSessionInfo
from ...db.session import get_db
from ...services.auth_service import authenticate_user, revoke_token

router = APIRouter()


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> LoginResponse:
    user, token, expiry = await authenticate_user(db, payload.username, payload.password)
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


@router.get("/me", response_model=CurrentUserResponse)
async def me(actor=Depends(require_api_access)) -> CurrentUserResponse:
    user = actor.user
    if user is None:
        return CurrentUserResponse(id=0, username="system", full_name="System API Key", role=actor.role)
    return CurrentUserResponse(id=user.id, username=user.username, full_name=user.full_name, role=user.role)


@router.post("/logout")
async def logout(
    authorization: str | None = Header(default=None),
    _actor=Depends(require_api_access),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        if token:
            await revoke_token(db, token)
    return {"success": True}
