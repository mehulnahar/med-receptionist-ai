"""
Tests for Appointment Booking Flow (Phase 6: BOOK-07 through BOOK-12).

Pure unit tests -- NO database, NO running server.
Tests cover: positive English/Spanish flows, negative full-schedule and
holiday/closed-day cases, edge cases for overbooking and boundary times,
plus cancellation and rescheduling flows.

Covers:
  BOOK-07: Positive - full English booking flow (check patient, availability, book, SMS)
  BOOK-08: Positive - full Spanish booking flow (language detection, Spanish SMS)
  BOOK-09: Negative - fully booked schedule returns friendly error
  BOOK-10: Negative - holiday/closed day returns no availability
  BOOK-11: Edge - overbooking-enabled slot allows extra appointments
  BOOK-12: Edge - first/last slot boundary times both bookable
  BOOK-05: Cancel appointment flow verification
  BOOK-06: Reschedule appointment flow verification
"""

import uuid
from datetime import date, time, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.booking_service import _generate_time_slots


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PRACTICE_ID = uuid.uuid4()
PATIENT_ID = uuid.uuid4()
APPOINTMENT_TYPE_ID = uuid.uuid4()
APPOINTMENT_ID = uuid.uuid4()
CALL_ID = uuid.uuid4()
VAPI_CALL_ID = "call_booking_test_001"

# A future date that is safely in the future for testing
FUTURE_DATE = date(2026, 6, 15)  # Monday
FUTURE_DATE_STR = "2026-06-15"
FUTURE_TIME_STR = "10:00"


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _mock_patient(**overrides):
    """Create a mock Patient object."""
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
    return patient


def _mock_appointment_type(**overrides):
    """Create a mock AppointmentType object."""
    appt_type = MagicMock()
    appt_type.id = overrides.get("id", APPOINTMENT_TYPE_ID)
    appt_type.practice_id = overrides.get("practice_id", PRACTICE_ID)
    appt_type.name = overrides.get("name", "General Consultation")
    appt_type.duration_minutes = overrides.get("duration_minutes", 30)
    appt_type.is_active = overrides.get("is_active", True)
    appt_type.sort_order = overrides.get("sort_order", 0)
    return appt_type


def _mock_appointment(**overrides):
    """Create a mock Appointment object."""
    appt = MagicMock()
    appt.id = overrides.get("id", APPOINTMENT_ID)
    appt.practice_id = overrides.get("practice_id", PRACTICE_ID)
    appt.patient_id = overrides.get("patient_id", PATIENT_ID)
    appt.appointment_type_id = overrides.get("appointment_type_id", APPOINTMENT_TYPE_ID)
    appt.date = overrides.get("date", FUTURE_DATE)
    appt.time = overrides.get("time", time(10, 0))
    appt.duration_minutes = overrides.get("duration_minutes", 30)
    appt.status = overrides.get("status", "booked")
    appt.booked_by = overrides.get("booked_by", "ai")
    appt.call_id = overrides.get("call_id", None)
    appt.notes = overrides.get("notes", None)
    appt.sms_confirmation_sent = overrides.get("sms_confirmation_sent", False)
    return appt


# ---------------------------------------------------------------------------
# Patch targets
# ---------------------------------------------------------------------------
# Top-level imports in vapi_tools.py (patchable as module attributes):
#   find_or_create_patient, book_appointment, cancel_appointment,
#   reschedule_appointment, get_available_slots, link_call_to_patient,
#   link_call_to_appointment
#
# Locally-imported functions (must be patched at source module):
#   app.services.sms_service.send_appointment_confirmation
#   app.services.reminder_service.schedule_reminders
#   app.services.reminder_service.cancel_reminders
#   app.services.waitlist_service.check_waitlist_on_cancellation

