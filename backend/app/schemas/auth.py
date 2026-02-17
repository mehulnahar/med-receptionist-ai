from pydantic import BaseModel, EmailStr, Field
from uuid import UUID
from datetime import datetime

from app.schemas.user import UserResponse


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)


class TokenPayload(BaseModel):
    sub: str
    email: str
    role: str
    practice_id: str | None = None
    exp: datetime
    iat: datetime
