import logging

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run migrations and seed on startup."""
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
    yield


app = FastAPI(
    title="AI Medical Receptionist API",
    version="1.0.0",
    lifespan=lifespan,
)

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


@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "version": "1.0.0"}