_P_FIND_PATIENT = "app.services.vapi_tools.find_or_create_patient"
_P_BOOK = "app.services.vapi_tools.book_appointment"
_P_CANCEL = "app.services.vapi_tools.cancel_appointment"
_P_RESCHEDULE = "app.services.vapi_tools.reschedule_appointment"
_P_GET_SLOTS = "app.services.vapi_tools.get_available_slots"
_P_FIRST_APPT_TYPE = "app.services.vapi_tools._get_first_active_appointment_type"
_P_FIND_UPCOMING = "app.services.vapi_tools._find_upcoming_appointment"
_P_LINK_PATIENT = "app.services.vapi_tools.link_call_to_patient"
_P_LINK_APPT = "app.services.vapi_tools.link_call_to_appointment"
_P_SMS = "app.services.sms_service.send_appointment_confirmation"
_P_SCHEDULE_REM = "app.services.reminder_service.schedule_reminders"
_P_CANCEL_REM = "app.services.reminder_service.cancel_reminders"
_P_WAITLIST = "app.services.waitlist_service.check_waitlist_on_cancellation"


# ===========================================================================
# Class 1: TestFullBookingFlowEnglish (BOOK-07)
# ===========================================================================

class TestFullBookingFlowEnglish:
    """BOOK-07: Positive test - full booking flow in English (new patient)."""

    @pytest.mark.asyncio
    @patch(_P_SCHEDULE_REM, new_callable=AsyncMock, return_value=[])
    @patch(_P_SMS, new_callable=AsyncMock)
    @patch(_P_LINK_APPT, new_callable=AsyncMock)
    @patch(_P_LINK_PATIENT, new_callable=AsyncMock)
    @patch(_P_BOOK, new_callable=AsyncMock)
    @patch(_P_FIRST_APPT_TYPE, new_callable=AsyncMock)
    @patch(_P_FIND_PATIENT, new_callable=AsyncMock)
    async def test_full_english_booking_flow(
        self,
        mock_find_patient,
        mock_get_appt_type,
        mock_book,
        mock_link_patient,
        mock_link_appt,
        mock_sms,
        mock_reminders,
    ):
        """BOOK-07: Complete English flow: patient create, appointment type lookup,
        book appointment, SMS confirmation sent."""
        from app.services.vapi_tools import tool_book_appointment

        patient = _mock_patient(language_preference="en")
        appt_type = _mock_appointment_type()
        appointment = _mock_appointment()

        mock_find_patient.return_value = patient
        mock_get_appt_type.return_value = appt_type
        mock_book.return_value = appointment
        mock_sms.return_value = {"success": True, "message_sid": "SM123"}

        # Mock DB for language lookup (Call.language query) and call_id lookup
        mock_lang_result = MagicMock()
        mock_lang_result.scalar_one_or_none.return_value = None  # no call record
        mock_call_id_result = MagicMock()
        mock_call_id_result.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[mock_lang_result, mock_call_id_result])

        result = await tool_book_appointment(
            db=db,
            practice_id=PRACTICE_ID,
            params={
                "first_name": "John",
                "last_name": "Doe",
                "dob": "1990-01-15",
                "phone": "+12125551234",
                "date": FUTURE_DATE_STR,
                "time": FUTURE_TIME_STR,
            },
            vapi_call_id=VAPI_CALL_ID,
        )

        assert result["success"] is True
        assert result["sms_sent"] is True
        assert result["language"] == "en"
        assert result["patient_name"] == "John Doe"
        assert result["appointment_type"] == "General Consultation"

        # Verify find_or_create_patient was called with language_preference="en"
        mock_find_patient.assert_called_once()
        call_kwargs = mock_find_patient.call_args
        assert call_kwargs.kwargs.get("language_preference") == "en"

    @pytest.mark.asyncio
    @patch(_P_SCHEDULE_REM, new_callable=AsyncMock, return_value=[])
    @patch(_P_SMS, new_callable=AsyncMock)
    @patch(_P_BOOK, new_callable=AsyncMock)
    @patch(_P_FIRST_APPT_TYPE, new_callable=AsyncMock)
    @patch(_P_FIND_PATIENT, new_callable=AsyncMock)
    async def test_english_booking_sms_confirmation_called(
        self,
        mock_find_patient,
        mock_get_appt_type,
        mock_book,
        mock_sms,
        mock_reminders,
    ):
        """BOOK-07: Verify send_appointment_confirmation is called after booking."""
        from app.services.vapi_tools import tool_book_appointment

        patient = _mock_patient()
        appt_type = _mock_appointment_type()
        appointment = _mock_appointment()

        mock_find_patient.return_value = patient
        mock_get_appt_type.return_value = appt_type
        mock_book.return_value = appointment
        mock_sms.return_value = {"success": True, "message_sid": "SM456"}

        # No vapi_call_id -> no language/call_id DB lookups needed
        db = AsyncMock()

        result = await tool_book_appointment(
            db=db,
            practice_id=PRACTICE_ID,
            params={
                "first_name": "Jane",
                "last_name": "Smith",
                "dob": "1985-05-20",
                "date": FUTURE_DATE_STR,
                "time": "14:30",
            },
            vapi_call_id=None,
        )

        assert result["success"] is True
        mock_sms.assert_called_once_with(
            db=db,
            practice_id=PRACTICE_ID,
            appointment_id=appointment.id,
        )

    @pytest.mark.asyncio
    @patch(_P_SCHEDULE_REM, new_callable=AsyncMock, return_value=[])
    @patch(_P_SMS, new_callable=AsyncMock)
    @patch(_P_BOOK, new_callable=AsyncMock)
    @patch(_P_FIRST_APPT_TYPE, new_callable=AsyncMock)
    @patch(_P_FIND_PATIENT, new_callable=AsyncMock)
    async def test_english_booking_sms_failure_does_not_block(
        self,
        mock_find_patient,
        mock_get_appt_type,
        mock_book,
        mock_sms,
        mock_reminders,
    ):
        """BOOK-07: SMS failure should not block booking success response."""
        from app.services.vapi_tools import tool_book_appointment

        patient = _mock_patient()
        appt_type = _mock_appointment_type()
        appointment = _mock_appointment()

        mock_find_patient.return_value = patient
        mock_get_appt_type.return_value = appt_type
        mock_book.return_value = appointment
        mock_sms.return_value = {"success": False, "error": "Twilio down"}

        db = AsyncMock()

        result = await tool_book_appointment(
            db=db,
            practice_id=PRACTICE_ID,
            params={
                "first_name": "John",
                "last_name": "Doe",
                "dob": "1990-01-15",
                "date": FUTURE_DATE_STR,
                "time": FUTURE_TIME_STR,
            },
        )

        assert result["success"] is True
        assert result["sms_sent"] is False


