from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.practice import Practice
from app.schemas.user import UserCreate, UserUpdate, UserResponse, UserListResponse
from app.schemas.practice import PracticeCreate, PracticeUpdate, PracticeResponse, PracticeListResponse
from app.models.practice_config import PracticeConfig
from app.schemas.practice_config import PracticeConfigResponse, PracticeConfigUpdate
from app.schemas.common import MessageResponse
from app.services.auth_service import hash_password
from app.middleware.auth import require_super_admin

router = APIRouter()


# --- Practices ---

@router.get("/practices", response_model=PracticeListResponse)
async def list_practices(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status"),
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all practices (super admin only)."""
    query = select(Practice)
    count_query = select(func.count(Practice.id))

    if status_filter:
        query = query.where(Practice.status == status_filter)
        count_query = count_query.where(Practice.status == status_filter)

    query = query.offset(skip).limit(limit).order_by(Practice.created_at.desc())

    result = await db.execute(query)
    practices = result.scalars().all()

    count_result = await db.execute(count_query)
    total = count_result.scalar()

    return PracticeListResponse(
        practices=[PracticeResponse.model_validate(p) for p in practices],
        total=total,
    )


@router.post("/practices", response_model=PracticeResponse, status_code=status.HTTP_201_CREATED)
async def create_practice(
    request: PracticeCreate,
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new practice (super admin only)."""
    # Check slug uniqueness
    existing = await db.execute(select(Practice).where(Practice.slug == request.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Practice slug already exists")

    practice = Practice(**request.model_dump())
    db.add(practice)
    await db.commit()
    await db.refresh(practice)
    return PracticeResponse.model_validate(practice)


@router.get("/practices/{practice_id}", response_model=PracticeResponse)
async def get_practice(
    practice_id: UUID,
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get practice details (super admin only)."""
    result = await db.execute(select(Practice).where(Practice.id == practice_id))
    practice = result.scalar_one_or_none()
    if not practice:
        raise HTTPException(status_code=404, detail="Practice not found")
    return PracticeResponse.model_validate(practice)


@router.put("/practices/{practice_id}", response_model=PracticeResponse)
async def update_practice(
    practice_id: UUID,
    request: PracticeUpdate,
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update practice (super admin only)."""
    result = await db.execute(select(Practice).where(Practice.id == practice_id))
    practice = result.scalar_one_or_none()
    if not practice:
        raise HTTPException(status_code=404, detail="Practice not found")

    update_data = request.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(practice, field, value)

    await db.commit()
    await db.refresh(practice)
    return PracticeResponse.model_validate(practice)


# --- Users ---

@router.get("/users", response_model=UserListResponse)
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    practice_id: UUID | None = None,
    role: str | None = None,
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all users across all practices (super admin only)."""
    query = select(User)
    count_query = select(func.count(User.id))

    if practice_id:
        query = query.where(User.practice_id == practice_id)
        count_query = count_query.where(User.practice_id == practice_id)
    if role:
        query = query.where(User.role == role)
        count_query = count_query.where(User.role == role)

    query = query.offset(skip).limit(limit).order_by(User.created_at.desc())

    result = await db.execute(query)
    users = result.scalars().all()

    count_result = await db.execute(count_query)
    total = count_result.scalar()

    return UserListResponse(
        users=[UserResponse.model_validate(u) for u in users],
        total=total,
    )


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    request: UserCreate,
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a user for any practice (super admin only)."""
    # Check email uniqueness
    existing = await db.execute(select(User).where(User.email == request.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    # Validate practice exists if provided
    if request.practice_id:
        practice = await db.execute(select(Practice).where(Practice.id == request.practice_id))
        if not practice.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Practice not found")

    user_data = request.model_dump()
    user_data["password_hash"] = hash_password(user_data.pop("password"))

    user = User(**user_data)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user)


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    request: UserUpdate,
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update any user (super admin only)."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    update_data = request.model_dump(exclude_unset=True)

    # Check email uniqueness if changing
    if "email" in update_data:
        existing = await db.execute(
            select(User).where(User.email == update_data["email"], User.id != user_id)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Email already in use")

    for field, value in update_data.items():
        setattr(user, field, value)

    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user)


@router.delete("/users/{user_id}", response_model=MessageResponse)
async def deactivate_user(
    user_id: UUID,
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate a user (super admin only). Soft delete."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")

    user.is_active = False
    await db.commit()
    return MessageResponse(message=f"User {user.email} deactivated")


# --- Practice Config (super admin can manage any practice's config) ---

@router.get("/practices/{practice_id}/config", response_model=PracticeConfigResponse)
async def get_practice_config(
    practice_id: UUID,
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get config for any practice (super admin only)."""
    # Verify practice exists
    practice_result = await db.execute(select(Practice).where(Practice.id == practice_id))
    practice = practice_result.scalar_one_or_none()
    if not practice:
        raise HTTPException(status_code=404, detail="Practice not found")

    result = await db.execute(
        select(PracticeConfig).where(PracticeConfig.practice_id == practice_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Practice config not found")

    return PracticeConfigResponse.model_validate(config)


@router.put("/practices/{practice_id}/config", response_model=PracticeConfigResponse)
async def update_practice_config(
    practice_id: UUID,
    request: PracticeConfigUpdate,
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update config for any practice (super admin only).

    This is how you set API keys, prompts, voice config, etc.
    Creates the config record if it doesn't exist yet.
    """
    # Verify practice exists
    practice_result = await db.execute(select(Practice).where(Practice.id == practice_id))
    practice = practice_result.scalar_one_or_none()
    if not practice:
        raise HTTPException(status_code=404, detail="Practice not found")

    result = await db.execute(
        select(PracticeConfig).where(PracticeConfig.practice_id == practice_id)
    )
    config = result.scalar_one_or_none()

    update_data = request.model_dump(exclude_unset=True)

    if config:
        # Update existing config
        for field, value in update_data.items():
            setattr(config, field, value)
    else:
        # Create new config for this practice
        config = PracticeConfig(practice_id=practice_id, **update_data)
        db.add(config)

    await db.commit()
    await db.refresh(config)
    return PracticeConfigResponse.model_validate(config)
