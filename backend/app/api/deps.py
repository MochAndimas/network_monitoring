from fastapi import Header, HTTPException, status

from ..core.config import settings


def require_internal_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if not settings.internal_api_key:
        if settings.app_env.lower() == "production":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="INTERNAL_API_KEY is required in production",
            )
        return
    if x_api_key != settings.internal_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