# ===========================================================================
# Class 2: TestFullBookingFlowSpanish (BOOK-08)
# ===========================================================================

class TestFullBookingFlowSpanish:
    """BOOK-08: Positive test - full booking flow in Spanish."""

    @pytest.mark.asyncio
    @patch(_P_SCHEDULE_REM, new_callable=AsyncMock, return_value=[])
    @patch(_P_SMS, new_callable=AsyncMock)
    @patch(_P_LINK_APPT, new_callable=AsyncMock)
    @patch(_P_LINK_PATIENT, new_callable=AsyncMock)
    @patch(_P_BOOK, new_callable=AsyncMock)
    @patch(_P_FIRST_APPT_TYPE, new_callable=AsyncMock)
    @patch(_P_FIND_PATIENT, new_callable=AsyncMock)
    async def test_spanish_language_from_call_record(
        self,
        mock_find_patient,
        mock_get_appt_type,
        mock_book,
        mock_link_patient,
        mock_link_appt,
        mock_sms,
        mock_reminders,
    ):
        """BOOK-08: Language detected from Call.language='es' when no explicit param."""
        from app.services.vapi_tools import tool_book_appointment

        patient = _mock_patient(language_preference="es")
        appt_type = _mock_appointment_type()
        appointment = _mock_appointment()

        mock_find_patient.return_value = patient
        mock_get_appt_type.return_value = appt_type
        mock_book.return_value = appointment
        mock_sms.return_value = {"success": True, "message_sid": "SM789"}

        # First DB call: Call.language lookup returns "es"
        mock_lang_result = MagicMock()
        mock_lang_result.scalar_one_or_none.return_value = "es"
        # Second DB call: Call.id lookup for call_id
        mock_call_id_result = MagicMock()
        mock_call_id_result.scalar_one_or_none.return_value = CALL_ID

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[mock_lang_result, mock_call_id_result])

        result = await tool_book_appointment(
            db=db,
            practice_id=PRACTICE_ID,
            params={
                "first_name": "Maria",
                "last_name": "Garcia",
                "dob": "1988-03-22",
                "phone": "+12125559876",
                "date": FUTURE_DATE_STR,
                "time": "11:00",
            },
            vapi_call_id=VAPI_CALL_ID,
        )

        assert result["success"] is True
        assert result["language"] == "es"
        assert result["sms_sent"] is True

        # Verify find_or_create_patient was called with language_preference="es"
        mock_find_patient.assert_called_once()
        call_kwargs = mock_find_patient.call_args
        assert call_kwargs.kwargs.get("language_preference") == "es"

    @pytest.mark.asyncio
    @patch(_P_SCHEDULE_REM, new_callable=AsyncMock, return_value=[])
    @patch(_P_SMS, new_callable=AsyncMock)
    @patch(_P_BOOK, new_callable=AsyncMock)
    @patch(_P_FIRST_APPT_TYPE, new_callable=AsyncMock)
    @patch(_P_FIND_PATIENT, new_callable=AsyncMock)
    async def test_explicit_spanish_param_overrides_call_record(
        self,
        mock_find_patient,
        mock_get_appt_type,
        mock_book,
        mock_sms,
        mock_reminders,
    ):
        """BOOK-08: Explicit language='es' param takes priority over call record."""
        from app.services.vapi_tools import tool_book_appointment

        patient = _mock_patient(language_preference="es")
        appt_type = _mock_appointment_type()
        appointment = _mock_appointment()

        mock_find_patient.return_value = patient
        mock_get_appt_type.return_value = appt_type
        mock_book.return_value = appointment
        mock_sms.return_value = {"success": True, "message_sid": "SM101"}

        # With explicit language param, no Call.language DB lookup needed
        db = AsyncMock()

        result = await tool_book_appointment(
            db=db,
            practice_id=PRACTICE_ID,
            params={
                "first_name": "Carlos",
                "last_name": "Ruiz",
                "dob": "1975-11-08",
                "language": "es",
                "date": FUTURE_DATE_STR,
                "time": "09:00",
            },
            vapi_call_id=None,
        )

        assert result["success"] is True
        assert result["language"] == "es"

        # Verify find_or_create_patient was called with language_preference="es"
        mock_find_patient.assert_called_once()
        call_kwargs = mock_find_patient.call_args
        assert call_kwargs.kwargs.get("language_preference") == "es"


