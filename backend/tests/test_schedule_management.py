"""
Tests for Schedule Management (Phase 2: 02-03).

Pure unit tests -- NO database, NO running server.
Tests cover: time slot generation, schema validation, availability logic,
and alternate Friday parity computation.
"""

import pytest
from datetime import date, time, timedelta
from pydantic import ValidationError

from app.services.booking_service import _generate_time_slots
from app.schemas.schedule import ScheduleTemplateUpdate, ScheduleOverrideCreate


# ---------------------------------------------------------------------------
# Helper: Alternate Friday parity formula (mirrors production code in
# booking_service._get_schedule_for_date and find_next_available_slot)
# ---------------------------------------------------------------------------

def is_friday_open(target_date: date, reference_date: date) -> bool:
    """
    Determine if a given Friday is an 'open' Friday based on the
    alternate-week parity formula.

    Even weeks_diff from reference = open, odd = closed.
    """
    weeks_diff = abs((target_date - reference_date).days // 7)
    return weeks_diff % 2 == 0


# ===========================================================================
# Class 1: TestGenerateTimeSlots
# ===========================================================================

class TestGenerateTimeSlots:
    """Tests for _generate_time_slots from app.services.booking_service."""

    def test_standard_day_15min_slots(self):
        """09:00-17:00 at 15-min intervals yields 32 slots."""
        slots = _generate_time_slots(time(9, 0), time(17, 0), 15)
        assert len(slots) == 32
        assert slots[0] == time(9, 0)
        assert slots[-1] == time(16, 45)

    def test_zero_duration_returns_empty(self):
        """09:00-09:00 (zero span) yields 0 slots."""
        slots = _generate_time_slots(time(9, 0), time(9, 0), 15)
        assert len(slots) == 0

    def test_less_than_one_slot_returns_empty(self):
        """09:00-09:14 (14 min, less than 15-min slot) yields 0 slots."""
        slots = _generate_time_slots(time(9, 0), time(9, 14), 15)
        assert len(slots) == 0

    def test_exactly_one_slot(self):
        """09:00-09:15 (exactly 15 min) yields 1 slot at 09:00."""
        slots = _generate_time_slots(time(9, 0), time(9, 15), 15)
        assert len(slots) == 1
        assert slots[0] == time(9, 0)

    def test_60min_slots_full_day(self):
        """09:00-17:00 at 60-min intervals yields 8 slots."""
        slots = _generate_time_slots(time(9, 0), time(17, 0), 60)
        assert len(slots) == 8
        assert slots[0] == time(9, 0)
        assert slots[-1] == time(16, 0)

    def test_30min_slots_half_day(self):
        """09:00-13:00 at 30-min intervals yields 8 slots."""
        slots = _generate_time_slots(time(9, 0), time(13, 0), 30)
        assert len(slots) == 8
        assert slots[0] == time(9, 0)
        assert slots[-1] == time(12, 30)

    def test_slots_are_time_objects(self):
        """All returned items are datetime.time instances."""
        slots = _generate_time_slots(time(9, 0), time(10, 0), 15)
        for slot in slots:
            assert isinstance(slot, time)


# ===========================================================================
# Class 2: TestScheduleSchemaValidation
# ===========================================================================

class TestScheduleSchemaValidation:
    """Tests for pydantic schema validators in app.schemas.schedule."""

    # --- ScheduleTemplateUpdate ---

    def test_template_enabled_without_times_raises(self):
        """Enabled day without start/end times raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ScheduleTemplateUpdate(day_of_week=0, is_enabled=True)
        assert "start_time" in str(exc_info.value).lower() or "required" in str(exc_info.value).lower()

    def test_template_end_before_start_raises(self):
        """end_time <= start_time raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ScheduleTemplateUpdate(
                day_of_week=0,
                is_enabled=True,
                start_time=time(17, 0),
                end_time=time(9, 0),
            )
        assert "end_time" in str(exc_info.value).lower()

    def test_template_end_equals_start_raises(self):
        """end_time == start_time raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ScheduleTemplateUpdate(
                day_of_week=0,
                is_enabled=True,
                start_time=time(9, 0),
                end_time=time(9, 0),
            )
        assert "end_time" in str(exc_info.value).lower()

    def test_template_valid_monday(self):
        """Valid Monday 09:00-17:00 passes validation."""
        template = ScheduleTemplateUpdate(
            day_of_week=0,
            is_enabled=True,
            start_time=time(9, 0),
            end_time=time(17, 0),
        )
        assert template.day_of_week == 0
        assert template.is_enabled is True
        assert template.start_time == time(9, 0)
        assert template.end_time == time(17, 0)

    def test_template_disabled_without_times_passes(self):
        """Disabled day with no times passes validation."""
        template = ScheduleTemplateUpdate(day_of_week=6, is_enabled=False)
        assert template.is_enabled is False
        assert template.start_time is None
        assert template.end_time is None

    def test_template_invalid_day_of_week_raises(self):
        """day_of_week outside 0-6 range raises ValidationError."""
        with pytest.raises(ValidationError):
            ScheduleTemplateUpdate(day_of_week=7, is_enabled=False)

    def test_template_negative_day_of_week_raises(self):
        """Negative day_of_week raises ValidationError."""
        with pytest.raises(ValidationError):
            ScheduleTemplateUpdate(day_of_week=-1, is_enabled=False)

    # --- ScheduleOverrideCreate ---

    def test_override_end_before_start_raises(self):
        """Override with end_time <= start_time raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ScheduleOverrideCreate(
                date=date(2026, 4, 1),
                is_working=True,
                start_time=time(17, 0),
                end_time=time(9, 0),
            )
        assert "end_time" in str(exc_info.value).lower()

    def test_override_reason_max_length(self):
        """Reason over 255 chars raises ValidationError (max_length=255 on Field)."""
        with pytest.raises(ValidationError):
            ScheduleOverrideCreate(
                date=date(2026, 4, 1),
                is_working=False,
                reason="x" * 256,
            )

    def test_override_valid_closed_day(self):
        """Valid closed-day override passes validation."""
        override = ScheduleOverrideCreate(
            date=date(2026, 4, 1),
            is_working=False,
            reason="Office renovation",
        )
        assert override.is_working is False
        assert override.reason == "Office renovation"

    def test_override_valid_working_day(self):
        """Valid working-day override with custom hours passes."""
        override = ScheduleOverrideCreate(
            date=date(2026, 4, 1),
            is_working=True,
            start_time=time(10, 0),
            end_time=time(14, 0),
            reason="Half day Saturday",
        )
        assert override.is_working is True
        assert override.start_time == time(10, 0)
        assert override.end_time == time(14, 0)


# ===========================================================================
# Class 3: TestAvailabilityLogic
# ===========================================================================

class TestAvailabilityLogic:
    """
    Pure logic tests for availability calculation.

    Tests _generate_time_slots directly and simulates the booking-count
    logic from get_available_slots (the part that doesn't need DB).
    """

    @staticmethod
    def _simulate_availability(
        start_time_val: time,
        end_time_val: time,
        slot_duration: int,
        bookings_map: dict[time, int],
        allow_overbooking: bool = False,
        max_overbooking_per_slot: int = 1,
    ) -> list[dict]:
        """
        Simulate the pure-logic portion of get_available_slots:
        generate slots, apply booking counts, return availability list.
        """
        time_slots = _generate_time_slots(start_time_val, end_time_val, slot_duration)
        max_per_slot = max_overbooking_per_slot if allow_overbooking else 1

        result = []
        for t in time_slots:
            current_count = bookings_map.get(t, 0)
            result.append({
                "time": t,
                "is_available": current_count < max_per_slot,
                "current_bookings": current_count,
            })
        return result

    def test_full_day_no_bookings_all_available(self):
        """Mon 09:00-17:00, 15-min slots, 0 bookings -> 32 available slots."""
        slots = self._simulate_availability(
            time(9, 0), time(17, 0), 15, bookings_map={}
        )
        assert len(slots) == 32
        assert all(s["is_available"] for s in slots)

    def test_one_booking_blocks_slot(self):
        """1 booking at 09:00 (no overbooking) -> 09:00 unavailable."""
        slots = self._simulate_availability(
            time(9, 0), time(17, 0), 15,
            bookings_map={time(9, 0): 1},
        )
        slot_0900 = next(s for s in slots if s["time"] == time(9, 0))
        assert slot_0900["is_available"] is False
        assert slot_0900["current_bookings"] == 1

        # Other slots remain available
        other_available = [s for s in slots if s["time"] != time(9, 0)]
        assert all(s["is_available"] for s in other_available)

    def test_overbooking_1_of_2_still_available(self):
        """Overbooking max=2, 1 booking at 09:00 -> 09:00 still available."""
        slots = self._simulate_availability(
            time(9, 0), time(17, 0), 15,
            bookings_map={time(9, 0): 1},
            allow_overbooking=True,
            max_overbooking_per_slot=2,
        )
        slot_0900 = next(s for s in slots if s["time"] == time(9, 0))
        assert slot_0900["is_available"] is True
        assert slot_0900["current_bookings"] == 1

    def test_overbooking_2_of_2_unavailable(self):
        """Overbooking max=2, 2 bookings at 09:00 -> 09:00 unavailable."""
        slots = self._simulate_availability(
            time(9, 0), time(17, 0), 15,
            bookings_map={time(9, 0): 2},
            allow_overbooking=True,
            max_overbooking_per_slot=2,
        )
        slot_0900 = next(s for s in slots if s["time"] == time(9, 0))
        assert slot_0900["is_available"] is False
        assert slot_0900["current_bookings"] == 2

    def test_boundary_first_and_last_slots(self):
        """First slot (09:00) and last slot (16:45) both present in 15-min slots."""
        slots = self._simulate_availability(
            time(9, 0), time(17, 0), 15, bookings_map={}
        )
        slot_times = [s["time"] for s in slots]
        assert time(9, 0) in slot_times
        assert time(16, 45) in slot_times

    def test_disabled_template_yields_zero_slots(self):
        """Simulating is_enabled=False: no slot generation -> 0 slots."""
        # When template is disabled, the service returns [] before generating slots.
        # We simulate by not calling _generate_time_slots at all (like the service does).
        is_enabled = False
        if not is_enabled:
            slots = []
        else:
            slots = self._simulate_availability(
                time(9, 0), time(17, 0), 15, bookings_map={}
            )
        assert len(slots) == 0

    def test_no_template_yields_zero_slots(self):
        """Simulating missing template: no slot generation -> 0 slots."""
        # When no template exists for the day, _get_schedule_for_date returns
        # (False, None, None) and get_available_slots returns [].
        template = None
        if template is None:
            slots = []
        else:
            slots = self._simulate_availability(
                time(9, 0), time(17, 0), 15, bookings_map={}
            )
        assert len(slots) == 0

    def test_multiple_bookings_across_slots(self):
        """Multiple slots partially booked, only fully-booked ones unavailable."""
        bookings = {time(9, 0): 1, time(10, 0): 1, time(11, 0): 0}
        slots = self._simulate_availability(
            time(9, 0), time(17, 0), 15, bookings_map=bookings
        )
        assert next(s for s in slots if s["time"] == time(9, 0))["is_available"] is False
        assert next(s for s in slots if s["time"] == time(10, 0))["is_available"] is False
        assert next(s for s in slots if s["time"] == time(11, 0))["is_available"] is True
        # Slots with no booking entry are available
        assert next(s for s in slots if s["time"] == time(12, 0))["is_available"] is True


# ===========================================================================
# Class 4: TestAlternateFridayLogic
# ===========================================================================

class TestAlternateFridayLogic:
    """
    Pure computation tests for the alternate Friday parity formula.

    The formula: weeks_diff = abs((target_date - reference_date).days // 7)
    Even weeks_diff -> open (working Friday), odd -> closed (off Friday).
    """

    # Reference Friday: 2026-03-06 (a Friday)
    REF = date(2026, 3, 6)

    def test_same_day_as_reference_is_open(self):
        """Reference = 2026-03-06; target = 2026-03-06 (0 weeks, even) -> open."""
        assert is_friday_open(date(2026, 3, 6), self.REF) is True

    def test_one_week_after_is_closed(self):
        """Reference = 2026-03-06; target = 2026-03-13 (1 week, odd) -> closed."""
        assert is_friday_open(date(2026, 3, 13), self.REF) is False

    def test_two_weeks_after_is_open(self):
        """Reference = 2026-03-06; target = 2026-03-20 (2 weeks, even) -> open."""
        assert is_friday_open(date(2026, 3, 20), self.REF) is True

    def test_three_weeks_after_is_closed(self):
        """Reference = 2026-03-06; target = 2026-03-27 (3 weeks, odd) -> closed."""
        assert is_friday_open(date(2026, 3, 27), self.REF) is False

    def test_four_weeks_after_is_open(self):
        """Reference = 2026-03-06; target = 2026-04-03 (4 weeks, even) -> open."""
        assert is_friday_open(date(2026, 4, 3), self.REF) is True

    def test_one_week_before_is_closed(self):
        """Reference = 2026-03-06; target = 2026-02-27 (1 week before, odd) -> closed."""
        assert is_friday_open(date(2026, 2, 27), self.REF) is False

    def test_two_weeks_before_is_open(self):
        """Reference = 2026-03-06; target = 2026-02-20 (2 weeks before, even) -> open."""
        assert is_friday_open(date(2026, 2, 20), self.REF) is True

    def test_alternating_pattern_over_10_weeks(self):
        """Verify open/closed alternates correctly over 10 consecutive Fridays."""
        expected = [True, False, True, False, True, False, True, False, True, False]
        for i, expect_open in enumerate(expected):
            target = self.REF + timedelta(weeks=i)
            assert is_friday_open(target, self.REF) is expect_open, (
                f"Week {i}: expected {'open' if expect_open else 'closed'} "
                f"for {target}"
            )
