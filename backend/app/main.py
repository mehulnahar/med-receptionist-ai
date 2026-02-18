import logging

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.security import SecurityHeadersMiddleware

settings = get_settings()
logger = logging.getLogger(__name__)


async def _run_startup_migrations():
    """Run lightweight idempotent schema migrations on startup."""
    from app.database import AsyncSessionLocal
    from sqlalchemy import text

    async with AsyncSessionLocal() as session:
        # Add caller_name column to calls table if not exists
        try:
            await session.execute(text(
                "ALTER TABLE calls ADD COLUMN IF NOT EXISTS caller_name VARCHAR(255)"
            ))
            await session.commit()
            logger.info("startup_migrations: caller_name column ensured on calls table")
        except Exception as e:
            await session.rollback()
            logger.warning("startup_migrations: caller_name migration skipped: %s", e)

        # Add callback tracking columns
        try:
            await session.execute(text(
                "ALTER TABLE calls ADD COLUMN IF NOT EXISTS callback_needed BOOLEAN NOT NULL DEFAULT FALSE"
            ))
            await session.execute(text(
                "ALTER TABLE calls ADD COLUMN IF NOT EXISTS callback_completed BOOLEAN NOT NULL DEFAULT FALSE"
            ))
            await session.execute(text(
                "ALTER TABLE calls ADD COLUMN IF NOT EXISTS callback_notes TEXT"
            ))
            await session.execute(text(
                "ALTER TABLE calls ADD COLUMN IF NOT EXISTS callback_completed_at TIMESTAMPTZ"
            ))
            await session.execute(text(
                "ALTER TABLE calls ADD COLUMN IF NOT EXISTS callback_completed_by UUID REFERENCES users(id)"
            ))
            await session.commit()
            logger.info("startup_migrations: callback tracking columns ensured on calls table")
        except Exception as e:
            await session.rollback()
            logger.warning("startup_migrations: callback tracking migration skipped: %s", e)

        # Add structured analysis columns
        try:
            await session.execute(text(
                "ALTER TABLE calls ADD COLUMN IF NOT EXISTS structured_data JSONB"
            ))
            await session.execute(text(
                "ALTER TABLE calls ADD COLUMN IF NOT EXISTS success_evaluation VARCHAR(20)"
            ))
            await session.execute(text(
                "ALTER TABLE calls ADD COLUMN IF NOT EXISTS caller_intent VARCHAR(50)"
            ))
            await session.execute(text(
                "ALTER TABLE calls ADD COLUMN IF NOT EXISTS caller_sentiment VARCHAR(20)"
            ))
            await session.commit()
            logger.info("startup_migrations: structured analysis columns ensured on calls table")
        except Exception as e:
            await session.rollback()
            logger.warning("startup_migrations: structured analysis migration skipped: %s", e)

        # Create feedback loop tables
        try:
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS call_feedback (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    call_id UUID NOT NULL REFERENCES calls(id),
                    practice_id UUID NOT NULL REFERENCES practices(id),
                    overall_score FLOAT,
                    resolution_score FLOAT,
                    efficiency_score FLOAT,
                    empathy_score FLOAT,
                    accuracy_score FLOAT,
                    failure_point VARCHAR(100),
                    failure_reason TEXT,
                    improvement_suggestion TEXT,
                    call_complexity VARCHAR(20),
                    language_detected VARCHAR(10),
                    was_successful BOOLEAN,
                    caller_dropped BOOLEAN DEFAULT FALSE,
                    raw_analysis JSONB,
                    prompt_version INTEGER,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE(call_id)
                )
            """))
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS prompt_versions (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    practice_id UUID NOT NULL REFERENCES practices(id),
                    version INTEGER NOT NULL,
                    prompt_text TEXT NOT NULL,
                    change_reason TEXT,
                    change_diff TEXT,
                    total_calls INTEGER DEFAULT 0,
                    successful_calls INTEGER DEFAULT 0,
                    avg_score FLOAT,
                    avg_duration_seconds FLOAT,
                    booking_rate FLOAT,
                    is_active BOOLEAN DEFAULT FALSE,
                    activated_at TIMESTAMPTZ,
                    deactivated_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """))
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS feedback_insights (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    practice_id UUID NOT NULL REFERENCES practices(id),
                    insight_type VARCHAR(50) NOT NULL,
                    category VARCHAR(50),
                    severity VARCHAR(20),
                    title VARCHAR(255) NOT NULL,
                    description TEXT NOT NULL,
                    suggested_fix TEXT,
                    affected_calls INTEGER DEFAULT 0,
                    sample_call_ids JSONB,
                    status VARCHAR(20) DEFAULT 'open',
                    applied_at TIMESTAMPTZ,
                    applied_to_version INTEGER,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """))
            await session.commit()
            logger.info("startup_migrations: feedback loop tables ensured")
        except Exception as e:
            await session.rollback()
            logger.warning("startup_migrations: feedback tables migration skipped: %s", e)

        # Create refill requests table
        try:
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS refill_requests (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    practice_id UUID NOT NULL REFERENCES practices(id),
                    patient_id UUID REFERENCES patients(id),
                    call_id UUID REFERENCES calls(id),
                    medication_name VARCHAR(255) NOT NULL,
                    dosage VARCHAR(100),
                    pharmacy_name VARCHAR(255),
                    pharmacy_phone VARCHAR(20),
                    prescribing_doctor VARCHAR(255),
                    caller_name VARCHAR(255),
                    caller_phone VARCHAR(20),
                    urgency VARCHAR(20) DEFAULT 'normal',
                    notes TEXT,
                    status VARCHAR(30) DEFAULT 'pending',
                    reviewed_by UUID REFERENCES users(id),
                    reviewed_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """))
            await session.commit()
            logger.info("startup_migrations: refill_requests table ensured")
        except Exception as e:
            await session.rollback()
            logger.warning("startup_migrations: refill_requests table migration skipped: %s", e)

        # Create voicemails table
        try:
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS voicemails (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    practice_id UUID NOT NULL REFERENCES practices(id),
                    call_id UUID REFERENCES calls(id),
                    patient_id UUID REFERENCES patients(id),
                    caller_name VARCHAR(255),
                    caller_phone VARCHAR(20),
                    message TEXT NOT NULL,
                    urgency VARCHAR(20) DEFAULT 'normal',
                    callback_requested BOOLEAN DEFAULT TRUE,
                    preferred_callback_time VARCHAR(100),
                    reason VARCHAR(100),
                    status VARCHAR(20) DEFAULT 'new',
                    responded_by UUID REFERENCES users(id),
                    responded_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """))
            await session.commit()
            logger.info("startup_migrations: voicemails table ensured")
        except Exception as e:
            await session.rollback()
            logger.warning("startup_migrations: voicemails table migration skipped: %s", e)

        # Create appointment_reminders table
        try:
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS appointment_reminders (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    practice_id UUID NOT NULL REFERENCES practices(id),
                    appointment_id UUID NOT NULL REFERENCES appointments(id),
                    patient_id UUID NOT NULL REFERENCES patients(id),
                    reminder_type VARCHAR(20) NOT NULL DEFAULT 'sms',
                    scheduled_for TIMESTAMPTZ NOT NULL,
                    sent_at TIMESTAMPTZ,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    message_content TEXT,
                    response TEXT,
                    message_sid VARCHAR(100),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """))
            await session.commit()
            logger.info("startup_migrations: appointment_reminders table ensured")
        except Exception as e:
            await session.rollback()
            logger.warning("startup_migrations: appointment_reminders table migration skipped: %s", e)

        # Create waitlist_entries table
        try:
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS waitlist_entries (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    practice_id UUID NOT NULL REFERENCES practices(id),
                    patient_id UUID REFERENCES patients(id),
                    patient_name VARCHAR(255) NOT NULL,
                    patient_phone VARCHAR(20) NOT NULL,
                    appointment_type_id UUID REFERENCES appointment_types(id),
                    preferred_date_start DATE,
                    preferred_date_end DATE,
                    preferred_time_start TIME,
                    preferred_time_end TIME,
                    notes TEXT,
                    priority INTEGER NOT NULL DEFAULT 3,
                    status VARCHAR(20) NOT NULL DEFAULT 'waiting',
                    notified_at TIMESTAMPTZ,
                    expires_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """))
            await session.commit()
            logger.info("startup_migrations: waitlist_entries table ensured")
        except Exception as e:
            await session.rollback()
            logger.warning("startup_migrations: waitlist_entries table migration skipped: %s", e)


async def _reminder_check_loop():
    """Background loop that processes pending appointment reminders every 60 seconds."""
    import asyncio
    from app.database import AsyncSessionLocal
    from app.services.reminder_service import process_pending_reminders

    logger.info("reminder_check_loop: started")

    while True:
        try:
            await asyncio.sleep(60)
            async with AsyncSessionLocal() as db:
                sent = await process_pending_reminders(db)
                await db.commit()
                if sent > 0:
                    logger.info("reminder_check_loop: sent %d reminders", sent)
        except Exception as e:
            logger.warning("reminder_check_loop: error in cycle: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run migrations, seed, and start background tasks on startup."""
    import asyncio

    # Run lightweight schema migrations
    try:
        await _run_startup_migrations()
    except Exception as exc:
        logger.warning("Startup migrations skipped: %s", exc)

    # Run seed (idempotent)
    try:
        from app.seed import seed_database
        await seed_database()
    except Exception as exc:
        logger.warning("Seed skipped or failed: %s", exc)

    # Start background reminder scheduler
    reminder_task = asyncio.create_task(_reminder_check_loop())

    yield

    # Cleanup: cancel the background task on shutdown
    reminder_task.cancel()
    try:
        await reminder_task
    except asyncio.CancelledError:
        logger.info("reminder_check_loop: stopped")


app = FastAPI(
    title="AI Medical Receptionist API",
    version="1.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Middleware stack (last added = outermost = processes requests first)
# Request flow: CORS -> RateLimit -> Security -> Routes
# ---------------------------------------------------------------------------
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.CORS_ORIGINS.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Route blueprints
# ---------------------------------------------------------------------------
from app.routes.auth import router as auth_router
from app.routes.admin import router as admin_router
from app.routes.practice import router as practice_router
from app.routes.config import router as config_router
from app.routes.schedule import router as schedule_router
from app.routes.appointment_types import router as appt_types_router
from app.routes.insurance_carriers import router as insurance_router
from app.routes.patients import router as patients_router
from app.routes.appointments import router as appointments_router
from app.routes.webhooks import router as webhook_router
from app.routes.insurance_verification import router as insurance_verify_router
from app.routes.sms import router as sms_router
from app.routes.feedback import router as feedback_router
from app.routes.refills import router as refills_router
from app.routes.voicemails import router as voicemails_router
from app.routes.reminders import router as reminders_router
from app.routes.waitlist import router as waitlist_router
from app.routes.analytics import router as analytics_router

app.include_router(auth_router, prefix="/api/auth", tags=["Auth"])
app.include_router(admin_router, prefix="/api/admin", tags=["Admin"])
app.include_router(practice_router, prefix="/api/practice", tags=["Practice"])
app.include_router(config_router, prefix="/api/practice/config", tags=["Practice Config"])
app.include_router(schedule_router, prefix="/api/practice/schedule", tags=["Schedule"])
app.include_router(appt_types_router, prefix="/api/practice/appointment-types", tags=["Appointment Types"])
app.include_router(insurance_router, prefix="/api/practice/insurance-carriers", tags=["Insurance Carriers"])
app.include_router(patients_router, prefix="/api/patients", tags=["Patients"])
app.include_router(appointments_router, prefix="/api/appointments", tags=["Appointments"])
app.include_router(webhook_router, prefix="/api/webhooks", tags=["Webhooks"])
app.include_router(insurance_verify_router, prefix="/api/insurance", tags=["Insurance Verification"])
app.include_router(sms_router, prefix="/api/sms", tags=["SMS Notifications"])
app.include_router(feedback_router, prefix="/api/feedback", tags=["Feedback Loop"])
app.include_router(refills_router, prefix="/api/refills", tags=["Prescription Refills"])
app.include_router(voicemails_router, prefix="/api/voicemails", tags=["Voicemails"])
app.include_router(reminders_router, prefix="/api/reminders", tags=["Appointment Reminders"])
app.include_router(waitlist_router, prefix="/api/waitlist", tags=["Waitlist"])
app.include_router(analytics_router, prefix="/api/analytics", tags=["Analytics"])


@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "version": "1.0.0"}