# ===========================================================================
# Class 3: TestBookingScheduleFull (BOOK-09)
# ===========================================================================

class TestBookingScheduleFull:
    """BOOK-09: Negative test - fully booked schedule returns friendly error."""

    @pytest.mark.asyncio
    @patch(_P_SCHEDULE_REM, new_callable=AsyncMock, return_value=[])
    @patch(_P_SMS, new_callable=AsyncMock)
    @patch(_P_BOOK, new_callable=AsyncMock)
    @patch(_P_FIRST_APPT_TYPE, new_callable=AsyncMock)
    @patch(_P_FIND_PATIENT, new_callable=AsyncMock)
    async def test_fully_booked_slot_returns_error(
        self,
        mock_find_patient,
        mock_get_appt_type,
        mock_book,
        mock_sms,
        mock_reminders,
    ):
        """BOOK-09: Booking on a fully-booked slot returns success=False with error."""
        from app.services.vapi_tools import tool_book_appointment

        patient = _mock_patient()
        appt_type = _mock_appointment_type()

        mock_find_patient.return_value = patient
        mock_get_appt_type.return_value = appt_type
        mock_book.side_effect = ValueError(
            "Time slot 10:00 on 2026-06-15 is fully booked"
        )

        db = AsyncMock()

        result = await tool_book_appointment(
            db=db,
            practice_id=PRACTICE_ID,
            params={
                "first_name": "Test",
                "last_name": "User",
                "dob": "1990-01-01",
                "date": FUTURE_DATE_STR,
                "time": FUTURE_TIME_STR,
            },
        )

        assert result["success"] is False
        assert "fully booked" in result["error"]

    @pytest.mark.asyncio
    @patch(_P_GET_SLOTS, new_callable=AsyncMock)
    async def test_check_availability_all_booked_returns_zero(self, mock_get_slots):
        """BOOK-09: tool_check_availability with all slots booked returns total_available=0."""
        from app.services.vapi_tools import tool_check_availability

        # Mock all slots as unavailable
        all_booked_slots = [
            {"time": time(h, m), "is_available": False, "current_bookings": 1}
            for h in range(9, 17) for m in (0, 30)
        ]
        mock_get_slots.return_value = all_booked_slots

        # Mock DB calls: Practice.timezone, PracticeConfig.booking_horizon_days
        mock_tz_result = MagicMock()
        mock_tz_result.scalar_one_or_none.return_value = "America/New_York"
        mock_horizon_result = MagicMock()
        mock_horizon_result.scalar_one_or_none.return_value = 90

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[mock_tz_result, mock_horizon_result])

        result = await tool_check_availability(
            db=db,
            practice_id=PRACTICE_ID,
            params={"date": FUTURE_DATE_STR},
        )

        assert result["total_available"] == 0
        assert result["available_slots"] == []
        assert "message" in result


