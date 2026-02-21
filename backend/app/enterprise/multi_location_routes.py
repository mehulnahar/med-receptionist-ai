"""
Multi-location API routes.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import require_any_staff, require_practice_admin
from app.models.user import User
from app.enterprise.multi_location import LocationService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/locations", tags=["Multi-Location"])


class CreateLocationRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    address_line1: str = ""
    address_line2: str = ""
    city: str = ""
    state: str = Field("", max_length=2)
    zip_code: str = Field("", max_length=10)
    phone: str = ""
    fax: str = ""
    timezone: str = "America/New_York"
    is_primary: bool = False


class UpdateLocationRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    phone: str | None = None
    fax: str | None = None
    timezone: str | None = None
    is_primary: bool | None = None


class AssignProviderRequest(BaseModel):
    provider_id: str
    is_primary: bool = False


def _ensure_practice(user: User) -> UUID:
    if not user.practice_id:
        raise HTTPException(status_code=400, detail="No practice associated")
    return user.practice_id


@router.get("/")
async def list_locations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_any_staff),
):
    pid = _ensure_practice(current_user)
    locations = await LocationService.list_locations(db, pid)
    return {"locations": locations, "total": len(locations)}


@router.post("/", status_code=201)
async def create_location(
    body: CreateLocationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    pid = _ensure_practice(current_user)
    return await LocationService.create_location(
        db, pid,
        name=body.name,
        address_line1=body.address_line1,
        address_line2=body.address_line2,
        city=body.city,
        state=body.state,
        zip_code=body.zip_code,
        phone=body.phone,
        fax=body.fax,
        timezone_str=body.timezone,
        is_primary=body.is_primary,
    )


@router.get("/{location_id}")
async def get_location(
    location_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_any_staff),
):
    pid = _ensure_practice(current_user)
    location = await LocationService.get_location(db, location_id, pid)
    if not location:
        raise HTTPException(status_code=404, detail="Location not found")
    return location


@router.put("/{location_id}")
async def update_location(
    location_id: str,
    body: UpdateLocationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    pid = _ensure_practice(current_user)
    return await LocationService.update_location(
        db, location_id, pid, **body.model_dump(exclude_unset=True)
    )


@router.delete("/{location_id}", status_code=204)
async def deactivate_location(
    location_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    pid = _ensure_practice(current_user)
    success = await LocationService.deactivate_location(db, location_id, pid)
    if not success:
        raise HTTPException(
            status_code=400,
            detail="Cannot deactivate: location not found or is primary",
        )


@router.post("/{location_id}/providers")
async def assign_provider(
    location_id: str,
    body: AssignProviderRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    pid = _ensure_practice(current_user)
    success = await LocationService.assign_provider_to_location(
        db, body.provider_id, location_id, pid, body.is_primary
    )
    if not success:
        raise HTTPException(status_code=400, detail="Location not found")
    return {"success": True}


@router.get("/{location_id}/providers")
async def get_location_providers(
    location_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_any_staff),
):
    pid = _ensure_practice(current_user)
    providers = await LocationService.get_location_providers(db, location_id, pid)
    return {"providers": providers}
