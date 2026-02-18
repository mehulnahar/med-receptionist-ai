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


@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "version": "1.0.0"}
