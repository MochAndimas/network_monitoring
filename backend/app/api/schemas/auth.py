from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=255)


class UserSessionInfo(BaseModel):
    id: int
    username: str
    full_name: str
    role: str
    expires_at: datetime


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    user: UserSessionInfo


class CurrentUserResponse(BaseModel):
    id: int
    username: str
    full_name: str
    role: str

