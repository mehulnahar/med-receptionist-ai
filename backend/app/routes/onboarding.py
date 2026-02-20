"""
Onboarding API endpoints for the AI Medical Receptionist.

Provides endpoints for:
- Validating and saving API keys (Vapi, Twilio, OpenAI, Stedi)
- Creating Vapi assistants with all tool definitions
- Listing and assigning phone numbers (Vapi + Twilio)
- Checking onboarding completion status
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.middleware.auth import require_practice_admin
from app.schemas.onboarding import (
    ValidateVapiKeyRequest,
    ValidateVapiKeyResponse,
    CreateAssistantRequest,
    CreateAssistantResponse,
    VapiPhoneListResponse,
    VapiPhoneNumber,
    AssignPhoneRequest,
    AssignPhoneResponse,
    ValidateTwilioRequest,
    ValidateTwilioResponse,
    TwilioPhoneListResponse,
    TwilioPhoneNumber,
    SaveTwilioConfigRequest,
    SaveTwilioConfigResponse,
    ValidateOpenAIKeyRequest,
    ValidateOpenAIKeyResponse,
    ValidateStediKeyRequest,
    ValidateStediKeyResponse,
    OnboardingStatusResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _ensure_practice(user: User) -> UUID:
    if not user.practice_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No practice associated with this user",
        )
    return user.practice_id


# ---------------------------------------------------------------------------
# Onboarding Status
# ---------------------------------------------------------------------------

@router.get("/status", response_model=OnboardingStatusResponse)
async def get_status(
    current_user: User = Depends(require_practice_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get the onboarding completion status for all integration steps."""
    practice_id = _ensure_practice(current_user)

    from app.services.onboarding_service import get_onboarding_status
    return await get_onboarding_status(db, practice_id)


# ---------------------------------------------------------------------------
# Vapi Endpoints
# ---------------------------------------------------------------------------

@router.post("/validate-vapi", response_model=ValidateVapiKeyResponse)
async def validate_vapi(
    body: ValidateVapiKeyRequest,
    current_user: User = Depends(require_practice_admin),
    db: AsyncSession = Depends(get_db),
):
    """Validate a Vapi API key and save it if valid."""
    practice_id = _ensure_practice(current_user)

    from app.services.onboarding_service import validate_vapi_key, save_vapi_key
    result = await validate_vapi_key(body.api_key)

    if result["valid"]:
        await save_vapi_key(db, practice_id, body.api_key)
        logger.info("Vapi API key validated and saved for practice %s", practice_id)

    return ValidateVapiKeyResponse(**result)


