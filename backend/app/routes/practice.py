from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.practice import Practice
from app.schemas.user import UserCreate, UserUpdate, UserResponse, UserListResponse
from app.schemas.practice import PracticeResponse, PracticeUpdate
from app.schemas.common import MessageResponse
from app.services.auth_service import hash_password
from app.middleware.auth import get_current_user, require_practice_admin, require_any_staff

router = APIRouter()


@router.get("/settings", response_model=PracticeResponse)
async def get_practice_settings(
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Get my practice settings."""
    if not current_user.practice_id:
        raise HTTPException(status_code=400, detail="No practice associated")

    result = await db.execute(select(Practice).where(Practice.id == current_user.practice_id))
    practice = result.scalar_one_or_none()
    if not practice:
        raise HTTPException(status_code=404, detail="Practice not found")
    return PracticeResponse.model_validate(practice)


@router.put("/settings", response_model=PracticeResponse)
async def update_practice_settings(
    request: PracticeUpdate,
    current_user: User = Depends(require_practice_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update my practice settings (practice admin only)."""
    result = await db.execute(select(Practice).where(Practice.id == current_user.practice_id))
    practice = result.scalar_one_or_none()
    if not practice:
        raise HTTPException(status_code=404, detail="Practice not found")

    update_data = request.model_dump(exclude_unset=True)
    # Don't allow practice admins to change status
    update_data.pop("status", None)

    for field, value in update_data.items():
        setattr(practice, field, value)

    await db.commit()
    await db.refresh(practice)
    return PracticeResponse.model_validate(practice)


@router.get("/users", response_model=UserListResponse)
async def list_practice_users(
    current_user: User = Depends(require_practice_admin),
    db: AsyncSession = Depends(get_db),
):
    """List users in my practice."""
    query = select(User).where(User.practice_id == current_user.practice_id)
    result = await db.execute(query)
    users = result.scalars().all()

    return UserListResponse(
        users=[UserResponse.model_validate(u) for u in users],
        total=len(users),
    )


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_practice_user(
    request: UserCreate,
    current_user: User = Depends(require_practice_admin),
    db: AsyncSession = Depends(get_db),
):
    """Add a secretary to my practice (practice admin only)."""
    # Only allow creating secretaries
    if request.role not in ("secretary",):
        raise HTTPException(status_code=400, detail="Can only create secretary accounts")

    # Check email uniqueness
    existing = await db.execute(select(User).where(User.email == request.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    user_data = request.model_dump()
    user_data["password_hash"] = await hash_password(user_data.pop("password"))
    user_data["practice_id"] = current_user.practice_id  # Force to own practice
    user_data["role"] = "secretary"  # Force secretary role

    user = User(**user_data)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user)


@router.delete("/users/{user_id}", response_model=MessageResponse)
async def remove_practice_user(
    user_id: UUID,
    current_user: User = Depends(require_practice_admin),
    db: AsyncSession = Depends(get_db),
):
    """Remove a secretary from my practice (practice admin only)."""
    result = await db.execute(
        select(User).where(User.id == user_id, User.practice_id == current_user.practice_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found in your practice")

    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot remove yourself")

    user.is_active = False
    await db.commit()
    return MessageResponse(message=f"User {user.email} removed from practice")
