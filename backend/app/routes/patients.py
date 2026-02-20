"""Patient management endpoints — CRUD operations for patient records."""

import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from sqlalchemy import select, func, or_, and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.patient import Patient
from app.schemas.patient import (
    PatientCreate,
    PatientUpdate,
    PatientResponse,
    PatientListResponse,
)
from app.schemas.common import MessageResponse
from app.middleware.auth import get_current_user, require_any_staff
from app.services.audit_service import log_audit

router = APIRouter()


def _escape_like(value: str) -> str:
    """Escape special characters (%, _, \\) in ILIKE search terms."""
    value = value.replace("\\", "\\\\")
    value = value.replace("%", "\\%")
    value = value.replace("_", "\\_")
    return value


def _resolve_practice_id(user: User, practice_id_override: UUID | None = None) -> UUID:
    """Return the effective practice_id for the current request.

    - Regular staff: always use their own practice_id (override ignored).
    - Super admin: use ``practice_id_override`` if provided, otherwise
      fall back to their own practice_id (which may be None).
    - Raises 400 if no practice can be resolved at all.
    """
    if user.role == "super_admin" and practice_id_override:
        return practice_id_override
    if user.practice_id:
        return user.practice_id
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="No practice associated with this user. Super admins must pass ?practice_id=<uuid>.",
    )


# ---------------------------------------------------------------------------
# Create patient
# ---------------------------------------------------------------------------


