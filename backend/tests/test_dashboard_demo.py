"""
Tests for Dashboard & Demo Readiness (Phase 8: DASH-01 through DASH-10).

Integration-style tests using the ASGI TestClient against live FastAPI routes
with dependency overrides for authentication and database. Verifies all 12
frontend pages have working backend API endpoints, auth gates return 401,
empty data returns empty lists (not errors), and status changes work.

Covers:
  DASH-01: Dashboard appointments endpoint (today's appointments, 30s polling)
  DASH-02: Appointment status change (booked -> confirmed -> entered_in_ehr)
  DASH-03: Call log with recording, transcript, summary fields
  DASH-04: Analytics overview with chart-compatible data
  DASH-05: Settings/config with integration fields (Vapi, Twilio, Stedi)
  DASH-06: Admin panel CRUD (list/create practices, list/create users)
  DASH-07: Patient search by name, phone, DOB
  DASH-08: All key API endpoints respond 200 (page load positive)
  DASH-09: Unauthenticated requests return 401
  DASH-10: Empty data edge cases (empty lists, not errors)
"""

import uuid
from datetime import date, time, datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PRACTICE_ID = uuid.uuid4()
PATIENT_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
APPOINTMENT_ID = uuid.uuid4()
APPOINTMENT_TYPE_ID = uuid.uuid4()
CALL_ID = uuid.uuid4()


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _mock_user(role="secretary", practice_id=PRACTICE_ID, **overrides):
    """Create a mock User object for auth dependency injection."""
    user = MagicMock()
    user.id = overrides.get("id", USER_ID)
    user.email = overrides.get("email", "test@example.com")
    user.name = overrides.get("name", "Test User")
    user.role = role
    user.practice_id = practice_id
    user.is_active = True
    user.password_change_required = False
    return user


def _mock_appointment(**overrides):
    """Create a mock Appointment ORM object with relationships."""
    appt = MagicMock()
    appt.id = overrides.get("id", APPOINTMENT_ID)
    appt.practice_id = overrides.get("practice_id", PRACTICE_ID)
    appt.patient_id = overrides.get("patient_id", PATIENT_ID)
    appt.appointment_type_id = overrides.get("appointment_type_id", APPOINTMENT_TYPE_ID)
    appt.date = overrides.get("date", date(2026, 6, 15))
    appt.time = overrides.get("time", time(10, 0))
    appt.duration_minutes = overrides.get("duration_minutes", 30)
    appt.status = overrides.get("status", "booked")
    appt.insurance_verified = overrides.get("insurance_verified", False)
    appt.insurance_verification_result = overrides.get("insurance_verification_result", None)
    appt.booked_by = overrides.get("booked_by", "ai")
    appt.call_id = overrides.get("call_id", None)
    appt.notes = overrides.get("notes", None)
    appt.sms_confirmation_sent = overrides.get("sms_confirmation_sent", False)
    appt.entered_in_ehr_at = overrides.get("entered_in_ehr_at", None)
    appt.entered_in_ehr_by = overrides.get("entered_in_ehr_by", None)
    appt.created_at = overrides.get("created_at", datetime.now(timezone.utc))
    appt.updated_at = overrides.get("updated_at", datetime.now(timezone.utc))

    # Relationships
    patient = MagicMock()
    patient.first_name = overrides.get("patient_first", "John")
    patient.last_name = overrides.get("patient_last", "Doe")
    appt.patient = patient

    appt_type = MagicMock()
    appt_type.name = overrides.get("type_name", "General Consultation")
    appt.appointment_type = appt_type

    return appt


def _mock_call(**overrides):
    """Create a mock Call ORM object."""
    call = MagicMock()
    call.id = overrides.get("id", CALL_ID)
    call.vapi_call_id = overrides.get("vapi_call_id", "call_test_001")
    call.practice_id = overrides.get("practice_id", PRACTICE_ID)
    call.direction = overrides.get("direction", "inbound")
    call.caller_phone = overrides.get("caller_phone", "+12125551234")
    call.caller_name = overrides.get("caller_name", "Test Caller")
    call.status = overrides.get("status", "ended")
    call.duration_seconds = overrides.get("duration_seconds", 120)
    call.patient_id = overrides.get("patient_id", None)
    call.started_at = overrides.get("started_at", datetime.now(timezone.utc))
    call.ended_at = overrides.get("ended_at", datetime.now(timezone.utc))
    call.transcription = overrides.get("transcription", "Hello, I need an appointment.")
    call.ai_summary = overrides.get("ai_summary", "Patient requested appointment.")
    call.vapi_cost = overrides.get("vapi_cost", Decimal("0.15"))
    call.recording_url = overrides.get("recording_url", "https://example.com/recording.mp3")
    call.outcome = overrides.get("outcome", "customer-ended-call")
    call.created_at = overrides.get("created_at", datetime.now(timezone.utc))
    call.callback_needed = overrides.get("callback_needed", False)
    call.callback_completed = overrides.get("callback_completed", False)
    call.callback_notes = overrides.get("callback_notes", None)
    call.callback_completed_at = overrides.get("callback_completed_at", None)
    call.structured_data = overrides.get("structured_data", None)
    call.caller_intent = overrides.get("caller_intent", "book")
    call.caller_sentiment = overrides.get("caller_sentiment", "positive")
    call.success_evaluation = overrides.get("success_evaluation", None)
    call.language = overrides.get("language", "en")
    return call