# ===========================================================================
# Class 4: TestBookingHolidayClosed (BOOK-10)
# ===========================================================================

class TestBookingHolidayClosed:
    """BOOK-10: Negative test - holiday/closed day returns no availability."""

    @pytest.mark.asyncio
    @patch(_P_GET_SLOTS, new_callable=AsyncMock, return_value=[])
    async def test_holiday_returns_empty_slots(self, mock_get_slots):
        """BOOK-10: tool_check_availability on a holiday returns 0 available slots."""
        from app.services.vapi_tools import tool_check_availability

        mock_tz_result = MagicMock()
        mock_tz_result.scalar_one_or_none.return_value = "America/New_York"
        mock_horizon_result = MagicMock()
        mock_horizon_result.scalar_one_or_none.return_value = 90

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[mock_tz_result, mock_horizon_result])

        result = await tool_check_availability(
            db=db,
            practice_id=PRACTICE_ID,
            params={"date": FUTURE_DATE_STR},
        )

        assert result["total_available"] == 0
        assert result["available_slots"] == []
        assert "message" in result

    @pytest.mark.asyncio
    @patch(_P_SCHEDULE_REM, new_callable=AsyncMock, return_value=[])
    @patch(_P_SMS, new_callable=AsyncMock)
    @patch(_P_BOOK, new_callable=AsyncMock)
    @patch(_P_FIRST_APPT_TYPE, new_callable=AsyncMock)
    @patch(_P_FIND_PATIENT, new_callable=AsyncMock)
    async def test_booking_on_closed_day_returns_error(
        self,
        mock_find_patient,
        mock_get_appt_type,
        mock_book,
        mock_sms,
        mock_reminders,
    ):
        """BOOK-10: Attempting to book on a closed day returns a validation error."""
        from app.services.vapi_tools import tool_book_appointment

        patient = _mock_patient()
        appt_type = _mock_appointment_type()

        mock_find_patient.return_value = patient
        mock_get_appt_type.return_value = appt_type
        # book_appointment raises ValueError when no valid slot exists
        mock_book.side_effect = ValueError(
            "Time slot 10:00 is not a valid slot on 2026-06-15"
        )

        db = AsyncMock()

        result = await tool_book_appointment(
            db=db,
            practice_id=PRACTICE_ID,
            params={
                "first_name": "Holiday",
                "last_name": "Tester",
                "dob": "1995-12-25",
                "date": FUTURE_DATE_STR,
                "time": FUTURE_TIME_STR,
            },
        )

        assert result["success"] is False
        assert "not a valid slot" in result["error"]


# ===========================================================================
# Class 5: TestBookingOverbooking (BOOK-11)
# ===========================================================================

