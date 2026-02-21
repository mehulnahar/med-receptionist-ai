"""
Patient portal API routes — intake forms via text link.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import require_any_staff, require_practice_admin
from app.models.user import User
from app.enterprise.patient_portal import PatientPortalService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/portal", tags=["Patient Portal"])


class SendIntakeLinkRequest(BaseModel):
    patient_phone: str = Field(..., min_length=1, max_length=20)
    patient_name: str = Field(..., min_length=1, max_length=255)
    appointment_id: str | None = None


class IntakeFormSubmission(BaseModel):
    token: str
    demographics: dict = {}
    insurance_info: dict = {}
    medical_history: dict = {}
    medications: dict = {}
    allergies: dict = {}
    emergency_contact: dict = {}
    consent_signatures: dict = {}


@router.post("/send-link")
async def send_intake_link(
    body: SendIntakeLinkRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_any_staff),
):
    """Send intake form link to a patient."""
    if not current_user.practice_id:
        raise HTTPException(status_code=400, detail="No practice associated")

    token = await PatientPortalService.send_intake_link(
        db,
        practice_id=str(current_user.practice_id),
        patient_phone=body.patient_phone,
        patient_name=body.patient_name,
        appointment_id=body.appointment_id,
    )
    return {"success": True, "message": "Intake link sent"}


@router.get("/validate/{token}")
async def validate_intake_token(token: str):
    """Validate an intake token (public endpoint for the intake form page)."""
    payload = PatientPortalService.validate_intake_token(token)
    if not payload:
        raise HTTPException(status_code=400, detail="Invalid or expired link")

    return {
        "valid": True,
        "patient_name": payload.get("patient_name"),
        "practice_id": payload.get("practice_id"),
    }


@router.post("/submit/{token}")
async def submit_intake_form(
    token: str,
    body: IntakeFormSubmission,
    db: AsyncSession = Depends(get_db),
):
    """Submit a completed intake form (public endpoint)."""
    form_data = {
        "demographics": body.demographics,
        "insurance_info": body.insurance_info,
        "medical_history": body.medical_history,
        "medications": body.medications,
        "allergies": body.allergies,
        "emergency_contact": body.emergency_contact,
        "consent_signatures": body.consent_signatures,
    }

    result = await PatientPortalService.save_intake_form(db, token, form_data)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/submissions")
async def list_submissions(
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    """List intake submissions."""
    if not current_user.practice_id:
        return {"submissions": []}

    submissions = await PatientPortalService.list_intake_submissions(
        db, str(current_user.practice_id), status, limit
    )
    return {"submissions": submissions}


@router.get("/submissions/{submission_id}")
async def get_submission(
    submission_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_any_staff),
):
    """Get intake submission detail."""
    if not current_user.practice_id:
        raise HTTPException(status_code=400, detail="No practice associated")

    submission = await PatientPortalService.get_intake_submission(
        db, submission_id, str(current_user.practice_id)
    )
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    return submission


@router.patch("/submissions/{submission_id}/review")
async def review_submission(
    submission_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_any_staff),
):
    """Mark a submission as reviewed."""
    if not current_user.practice_id:
        raise HTTPException(status_code=400, detail="No practice associated")

    from sqlalchemy import text
    result = await db.execute(
        text("""
            UPDATE intake_submissions
            SET status = 'reviewed', reviewed_by = :uid, reviewed_at = NOW()
            WHERE id = :sid AND practice_id = :pid AND status = 'submitted'
        """),
        {
            "uid": str(current_user.id),
            "sid": submission_id,
            "pid": str(current_user.practice_id),
        },
    )
    await db.commit()

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Submission not found or already reviewed")
    return {"success": True}


@router.get("/stats")
async def intake_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    """Get intake completion statistics."""
    if not current_user.practice_id:
        return {}

    return await PatientPortalService.get_intake_stats(
        db, str(current_user.practice_id)
    )
