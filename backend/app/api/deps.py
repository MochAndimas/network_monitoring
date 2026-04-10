from fastapi import Header, HTTPException, status

from ..core.config import settings


def require_internal_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if not settings.internal_api_key:
        return
    if x_api_key != settings.internal_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