class TestBookingOverbooking:
    """BOOK-11: Edge test - overbooking-enabled slot allows extra appointments."""

    def test_overbooking_allows_extra_bookings(self):
        """BOOK-11: With overbooking max=3 and 1 existing booking, slot is available."""
        # Simulate the pure availability logic from get_available_slots
        time_slots = _generate_time_slots(time(9, 0), time(17, 0), 30)
        bookings_map = {time(10, 0): 1}  # 1 existing booking at 10:00

        allow_overbooking = True
        max_overbooking_per_slot = 3
        max_per_slot = max_overbooking_per_slot if allow_overbooking else 1

        slots = []
        for t in time_slots:
            current_count = bookings_map.get(t, 0)
            slots.append({
                "time": t,
                "is_available": current_count < max_per_slot,
                "current_bookings": current_count,
            })

        # The 10:00 slot with 1 booking should still be available (1 < 3)
        slot_1000 = next(s for s in slots if s["time"] == time(10, 0))
        assert slot_1000["is_available"] is True
        assert slot_1000["current_bookings"] == 1

    def test_overbooking_at_max_blocks_slot(self):
        """BOOK-11: With overbooking max=3 and 3 existing bookings, slot is blocked."""
        time_slots = _generate_time_slots(time(9, 0), time(17, 0), 30)
        bookings_map = {time(10, 0): 3}

        allow_overbooking = True
        max_overbooking_per_slot = 3
        max_per_slot = max_overbooking_per_slot if allow_overbooking else 1

        slots = []
        for t in time_slots:
            current_count = bookings_map.get(t, 0)
            slots.append({
                "time": t,
                "is_available": current_count < max_per_slot,
                "current_bookings": current_count,
            })

        slot_1000 = next(s for s in slots if s["time"] == time(10, 0))
        assert slot_1000["is_available"] is False
        assert slot_1000["current_bookings"] == 3

    def test_overbooking_disabled_blocks_at_one(self):
        """BOOK-11: With overbooking disabled, 1 booking blocks the slot."""
        time_slots = _generate_time_slots(time(9, 0), time(17, 0), 30)
        bookings_map = {time(10, 0): 1}

        allow_overbooking = False
        max_overbooking_per_slot = 1
        max_per_slot = max_overbooking_per_slot if allow_overbooking else 1

        slots = []
        for t in time_slots:
            current_count = bookings_map.get(t, 0)
            slots.append({
                "time": t,
                "is_available": current_count < max_per_slot,
                "current_bookings": current_count,
            })

        slot_1000 = next(s for s in slots if s["time"] == time(10, 0))
        assert slot_1000["is_available"] is False


# ===========================================================================
# Class 6: TestBookingBoundaryTimes (BOOK-12)
# ===========================================================================

class TestBookingBoundaryTimes:
    """BOOK-12: Edge test - first and last slot boundary times."""

    def test_first_and_last_slots_exist_30min(self):
        """BOOK-12: 9:00-17:00 with 30-min slots has first=9:00 and last=16:30."""
        slots = _generate_time_slots(time(9, 0), time(17, 0), 30)
        slot_times = [s for s in slots]
        assert time(9, 0) in slot_times, "First slot 09:00 must be present"
        assert time(16, 30) in slot_times, "Last slot 16:30 must be present"

    def test_first_slot_is_bookable(self):
        """BOOK-12: First slot (09:00) with no bookings is available."""
        time_slots = _generate_time_slots(time(9, 0), time(17, 0), 30)
        bookings_map = {}
        max_per_slot = 1

        slots = []
        for t in time_slots:
            current_count = bookings_map.get(t, 0)
            slots.append({
                "time": t,
                "is_available": current_count < max_per_slot,
                "current_bookings": current_count,
            })

        first_slot = slots[0]
        assert first_slot["time"] == time(9, 0)
        assert first_slot["is_available"] is True

    def test_last_slot_is_bookable(self):
        """BOOK-12: Last slot (16:30) with no bookings is available."""
        time_slots = _generate_time_slots(time(9, 0), time(17, 0), 30)
        bookings_map = {}
        max_per_slot = 1

        slots = []
        for t in time_slots:
            current_count = bookings_map.get(t, 0)
            slots.append({
                "time": t,
                "is_available": current_count < max_per_slot,
                "current_bookings": current_count,
            })

        last_slot = slots[-1]
        assert last_slot["time"] == time(16, 30)
        assert last_slot["is_available"] is True

    @pytest.mark.asyncio
    @patch(_P_SCHEDULE_REM, new_callable=AsyncMock, return_value=[])
    @patch(_P_SMS, new_callable=AsyncMock)
    @patch(_P_BOOK, new_callable=AsyncMock)
    @patch(_P_FIRST_APPT_TYPE, new_callable=AsyncMock)
    @patch(_P_FIND_PATIENT, new_callable=AsyncMock)
    async def test_book_at_first_slot_succeeds(
        self,
        mock_find_patient,
        mock_get_appt_type,
        mock_book,
        mock_sms,
        mock_reminders,
    ):
        """BOOK-12: Booking at 09:00 (first slot) succeeds."""
        from app.services.vapi_tools import tool_book_appointment

        patient = _mock_patient()
        appt_type = _mock_appointment_type()
        appointment = _mock_appointment(time=time(9, 0))

        mock_find_patient.return_value = patient
        mock_get_appt_type.return_value = appt_type
        mock_book.return_value = appointment
        mock_sms.return_value = {"success": True, "message_sid": "SM_FIRST"}

        db = AsyncMock()

        result = await tool_book_appointment(
            db=db,
            practice_id=PRACTICE_ID,
            params={
                "first_name": "Early",
                "last_name": "Bird",
                "dob": "1990-01-01",
                "date": FUTURE_DATE_STR,
                "time": "09:00",
            },
        )

        assert result["success"] is True
        assert result["time"] == "09:00"

    @pytest.mark.asyncio
    @patch(_P_SCHEDULE_REM, new_callable=AsyncMock, return_value=[])
    @patch(_P_SMS, new_callable=AsyncMock)
    @patch(_P_BOOK, new_callable=AsyncMock)
    @patch(_P_FIRST_APPT_TYPE, new_callable=AsyncMock)
    @patch(_P_FIND_PATIENT, new_callable=AsyncMock)
    async def test_book_at_last_slot_succeeds(
        self,
        mock_find_patient,
        mock_get_appt_type,
        mock_book,
        mock_sms,
        mock_reminders,
    ):
        """BOOK-12: Booking at 16:30 (last slot) succeeds."""
        from app.services.vapi_tools import tool_book_appointment

        patient = _mock_patient()
        appt_type = _mock_appointment_type()
        appointment = _mock_appointment(time=time(16, 30))

        mock_find_patient.return_value = patient
        mock_get_appt_type.return_value = appt_type
        mock_book.return_value = appointment
        mock_sms.return_value = {"success": True, "message_sid": "SM_LAST"}

        db = AsyncMock()

        result = await tool_book_appointment(
            db=db,
            practice_id=PRACTICE_ID,
            params={
                "first_name": "Late",
                "last_name": "Closer",
                "dob": "1992-07-10",
                "date": FUTURE_DATE_STR,
                "time": "16:30",
            },
        )

        assert result["success"] is True
        assert result["time"] == "16:30"