@router.post("/create-assistant", response_model=CreateAssistantResponse)
async def create_assistant(
    body: CreateAssistantRequest = CreateAssistantRequest(),
    current_user: User = Depends(require_practice_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new Vapi AI assistant with all tool definitions."""
    practice_id = _ensure_practice(current_user)

    from app.services.onboarding_service import create_vapi_assistant
    result = await create_vapi_assistant(
        db=db,
        practice_id=practice_id,
        system_prompt=body.system_prompt,
        first_message=body.first_message,
    )

    return CreateAssistantResponse(**result)


@router.get("/vapi-phones", response_model=VapiPhoneListResponse)
async def list_vapi_phones(
    current_user: User = Depends(require_practice_admin),
    db: AsyncSession = Depends(get_db),
):
    """List phone numbers available on the Vapi account."""
    practice_id = _ensure_practice(current_user)

    from app.services.onboarding_service import list_vapi_phone_numbers, _get_vapi_key
    api_key = await _get_vapi_key(db, practice_id)
    if not api_key:
        raise HTTPException(status_code=400, detail="Vapi API key not configured. Complete Step 1 first.")

    numbers = await list_vapi_phone_numbers(api_key)

    return VapiPhoneListResponse(
        phone_numbers=[VapiPhoneNumber(**n) for n in numbers],
        total=len(numbers),
    )


@router.post("/assign-phone", response_model=AssignPhoneResponse)
async def assign_phone(
    body: AssignPhoneRequest,
    current_user: User = Depends(require_practice_admin),
    db: AsyncSession = Depends(get_db),
):
    """Assign a Vapi phone number to the practice's AI assistant."""
    practice_id = _ensure_practice(current_user)

    from app.services.onboarding_service import assign_vapi_phone, _get_vapi_key, _get_assistant_id
    api_key = await _get_vapi_key(db, practice_id)
    if not api_key:
        raise HTTPException(status_code=400, detail="Vapi API key not configured.")

    assistant_id = await _get_assistant_id(db, practice_id)
    if not assistant_id:
        raise HTTPException(status_code=400, detail="Vapi assistant not created yet. Complete Step 2 first.")

    result = await assign_vapi_phone(
        db=db,
        practice_id=practice_id,
        api_key=api_key,
        phone_number_id=body.phone_number_id,
        assistant_id=assistant_id,
    )

    return AssignPhoneResponse(**result)


# ---------------------------------------------------------------------------
# Twilio Endpoints
# ---------------------------------------------------------------------------

@router.post("/validate-twilio", response_model=ValidateTwilioResponse)
async def validate_twilio(
    body: ValidateTwilioRequest,
    current_user: User = Depends(require_practice_admin),
):
    """Validate Twilio credentials."""
    _ensure_practice(current_user)

    from app.services.onboarding_service import validate_twilio_credentials
    result = await validate_twilio_credentials(body.account_sid, body.auth_token)

    return ValidateTwilioResponse(**result)


@router.get("/twilio-phones", response_model=TwilioPhoneListResponse)
async def list_twilio_phones(
    account_sid: str,
    auth_token: str,
    current_user: User = Depends(require_practice_admin),
):
    """List phone numbers from a Twilio account."""
    _ensure_practice(current_user)

    from app.services.onboarding_service import list_twilio_phone_numbers
    numbers = await list_twilio_phone_numbers(account_sid, auth_token)

    return TwilioPhoneListResponse(
        phone_numbers=[TwilioPhoneNumber(**n) for n in numbers],
        total=len(numbers),
    )


@router.post("/save-twilio", response_model=SaveTwilioConfigResponse)
async def save_twilio(
    body: SaveTwilioConfigRequest,
    current_user: User = Depends(require_practice_admin),
    db: AsyncSession = Depends(get_db),
):
    """Save Twilio configuration after validation."""
    practice_id = _ensure_practice(current_user)

    from app.services.onboarding_service import save_twilio_config
    await save_twilio_config(
        db=db,
        practice_id=practice_id,
        account_sid=body.account_sid,
        auth_token=body.auth_token,
        phone_number=body.phone_number,
    )

    logger.info("Twilio config saved for practice %s", practice_id)
    return SaveTwilioConfigResponse(success=True, message="Twilio configuration saved successfully")


# ---------------------------------------------------------------------------
# OpenAI Key Endpoints
# ---------------------------------------------------------------------------

@router.post("/validate-openai", response_model=ValidateOpenAIKeyResponse)
async def validate_openai(
    body: ValidateOpenAIKeyRequest,
    current_user: User = Depends(require_practice_admin),
    db: AsyncSession = Depends(get_db),
):
    """Validate and save an OpenAI API key (used for training pipeline and feedback loop)."""
    practice_id = _ensure_practice(current_user)

    from app.services.onboarding_service import validate_openai_key, save_openai_key
    result = await validate_openai_key(body.api_key)

    if result["valid"]:
        await save_openai_key(db, practice_id, body.api_key)
        logger.info("OpenAI API key validated and saved for practice %s", practice_id)

    return ValidateOpenAIKeyResponse(**result)


# ---------------------------------------------------------------------------
# Stedi Key Endpoints
# ---------------------------------------------------------------------------

@router.post("/validate-stedi", response_model=ValidateStediKeyResponse)
async def validate_stedi(
    body: ValidateStediKeyRequest,
    current_user: User = Depends(require_practice_admin),
    db: AsyncSession = Depends(get_db),
):
    """Validate and save a Stedi API key (used for insurance verification)."""
    practice_id = _ensure_practice(current_user)

    from app.services.onboarding_service import validate_stedi_key, save_stedi_key
    result = await validate_stedi_key(body.api_key)

    if result["valid"]:
        await save_stedi_key(db, practice_id, body.api_key)
        logger.info("Stedi API key validated and saved for practice %s", practice_id)

    return ValidateStediKeyResponse(**result)
