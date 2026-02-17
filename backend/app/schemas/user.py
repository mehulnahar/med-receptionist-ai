from pydantic import BaseModel, EmailStr, Field
from uuid import UUID
from datetime import datetime
from typing import Optional


class UserBase(BaseModel):
    email: EmailStr
    name: str = Field(..., min_length=1, max_length=255)
    role: str = Field(..., pattern="^(super_admin|practice_admin|secretary)$")


class UserCreate(UserBase):
    password: str = Field(..., min_length=8)
    practice_id: UUID | None = None


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    name: str | None = Field(None, min_length=1, max_length=255)
    role: str | None = Field(None, pattern="^(super_admin|practice_admin|secretary)$")
    is_active: bool | None = None


class UserResponse(BaseModel):
    id: UUID
    email: str
    name: str
    role: str
    practice_id: UUID | None = None
    is_active: bool
    last_login: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    users: list[UserResponse]
    total: int
