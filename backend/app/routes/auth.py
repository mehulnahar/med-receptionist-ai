from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    ChangePasswordRequest,
    RefreshRequest,
    RefreshResponse,
)
from app.schemas.user import UserResponse
from app.schemas.common import MessageResponse
from app.services.auth_service import (
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_password,
)
from app.middleware.auth import get_current_user
from app.services.audit_service import log_audit

router = APIRouter()


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    """Set the refresh token as an httpOnly secure cookie."""
    settings = get_settings()
    is_prod = settings.APP_ENV == "production"
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=is_prod,
        samesite="lax",
        max_age=7 * 24 * 3600,  # 7 days, matching JWT refresh expiry
        path="/api/auth",  # Only sent to auth endpoints
    )


def _clear_refresh_cookie(response: Response) -> None:
    """Delete the refresh token cookie."""
    settings = get_settings()
    is_prod = settings.APP_ENV == "production"
    response.delete_cookie(
        key="refresh_token",
        httponly=True,
        secure=is_prod,
        samesite="lax",
        path="/api/auth",
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    http_request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate user and return JWT access + refresh tokens.

    The refresh token is also set as an httpOnly cookie for XSS-safe storage.
    The access token is returned in the JSON body only (kept in memory by the client).
    """
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()

    if user is None or not await verify_password(request.password, user.password_hash):
        # Log failed attempt (HIPAA requires tracking failed logins)
        await log_audit(
            db, action="login_failed", entity_type="user",
            new_value={"email": request.email}, request=http_request,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    # Update last login
    user.last_login = datetime.now(timezone.utc)

    await log_audit(
        db, action="login", entity_type="user", entity_id=user.id,
        user=user, request=http_request,
    )
    await db.commit()

    access_token = create_access_token(
        user_id=user.id,
        email=user.email,
        role=user.role,
        practice_id=user.practice_id,
    )
    refresh_token = create_refresh_token(user_id=user.id)

    # Set refresh token as httpOnly cookie (XSS-safe)
    _set_refresh_cookie(response, refresh_token)

    # Don't return refresh_token in JSON body — it's already in the
    # httpOnly cookie. Exposing it in the response body would allow XSS
    # attacks to steal the long-lived refresh token.
    return LoginResponse(
        access_token=access_token,
        refresh_token=None,
        user=UserResponse.model_validate(user),
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_access_token(
    request: RefreshRequest = None,
    refresh_token_cookie: str | None = Cookie(None, alias="refresh_token"),
    db: AsyncSession = Depends(get_db),
):
    """Exchange a valid refresh token for a new access token.

    Accepts the refresh token from either:
    1. The httpOnly cookie (preferred, XSS-safe)
    2. The JSON body (backward compatibility)

    The refresh token itself is NOT rotated — it remains valid until
    it expires (7 days from issuance).
    """
    # Prefer cookie, fall back to body
    token_value = refresh_token_cookie or (request.refresh_token if request else None)
    if not token_value:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token required",
        )

    payload = decode_refresh_token(token_value)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token payload",
        )

    # Verify user still exists and is active
    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated",
        )

    new_access_token = create_access_token(
        user_id=user.id,
        email=user.email,
        role=user.role,
        practice_id=user.practice_id,
    )

    return RefreshResponse(access_token=new_access_token)


@router.post("/logout", response_model=MessageResponse)
async def logout(
    response: Response,
    current_user: User = Depends(get_current_user),
):
    """Logout — clear the refresh token cookie."""
    _clear_refresh_cookie(response)
    return MessageResponse(message="Logged out successfully")


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """Get current user profile."""
    return UserResponse.model_validate(current_user)


@router.put("/change-password", response_model=MessageResponse)
async def change_password(
    request: ChangePasswordRequest,
    http_request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change current user's password."""
    if not await verify_password(request.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    if request.current_password == request.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from current password",
        )

    current_user.password_hash = await hash_password(request.new_password)
    current_user.password_change_required = False
    await log_audit(
        db, action="change_password", entity_type="user", entity_id=current_user.id,
        user=current_user, request=http_request,
    )
    await db.commit()

    return MessageResponse(message="Password changed successfully")
