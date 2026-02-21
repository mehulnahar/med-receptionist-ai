import contextvars
import logging
import time
import traceback
import uuid

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.security import SecurityHeadersMiddleware

settings = get_settings()
logger = logging.getLogger(__name__)

_is_production = settings.APP_ENV == "production"

# ---------------------------------------------------------------------------
# Request ID context — propagated into every log record automatically
# ---------------------------------------------------------------------------
request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class _RequestIdFilter(logging.Filter):
    """Inject the current request ID into every log record."""
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get("-")
        return True


# Attach the filter to the root logger so ALL loggers inherit it
logging.getLogger().addFilter(_RequestIdFilter())

# Background task health tracking — updated by each loop iteration
_background_health: dict[str, float] = {}


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

        # Add password_change_required column to users table
        try:
            await session.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_change_required BOOLEAN NOT NULL DEFAULT FALSE"
            ))
            await session.commit()
            logger.info("startup_migrations: password_change_required column ensured on users table")
        except Exception as e:
            await session.rollback()
            logger.warning("startup_migrations: password_change_required migration skipped: %s", e)

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
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
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

        # Unique constraint to prevent duplicate reminders (race condition guard)
        try:
            await session.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_reminders_appt_schedule "
                "ON appointment_reminders(appointment_id, scheduled_for) "
                "WHERE status IN ('pending', 'sent')"
            ))
            await session.commit()
            logger.info("startup_migrations: reminder unique constraint ensured")
        except Exception as e:
            await session.rollback()
            logger.warning("startup_migrations: reminder unique constraint skipped: %s", e)

        # Create training_sessions and training_recordings tables
        try:
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS training_sessions (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    practice_id UUID NOT NULL REFERENCES practices(id) ON DELETE CASCADE,
                    name VARCHAR(200),
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    total_recordings INTEGER NOT NULL DEFAULT 0,
                    processed_count INTEGER NOT NULL DEFAULT 0,
                    aggregated_insights JSONB,
                    generated_prompt TEXT,
                    current_prompt_snapshot TEXT,
                    created_by UUID REFERENCES users(id),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    completed_at TIMESTAMPTZ
                )
            """))
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS training_recordings (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    practice_id UUID NOT NULL REFERENCES practices(id) ON DELETE CASCADE,
                    session_id UUID NOT NULL REFERENCES training_sessions(id) ON DELETE CASCADE,
                    original_filename VARCHAR(255) NOT NULL,
                    file_size_bytes INTEGER,
                    mime_type VARCHAR(50),
                    status VARCHAR(20) NOT NULL DEFAULT 'uploaded',
                    transcript TEXT,
                    language_detected VARCHAR(10),
                    duration_seconds FLOAT,
                    analysis JSONB,
                    error_message TEXT,
                    uploaded_by UUID REFERENCES users(id),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """))
            await session.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_training_sessions_practice ON training_sessions(practice_id)"
            ))
            await session.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_training_recordings_session ON training_recordings(session_id)"
            ))
            await session.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_training_recordings_practice ON training_recordings(practice_id)"
            ))
            await session.commit()
            logger.info("startup_migrations: training tables ensured")
        except Exception as e:
            await session.rollback()
            logger.warning("startup_migrations: training tables migration skipped: %s", e)

        # Drop overly-strict unique patient index (replaced with non-unique)
        try:
            await session.execute(text(
                "DROP INDEX IF EXISTS uq_patients_practice_name_dob"
            ))
            await session.commit()
            logger.info("startup_migrations: dropped unique patient name index (replaced with non-unique)")
        except Exception as e:
            await session.rollback()
            logger.warning("startup_migrations: patient index cleanup skipped: %s", e)

        # Assign admin user to Stefanides practice if not already assigned
        try:
            result = await session.execute(text("""
                UPDATE users SET practice_id = (
                    SELECT id FROM practices LIMIT 1
                )
                WHERE email = 'admin@mindcrew.tech'
                AND practice_id IS NULL
            """))
            if result.rowcount > 0:
                await session.commit()
                logger.info("startup_migrations: assigned admin user to practice")
            else:
                await session.rollback()
        except Exception as e:
            await session.rollback()
            logger.warning("startup_migrations: admin practice assignment skipped: %s", e)

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
    """Background loop that processes pending appointment reminders every 60 seconds.

    Uses a PostgreSQL advisory lock (pg_try_advisory_lock) so that when
    multiple Uvicorn workers run this loop, only ONE worker processes
    reminders at a time — preventing duplicate SMS sends.
    """
    import asyncio
    from sqlalchemy import text
    from app.database import AsyncSessionLocal
    from app.services.reminder_service import process_pending_reminders

    ADVISORY_LOCK_ID = 123456789  # Arbitrary unique ID for this lock

    logger.info("reminder_check_loop: started")

    consecutive_errors = 0

    while True:
        try:
            await asyncio.sleep(60)
            async with AsyncSessionLocal() as db:
                # Try to acquire advisory lock (non-blocking). Only one worker wins.
                lock_result = await db.execute(
                    text(f"SELECT pg_try_advisory_lock({ADVISORY_LOCK_ID})")
                )
                acquired = lock_result.scalar_one()

                if not acquired:
                    # Another worker already holds the lock — skip this cycle
                    continue

                try:
                    sent = await process_pending_reminders(db)
                    # Each reminder is committed individually inside process_pending_reminders
                    # to prevent batch rollback causing duplicate SMS sends.
                    if sent > 0:
                        logger.info("reminder_check_loop: sent %d reminders", sent)
                finally:
                    # Always release the lock when done
                    await db.execute(
                        text(f"SELECT pg_advisory_unlock({ADVISORY_LOCK_ID})")
                    )
                    await db.commit()

            consecutive_errors = 0  # Reset on success
            _background_health["reminder_loop_last_ok"] = time.time()

        except Exception as e:
            consecutive_errors += 1
            logger.warning(
                "reminder_check_loop: error in cycle (%d consecutive): %s",
                consecutive_errors, e,
            )
            # On persistent DB connection failures, dispose the engine pool
            # so the next cycle gets fresh connections
            if consecutive_errors >= 3:
                try:
                    from app.database import engine
                    await engine.dispose()
                    logger.info("reminder_check_loop: disposed connection pool after %d consecutive errors", consecutive_errors)
                except Exception:
                    pass
                # Back off longer when DB is down to avoid log spam
                await asyncio.sleep(30)


