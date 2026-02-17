"""Patient management endpoints — CRUD operations for patient records."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select, func, or_
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

router = APIRouter()


def _ensure_practice(user: User) -> UUID:
    """Return the user's practice_id or raise 400 if it is None."""
    if not user.practice_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No practice associated with this user",
        )
    return user.practice_id


# ---------------------------------------------------------------------------
# Create patient
# ---------------------------------------------------------------------------


@router.post("/", response_model=PatientResponse, status_code=status.HTTP_201_CREATED)
async def create_patient(
    request: PatientCreate,
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Create a new patient record for the current practice."""
    practice_id = _ensure_practice(current_user)

    patient = Patient(
        **request.model_dump(),
        practice_id=practice_id,
    )
    db.add(patient)
    await db.commit()
    await db.refresh(patient)

    return PatientResponse.model_validate(patient)


# ---------------------------------------------------------------------------
# List patients
# ---------------------------------------------------------------------------


@router.get("/", response_model=PatientListResponse)
async def list_patients(
    search: str | None = Query(None, description="Search first_name, last_name, or phone"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """List patients for the current practice with optional search."""
    practice_id = _ensure_practice(current_user)

    base_filter = Patient.practice_id == practice_id

    # Build search filter
    if search:
        search_term = f"%{search}%"
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

    return PatientListResponse(
        patients=[PatientResponse.model_validate(p) for p in patients],
        total=total,
    )


# ---------------------------------------------------------------------------
# Search patients (structured)
# ---------------------------------------------------------------------------


@router.get("/search", response_model=PatientListResponse)
async def search_patients(
    first_name: str | None = Query(None, description="Patient first name (partial match)"),
    last_name: str | None = Query(None, description="Patient last name (partial match)"),
    dob: str | None = Query(None, description="Date of birth (YYYY-MM-DD)"),
    phone: str | None = Query(None, description="Phone number (exact match)"),
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Search patients by specific fields. At least one field must be provided."""
    practice_id = _ensure_practice(current_user)

    if not any([first_name, last_name, dob, phone]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one search field must be provided (first_name, last_name, dob, or phone)",
        )

    filters = [Patient.practice_id == practice_id]

    if first_name:
        filters.append(Patient.first_name.ilike(f"%{first_name}%"))
    if last_name:
        filters.append(Patient.last_name.ilike(f"%{last_name}%"))
    if dob:
        filters.append(Patient.dob == dob)
    if phone:
        filters.append(Patient.phone == phone)

    # Total count
    count_query = select(func.count(Patient.id)).where(*filters)
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    # Results
    query = (
        select(Patient)
        .where(*filters)
        .order_by(Patient.last_name, Patient.first_name)
    )
    result = await db.execute(query)
    patients = result.scalars().all()

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
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Get a single patient by ID, scoped to the current practice."""
    practice_id = _ensure_practice(current_user)

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

    return PatientResponse.model_validate(patient)


# ---------------------------------------------------------------------------
# Update patient
# ---------------------------------------------------------------------------


@router.put("/{patient_id}", response_model=PatientResponse)
async def update_patient(
    patient_id: UUID,
    request: PatientUpdate,
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Update a patient record. Only provided fields are updated."""
    practice_id = _ensure_practice(current_user)

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
    for field, value in update_data.items():
        setattr(patient, field, value)

    await db.commit()
    await db.refresh(patient)

    return PatientResponse.model_validate(patient)