# ===========================================================================
# Class 7: TestCancelAppointment (BOOK-05 verification)
# ===========================================================================

class TestCancelAppointment:
    """BOOK-05 verification: Cancel appointment flow."""

    @pytest.mark.asyncio
    @patch(_P_WAITLIST, new_callable=AsyncMock, return_value=[])
    @patch(_P_CANCEL_REM, new_callable=AsyncMock)
    @patch(_P_CANCEL, new_callable=AsyncMock)
    @patch(_P_FIND_UPCOMING, new_callable=AsyncMock)
    async def test_cancel_success(
        self,
        mock_find_appt,
        mock_cancel,
        mock_cancel_rem,
        mock_waitlist,
    ):
        """BOOK-05: Cancelling an existing appointment returns success=True."""
        from app.services.vapi_tools import tool_cancel_appointment

        appointment = _mock_appointment(
            date=FUTURE_DATE,
            time=time(10, 0),
            status="cancelled",
        )
        mock_find_appt.return_value = appointment
        mock_cancel.return_value = appointment

        # DB calls: Practice.timezone lookup
        mock_tz_result = MagicMock()
        mock_tz_result.scalar_one_or_none.return_value = "America/New_York"

        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_tz_result)

        result = await tool_cancel_appointment(
            db=db,
            practice_id=PRACTICE_ID,
            params={"patient_id": str(PATIENT_ID)},
        )

        assert result["success"] is True
        assert result["cancelled_date"] == FUTURE_DATE.isoformat()
        assert result["cancelled_time"] == "10:00"

    @pytest.mark.asyncio
    @patch(_P_FIND_UPCOMING, new_callable=AsyncMock, return_value=None)
    async def test_cancel_no_appointment_found(self, mock_find_appt):
        """BOOK-05: Cancel with no upcoming appointment returns friendly error."""
        from app.services.vapi_tools import tool_cancel_appointment

        mock_tz_result = MagicMock()
        mock_tz_result.scalar_one_or_none.return_value = "America/New_York"

        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_tz_result)

        result = await tool_cancel_appointment(
            db=db,
            practice_id=PRACTICE_ID,
            params={"patient_id": str(PATIENT_ID)},
        )

        assert result["success"] is False
        assert "No upcoming appointment" in result["error"]