async def _batch_eligibility_loop():
    """Nightly loop: pre-verify insurance for next-day appointments.

    Runs once per day at ~2 AM UTC. Uses advisory lock to prevent
    duplicate runs across multiple workers.
    """
    import asyncio
    from datetime import datetime, timezone

    ADVISORY_LOCK_ID = 987654321
    logger.info("batch_eligibility_loop: started")

    while True:
        try:
            # Sleep until ~2 AM UTC
            now = datetime.now(timezone.utc)
            next_run = now.replace(hour=2, minute=0, second=0, microsecond=0)
            if now >= next_run:
                from datetime import timedelta
                next_run += timedelta(days=1)
            sleep_seconds = (next_run - now).total_seconds()
            logger.info("batch_eligibility_loop: next run in %.0f seconds", sleep_seconds)
            await asyncio.sleep(sleep_seconds)

            from app.database import AsyncSessionLocal
            from sqlalchemy import text as sa_text
            async with AsyncSessionLocal() as db:
                lock_result = await db.execute(
                    sa_text(f"SELECT pg_try_advisory_lock({ADVISORY_LOCK_ID})")
                )
                acquired = lock_result.scalar_one()
                if not acquired:
                    continue

                try:
                    from app.commercial.batch_eligibility import run_batch_eligibility_check
                    results = await run_batch_eligibility_check()
                    logger.info("batch_eligibility_loop: completed — %s", results)
                    _background_health["batch_eligibility_last_ok"] = time.time()
                finally:
                    await db.execute(
                        sa_text(f"SELECT pg_advisory_unlock({ADVISORY_LOCK_ID})")
                    )
                    await db.commit()

        except Exception as e:
            logger.warning("batch_eligibility_loop: error: %s", e)
            await asyncio.sleep(300)  # Retry in 5 min on error


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run migrations, seed, and start background tasks on startup."""
    import asyncio

    # Run lightweight schema migrations
    try:
        await _run_startup_migrations()
    except Exception as exc:
        logger.warning("Startup migrations skipped: %s", exc)

    # Run HIPAA compliance migrations (audit tables, password history, etc.)
    try:
        from app.hipaa.startup_migrations import run_hipaa_migrations
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            await run_hipaa_migrations(session)
    except Exception as exc:
        logger.warning("HIPAA migrations skipped: %s", exc)

    # Run Phase 5 & 6 migrations (surveys, locations, billing, portal, etc.)
    try:
        from app.scale.startup_migrations import run_phase5_6_migrations
        async with AsyncSessionLocal() as session:
            await run_phase5_6_migrations(session)
    except Exception as exc:
        logger.warning("Phase 5/6 migrations skipped: %s", exc)

    # Run seed (idempotent)
    try:
        from app.seed import seed_database
        await seed_database()
    except Exception as exc:
        logger.warning("Seed skipped or failed: %s", exc)

    # Start background reminder scheduler
    reminder_task = asyncio.create_task(_reminder_check_loop())

    # Start nightly batch eligibility check loop
    batch_eligibility_task = asyncio.create_task(_batch_eligibility_loop())

    # Start waitlist notification expiry loop
    from app.scale.waitlist_notifier import waitlist_notification_loop
    waitlist_task = asyncio.create_task(waitlist_notification_loop())

    logger.info("Application startup complete")
    yield

    # --- Graceful shutdown ---
    logger.info("Shutting down — cancelling background tasks...")

    # 1. Cancel the background tasks
    reminder_task.cancel()
    batch_eligibility_task.cancel()
    waitlist_task.cancel()
    try:
        await reminder_task
    except asyncio.CancelledError:
        logger.info("reminder_check_loop: stopped")
    try:
        await batch_eligibility_task
    except asyncio.CancelledError:
        logger.info("batch_eligibility_loop: stopped")
    try:
        await waitlist_task
    except asyncio.CancelledError:
        logger.info("waitlist_notification_loop: stopped")

    # 2. Dispose the database engine to close all pooled connections
    try:
        from app.database import engine
        await engine.dispose()
        logger.info("Database connection pool disposed")
    except Exception as exc:
        logger.warning("Error disposing database engine: %s", exc)

    # 3. Close shared HTTP client
    try:
        from app.utils.http_client import close_http_client
        await close_http_client()
        logger.info("Shared HTTP client closed")
    except Exception as exc:
        logger.warning("Error closing HTTP client: %s", exc)

    # 4. Clear in-memory caches
    try:
        from app.utils.cache import practice_config_cache
        practice_config_cache.clear()
    except Exception:
        pass

    logger.info("Shutdown complete")


app = FastAPI(
    title="AI Medical Receptionist API",
    version="1.1.0",
    lifespan=lifespan,
    # Disable interactive API docs in production — exposes full schema to attackers
    docs_url=None if _is_production else "/docs",
    redoc_url=None if _is_production else "/redoc",
    openapi_url=None if _is_production else "/openapi.json",
)


# ---------------------------------------------------------------------------
# Global exception handler — catch unhandled errors, log them, return 500
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception):
    logger.error(
        "Unhandled exception on %s %s: %s\n%s",
        request.method,
        request.url.path,
        exc,
        traceback.format_exc(),
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )

# ---------------------------------------------------------------------------
# Middleware stack (last added = outermost = processes requests first)
# Request flow: CORS -> RateLimit -> Security -> Routes
# ---------------------------------------------------------------------------
# HIPAA PHI Read Audit Middleware — logs all GET requests to PHI endpoints
try:
    from app.hipaa.audit_read_log import PHIReadAuditMiddleware
    app.add_middleware(PHIReadAuditMiddleware)
except Exception as e:
    logger.warning("PHI audit middleware not loaded: %s", e)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.CORS_ORIGINS.split(",")],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Requested-With", "X-Idempotency-Key"],
)

# ---------------------------------------------------------------------------
# Request body size limit (5 MB default for non-webhook routes)
# Webhooks have their own 1 MB limit in the handler.
# ---------------------------------------------------------------------------
MAX_BODY_BYTES = 5 * 1024 * 1024  # 5 MB

@app.middleware("http")
async def _limit_request_body(request: Request, call_next):
    """Reject oversized request bodies to prevent OOM from malicious payloads.

    Checks both the Content-Length header (fast path) and, for chunked
    transfers that omit Content-Length, reads the body and checks actual
    size.  GET/HEAD/OPTIONS/DELETE requests are skipped since they
    typically carry no body.
    """
    # Skip methods that shouldn't carry a body
    if request.method in ("GET", "HEAD", "OPTIONS", "DELETE"):
        return await call_next(request)

    # Allow larger uploads for training recordings (30 MB)
    path = request.url.path
    if "/training/" in path and path.endswith("/upload"):
        limit = 30 * 1024 * 1024  # 30 MB for audio uploads
    else:
        limit = MAX_BODY_BYTES

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > limit:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Request body too large"},
                )
        except (ValueError, TypeError):
            return JSONResponse(
                status_code=400,
                content={"detail": "Invalid Content-Length header"},
            )
    else:
        # No Content-Length — likely chunked transfer encoding.
        # Read the actual body to enforce the limit.
        body = await request.body()
        if len(body) > limit:
            return JSONResponse(
                status_code=413,
                content={"detail": "Request body too large"},
            )

    return await call_next(request)

# ---------------------------------------------------------------------------
# Request ID correlation — attach a unique ID to every request/response for
# log tracing and incident debugging.
# ---------------------------------------------------------------------------
@app.middleware("http")
async def _request_id(request: Request, call_next):
    """Attach a unique X-Request-ID to every response for distributed tracing.

    Also sets the request_id contextvar so all log records within this
    request automatically include the ID (via _RequestIdFilter).
    """
    rid = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = rid
    token = request_id_ctx.set(rid)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response
    finally:
        request_id_ctx.reset(token)

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
from app.routes.training import router as training_router
from app.routes.onboarding import router as onboarding_router
from app.routes.hipaa import router as hipaa_router
from app.routes.roi import router as roi_router
from app.routes.ehr import router as ehr_router
from app.voice.twilio_relay import router as voice_router

# Phase 5: Scale & Intelligence
from app.scale.monitoring_routes import router as monitoring_router
from app.scale.survey_routes import router as survey_router

# Phase 6: Enterprise Features
from app.enterprise.multi_location_routes import router as location_router
from app.enterprise.billing_routes import router as billing_router
from app.enterprise.payment_routes import router as payment_router
from app.enterprise.patient_portal_routes import router as portal_router
from app.enterprise.recall_routes import router as recall_router
from app.enterprise.self_service_routes import router as signup_router

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
app.include_router(training_router, prefix="/api/training", tags=["Training Pipeline"])
app.include_router(onboarding_router, prefix="/api/practice/onboarding", tags=["Onboarding"])
app.include_router(hipaa_router, prefix="/api", tags=["HIPAA Compliance"])
app.include_router(roi_router, prefix="/api", tags=["ROI Dashboard"])
app.include_router(ehr_router, prefix="/api", tags=["EHR Integration"])
app.include_router(voice_router, prefix="/api/voice", tags=["Voice Stack"])

# Phase 5: Scale & Intelligence
app.include_router(monitoring_router, prefix="/api", tags=["Monitoring"])
app.include_router(survey_router, prefix="/api", tags=["Surveys"])

# Phase 6: Enterprise Features
app.include_router(location_router, prefix="/api", tags=["Multi-Location"])
app.include_router(billing_router, prefix="/api", tags=["Billing"])
app.include_router(payment_router, prefix="/api", tags=["Payments"])
app.include_router(portal_router, prefix="/api", tags=["Patient Portal"])
app.include_router(recall_router, prefix="/api", tags=["Recall Campaigns"])
app.include_router(signup_router, prefix="/api", tags=["Self-Service Onboarding"])


@app.post("/api/client-errors", status_code=204)
async def report_client_error(request: Request):
    """Accept frontend error reports (e.g. unhandled JS exceptions).

    Body (JSON): { "message": str, "stack": str?, "url": str?, "userAgent": str? }
    No auth required — the endpoint is intentionally open so error reports
    always reach the server, but it rate-limits and caps body size.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"detail": "Invalid JSON"})

    # Cap individual fields to prevent log injection / abuse
    message = str(body.get("message", ""))[:500]
    stack = str(body.get("stack", ""))[:2000]
    url = str(body.get("url", ""))[:500]

    logger.warning(
        "client_error: %s | url=%s | stack=%s",
        message,
        url,
        stack[:200],  # abbreviated in log line
    )
    return JSONResponse(status_code=204, content=None)


