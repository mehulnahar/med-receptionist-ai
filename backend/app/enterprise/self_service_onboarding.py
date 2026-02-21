"""
Practice self-service onboarding — signup → verify → configure → launch.

Practices can sign up and configure their AI receptionist without
MindCrew involvement.
"""

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timezone, timedelta

import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings

logger = logging.getLogger(__name__)

VERIFICATION_CODE_EXPIRY_MINUTES = 15
MAX_SIGNUPS_PER_EMAIL_PER_DAY = 3

ONBOARDING_STEPS = [
    "email_verification",
    "practice_info",
    "admin_account",
    "schedule_setup",
    "ai_preferences",
    "review_launch",
]


class SelfServiceOnboardingService:

    @staticmethod
    async def create_signup(
        db: AsyncSession,
        email: str,
        practice_name: str,
        phone: str = "",
        plan: str = "starter",
    ) -> dict:
        """Create a new pending signup and send verification code."""
        # Rate limit
        count_result = await db.execute(
            text("""
                SELECT COUNT(*) FROM practice_signups
                WHERE email = :email AND created_at >= NOW() - INTERVAL '24 hours'
            """),
            {"email": email.lower()},
        )
        count = count_result.scalar_one()
        if count >= MAX_SIGNUPS_PER_EMAIL_PER_DAY:
            return {"error": "Too many signup attempts. Try again in 24 hours."}

        # Generate 6-digit code
        code = f"{secrets.randbelow(1000000):06d}"
        code_expires = datetime.now(timezone.utc) + timedelta(minutes=VERIFICATION_CODE_EXPIRY_MINUTES)

        result = await db.execute(
            text("""
                INSERT INTO practice_signups
                    (id, email, practice_name, phone, plan,
                     verification_code, code_expires_at, email_verified,
                     onboarding_step, status, created_at, updated_at)
                VALUES
                    (gen_random_uuid(), :email, :name, :phone, :plan,
                     :code, :expires, FALSE,
                     0, 'pending', NOW(), NOW())
                RETURNING id
            """),
            {
                "email": email.lower(),
                "name": practice_name,
                "phone": phone,
                "plan": plan,
                "code": code,
                "expires": code_expires,
            },
        )
        row = result.fetchone()
        await db.commit()

        signup_id = str(row.id)

        # Send verification email/SMS
        settings = get_settings()
        if phone and settings.TWILIO_ACCOUNT_SID:
            try:
                from twilio.rest import Client
                client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
                client.messages.create(
                    body=f"Your AI Receptionist verification code: {code}",
                    from_=settings.TWILIO_PHONE_NUMBER,
                    to=phone,
                )
            except Exception as e:
                logger.warning("Verification SMS failed: %s", e)

        logger.info("Signup created: %s for %s", signup_id, email)
        return {"signup_id": signup_id, "email": email}

    @staticmethod
    async def verify_email(
        db: AsyncSession, signup_id: str, code: str
    ) -> bool:
        """Verify the 6-digit email/SMS code."""
        result = await db.execute(
            text("""
                SELECT verification_code, code_expires_at, email_verified
                FROM practice_signups
                WHERE id = :sid AND status = 'pending'
            """),
            {"sid": signup_id},
        )
        row = result.fetchone()
        if not row:
            return False

        if row.email_verified:
            return True  # Already verified

        if row.code_expires_at and datetime.now(timezone.utc) > row.code_expires_at:
            return False  # Expired

        if not hmac.compare_digest(row.verification_code, code):
            return False

        await db.execute(
            text("""
                UPDATE practice_signups
                SET email_verified = TRUE, status = 'verified',
                    onboarding_step = 1, updated_at = NOW()
                WHERE id = :sid
            """),
            {"sid": signup_id},
        )
        await db.commit()
        return True

    @staticmethod
    async def resend_verification(db: AsyncSession, signup_id: str) -> bool:
        """Resend verification code."""
        code = f"{secrets.randbelow(1000000):06d}"
        expires = datetime.now(timezone.utc) + timedelta(minutes=VERIFICATION_CODE_EXPIRY_MINUTES)

        result = await db.execute(
            text("""
                UPDATE practice_signups
                SET verification_code = :code, code_expires_at = :expires,
                    updated_at = NOW()
                WHERE id = :sid AND status = 'pending'
                RETURNING phone
            """),
            {"sid": signup_id, "code": code, "expires": expires},
        )
        row = result.fetchone()
        await db.commit()

        if not row:
            return False

        # Send via SMS
        if row.phone:
            settings = get_settings()
            try:
                from twilio.rest import Client
                client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
                client.messages.create(
                    body=f"Your verification code: {code}",
                    from_=settings.TWILIO_PHONE_NUMBER,
                    to=row.phone,
                )
            except Exception as e:
                logger.warning("Resend verification SMS failed: %s", e)

        return True

    @staticmethod
    async def complete_onboarding(
        db: AsyncSession, signup_id: str, onboarding_data: dict
    ) -> dict:
        """Complete onboarding — create practice, admin user, defaults."""
        # Verify signup is verified
        result = await db.execute(
            text("""
                SELECT email, practice_name, phone, plan, email_verified
                FROM practice_signups WHERE id = :sid
            """),
            {"sid": signup_id},
        )
        signup = result.fetchone()
        if not signup or not signup.email_verified:
            return {"error": "Signup not verified"}

        admin_info = onboarding_data.get("admin", {})
        practice_info = onboarding_data.get("practice_details", {})
        preferences = onboarding_data.get("preferences", {})

        # 1. Create practice
        practice_result = await db.execute(
            text("""
                INSERT INTO practices
                    (id, name, phone, address, city, state, zip_code,
                     npi, tax_id, timezone, is_active, config, created_at, updated_at)
                VALUES
                    (gen_random_uuid(), :name, :phone, :address, :city, :state,
                     :zip, :npi, :tax_id, :tz, TRUE, '{}'::jsonb, NOW(), NOW())
                RETURNING id
            """),
            {
                "name": signup.practice_name,
                "phone": practice_info.get("phone", signup.phone or ""),
                "address": practice_info.get("address", ""),
                "city": practice_info.get("city", ""),
                "state": practice_info.get("state", ""),
                "zip": practice_info.get("zip_code", ""),
                "npi": practice_info.get("npi", ""),
                "tax_id": practice_info.get("tax_id", ""),
                "tz": practice_info.get("timezone", "America/New_York"),
            },
        )
        practice_id = str(practice_result.fetchone().id)

        # 2. Create admin user
        admin_name = admin_info.get("name", "Admin")
        admin_password = admin_info.get("password", "")
        name_parts = admin_name.split(" ", 1)

        from app.middleware.auth import get_password_hash
        hashed = get_password_hash(admin_password)

        user_result = await db.execute(
            text("""
                INSERT INTO users
                    (id, email, hashed_password, first_name, last_name,
                     role, practice_id, is_active, created_at, updated_at)
                VALUES
                    (gen_random_uuid(), :email, :password, :first, :last,
                     'practice_admin', :pid, TRUE, NOW(), NOW())
                RETURNING id
            """),
            {
                "email": signup.email,
                "password": hashed,
                "first": name_parts[0],
                "last": name_parts[1] if len(name_parts) > 1 else "",
                "pid": practice_id,
            },
        )
        user_id = str(user_result.fetchone().id)

        # 3. Create API key
        api_key = secrets.token_urlsafe(32)
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()

        await db.execute(
            text("""
                INSERT INTO practice_api_keys
                    (id, practice_id, key_hash, key_prefix, name, is_active, created_at)
                VALUES
                    (gen_random_uuid(), :pid, :hash, :prefix, 'Default API Key', TRUE, NOW())
            """),
            {
                "pid": practice_id,
                "hash": key_hash,
                "prefix": api_key[:8],
            },
        )

        # 4. Mark signup as completed
        await db.execute(
            text("""
                UPDATE practice_signups
                SET status = 'completed', completed_at = NOW(),
                    onboarding_step = 6, updated_at = NOW()
                WHERE id = :sid
            """),
            {"sid": signup_id},
        )

        await db.commit()

        logger.info(
            "Self-service onboarding complete: practice=%s user=%s",
            practice_id,
            user_id,
        )

        return {
            "practice_id": practice_id,
            "admin_user_id": user_id,
            "api_key": api_key,
            "plan": signup.plan,
        }

    @staticmethod
    async def get_onboarding_progress(
        db: AsyncSession, signup_id: str
    ) -> dict:
        """Get onboarding progress."""
        result = await db.execute(
            text("""
                SELECT onboarding_step, email_verified, status, created_at
                FROM practice_signups WHERE id = :sid
            """),
            {"sid": signup_id},
        )
        row = result.fetchone()
        if not row:
            return {"error": "Signup not found"}

        step = row.onboarding_step or 0
        return {
            "current_step": step,
            "current_step_name": ONBOARDING_STEPS[step] if step < len(ONBOARDING_STEPS) else "completed",
            "email_verified": row.email_verified,
            "status": row.status,
            "completed_steps": ONBOARDING_STEPS[:step],
            "remaining_steps": ONBOARDING_STEPS[step:],
            "progress_pct": round(step / len(ONBOARDING_STEPS) * 100, 1),
        }
