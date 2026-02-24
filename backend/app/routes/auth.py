from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select, text
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

    HIPAA enhancements:
    - Account lockout after 5 failed attempts (30 min)
    - Failed login auditing with attempt counts
    - Password expiry check
    - MFA challenge if enabled
    """
    from app.hipaa.password_policy import (
        check_account_lockout,
        record_failed_login,
        reset_failed_login_attempts,
        is_password_expired,
    )

    # 1. Find user by email
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()

    if user is None:
        await log_audit(
            db, action="login_failed", entity_type="user",
            new_value={"email": request.email, "reason": "unknown_email"},
            request=http_request,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # 2. Check account lockout BEFORE password verification
    is_locked, locked_until = await check_account_lockout(db, user.id)
    if is_locked:
        remaining_minutes = 30
        if locked_until:
            remaining_minutes = max(1, int((locked_until - datetime.now(timezone.utc)).total_seconds() / 60) + 1)
        await log_audit(
            db, action="login_blocked", entity_type="user", entity_id=user.id,
            new_value={"email": request.email, "reason": "account_locked"},
            request=http_request,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Account locked due to too many failed attempts. Try again in {remaining_minutes} minutes.",
        )

    # 3. Verify password
    if not await verify_password(request.password, user.password_hash):
        attempt_count, new_locked_until = await record_failed_login(db, user.id)
        await log_audit(
            db, action="login_failed", entity_type="user", entity_id=user.id,
            new_value={"email": request.email, "reason": "wrong_password", "attempt": attempt_count},
            request=http_request,
        )
        await db.commit()

        if new_locked_until:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account locked due to too many failed attempts. Try again in 30 minutes.",
            )
        remaining = 5 - attempt_count
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid email or password. {remaining} attempt{'s' if remaining != 1 else ''} remaining.",
        )

    # 4. Check account active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    # 5. Successful login — reset failed attempts
    await reset_failed_login_attempts(db, user.id)

    # 6. Check password expiry
    password_expired = is_password_expired(getattr(user, "last_password_change", None))
    if password_expired:
        user.password_change_required = True

    # 7. Check MFA
    mfa_enabled = getattr(user, "mfa_enabled", False)
    if mfa_enabled:
        from app.services.auth_service import create_mfa_token
        mfa_token = create_mfa_token(user.id)
        await log_audit(
            db, action="login_mfa_required", entity_type="user", entity_id=user.id,
            user=user, request=http_request,
        )
        await db.commit()
        return LoginResponse(
            access_token="",
            refresh_token=None,
            user=UserResponse.model_validate(user),
            mfa_required=True,
            mfa_token=mfa_token,
        )

    # 8. Update last login
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

    _set_refresh_cookie(response, refresh_token)

    return LoginResponse(
        access_token=access_token,
        refresh_token=None,
        user=UserResponse.model_validate(user),
    )


# --- MFA Login Verification ---

class MFAVerifyLoginRequest(BaseModel):
    mfa_token: str
    code: str


@router.post("/mfa-verify", response_model=LoginResponse)
async def mfa_verify_login(
    request: MFAVerifyLoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Complete login after MFA challenge. Exchange mfa_token + TOTP code for real tokens."""
    from app.services.auth_service import decode_mfa_token
    from app.hipaa.mfa import verify_totp

    payload = decode_mfa_token(request.mfa_token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired MFA token")

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # Get MFA secret
    mfa_result = await db.execute(
        text("SELECT mfa_secret FROM users WHERE id = :uid"),
        {"uid": user_id},
    )
    mfa_row = mfa_result.fetchone()
    secret = mfa_row[0] if mfa_row else None

    if not secret or not verify_totp(secret, request.code):
        raise HTTPException(status_code=401, detail="Invalid MFA code")

    # MFA verified — issue real tokens
    user.last_login = datetime.now(timezone.utc)
    await db.commit()

    access_token = create_access_token(
        user_id=user.id,
        email=user.email,
        role=user.role,
        practice_id=user.practice_id,
    )
    refresh_token = create_refresh_token(user_id=user.id)
    _set_refresh_cookie(response, refresh_token)

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
    """Exchange a valid refresh token for a new access token."""
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
    """Change current user's password with HIPAA policy enforcement."""
    from app.hipaa.password_policy import (
        validate_password_strength,
        check_password_history,
        save_password_to_history,
    )

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

    # HIPAA password strength validation
    is_valid, errors = validate_password_strength(request.new_password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="; ".join(errors),
        )

    # Check password history (prevent reuse)
    is_reused = await check_password_history(db, current_user.id, request.new_password)
    if is_reused:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This password was used recently. Please choose a different one.",
        )

    # Hash and save
    new_hash = await hash_password(request.new_password)
    current_user.password_hash = new_hash
    current_user.password_change_required = False

    # Save to password history
    await save_password_to_history(db, current_user.id, new_hash)

    # Update last_password_change
    await db.execute(
        text("UPDATE users SET last_password_change = NOW() WHERE id = :uid"),
        {"uid": str(current_user.id)},
    )

    await log_audit(
        db, action="change_password", entity_type="user", entity_id=current_user.id,
        user=current_user, request=http_request,
    )
    await db.commit()

    return MessageResponse(message="Password changed successfully")
