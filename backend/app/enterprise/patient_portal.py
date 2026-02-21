"""
Patient portal — digital intake forms via text link.

Patients receive an SMS with a secure link to complete intake forms
(demographics, insurance, medical history, etc.) before their visit.
"""

import hashlib
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings

logger = logging.getLogger(__name__)

INTAKE_TOKEN_EXPIRY_HOURS = 24


class PatientPortalService:

    @staticmethod
    async def send_intake_link(
        db: AsyncSession,
        practice_id: str,
        patient_phone: str,
        patient_name: str,
        appointment_id: Optional[str] = None,
    ) -> str:
        """Send a patient intake form link via SMS."""
        settings = get_settings()

        # Create JWT token
        payload = {
            "type": "intake",
            "practice_id": practice_id,
            "patient_phone": patient_phone,
            "patient_name": patient_name,
            "appointment_id": appointment_id or "",
            "exp": datetime.now(timezone.utc) + timedelta(hours=INTAKE_TOKEN_EXPIRY_HOURS),
        }
        token = jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        link = f"{settings.APP_URL}/intake/{token}"

        # Store link record
        await db.execute(
            text("""
                INSERT INTO intake_links
                    (id, practice_id, patient_phone, patient_name,
                     appointment_id, token_hash, status, sent_at,
                     expires_at, created_at)
                VALUES
                    (gen_random_uuid(), :pid, :phone, :name,
                     :appt_id, :hash, 'sent', NOW(),
                     :expires, NOW())
            """),
            {
                "pid": practice_id,
                "phone": patient_phone,
                "name": patient_name,
                "appt_id": appointment_id,
                "hash": token_hash,
                "expires": datetime.now(timezone.utc) + timedelta(hours=INTAKE_TOKEN_EXPIRY_HOURS),
            },
        )
        await db.commit()

        # Send bilingual SMS
        msg_en = (
            f"Hi {patient_name}, please complete your intake form "
            f"before your visit: {link}"
        )
        msg_es = (
            f"Hola {patient_name}, por favor complete su formulario "
            f"de ingreso antes de su visita: {link}"
        )
        message = f"{msg_en}\n---\n{msg_es}"

        await _send_portal_sms(patient_phone, message, practice_id)
        return token

    @staticmethod
    def validate_intake_token(token: str) -> Optional[dict]:
        """Decode and validate an intake JWT token."""
        settings = get_settings()
        try:
            payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
            if payload.get("type") != "intake":
                return None
            return payload
        except jwt.ExpiredSignatureError:
            logger.warning("Intake token expired")
            return None
        except jwt.InvalidTokenError:
            logger.warning("Invalid intake token")
            return None

    @staticmethod
    async def save_intake_form(
        db: AsyncSession, token: str, form_data: dict
    ) -> dict:
        """Save a completed intake form submission."""
        payload = PatientPortalService.validate_intake_token(token)
        if not payload:
            return {"error": "Invalid or expired intake link"}

        practice_id = payload["practice_id"]
        patient_phone = payload["patient_phone"]
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        # Find the intake link record
        link_result = await db.execute(
            text("""
                SELECT id FROM intake_links
                WHERE token_hash = :hash AND practice_id = :pid
            """),
            {"hash": token_hash, "pid": practice_id},
        )
        link_row = link_result.fetchone()
        link_id = str(link_row.id) if link_row else None

        # Extract form sections
        demographics = form_data.get("demographics", {})
        insurance_info = form_data.get("insurance_info", {})
        medical_history = form_data.get("medical_history", {})
        medications = form_data.get("medications", {})
        allergies = form_data.get("allergies", {})
        emergency_contact = form_data.get("emergency_contact", {})
        consent = form_data.get("consent_signatures", {})

        import json
        await db.execute(
            text("""
                INSERT INTO intake_submissions
                    (id, practice_id, intake_link_id, patient_phone,
                     demographics, insurance_info, medical_history,
                     medications, allergies, emergency_contact,
                     consent_signatures, status, created_at)
                VALUES
                    (gen_random_uuid(), :pid, :link_id, :phone,
                     :demographics::jsonb, :insurance::jsonb, :history::jsonb,
                     :meds::jsonb, :allergies::jsonb, :emergency::jsonb,
                     :consent::jsonb, 'submitted', NOW())
                RETURNING id
            """),
            {
                "pid": practice_id,
                "link_id": link_id,
                "phone": patient_phone,
                "demographics": json.dumps(demographics),
                "insurance": json.dumps(insurance_info),
                "history": json.dumps(medical_history),
                "meds": json.dumps(medications),
                "allergies": json.dumps(allergies),
                "emergency": json.dumps(emergency_contact),
                "consent": json.dumps(consent),
            },
        )

        # Update link status
        if link_id:
            await db.execute(
                text("""
                    UPDATE intake_links SET status = 'completed', completed_at = NOW()
                    WHERE id = :lid
                """),
                {"lid": link_id},
            )

        await db.commit()

        return {
            "status": "submitted",
            "practice_id": practice_id,
            "patient_phone": patient_phone,
        }

    @staticmethod
    async def get_intake_submission(
        db: AsyncSession, submission_id: str, practice_id: str
    ) -> Optional[dict]:
        """Get a single intake submission."""
        result = await db.execute(
            text("""
                SELECT id, patient_phone, demographics, insurance_info,
                       medical_history, medications, allergies,
                       emergency_contact, consent_signatures,
                       status, reviewed_by, reviewed_at, created_at
                FROM intake_submissions
                WHERE id = :sid AND practice_id = :pid
            """),
            {"sid": submission_id, "pid": practice_id},
        )
        row = result.fetchone()
        if not row:
            return None

        return {
            "id": str(row.id),
            "patient_phone": row.patient_phone,
            "demographics": row.demographics,
            "insurance_info": row.insurance_info,
            "medical_history": row.medical_history,
            "medications": row.medications,
            "allergies": row.allergies,
            "emergency_contact": row.emergency_contact,
            "consent_signatures": row.consent_signatures,
            "status": row.status,
            "reviewed_by": str(row.reviewed_by) if row.reviewed_by else None,
            "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    @staticmethod
    async def list_intake_submissions(
        db: AsyncSession, practice_id: str, status: Optional[str] = None, limit: int = 50
    ) -> list[dict]:
        """List intake submissions for a practice."""
        query = """
            SELECT id, patient_phone, status, created_at,
                   demographics->>'first_name' AS first_name,
                   demographics->>'last_name' AS last_name
            FROM intake_submissions
            WHERE practice_id = :pid
        """
        params: dict = {"pid": practice_id, "limit": limit}
        if status:
            query += " AND status = :status"
            params["status"] = status
        query += " ORDER BY created_at DESC LIMIT :limit"

        result = await db.execute(text(query), params)
        return [
            {
                "id": str(row.id),
                "patient_phone": row.patient_phone,
                "patient_name": f"{row.first_name or ''} {row.last_name or ''}".strip(),
                "status": row.status,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in result.fetchall()
        ]

    @staticmethod
    async def get_intake_stats(db: AsyncSession, practice_id: str) -> dict:
        """Get intake form completion statistics."""
        result = await db.execute(
            text("""
                SELECT
                    COUNT(DISTINCT il.id) AS total_sent,
                    COUNT(DISTINCT CASE WHEN il.status = 'completed' THEN il.id END) AS total_completed,
                    AVG(CASE WHEN il.completed_at IS NOT NULL THEN
                        EXTRACT(EPOCH FROM (il.completed_at - il.sent_at)) / 60
                    END) AS avg_minutes
                FROM intake_links il
                WHERE il.practice_id = :pid
                  AND il.created_at >= NOW() - INTERVAL '30 days'
            """),
            {"pid": practice_id},
        )
        row = result.fetchone()
        total_sent = row.total_sent or 0
        total_completed = row.total_completed or 0
        completion_rate = (
            round(total_completed / total_sent * 100, 1) if total_sent > 0 else 0
        )

        return {
            "total_sent": total_sent,
            "total_completed": total_completed,
            "completion_rate": completion_rate,
            "avg_completion_time_minutes": round(float(row.avg_minutes or 0), 1),
        }


async def _send_portal_sms(phone: str, message: str, practice_id: str) -> bool:
    settings = get_settings()
    if not settings.TWILIO_ACCOUNT_SID:
        logger.warning("Twilio not configured — portal SMS not sent")
        return False
    try:
        from twilio.rest import Client
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        client.messages.create(body=message, from_=settings.TWILIO_ACCOUNT_SID, to=phone)
        return True
    except Exception as e:
        logger.error("Portal SMS failed to %s: %s", phone, e)
        return False