@app.get("/api/health")
async def health_check():
    """Health check endpoint that verifies DB connectivity.

    Returns HTTP 503 when the database is unreachable so that load balancers
    stop routing traffic to this instance.
    """
    from app.database import AsyncSessionLocal
    from sqlalchemy import text

    db_ok = False
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
            db_ok = True
    except Exception as e:
        logger.warning("health_check: database connection failed: %s", e)

    if not db_ok:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "version": "1.1.0", "database": "unavailable"},
        )

    # Check background task health — flag stale if no heartbeat in 5 minutes
    reminder_last_ok = _background_health.get("reminder_loop_last_ok")
    reminder_status = "unknown"
    if reminder_last_ok:
        age = time.time() - reminder_last_ok
        reminder_status = "ok" if age < 300 else f"stale ({int(age)}s ago)"

    batch_last_ok = _background_health.get("batch_eligibility_last_ok")
    batch_status = "unknown"
    if batch_last_ok:
        age = time.time() - batch_last_ok
        batch_status = "ok" if age < 90000 else f"stale ({int(age)}s ago)"

    return {
        "status": "healthy",
        "version": "1.2.0",
        "database": "connected",
        "background_tasks": {
            "reminder_loop": reminder_status,
            "batch_eligibility": batch_status,
            "waitlist_notifier": "active",
        },
    }