def _mock_practice(**overrides):
    """Create a mock Practice ORM object."""
    practice = MagicMock()
    practice.id = overrides.get("id", PRACTICE_ID)
    practice.name = overrides.get("name", "Test Practice")
    practice.slug = overrides.get("slug", "test-practice")
    practice.npi = overrides.get("npi", "1234567890")
    practice.tax_id = overrides.get("tax_id", "123456789")
    practice.phone = overrides.get("phone", "+12125551234")
    practice.address = overrides.get("address", "123 Test St")
    practice.timezone = overrides.get("timezone", "America/New_York")
    practice.status = overrides.get("status", "active")
    practice.created_at = overrides.get("created_at", datetime.now(timezone.utc))
    practice.updated_at = overrides.get("updated_at", datetime.now(timezone.utc))
    return practice


def _mock_practice_config(**overrides):
    """Create a mock PracticeConfig ORM object."""
    cfg = MagicMock()
    cfg.id = overrides.get("id", uuid.uuid4())
    cfg.practice_id = overrides.get("practice_id", PRACTICE_ID)
    cfg.twilio_phone_number = overrides.get("twilio_phone_number", "+12678052214")
    cfg.twilio_account_sid = overrides.get("twilio_account_sid", "AC1234567890")
    cfg.twilio_auth_token = overrides.get("twilio_auth_token", "token123")
    cfg.vonage_forwarding_enabled = overrides.get("vonage_forwarding_enabled", False)
    cfg.vonage_forwarding_number = overrides.get("vonage_forwarding_number", None)
    cfg.vapi_api_key = overrides.get("vapi_api_key", "vapi-key-123")
    cfg.vapi_agent_id = overrides.get("vapi_agent_id", None)
    cfg.vapi_assistant_id = overrides.get("vapi_assistant_id", "asst-123")
    cfg.vapi_phone_number_id = overrides.get("vapi_phone_number_id", "pn-123")
    cfg.vapi_system_prompt = overrides.get("vapi_system_prompt", "You are a medical receptionist.")
    cfg.vapi_first_message = overrides.get("vapi_first_message", "Hello!")
    cfg.vapi_model_provider = overrides.get("vapi_model_provider", "openai")
    cfg.vapi_model_name = overrides.get("vapi_model_name", "gpt-4o-mini")
    cfg.vapi_voice_provider = overrides.get("vapi_voice_provider", "11labs")
    cfg.vapi_voice_id = overrides.get("vapi_voice_id", "voice-123")
    cfg.stedi_api_key = overrides.get("stedi_api_key", None)
    cfg.stedi_enabled = overrides.get("stedi_enabled", False)
    cfg.insurance_verification_on_call = overrides.get("insurance_verification_on_call", True)
    cfg.languages = overrides.get("languages", ["en", "es"])
    cfg.primary_language = overrides.get("primary_language", "en")
    cfg.greek_transfer_to_staff = overrides.get("greek_transfer_to_staff", True)
    cfg.alternate_fridays_enabled = overrides.get("alternate_fridays_enabled", False)
    cfg.alternate_friday_reference_date = overrides.get("alternate_friday_reference_date", None)
    cfg.slot_duration_minutes = overrides.get("slot_duration_minutes", 15)
    cfg.allow_overbooking = overrides.get("allow_overbooking", False)
    cfg.max_overbooking_per_slot = overrides.get("max_overbooking_per_slot", 2)
    cfg.booking_horizon_days = overrides.get("booking_horizon_days", 90)
    cfg.greetings = overrides.get("greetings", {})
    cfg.transfer_number = overrides.get("transfer_number", "+16612288584")
    cfg.emergency_message = overrides.get("emergency_message", None)
    cfg.transfer_message = overrides.get("transfer_message", "Transferring you now.")
    cfg.fallback_phone_number = overrides.get("fallback_phone_number", "+12125559999")
    cfg.reminder_template_24h = overrides.get("reminder_template_24h", {})
    cfg.reminder_template_2h = overrides.get("reminder_template_2h", {})
    cfg.sms_confirmation_enabled = overrides.get("sms_confirmation_enabled", True)
    cfg.sms_confirmation_template = overrides.get("sms_confirmation_template", {})
    cfg.new_patient_fields = overrides.get("new_patient_fields", None)
    cfg.existing_patient_fields = overrides.get("existing_patient_fields", None)
    cfg.system_prompt = overrides.get("system_prompt", None)
    cfg.fallback_message = overrides.get("fallback_message", None)
    cfg.max_retries = overrides.get("max_retries", 3)
    cfg.created_at = overrides.get("created_at", datetime.now(timezone.utc))
    cfg.updated_at = overrides.get("updated_at", datetime.now(timezone.utc))
    # model_validate accesses this field via from_attributes -- must be None, not MagicMock
    cfg.vapi_sync_status = overrides.get("vapi_sync_status", None)
    return cfg


