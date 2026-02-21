"""
Self-service onboarding API routes — public endpoints for practice signup.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.enterprise.self_service_onboarding import SelfServiceOnboardingService
from app.enterprise.billing_service import PLANS

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/signup", tags=["Self-Service Onboarding"])


class SignupRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=255)
    practice_name: str = Field(..., min_length=1, max_length=255)
    phone: str = Field("", max_length=20)
    plan: str = Field("starter")


class VerifyRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)


class CompleteOnboardingRequest(BaseModel):
    admin: dict = {}  # {name, password}
    practice_details: dict = {}  # {address, city, state, zip, npi, tax_id, timezone}
    preferences: dict = {}  # {language, appointment_types}


@router.post("/")
async def create_signup(
    body: SignupRequest,
    db: AsyncSession = Depends(get_db),
):
    """Start the signup process (public, no auth)."""
    if body.plan not in PLANS:
        raise HTTPException(status_code=400, detail="Invalid plan")

    result = await SelfServiceOnboardingService.create_signup(
        db, body.email, body.practice_name, body.phone, body.plan
    )
    if "error" in result:
        raise HTTPException(status_code=429, detail=result["error"])
    return result


@router.post("/{signup_id}/verify")
async def verify_email(
    signup_id: str,
    body: VerifyRequest,
    db: AsyncSession = Depends(get_db),
):
    """Verify the signup email/phone code."""
    success = await SelfServiceOnboardingService.verify_email(
        db, signup_id, body.code
    )
    if not success:
        raise HTTPException(status_code=400, detail="Invalid or expired code")
    return {"verified": True}


@router.post("/{signup_id}/resend")
async def resend_code(
    signup_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Resend verification code."""
    success = await SelfServiceOnboardingService.resend_verification(db, signup_id)
    if not success:
        raise HTTPException(status_code=400, detail="Signup not found or already verified")
    return {"sent": True}


@router.get("/{signup_id}/progress")
async def get_progress(
    signup_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get onboarding progress."""
    result = await SelfServiceOnboardingService.get_onboarding_progress(db, signup_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/{signup_id}/complete")
async def complete_onboarding(
    signup_id: str,
    body: CompleteOnboardingRequest,
    db: AsyncSession = Depends(get_db),
):
    """Complete onboarding — create practice and admin user."""
    if not body.admin.get("password"):
        raise HTTPException(status_code=400, detail="Admin password required")

    result = await SelfServiceOnboardingService.complete_onboarding(
        db, signup_id, body.model_dump()
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/plans")
async def list_plans():
    """List available plans with pricing (public)."""
    return {
        "plans": [
            {
                "id": key,
                "name": plan["name"],
                "price": float(plan["base_price"]),
                "limits": plan["limits"],
            }
            for key, plan in PLANS.items()
        ]
    }
