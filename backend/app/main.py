from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings

settings = get_settings()

app = FastAPI(
    title="AI Medical Receptionist API",
    version="1.0.0",
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
