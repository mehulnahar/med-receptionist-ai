"""
Stedi Batch Eligibility — pre-verify all patients for next day's appointments.

Runs as a nightly background job. Dashboard shows green/red insurance status
before the patient arrives.
"""

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select, and_, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.appointment import Appointment
from app.models.patient import Patient
from app.models.practice import Practice
from app.services.insurance_service import check_eligibility

logger = logging.getLogger(__name__)


async def run_batch_eligibility_check() -> dict:
    """Run nightly batch eligibility check for all practices.

    Verifies insurance for all patients with appointments tomorrow.
    Returns summary of results.
    """
    logger.info("Starting batch eligibility check")
    results = {"total": 0, "verified": 0, "failed": 0, "skipped": 0}

    async with AsyncSessionLocal() as db:
        # Get all active practices
        practices = await db.execute(
            text("SELECT id, name, npi FROM practices WHERE is_active = TRUE")
        )
        practice_rows = practices.fetchall()

        for practice in practice_rows:
            practice_id = practice.id
            try:
                practice_results = await _verify_practice_appointments(
                    db, practice_id
                )
                results["total"] += practice_results["total"]
                results["verified"] += practice_results["verified"]
                results["failed"] += practice_results["failed"]
                results["skipped"] += practice_results["skipped"]
            except Exception as e:
                logger.error(
                    "Batch eligibility failed for practice %s: %s",
                    practice_id, e,
                )

    logger.info(
        "Batch eligibility complete: total=%d verified=%d failed=%d skipped=%d",
        results["total"], results["verified"], results["failed"], results["skipped"],
    )
    return results


async def _verify_practice_appointments(
    db: AsyncSession,
    practice_id: UUID,
) -> dict:
    """Verify insurance for all appointments tomorrow for a practice."""
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date()
    results = {"total": 0, "verified": 0, "failed": 0, "skipped": 0}

    # Get tomorrow's non-cancelled appointments
    appointments = await db.execute(
        select(Appointment)
        .where(
            and_(
                Appointment.practice_id == practice_id,
                Appointment.date == tomorrow,
                Appointment.status.notin_(["cancelled", "no_show"]),
            )
        )
    )
    appt_list = list(appointments.scalars().all())
    results["total"] = len(appt_list)

    for appt in appt_list:
        # Get patient
        patient_result = await db.execute(
            select(Patient).where(Patient.id == appt.patient_id)
        )
        patient = patient_result.scalar_one_or_none()

        if not patient:
            results["skipped"] += 1
            continue

        # Skip if no insurance info
        if not patient.insurance_carrier or not patient.member_id:
            results["skipped"] += 1
            continue

        try:
            result = await check_eligibility(
                db=db,
                practice_id=practice_id,
                patient_id=patient.id,
                carrier_name=patient.insurance_carrier,
                member_id=patient.member_id,
                first_name=patient.first_name,
                last_name=patient.last_name,
                dob=patient.dob,
            )
            await db.commit()

            if result.get("verified"):
                results["verified"] += 1
            else:
                results["failed"] += 1

        except Exception as e:
            logger.warning(
                "Batch verification failed for patient %s: %s",
                patient.id, e,
            )
            results["failed"] += 1

        # Rate limit — don't hammer Stedi
        await asyncio.sleep(0.5)

    return results


async def get_batch_status(
    db: AsyncSession,
    practice_id: UUID,
    target_date: Optional[date] = None,
) -> list[dict]:
    """Get insurance verification status for a day's appointments.

    Returns list of appointments with verification status for the dashboard.
    """
    if target_date is None:
        target_date = (datetime.now(timezone.utc) + timedelta(days=1)).date()

    result = await db.execute(text("""
        SELECT
            a.id as appointment_id,
            a.date,
            a.time,
            a.status as appt_status,
            p.first_name,
            p.last_name,
            p.insurance_carrier,
            p.member_id,
            iv.status as verification_status,
            iv.is_active as insurance_active,
            iv.plan_name,
            iv.copay,
            iv.verified_at
        FROM appointments a
        JOIN patients p ON a.patient_id = p.id
        LEFT JOIN LATERAL (
            SELECT * FROM insurance_verifications
            WHERE patient_id = p.id
                AND practice_id = a.practice_id
            ORDER BY verified_at DESC
            LIMIT 1
        ) iv ON TRUE
        WHERE a.practice_id = :pid
            AND a.date = :target_date
            AND a.status NOT IN ('cancelled', 'no_show')
        ORDER BY a.time
    """), {"pid": str(practice_id), "target_date": target_date})

    rows = result.fetchall()
    return [
        {
            "appointment_id": str(row.appointment_id),
            "date": row.date.isoformat() if row.date else None,
            "time": row.time.strftime("%H:%M") if row.time else None,
            "status": row.appt_status,
            "patient_name": f"{row.first_name} {row.last_name}",
            "insurance_carrier": row.insurance_carrier,
            "member_id": row.member_id,
            "verification_status": row.verification_status or "unverified",
            "insurance_active": row.insurance_active,
            "plan_name": row.plan_name,
            "copay": float(row.copay) if row.copay else None,
            "verified_at": row.verified_at.isoformat() if row.verified_at else None,
        }
        for row in rows
    ]