@router.post("/", response_model=PatientResponse, status_code=status.HTTP_201_CREATED)
async def create_patient(
    request: PatientCreate,
    http_request: Request,
    practice_id: UUID | None = Query(None, description="Practice ID (super_admin only)"),
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Create a new patient record for the current practice."""
    practice_id = _resolve_practice_id(current_user, practice_id)

    # Check for duplicate patient (same name + DOB within practice)
    dup_stmt = select(Patient).where(
        and_(
            Patient.practice_id == practice_id,
            func.lower(Patient.first_name) == request.first_name.lower(),
            func.lower(Patient.last_name) == request.last_name.lower(),
            Patient.dob == request.dob,
        )
    ).limit(1)
    dup_result = await db.execute(dup_stmt)
    existing = dup_result.scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Patient '{request.first_name} {request.last_name}' with DOB {request.dob} already exists.",
        )

    patient = Patient(
        **request.model_dump(),
        practice_id=practice_id,
    )
    db.add(patient)

    try:
        await db.flush()  # get patient.id before commit
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Patient '{request.first_name} {request.last_name}' with DOB {request.dob} already exists.",
        )

    await log_audit(
        db, action="create", entity_type="patient", entity_id=patient.id,
        user=current_user, new_value=request.model_dump(), request=http_request,
    )
    await db.commit()
    await db.refresh(patient)

    return PatientResponse.model_validate(patient)


# ---------------------------------------------------------------------------
# List patients
# ---------------------------------------------------------------------------


@router.get("/", response_model=PatientListResponse)
async def list_patients(
    http_request: Request,
    search: str | None = Query(None, description="Search first_name, last_name, or phone"),
    practice_id: UUID | None = Query(None, description="Practice ID (super_admin only)"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """List patients for the current practice with optional search."""
    practice_id = _resolve_practice_id(current_user, practice_id)

    base_filter = Patient.practice_id == practice_id

    # Build search filter
    if search:
        search_term = f"%{_escape_like(search)}%"
        search_filter = or_(
            Patient.first_name.ilike(search_term),
            Patient.last_name.ilike(search_term),
            Patient.phone.ilike(search_term),
        )
        where_clause = [base_filter, search_filter]
    else:
        where_clause = [base_filter]

    # Total count
    count_query = select(func.count(Patient.id)).where(*where_clause)
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    # Paginated results
    query = (
        select(Patient)
        .where(*where_clause)
        .order_by(Patient.last_name, Patient.first_name)
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(query)
    patients = result.scalars().all()

    # HIPAA: audit bulk patient data access
    await log_audit(
        db, action="list", entity_type="patient",
        user=current_user, new_value={"search": search, "limit": limit, "offset": offset, "results": total},
        request=http_request,
    )
    await db.commit()

    return PatientListResponse(
        patients=[PatientResponse.model_validate(p) for p in patients],
        total=total,
    )


# ---------------------------------------------------------------------------
# Search patients (structured)
# ---------------------------------------------------------------------------


@router.get("/search", response_model=PatientListResponse)
async def search_patients(
    http_request: Request,
    first_name: str | None = Query(None, description="Patient first name (partial match)"),
    last_name: str | None = Query(None, description="Patient last name (partial match)"),
    dob: str | None = Query(None, description="Date of birth (YYYY-MM-DD)"),
    phone: str | None = Query(None, description="Phone number (exact match)"),
    practice_id: UUID | None = Query(None, description="Practice ID (super_admin only)"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Search patients by specific fields. At least one field must be provided."""
    practice_id = _resolve_practice_id(current_user, practice_id)

    if not any([first_name, last_name, dob, phone]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one search field must be provided (first_name, last_name, dob, or phone)",
        )

    filters = [Patient.practice_id == practice_id]

    if first_name:
        filters.append(Patient.first_name.ilike(f"%{_escape_like(first_name)}%"))
    if last_name:
        filters.append(Patient.last_name.ilike(f"%{_escape_like(last_name)}%"))
    if dob:
        filters.append(Patient.dob == dob)
    if phone:
        filters.append(Patient.phone == phone)

    # Total count
    count_query = select(func.count(Patient.id)).where(*filters)
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    # Results (paginated)
    query = (
        select(Patient)
        .where(*filters)
        .order_by(Patient.last_name, Patient.first_name)
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(query)
    patients = result.scalars().all()

    # HIPAA: audit patient search access
    await log_audit(
        db, action="search", entity_type="patient",
        user=current_user,
        new_value={"first_name": first_name, "last_name": last_name, "dob": dob, "results": total},
        request=http_request,
    )
    await db.commit()

    return PatientListResponse(
        patients=[PatientResponse.model_validate(p) for p in patients],
        total=total,
    )


# ---------------------------------------------------------------------------
# Get patient by ID
# ---------------------------------------------------------------------------


@router.get("/{patient_id}", response_model=PatientResponse)
async def get_patient(
    patient_id: UUID,
    http_request: Request,
    practice_id: UUID | None = Query(None, description="Practice ID (super_admin only)"),
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Get a single patient by ID, scoped to the current practice."""
    practice_id = _resolve_practice_id(current_user, practice_id)

    result = await db.execute(
        select(Patient).where(
            Patient.id == patient_id,
            Patient.practice_id == practice_id,
        )
    )
    patient = result.scalar_one_or_none()

    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient not found",
        )

    await log_audit(
        db, action="view", entity_type="patient", entity_id=patient.id,
        user=current_user, request=http_request,
    )
    await db.commit()

    return PatientResponse.model_validate(patient)


# ---------------------------------------------------------------------------
# Update patient
# ---------------------------------------------------------------------------


@router.put("/{patient_id}", response_model=PatientResponse)
async def update_patient(
    patient_id: UUID,
    request: PatientUpdate,
    http_request: Request,
    practice_id: UUID | None = Query(None, description="Practice ID (super_admin only)"),
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Update a patient record. Only provided fields are updated."""
    practice_id = _resolve_practice_id(current_user, practice_id)

    result = await db.execute(
        select(Patient).where(
            Patient.id == patient_id,
            Patient.practice_id == practice_id,
        )
    )
    patient = result.scalar_one_or_none()

    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient not found",
        )

    update_data = request.model_dump(exclude_unset=True)

    # Capture old values for audit trail
    old_values = {field: getattr(patient, field) for field in update_data}
    # Serialize date/UUID fields for JSON storage
    for k, v in old_values.items():
        if hasattr(v, "isoformat"):
            old_values[k] = v.isoformat()
        elif hasattr(v, "hex"):
            old_values[k] = str(v)

    for field, value in update_data.items():
        setattr(patient, field, value)

    await log_audit(
        db, action="update", entity_type="patient", entity_id=patient.id,
        user=current_user, old_value=old_values, new_value=update_data,
        request=http_request,
    )
    await db.commit()
    await db.refresh(patient)

    return PatientResponse.model_validate(patient)