# ===========================================================================
# Class 8: TestRescheduleAppointment (BOOK-06 verification)
# ===========================================================================

class TestRescheduleAppointment:
    """BOOK-06 verification: Reschedule appointment flow."""

    @pytest.mark.asyncio
    @patch(_P_SCHEDULE_REM, new_callable=AsyncMock, return_value=[])
    @patch(_P_CANCEL_REM, new_callable=AsyncMock)
    @patch(_P_RESCHEDULE, new_callable=AsyncMock)
    @patch(_P_FIND_UPCOMING, new_callable=AsyncMock)
    async def test_reschedule_success(
        self,
        mock_find_appt,
        mock_reschedule,
        mock_cancel_rem,
        mock_schedule_rem,
    ):
        """BOOK-06: Rescheduling an appointment returns success with new date/time."""
        from app.services.vapi_tools import tool_reschedule_appointment

        old_appointment = _mock_appointment(
            date=FUTURE_DATE,
            time=time(10, 0),
        )
        new_date = FUTURE_DATE + timedelta(days=7)
        new_appointment = _mock_appointment(
            id=uuid.uuid4(),
            date=new_date,
            time=time(14, 0),
        )

        mock_find_appt.return_value = old_appointment
        mock_reschedule.return_value = new_appointment

        # DB calls: Practice.timezone lookup
        mock_tz_result = MagicMock()
        mock_tz_result.scalar_one_or_none.return_value = "America/New_York"

        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_tz_result)

        result = await tool_reschedule_appointment(
            db=db,
            practice_id=PRACTICE_ID,
            params={
                "patient_id": str(PATIENT_ID),
                "new_date": new_date.isoformat(),
                "new_time": "14:00",
            },
        )

        assert result["success"] is True
        assert result["old_date"] == FUTURE_DATE.isoformat()
        assert result["old_time"] == "10:00"
        assert result["new_date"] == new_date.isoformat()
        assert result["new_time"] == "14:00"

    @pytest.mark.asyncio
    @patch(_P_FIND_UPCOMING, new_callable=AsyncMock, return_value=None)
    async def test_reschedule_no_appointment_found(self, mock_find_appt):
        """BOOK-06: Reschedule with no upcoming appointment returns error."""
        from app.services.vapi_tools import tool_reschedule_appointment

        mock_tz_result = MagicMock()
        mock_tz_result.scalar_one_or_none.return_value = "America/New_York"

        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_tz_result)

        result = await tool_reschedule_appointment(
            db=db,
            practice_id=PRACTICE_ID,
            params={
                "patient_id": str(PATIENT_ID),
                "new_date": "2026-06-22",
                "new_time": "15:00",
            },
        )

        assert result["success"] is False
        assert "No upcoming appointment" in result["error"]

    @pytest.mark.asyncio
    @patch(_P_SCHEDULE_REM, new_callable=AsyncMock, return_value=[])
    @patch(_P_CANCEL_REM, new_callable=AsyncMock)
    @patch(_P_RESCHEDULE, new_callable=AsyncMock)
    @patch(_P_FIND_UPCOMING, new_callable=AsyncMock)
    async def test_reschedule_to_booked_slot_returns_error(
        self,
        mock_find_appt,
        mock_reschedule,
        mock_cancel_rem,
        mock_schedule_rem,
    ):
        """BOOK-06: Rescheduling to a fully booked slot returns error."""
        from app.services.vapi_tools import tool_reschedule_appointment

        old_appointment = _mock_appointment(date=FUTURE_DATE, time=time(10, 0))
        mock_find_appt.return_value = old_appointment
        mock_reschedule.side_effect = ValueError(
            "Time slot 14:00 on 2026-06-22 is fully booked"
        )

        mock_tz_result = MagicMock()
        mock_tz_result.scalar_one_or_none.return_value = "America/New_York"

        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_tz_result)

        result = await tool_reschedule_appointment(
            db=db,
            practice_id=PRACTICE_ID,
            params={
                "patient_id": str(PATIENT_ID),
                "new_date": "2026-06-22",
                "new_time": "14:00",
            },
        )

        assert result["success"] is False
        assert "fully booked" in result["error"]