def _mock_patient(**overrides):
    """Create a mock Patient ORM object."""
    patient = MagicMock()
    patient.id = overrides.get("id", PATIENT_ID)
    patient.practice_id = overrides.get("practice_id", PRACTICE_ID)
    patient.first_name = overrides.get("first_name", "John")
    patient.last_name = overrides.get("last_name", "Doe")
    patient.dob = overrides.get("dob", date(1990, 1, 15))
    patient.phone = overrides.get("phone", "+12125551234")
    patient.language_preference = overrides.get("language_preference", "en")
    patient.is_new = overrides.get("is_new", True)
    patient.address = overrides.get("address", None)
    patient.insurance_carrier = overrides.get("insurance_carrier", None)
    patient.member_id = overrides.get("member_id", None)
    patient.group_number = overrides.get("group_number", None)
    patient.referring_physician = overrides.get("referring_physician", None)
    patient.accident_date = overrides.get("accident_date", None)
    patient.accident_type = overrides.get("accident_type", None)
    patient.notes = overrides.get("notes", None)
    patient.created_at = overrides.get("created_at", datetime.now(timezone.utc))
    patient.updated_at = overrides.get("updated_at", datetime.now(timezone.utc))
    return patient


# ---------------------------------------------------------------------------
# Fixtures with FastAPI dependency overrides
# ---------------------------------------------------------------------------

def _make_mock_db():
    """Create a fresh AsyncMock db session."""
    return AsyncMock()


def _clear_rate_limit_state(app):
    """Clear rate limiter request tracking to prevent 429 in test suites.

    Walks the Starlette middleware stack to find the RateLimitMiddleware
    instance and clears its in-memory request counter.
    """
    # Build middleware stack if not yet built (needed for first access)
    try:
        stack = app.middleware_stack
    except Exception:
        return
    if stack is None:
        return

    # Walk the ASGI app chain to find RateLimitMiddleware
    current = stack
    for _ in range(20):  # max depth safeguard
        if hasattr(current, "_requests"):
            current._requests.clear()
            return
        current = getattr(current, "app", None)
        if current is None:
            break




@pytest_asyncio.fixture
async def staff_client():
    """ASGI test client authenticated as secretary via dependency overrides."""
    from app.main import app
    from app.database import get_db
    from app.middleware.auth import get_current_user

    # Save existing overrides and restore after test
    saved = dict(app.dependency_overrides)

    mock_user = _mock_user(role="secretary")
    mock_db = _make_mock_db()

    async def override_get_current_user():
        return mock_user

    async def override_get_db():
        return mock_db

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_db] = override_get_db

    # Clear rate limit counters to prevent 429 in full suite runs
    _clear_rate_limit_state(app)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        ac.headers["Authorization"] = "Bearer fake-token"
        # Attach mock_db so tests can configure it
        ac._mock_db = mock_db
        ac._mock_user = mock_user
        yield ac

    app.dependency_overrides.clear()
    app.dependency_overrides.update(saved)


@pytest_asyncio.fixture
async def admin_client():
    """ASGI test client authenticated as super_admin via dependency overrides."""
    from app.main import app
    from app.database import get_db
    from app.middleware.auth import get_current_user

    saved = dict(app.dependency_overrides)

    mock_user = _mock_user(role="super_admin")
    mock_db = _make_mock_db()

    async def override_get_current_user():
        return mock_user

    async def override_get_db():
        return mock_db

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_db] = override_get_db

    # Clear rate limit counters to prevent 429 in full suite runs
    _clear_rate_limit_state(app)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        ac.headers["Authorization"] = "Bearer fake-admin-token"
        ac._mock_db = mock_db
        ac._mock_user = mock_user
        yield ac

    app.dependency_overrides.clear()
    app.dependency_overrides.update(saved)


