"""
Seed data script for the Medical Receptionist SaaS platform.

Seeds the database with initial data for Dr. Stefanides' practice.
Idempotent: safe to run multiple times without duplicating data.

Usage:
    python -m app.seed
"""

import asyncio
import datetime
import logging
import secrets

import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from app.database import AsyncSessionLocal
from app.models.practice import Practice
from app.models.user import User
from app.models.practice_config import PracticeConfig
from app.models.schedule import ScheduleTemplate
from app.models.appointment_type import AppointmentType
from app.models.insurance_carrier import InsuranceCarrier
from app.models.holiday import Holiday


def hash_password(password: str) -> str:
    """Hash a password using bcrypt directly."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


async def seed_database() -> None:
    """Seed the database with initial data for Stefanides practice."""
    async with AsyncSessionLocal() as session:
        # ------------------------------------------------------------------
        # 1. Practice
        # ------------------------------------------------------------------
        practice = await _get_or_create_practice(session)
        practice_id = practice.id

        # ------------------------------------------------------------------
        # 2. Users
        # ------------------------------------------------------------------
        await _seed_users(session, practice_id)

        # ------------------------------------------------------------------
        # 3. Practice Config
        # ------------------------------------------------------------------
        await _seed_practice_config(session, practice_id)

        # ------------------------------------------------------------------
        # 4. Schedule Templates
        # ------------------------------------------------------------------
        await _seed_schedule_templates(session, practice_id)

        # ------------------------------------------------------------------
        # 5. Appointment Types
        # ------------------------------------------------------------------
        await _seed_appointment_types(session, practice_id)

        # ------------------------------------------------------------------
        # 6. Insurance Carriers
        # ------------------------------------------------------------------
        await _seed_insurance_carriers(session, practice_id)

        # ------------------------------------------------------------------
        # 7. Holidays (2026)
        # ------------------------------------------------------------------
        await _seed_holidays(session)

        await session.commit()
        logger.info("Database seeding completed successfully.")


# ==========================================================================
# Helper functions
# ==========================================================================


async def _get_or_create_practice(session: AsyncSession) -> Practice:
    """Return the Stefanides practice, creating it if it does not exist."""
    result = await session.execute(
        select(Practice).where(Practice.slug == "stefanides-md")
    )
    practice = result.scalars().first()
    if practice:
        logger.info("Practice 'stefanides-md' already exists, skipping.")
        return practice

    practice = Practice(
        name="Stefanides Neofitos, MD PC",
        slug="stefanides-md",
        npi="1689880429",
        tax_id="263551213",
        timezone="America/New_York",
        status="active",
    )
    session.add(practice)
    await session.flush()
    logger.info("Created practice: Stefanides Neofitos, MD PC")
    return practice


async def _seed_users(session: AsyncSession, practice_id) -> None:
    """Create the super admin and secretary users if they do not exist."""
    users = [
        {
            "email": "admin@mindcrew.tech",
            "name": "Mehul (Admin)",
            "role": "super_admin",
            "practice_id": None,  # super_admin is not tied to a practice
        },
        {
            "email": "jennie@stefanides.com",
            "name": "Jennie",
            "role": "secretary",
            "practice_id": practice_id,
        },
    ]

    for user_data in users:
        result = await session.execute(
            select(User).where(User.email == user_data["email"])
        )
        if result.scalars().first():
            logger.info("User '%s' already exists, skipping.", user_data['email'])
            continue

        # Generate a random password for each user (printed to stdout for initial setup)
        password = secrets.token_urlsafe(16)

        user = User(
            email=user_data["email"],
            name=user_data["name"],
            role=user_data["role"],
            password_hash=hash_password(password),
            practice_id=user_data["practice_id"],
            is_active=True,
            password_change_required=True,
        )
        session.add(user)
        logger.info("Created user: %s (%s)", user_data['email'], user_data['role'])
        logger.warning("INITIAL PASSWORD for %s: %s  (change on first login)", user_data['email'], password)
        logger.warning("Save this password — it will NOT be shown again.")

    await session.flush()


async def _seed_practice_config(session: AsyncSession, practice_id) -> None:
    """Create the practice configuration if it does not exist."""
    result = await session.execute(
        select(PracticeConfig).where(PracticeConfig.practice_id == practice_id)
    )
    if result.scalars().first():
        logger.info("PracticeConfig already exists, skipping.")
        return

    config = PracticeConfig(
        practice_id=practice_id,
        languages=["en", "es"],
        primary_language="en",
        greek_transfer_to_staff=True,
        slot_duration_minutes=15,
        allow_overbooking=True,
        max_overbooking_per_slot=3,
        booking_horizon_days=90,
        greetings={
            "en": "Thank you for calling Dr. Stefanides' office. How can I help you today?",
            "es": "Gracias por llamar a la oficina del Dr. Stefanides. \u00bfC\u00f3mo puedo ayudarle hoy?",
        },
        emergency_message="If this is a medical emergency, please hang up and call 911.",
        sms_confirmation_template={
            "en": (
                "Your appointment with Dr. Stefanides is confirmed for {date} at {time}. "
                "Please bring your insurance card and photo ID."
            ),
            "es": (
                "Su cita con el Dr. Stefanides est\u00e1 confirmada para el {date} a las {time}. "
                "Por favor traiga su tarjeta de seguro y una identificaci\u00f3n con foto."
            ),
        },
        new_patient_fields=[
            "name",
            "dob",
            "address",
            "phone",
            "insurance_carrier",
            "member_id",
            "referring_physician",
            "accident_date",
        ],
        existing_patient_fields=[
            "name",
            "dob",
            "confirm_address",
            "confirm_phone",
            "new_injuries",
            "insurance_changed",
        ],
        max_retries=3,
        fallback_message="I apologize, I did not understand that. Could you please repeat?",
    )
    session.add(config)
    await session.flush()
    logger.info("Created PracticeConfig.")


async def _seed_schedule_templates(session: AsyncSession, practice_id) -> None:
    """Create the weekly schedule template if it does not exist."""
    result = await session.execute(
        select(ScheduleTemplate).where(ScheduleTemplate.practice_id == practice_id)
    )
    existing = result.scalars().all()
    if existing:
        logger.info("Schedule templates already exist, skipping.")
        return

    schedules = [
        # day_of_week, is_enabled, start_time, end_time
        (0, True, datetime.time(9, 0), datetime.time(19, 0)),    # Monday
        (1, True, datetime.time(10, 0), datetime.time(17, 0)),   # Tuesday
        (2, True, datetime.time(9, 0), datetime.time(19, 0)),    # Wednesday
        (3, True, datetime.time(10, 0), datetime.time(17, 0)),   # Thursday
        (4, True, datetime.time(9, 0), datetime.time(15, 0)),    # Friday (alternating via overrides)
        (5, False, None, None),                                   # Saturday
        (6, False, None, None),                                   # Sunday
    ]

    for day_of_week, is_enabled, start_time, end_time in schedules:
        template = ScheduleTemplate(
            practice_id=practice_id,
            day_of_week=day_of_week,
            is_enabled=is_enabled,
            start_time=start_time,
            end_time=end_time,
        )
        session.add(template)

    await session.flush()
    logger.info("Created 7 schedule templates (Mon-Sun).")


async def _seed_appointment_types(session: AsyncSession, practice_id) -> None:
    """Create appointment types if they do not exist."""
    result = await session.execute(
        select(AppointmentType).where(AppointmentType.practice_id == practice_id)
    )
    existing = result.scalars().all()
    if existing:
        logger.info("Appointment types already exist, skipping.")
        return

    types = [
        {
            "name": "New Patient Complete",
            "color": "#DC2626",
            "for_new_patients": True,
            "for_existing_patients": False,
            "requires_accident_date": False,
            "detection_rules": {"is_new": True, "has_accident": False},
            "sort_order": 0,
        },
        {
            "name": "Follow Up Visit",
            "color": "#6B7280",
            "for_new_patients": False,
            "for_existing_patients": True,
            "requires_accident_date": False,
            "detection_rules": {"is_new": False, "has_accident": False},
            "sort_order": 1,
        },
        {
            "name": "Workers Comp Follow Up",
            "color": "#EC4899",
            "for_new_patients": False,
            "for_existing_patients": True,
            "requires_accident_date": True,
            "detection_rules": {"is_new": False, "accident_type": "workers_comp"},
            "sort_order": 2,
        },
        {
            "name": "GHI Out of Network",
            "color": "#2563EB",
            "for_new_patients": True,
            "for_existing_patients": True,
            "requires_accident_date": False,
            "detection_rules": {"insurance_contains": "GHI"},
            "sort_order": 3,
        },
        {
            "name": "No Fault Follow Up",
            "color": "#06B6D4",
            "for_new_patients": False,
            "for_existing_patients": True,
            "requires_accident_date": True,
            "detection_rules": {"is_new": False, "accident_type": "no_fault"},
            "sort_order": 4,
        },
        {
            "name": "WC Initial",
            "color": "#EAB308",
            "for_new_patients": True,
            "for_existing_patients": False,
            "requires_accident_date": True,
            "detection_rules": {"is_new": True, "accident_type": "workers_comp"},
            "sort_order": 5,
        },
    ]

    for type_data in types:
        appt_type = AppointmentType(
            practice_id=practice_id,
            name=type_data["name"],
            color=type_data["color"],
            for_new_patients=type_data["for_new_patients"],
            for_existing_patients=type_data["for_existing_patients"],
            requires_accident_date=type_data["requires_accident_date"],
            detection_rules=type_data["detection_rules"],
            sort_order=type_data["sort_order"],
            is_active=True,
        )
        session.add(appt_type)

    await session.flush()
    logger.info("Created %d appointment types.", len(types))


async def _seed_insurance_carriers(session: AsyncSession, practice_id) -> None:
    """Create insurance carriers if they do not exist."""
    result = await session.execute(
        select(InsuranceCarrier).where(InsuranceCarrier.practice_id == practice_id)
    )
    existing = result.scalars().all()
    if existing:
        logger.info("Insurance carriers already exist, skipping.")
        return

    carriers = [
        {
            "name": "MetroPlus",
            "aliases": ["Metro Plus", "Metro", "MetroPlus Health"],
        },
        {
            "name": "Healthfirst",
            "aliases": ["Health First", "HF"],
        },
        {
            "name": "Fidelis Care",
            "aliases": ["Fidelis", "Fidelis NY"],
        },
        {
            "name": "UnitedHealthcare",
            "aliases": ["United", "UHC", "United Health Care", "United Healthcare"],
        },
        {
            "name": "Medicare",
            "aliases": ["Medicare Part A", "Medicare Part B", "CMS"],
        },
    ]

    for carrier_data in carriers:
        carrier = InsuranceCarrier(
            practice_id=practice_id,
            name=carrier_data["name"],
            aliases=carrier_data["aliases"],
            is_active=True,
        )
        session.add(carrier)

    await session.flush()
    logger.info("Created %d insurance carriers.", len(carriers))


async def _seed_holidays(session: AsyncSession) -> None:
    """Create US holidays for 2026 if they do not exist."""
    result = await session.execute(
        select(Holiday).where(Holiday.year == 2026)
    )
    existing = result.scalars().all()
    if existing:
        logger.info("2026 holidays already exist, skipping.")
        return

    holidays = [
        (datetime.date(2026, 1, 1), "New Year's Day"),
        (datetime.date(2026, 1, 19), "Martin Luther King Jr. Day"),
        (datetime.date(2026, 2, 16), "Presidents' Day"),
        (datetime.date(2026, 5, 25), "Memorial Day"),
        (datetime.date(2026, 7, 4), "Independence Day"),
        (datetime.date(2026, 9, 7), "Labor Day"),
        (datetime.date(2026, 11, 26), "Thanksgiving"),
        (datetime.date(2026, 12, 25), "Christmas Day"),
    ]

    for date, name in holidays:
        holiday = Holiday(
            date=date,
            name=name,
            year=2026,
        )
        session.add(holiday)

    await session.flush()
    logger.info("Created %d holidays for 2026.", len(holidays))


if __name__ == "__main__":
    asyncio.run(seed_database())
