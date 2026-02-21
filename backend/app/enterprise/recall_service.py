"""
Outbound recall campaigns — "6 months since last visit" automated outreach.

Finds patients overdue for preventive care and sends SMS recall messages.
Supports opt-out, rate limiting, and bilingual messaging.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings

logger = logging.getLogger(__name__)

RECALL_TYPES = {
    "preventive_care": {
        "description": "Patients not seen in 6+ months",
        "default_days": 180,
    },
    "annual_physical": {
        "description": "Annual physical exam due",
        "default_days": 365,
    },
    "follow_up": {
        "description": "Follow-up visit overdue",
        "default_days": 90,
    },
    "vaccination": {
        "description": "Vaccination reminder",
        "default_days": 365,
    },
}

DEFAULT_MESSAGE_EN = (
    "Hi {patient_name}, it's been {months} months since your last visit "
    "with Dr. {doctor_name}. Would you like to schedule an appointment? "
    "Reply YES or call {practice_phone}."
)
DEFAULT_MESSAGE_ES = (
    "Hola {patient_name}, han pasado {months} meses desde su ultima visita "
    "con Dr. {doctor_name}. Desea programar una cita? "
    "Responda SI o llame al {practice_phone}."
)


class RecallService:

    @staticmethod
    async def create_campaign(
        db: AsyncSession,
        practice_id: str,
        name: str,
        recall_type: str,
        params: Optional[dict] = None,
        created_by: Optional[str] = None,
    ) -> dict:
        """Create a new recall campaign."""
        if recall_type not in RECALL_TYPES:
            raise ValueError(f"Invalid recall type: {recall_type}")

        import json
        campaign_params = params or {}
        if "days_since_last_visit" not in campaign_params:
            campaign_params["days_since_last_visit"] = RECALL_TYPES[recall_type]["default_days"]

        result = await db.execute(
            text("""
                INSERT INTO recall_campaigns
                    (id, practice_id, name, recall_type, params, status,
                     created_by, created_at)
                VALUES
                    (gen_random_uuid(), :pid, :name, :type, :params::jsonb,
                     'draft', :created_by, NOW())
                RETURNING id, created_at
            """),
            {
                "pid": practice_id,
                "name": name,
                "type": recall_type,
                "params": json.dumps(campaign_params),
                "created_by": created_by,
            },
        )
        row = result.fetchone()
        await db.commit()

        return {
            "id": str(row.id),
            "name": name,
            "recall_type": recall_type,
            "status": "draft",
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    @staticmethod
    async def run_campaign(
        db: AsyncSession, campaign_id: str, practice_id: str
    ) -> dict:
        """Execute a recall campaign — find eligible patients and send messages."""
        # Get campaign details
        result = await db.execute(
            text("""
                SELECT id, name, recall_type, params, status
                FROM recall_campaigns
                WHERE id = :cid AND practice_id = :pid
            """),
            {"cid": campaign_id, "pid": practice_id},
        )
        campaign = result.fetchone()
        if not campaign:
            return {"error": "Campaign not found"}

        if campaign.status not in ("draft", "scheduled"):
            return {"error": f"Campaign cannot be run (status: {campaign.status})"}

        params = campaign.params if isinstance(campaign.params, dict) else {}
        days = params.get("days_since_last_visit", 180)

        # Mark as running
        await db.execute(
            text("""
                UPDATE recall_campaigns SET status = 'running', started_at = NOW()
                WHERE id = :cid
            """),
            {"cid": campaign_id},
        )
        await db.commit()

        # Find eligible patients
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        patients_result = await db.execute(
            text("""
                SELECT p.id, p.first_name, p.last_name, p.phone,
                       p.preferred_language,
                       MAX(a.date) AS last_visit
                FROM patients p
                LEFT JOIN appointments a ON a.patient_id = p.id AND a.status = 'completed'
                WHERE p.practice_id = :pid
                  AND COALESCE(p.opted_out_recall, FALSE) = FALSE
                  AND p.phone IS NOT NULL
                GROUP BY p.id
                HAVING MAX(a.date) < :cutoff OR MAX(a.date) IS NULL
                ORDER BY MAX(a.date) ASC NULLS FIRST
            """),
            {"pid": practice_id, "cutoff": cutoff_date.date()},
        )
        eligible = patients_result.fetchall()

        # Get practice info for messages
        practice_result = await db.execute(
            text("SELECT name, phone FROM practices WHERE id = :pid"),
            {"pid": practice_id},
        )
        practice = practice_result.fetchone()
        practice_phone = practice.phone if practice else ""

        contacted = 0
        skipped_opted_out = 0
        errors = 0
        settings = get_settings()

        for patient in eligible:
            patient_name = f"{patient.first_name or ''} {patient.last_name or ''}".strip()
            months_since = "6+"
            if patient.last_visit:
                delta = datetime.now(timezone.utc).date() - patient.last_visit
                months_since = str(max(1, delta.days // 30))

            # Build message
            template_en = params.get("message_template", DEFAULT_MESSAGE_EN)
            msg = template_en.format(
                patient_name=patient_name,
                months=months_since,
                doctor_name="your provider",
                practice_phone=practice_phone,
            )

            lang = (patient.preferred_language or "en").lower()
            if lang.startswith("es"):
                msg_es = DEFAULT_MESSAGE_ES.format(
                    patient_name=patient_name,
                    months=months_since,
                    doctor_name="su proveedor",
                    practice_phone=practice_phone,
                )
                msg = f"{msg}\n---\n{msg_es}"

            # Send SMS
            sent = await _send_recall_sms(patient.phone, msg, practice_id)

            # Record contact
            await db.execute(
                text("""
                    INSERT INTO recall_contacts
                        (id, campaign_id, practice_id, patient_id, patient_name,
                         patient_phone, last_visit_date, message_sent,
                         status, sent_at, created_at)
                    VALUES
                        (gen_random_uuid(), :cid, :pid, :patient_id, :name,
                         :phone, :last_visit, :msg,
                         :status, :sent_at, NOW())
                """),
                {
                    "cid": campaign_id,
                    "pid": practice_id,
                    "patient_id": str(patient.id),
                    "name": patient_name,
                    "phone": patient.phone,
                    "last_visit": patient.last_visit,
                    "msg": msg[:2000],
                    "status": "sent" if sent else "error",
                    "sent_at": datetime.now(timezone.utc) if sent else None,
                },
            )

            if sent:
                contacted += 1
            else:
                errors += 1

            # Rate limit: ~50/min
            await asyncio.sleep(1.2)

        # Mark campaign as completed
        await db.execute(
            text("""
                UPDATE recall_campaigns SET status = 'completed', completed_at = NOW()
                WHERE id = :cid
            """),
            {"cid": campaign_id},
        )
        await db.commit()

        return {
            "campaign_id": campaign_id,
            "total_eligible": len(eligible),
            "contacted": contacted,
            "skipped_opted_out": skipped_opted_out,
            "errors": errors,
        }

    @staticmethod
    async def process_recall_response(
        db: AsyncSession, phone: str, response_text: str
    ) -> dict:
        """Process a patient's reply to a recall message."""
        upper = response_text.strip().upper()

        if upper in ("STOP", "UNSUBSCRIBE", "OPTOUT"):
            # Opt out of future recalls
            await db.execute(
                text("UPDATE patients SET opted_out_recall = TRUE WHERE phone = :phone"),
                {"phone": phone},
            )
            await db.execute(
                text("""
                    UPDATE recall_contacts SET status = 'opted_out', responded_at = NOW()
                    WHERE patient_phone = :phone AND status = 'sent'
                    ORDER BY created_at DESC LIMIT 1
                """),
                {"phone": phone},
            )
            await db.commit()
            return {"status": "opted_out", "phone": phone}

        if upper in ("YES", "SI", "SÍ", "Y", "S"):
            await db.execute(
                text("""
                    UPDATE recall_contacts SET status = 'responded_yes', responded_at = NOW()
                    WHERE patient_phone = :phone AND status = 'sent'
                    ORDER BY created_at DESC LIMIT 1
                """),
                {"phone": phone},
            )
            await db.commit()
            return {"status": "responded_yes", "phone": phone}

        # Any other response
        await db.execute(
            text("""
                UPDATE recall_contacts SET status = 'responded_no', responded_at = NOW()
                WHERE patient_phone = :phone AND status = 'sent'
                ORDER BY created_at DESC LIMIT 1
            """),
            {"phone": phone},
        )
        await db.commit()
        return {"status": "responded_no", "phone": phone}

    @staticmethod
    async def get_campaign_stats(
        db: AsyncSession, campaign_id: str
    ) -> dict:
        """Get statistics for a campaign."""
        result = await db.execute(
            text("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(CASE WHEN status = 'sent' THEN 1 END) AS sent,
                    COUNT(CASE WHEN status = 'responded_yes' THEN 1 END) AS responded_yes,
                    COUNT(CASE WHEN status = 'responded_no' THEN 1 END) AS responded_no,
                    COUNT(CASE WHEN status = 'opted_out' THEN 1 END) AS opted_out,
                    COUNT(CASE WHEN status = 'error' THEN 1 END) AS errors
                FROM recall_contacts
                WHERE campaign_id = :cid
            """),
            {"cid": campaign_id},
        )
        row = result.fetchone()
        total = row.total or 0
        response_rate = 0
        if total > 0:
            responded = (row.responded_yes or 0) + (row.responded_no or 0) + (row.opted_out or 0)
            response_rate = round(responded / total * 100, 1)

        return {
            "total_contacts": total,
            "sent": row.sent or 0,
            "responded_yes": row.responded_yes or 0,
            "responded_no": row.responded_no or 0,
            "opted_out": row.opted_out or 0,
            "errors": row.errors or 0,
            "response_rate": response_rate,
        }

    @staticmethod
    async def list_campaigns(
        db: AsyncSession, practice_id: str, status: Optional[str] = None
    ) -> list[dict]:
        """List recall campaigns."""
        query = """
            SELECT id, name, recall_type, status, scheduled_at,
                   started_at, completed_at, created_at
            FROM recall_campaigns
            WHERE practice_id = :pid
        """
        params: dict = {"pid": practice_id}
        if status:
            query += " AND status = :status"
            params["status"] = status
        query += " ORDER BY created_at DESC"

        result = await db.execute(text(query), params)
        return [
            {
                "id": str(row.id),
                "name": row.name,
                "recall_type": row.recall_type,
                "status": row.status,
                "scheduled_at": row.scheduled_at.isoformat() if row.scheduled_at else None,
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in result.fetchall()
        ]


async def _send_recall_sms(phone: str, message: str, practice_id: str) -> bool:
    settings = get_settings()
    if not settings.TWILIO_ACCOUNT_SID:
        logger.warning("Twilio not configured — recall SMS not sent")
        return False
    try:
        from twilio.rest import Client
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        client.messages.create(body=message, from_=settings.TWILIO_ACCOUNT_SID, to=phone)
        return True
    except Exception as e:
        logger.error("Recall SMS failed to %s: %s", phone, e)
        return False