@pytest_asyncio.fixture
async def unauth_client():
    """ASGI test client with NO auth and NO dependency overrides."""
    from app.main import app

    # Save and clear overrides for this test
    saved = dict(app.dependency_overrides)
    app.dependency_overrides.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    app.dependency_overrides.clear()
    app.dependency_overrides.update(saved)


# ===========================================================================
# Class 1: TestDashboardAppointments (DASH-01, DASH-02)
# ===========================================================================

class TestDashboardAppointments:
    """DASH-01/02: Dashboard appointments endpoint and status change buttons."""

    @pytest.mark.asyncio
    async def test_get_today_appointments(self, staff_client):
        """DASH-01: GET /appointments/ with date filters returns 200 with list."""
        appt = _mock_appointment()

        with patch("app.routes.appointments.get_appointments", new_callable=AsyncMock) as mock_fn:
            mock_fn.return_value = ([appt], 1)

            today = date.today().isoformat()
            resp = await staff_client.get(
                f"/api/appointments/?from_date={today}&to_date={today}"
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "appointments" in data
            assert "total" in data
            assert isinstance(data["appointments"], list)
            assert data["total"] == 1

    @pytest.mark.asyncio
    async def test_update_appointment_status_confirmed(self, staff_client):
        """DASH-02: PATCH /appointments/{id}/status to 'confirmed' returns 200."""
        appt = _mock_appointment(status="booked")
        mock_db = staff_client._mock_db

        # Execute returns the appointment
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = appt
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        async def fake_refresh(obj):
            obj.status = "confirmed"
        mock_db.refresh = AsyncMock(side_effect=fake_refresh)

        resp = await staff_client.patch(
            f"/api/appointments/{APPOINTMENT_ID}/status",
            json={"status": "confirmed"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "confirmed"

    @pytest.mark.asyncio
    async def test_update_appointment_status_entered_in_ehr(self, staff_client):
        """DASH-02: PATCH /appointments/{id}/status to 'entered_in_ehr' returns 200."""
        appt = _mock_appointment(status="confirmed")
        mock_db = staff_client._mock_db

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = appt
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        async def fake_refresh(obj):
            obj.status = "entered_in_ehr"
        mock_db.refresh = AsyncMock(side_effect=fake_refresh)

        resp = await staff_client.patch(
            f"/api/appointments/{APPOINTMENT_ID}/status",
            json={"status": "entered_in_ehr"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "entered_in_ehr"

    @pytest.mark.asyncio
    async def test_update_appointment_invalid_status(self, staff_client):
        """DASH-02: PATCH with invalid status returns 422 (Pydantic regex validation)."""
        resp = await staff_client.patch(
            f"/api/appointments/{APPOINTMENT_ID}/status",
            json={"status": "invalid_value"},
        )
        assert resp.status_code == 422


# ===========================================================================
# Class 2: TestCallLog (DASH-03)
# ===========================================================================

class TestCallLog:
    """DASH-03: Call log with recording, transcript, and summary fields."""

    @pytest.mark.asyncio
    async def test_get_calls_list(self, staff_client):
        """DASH-03: GET /webhooks/calls returns 200 with calls list."""
        call = _mock_call()
        mock_db = staff_client._mock_db

        # Count query returns 1, data query returns row tuples
        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 1
        mock_data_result = MagicMock()
        mock_data_result.all.return_value = [(call, "John Doe")]

        mock_db.execute = AsyncMock(
            side_effect=[mock_count_result, mock_data_result]
        )

        resp = await staff_client.get("/api/webhooks/calls")
        assert resp.status_code == 200
        data = resp.json()
        assert "calls" in data
        assert "total" in data

    @pytest.mark.asyncio
    async def test_call_detail_fields(self, staff_client):
        """DASH-03: Call response includes recording_url, transcript, summary, duration, cost."""
        call = _mock_call(
            recording_url="https://example.com/rec.mp3",
            transcription="Patient said hello.",
            ai_summary="Brief call requesting info.",
            duration_seconds=90,
            vapi_cost=Decimal("0.25"),
        )
        mock_db = staff_client._mock_db

        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 1
        mock_data_result = MagicMock()
        mock_data_result.all.return_value = [(call, None)]
        mock_db.execute = AsyncMock(
            side_effect=[mock_count_result, mock_data_result]
        )

        resp = await staff_client.get("/api/webhooks/calls")
        assert resp.status_code == 200
        calls = resp.json()["calls"]
        assert len(calls) == 1
        c = calls[0]
        # Fields exist (may be None but the key is present)
        assert "recording_url" in c
        assert "transcript" in c
        assert "summary" in c
        assert "duration_seconds" in c
        assert "cost" in c
        # Verify actual values
        assert c["recording_url"] == "https://example.com/rec.mp3"
        assert c["transcript"] == "Patient said hello."
        assert c["summary"] == "Brief call requesting info."
        assert c["duration_seconds"] == 90
        assert float(c["cost"]) == 0.25


# ===========================================================================
# Class 3: TestAnalytics (DASH-04)
# ===========================================================================

class TestAnalytics:
    """DASH-04: Analytics overview with chart-compatible data."""

    @pytest.mark.asyncio
    async def test_analytics_overview(self, staff_client):
        """DASH-04: GET /analytics/overview returns 200 with dashboard fields."""
        mock_db = staff_client._mock_db

        # The overview endpoint runs 4 sequential queries:
        # 1. calls aggregate, 2. appointments aggregate,
        # 3. new patients count, 4. returning patients count
        calls_row = MagicMock()
        calls_row.total = 10
        calls_row.missed = 2
        calls_row.avg_duration = Decimal("95.5")
        calls_row.total_cost = Decimal("3.50")
        mock_calls = MagicMock()
        mock_calls.one.return_value = calls_row

        appt_row = MagicMock()
        appt_row.booked = 5
        appt_row.confirmed = 3
        appt_row.cancelled = 1
        appt_row.no_show = 0
        mock_appt = MagicMock()
        mock_appt.one.return_value = appt_row

        mock_new = MagicMock()
        mock_new.scalar.return_value = 4
        mock_ret = MagicMock()
        mock_ret.scalar.return_value = 2

        mock_db.execute = AsyncMock(side_effect=[
            mock_calls, mock_appt, mock_new, mock_ret,
        ])

        resp = await staff_client.get("/api/analytics/overview?period=month")
        assert resp.status_code == 200
        data = resp.json()
        assert "period" in data
        assert "calls" in data
        assert "appointments" in data
        assert "patients" in data
        assert "ai_performance" in data
        assert "total" in data["calls"]
        assert "missed" in data["calls"]
        assert "booked" in data["appointments"]
        assert "success_rate" in data["ai_performance"]

    @pytest.mark.asyncio
    async def test_analytics_call_volume(self, staff_client):
        """DASH-04: GET /analytics/call-volume returns response with data and summary."""
        mock_db = staff_client._mock_db

        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        resp = await staff_client.get("/api/analytics/call-volume")
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        assert "summary" in data
        assert isinstance(data["data"], list)


# ===========================================================================
# Class 4: TestSettings (DASH-05)
# ===========================================================================

class TestSettings:
    """DASH-05: Settings/config with integration fields."""

    @pytest.mark.asyncio
    async def test_get_practice_config(self, staff_client):
        """DASH-05: GET /practice/config/ returns 200 with config."""
        config = _mock_practice_config()
        mock_db = staff_client._mock_db

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = config
        mock_db.execute = AsyncMock(return_value=mock_result)

        resp = await staff_client.get("/api/practice/config/")
        assert resp.status_code == 200
        data = resp.json()
        assert "practice_id" in data

    @pytest.mark.asyncio
    async def test_config_has_integration_fields(self, staff_client):
        """DASH-05: Config response includes Vapi, Twilio, Stedi, transfer, fallback fields."""
        config = _mock_practice_config()
        mock_db = staff_client._mock_db

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = config
        mock_db.execute = AsyncMock(return_value=mock_result)

        resp = await staff_client.get("/api/practice/config/")
        assert resp.status_code == 200
        data = resp.json()
        # Vapi integration
        assert "vapi_assistant_id" in data
        assert "vapi_phone_number_id" in data
        assert "vapi_api_key" in data
        # Twilio integration
        assert "twilio_phone_number" in data
        assert "twilio_account_sid" in data
        # Stedi integration
        assert "stedi_api_key" in data
        assert "stedi_enabled" in data
        # Transfer/fallback
        assert "transfer_number" in data
        assert "fallback_phone_number" in data
        assert "transfer_message" in data


# ===========================================================================
# Class 5: TestAdminPanel (DASH-06)
# ===========================================================================

class TestAdminPanel:
    """DASH-06: Admin panel CRUD for practices and users."""

    @pytest.mark.asyncio
    async def test_admin_list_practices(self, admin_client):
        """DASH-06: GET /admin/practices as super_admin returns 200 with list."""
        practice = _mock_practice()
        mock_db = admin_client._mock_db

        mock_list_result = MagicMock()
        mock_list_result.scalars.return_value.all.return_value = [practice]
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 1

        mock_db.execute = AsyncMock(
            side_effect=[mock_list_result, mock_count_result]
        )

        resp = await admin_client.get("/api/admin/practices")
        assert resp.status_code == 200
        data = resp.json()
        assert "practices" in data
        assert "total" in data

    @pytest.mark.asyncio
    async def test_admin_list_users(self, admin_client):
        """DASH-06: GET /admin/users as super_admin returns 200 with list."""
        user = _mock_user()
        mock_db = admin_client._mock_db

        mock_list_result = MagicMock()
        mock_list_result.scalars.return_value.all.return_value = [user]
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 1

        mock_db.execute = AsyncMock(
            side_effect=[mock_list_result, mock_count_result]
        )

        resp = await admin_client.get("/api/admin/users")
        assert resp.status_code == 200
        data = resp.json()
        assert "users" in data
        assert "total" in data

    @pytest.mark.asyncio
    async def test_admin_create_practice(self, admin_client):
        """DASH-06: POST /admin/practices with valid data returns 201."""
        mock_db = admin_client._mock_db

        # Slug uniqueness check returns None (no duplicate)
        mock_slug_result = MagicMock()
        mock_slug_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_slug_result)
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        # refresh sets the server-generated fields (id, created_at, updated_at, status)
        async def fake_refresh(obj):
            if not hasattr(obj, '_refreshed'):
                obj.id = PRACTICE_ID
                obj.status = "setup"
                obj.created_at = datetime.now(timezone.utc)
                obj.updated_at = datetime.now(timezone.utc)
                obj._refreshed = True
        mock_db.refresh = AsyncMock(side_effect=fake_refresh)

        with patch("app.routes.admin.log_audit", new_callable=AsyncMock):
            resp = await admin_client.post(
                "/api/admin/practices",
                json={
                    "name": "New Practice",
                    "slug": "new-practice",
                    "npi": "9876543210",
                    "tax_id": "987654321",
                    "phone": "+12125559999",
                    "timezone": "America/New_York",
                },
            )
            assert resp.status_code == 201
            data = resp.json()
            assert "id" in data
            assert "name" in data

    @pytest.mark.asyncio
    async def test_admin_create_user(self, admin_client):
        """DASH-06: POST /admin/users with valid data returns 201."""
        mock_db = admin_client._mock_db

        # Email uniqueness check returns None, practice check returns a practice
        mock_email_result = MagicMock()
        mock_email_result.scalar_one_or_none.return_value = None
        mock_practice_result = MagicMock()
        mock_practice_result.scalar_one_or_none.return_value = _mock_practice()
        mock_db.execute = AsyncMock(
            side_effect=[mock_email_result, mock_practice_result]
        )
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        # refresh sets server-generated fields
        async def fake_refresh(obj):
            if not hasattr(obj, '_refreshed'):
                obj.id = uuid.uuid4()
                obj.is_active = True
                obj.password_change_required = False
                obj.last_login = None
                obj.created_at = datetime.now(timezone.utc)
                obj._refreshed = True
        mock_db.refresh = AsyncMock(side_effect=fake_refresh)

        with patch("app.routes.admin.hash_password", new_callable=AsyncMock, return_value="hashed"), \
             patch("app.routes.admin.log_audit", new_callable=AsyncMock):
            resp = await admin_client.post(
                "/api/admin/users",
                json={
                    "email": "newuser@example.com",
                    "name": "New User",
                    "role": "secretary",
                    "password": "SecurePass1",
                    "practice_id": str(PRACTICE_ID),
                },
            )
            assert resp.status_code == 201
            data = resp.json()
            assert "id" in data
            assert "email" in data


# ===========================================================================
# Class 6: TestPatientSearch (DASH-07)
# ===========================================================================

class TestPatientSearch:
    """DASH-07: Patient search by name, phone, and DOB."""

    @pytest.mark.asyncio
    async def test_search_by_name(self, staff_client):
        """DASH-07: GET /patients/search?first_name=Test returns 200."""
        patient = _mock_patient(first_name="Test")
        mock_db = staff_client._mock_db

        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 1
        mock_data_result = MagicMock()
        mock_data_result.scalars.return_value.all.return_value = [patient]

        mock_db.execute = AsyncMock(
            side_effect=[mock_count_result, mock_data_result]
        )
        mock_db.commit = AsyncMock()

        with patch("app.routes.patients.log_audit", new_callable=AsyncMock):
            resp = await staff_client.get("/api/patients/search?first_name=Test")
            assert resp.status_code == 200
            data = resp.json()
            assert "patients" in data

    @pytest.mark.asyncio
    async def test_search_by_phone(self, staff_client):
        """DASH-07: GET /patients/search?phone=+15551234567 returns 200."""
        mock_db = staff_client._mock_db

        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 0
        mock_data_result = MagicMock()
        mock_data_result.scalars.return_value.all.return_value = []

        mock_db.execute = AsyncMock(
            side_effect=[mock_count_result, mock_data_result]
        )
        mock_db.commit = AsyncMock()

        with patch("app.routes.patients.log_audit", new_callable=AsyncMock):
            resp = await staff_client.get(
                "/api/patients/search?phone=%2B15551234567"
            )
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_search_by_dob(self, staff_client):
        """DASH-07: GET /patients/search?dob=1990-01-15 returns 200."""
        mock_db = staff_client._mock_db

        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 0
        mock_data_result = MagicMock()
        mock_data_result.scalars.return_value.all.return_value = []

        mock_db.execute = AsyncMock(
            side_effect=[mock_count_result, mock_data_result]
        )
        mock_db.commit = AsyncMock()

        with patch("app.routes.patients.log_audit", new_callable=AsyncMock):
            resp = await staff_client.get(
                "/api/patients/search?dob=1990-01-15"
            )
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_search_requires_at_least_one_field(self, staff_client):
        """DASH-07: GET /patients/search with no params returns 400."""
        resp = await staff_client.get("/api/patients/search")
        assert resp.status_code == 400
        assert "at least one" in resp.json()["detail"].lower()


# ===========================================================================
# Class 7: TestPageLoadPositive (DASH-08)
# ===========================================================================

class TestPageLoadPositive:
    """DASH-08: All key API endpoints respond 200 (not 500)."""

    @pytest.mark.asyncio
    async def test_appointments_endpoint_responds(self, staff_client):
        """DASH-08: GET /appointments/ returns 200."""
        with patch("app.routes.appointments.get_appointments", new_callable=AsyncMock) as mock_fn:
            mock_fn.return_value = ([], 0)
            resp = await staff_client.get("/api/appointments/")
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_calls_endpoint_responds(self, staff_client):
        """DASH-08: GET /webhooks/calls returns 200."""
        mock_db = staff_client._mock_db

        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 0
        mock_data_result = MagicMock()
        mock_data_result.all.return_value = []
        mock_db.execute = AsyncMock(
            side_effect=[mock_count_result, mock_data_result]
        )

        resp = await staff_client.get("/api/webhooks/calls")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_call_stats_endpoint_responds(self, staff_client):
        """DASH-08: GET /webhooks/calls/stats returns 200."""
        mock_db = staff_client._mock_db

        # Stats runs many sequential queries
        mock_tz_result = MagicMock()
        mock_tz_result.scalar_one_or_none.return_value = "America/New_York"
        mock_zero = MagicMock()
        mock_zero.scalar_one.return_value = 0
        mock_none = MagicMock()
        mock_none.scalar_one.return_value = None

        mock_db.execute = AsyncMock(side_effect=[
            mock_tz_result,  # Practice.timezone
            mock_zero,       # total_today
            mock_zero,       # missed_today
            mock_none,       # avg_duration
            mock_zero,       # callbacks_pending
            mock_zero,       # total_week
            mock_none,       # total_cost
        ])

        resp = await staff_client.get("/api/webhooks/calls/stats")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_analytics_overview_endpoint_responds(self, staff_client):
        """DASH-08: GET /analytics/overview returns 200."""
        mock_db = staff_client._mock_db

        calls_row = MagicMock()
        calls_row.total = 0
        calls_row.missed = 0
        calls_row.avg_duration = Decimal("0")
        calls_row.total_cost = Decimal("0")
        mock_calls = MagicMock()
        mock_calls.one.return_value = calls_row

        appt_row = MagicMock()
        appt_row.booked = 0
        appt_row.confirmed = 0
        appt_row.cancelled = 0
        appt_row.no_show = 0
        mock_appt = MagicMock()
        mock_appt.one.return_value = appt_row

        mock_new = MagicMock()
        mock_new.scalar.return_value = 0
        mock_ret = MagicMock()
        mock_ret.scalar.return_value = 0

        mock_db.execute = AsyncMock(side_effect=[
            mock_calls, mock_appt, mock_new, mock_ret,
        ])

        resp = await staff_client.get("/api/analytics/overview")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_config_endpoint_responds(self, staff_client):
        """DASH-08: GET /practice/config/ returns 200."""
        config = _mock_practice_config()
        mock_db = staff_client._mock_db

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = config
        mock_db.execute = AsyncMock(return_value=mock_result)

        resp = await staff_client.get("/api/practice/config/")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_practices_endpoint_responds(self, admin_client):
        """DASH-08: GET /admin/practices as super_admin returns 200."""
        mock_db = admin_client._mock_db

        mock_list_result = MagicMock()
        mock_list_result.scalars.return_value.all.return_value = []
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0
        mock_db.execute = AsyncMock(
            side_effect=[mock_list_result, mock_count_result]
        )

        resp = await admin_client.get("/api/admin/practices")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_users_endpoint_responds(self, admin_client):
        """DASH-08: GET /admin/users as super_admin returns 200."""
        mock_db = admin_client._mock_db

        mock_list_result = MagicMock()
        mock_list_result.scalars.return_value.all.return_value = []
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0
        mock_db.execute = AsyncMock(
            side_effect=[mock_list_result, mock_count_result]
        )

        resp = await admin_client.get("/api/admin/users")
        assert resp.status_code == 200


# ===========================================================================
# Class 8: TestAuthNegative (DASH-09)
# ===========================================================================

class TestAuthNegative:
    """DASH-09: Unauthenticated requests return 401/403."""

    @pytest.mark.asyncio
    async def test_unauthenticated_appointments_returns_401(self, unauth_client):
        """DASH-09: GET /appointments/ without auth returns 401 or 403."""
        resp = await unauth_client.get("/api/appointments/")
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_unauthenticated_config_returns_401(self, unauth_client):
        """DASH-09: GET /practice/config/ without auth returns 401 or 403."""
        resp = await unauth_client.get("/api/practice/config/")
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_unauthenticated_calls_returns_401(self, unauth_client):
        """DASH-09: GET /webhooks/calls without auth returns 401 or 403."""
        resp = await unauth_client.get("/api/webhooks/calls")
        assert resp.status_code in (401, 403)


# ===========================================================================
# Class 9: TestEmptyDataEdge (DASH-10)
# ===========================================================================

class TestEmptyDataEdge:
    """DASH-10: Empty data scenarios return empty lists, not errors."""

    @pytest.mark.asyncio
    async def test_appointments_empty_day(self, staff_client):
        """DASH-10: GET /appointments/ for empty day returns 200 with empty list."""
        with patch("app.routes.appointments.get_appointments", new_callable=AsyncMock) as mock_fn:
            mock_fn.return_value = ([], 0)
            resp = await staff_client.get(
                "/api/appointments/?from_date=2025-01-01&to_date=2025-01-01"
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["appointments"] == []
            assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_calls_empty_range(self, staff_client):
        """DASH-10: GET /webhooks/calls for empty range returns 200 with empty list."""
        mock_db = staff_client._mock_db

        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 0
        mock_data_result = MagicMock()
        mock_data_result.all.return_value = []
        mock_db.execute = AsyncMock(
            side_effect=[mock_count_result, mock_data_result]
        )

        resp = await staff_client.get(
            "/api/webhooks/calls?from_date=2025-01-01&to_date=2025-01-01"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["calls"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_analytics_empty_period(self, staff_client):
        """DASH-10: GET /analytics/overview for empty period returns 200 with zero counts."""
        mock_db = staff_client._mock_db

        calls_row = MagicMock()
        calls_row.total = 0
        calls_row.missed = 0
        calls_row.avg_duration = Decimal("0")
        calls_row.total_cost = Decimal("0")
        mock_calls = MagicMock()
        mock_calls.one.return_value = calls_row

        appt_row = MagicMock()
        appt_row.booked = 0
        appt_row.confirmed = 0
        appt_row.cancelled = 0
        appt_row.no_show = 0
        mock_appt = MagicMock()
        mock_appt.one.return_value = appt_row

        mock_new = MagicMock()
        mock_new.scalar.return_value = 0
        mock_ret = MagicMock()
        mock_ret.scalar.return_value = 0

        mock_db.execute = AsyncMock(side_effect=[
            mock_calls, mock_appt, mock_new, mock_ret,
        ])

        resp = await staff_client.get("/api/analytics/overview?period=today")
        assert resp.status_code == 200
        data = resp.json()
        assert data["calls"]["total"] == 0
        assert data["appointments"]["booked"] == 0

    @pytest.mark.asyncio
    async def test_patient_search_no_results(self, staff_client):
        """DASH-10: Patient search with no matching results returns 200 with empty list."""
        mock_db = staff_client._mock_db

        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 0
        mock_data_result = MagicMock()
        mock_data_result.scalars.return_value.all.return_value = []

        mock_db.execute = AsyncMock(
            side_effect=[mock_count_result, mock_data_result]
        )
        mock_db.commit = AsyncMock()

        with patch("app.routes.patients.log_audit", new_callable=AsyncMock):
            resp = await staff_client.get(
                "/api/patients/search?first_name=ZZZZNONEXISTENT"
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["patients"] == []
            assert data["total"] == 0
