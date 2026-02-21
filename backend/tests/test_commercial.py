"""
Tests for the commercial module: insurance discovery, batch eligibility, ROI service.
All database and HTTP calls are mocked -- no live connections required.
"""
import pytest
from datetime import date, time, datetime, timezone
from decimal import Decimal
from unittest.mock import patch, AsyncMock, MagicMock
from uuid import uuid4
import httpx

# ---------------------------------------------------------------------------
# insurance_discovery tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_discover_insurance_no_api_key():
    """When STEDI_API_KEY is empty and no key passed, return found=False with error."""
    mock_settings = MagicMock()
    mock_settings.STEDI_API_KEY = ""
    with patch("app.commercial.insurance_discovery.get_settings", return_value=mock_settings):
        from app.commercial.insurance_discovery import discover_insurance
        result = await discover_insurance(
            first_name="Jane", last_name="Doe", dob="1990-01-15",
            practice_npi="1234567890", practice_name="Test Practice", api_key="",
        )
    assert result["found"] is False
    assert "not configured" in result["error"]


@pytest.mark.asyncio
async def test_discover_insurance_found():
    """When a payer returns active coverage, result should contain carrier info."""
    mock_settings = MagicMock()
    mock_settings.STEDI_API_KEY = "test-key-123"
    active_response = httpx.Response(
        200,
        json={
            "planStatus": [{"status": "Active Coverage", "planDetails": "Gold PPO"}],
            "subscriber": {"memberId": "MEM999"},
        },
        request=httpx.Request("POST", "https://example.com"),
    )
    with patch("app.commercial.insurance_discovery.get_settings", return_value=mock_settings):
        from app.commercial.insurance_discovery import discover_insurance
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=active_response):
            result = await discover_insurance(
                first_name="Jane", last_name="Doe", dob="1990-01-15",
                practice_npi="1234567890", practice_name="Test Practice",
            )
    assert result["found"] is True
    assert result["is_active"] is True
    assert result["member_id"] == "MEM999"
    assert result["plan_name"] == "Gold PPO"
    assert result["error"] is None


@pytest.mark.asyncio
async def test_discover_insurance_not_found():
    """When all payers return non-active status, result should be found=False."""
    mock_settings = MagicMock()
    mock_settings.STEDI_API_KEY = "test-key-123"
    inactive_response = httpx.Response(
        200,
        json={"planStatus": [{"status": "Inactive"}], "subscriber": {}},
        request=httpx.Request("POST", "https://example.com"),
    )
    with patch("app.commercial.insurance_discovery.get_settings", return_value=mock_settings):
        from app.commercial.insurance_discovery import discover_insurance
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=inactive_response):
            result = await discover_insurance(
                first_name="John", last_name="Smith", dob="1985-06-20",
                practice_npi="1234567890", practice_name="Test Practice",
            )
    assert result["found"] is False
    assert result["is_active"] is False
    assert "No active insurance" in result["error"]


@pytest.mark.asyncio
async def test_check_payer_non_200_returns_none():
    """A 404 response from Stedi should cause _check_payer to return None."""
    from app.commercial.insurance_discovery import _check_payer
    error_response = httpx.Response(
        404, json={"error": "not found"},
        request=httpx.Request("POST", "https://example.com"),
    )
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=error_response)
    result = await _check_payer(
        client=mock_client, payer_id="00901", carrier_name="Cigna",
        first_name="Jane", last_name="Doe", dob="19900115",
        practice_npi="1234567890", practice_name="Test Practice", api_key="test-key",
    )
    assert result is None


@pytest.mark.asyncio
async def test_check_payer_active_status():
    """A 200 response with planStatus Active Coverage should return member info."""
    from app.commercial.insurance_discovery import _check_payer
    ok_response = httpx.Response(
        200,
        json={
            "planStatus": [{"status": "Active Coverage", "planDetails": "Silver HMO"}],
            "subscriber": {"memberId": "ABC123"},
        },
        request=httpx.Request("POST", "https://example.com"),
    )
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=ok_response)
    result = await _check_payer(
        client=mock_client, payer_id="62308", carrier_name="UHC",
        first_name="Jane", last_name="Doe", dob="19900115",
        practice_npi="1234567890", practice_name="Test Practice", api_key="test-key",
    )
    assert result is not None
    assert result["is_active"] is True
    assert result["member_id"] == "ABC123"
    assert result["plan_name"] == "Silver HMO"


# ---------------------------------------------------------------------------
# batch_eligibility tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_batch_status_formats_correctly():
    """get_batch_status should format raw DB rows into dashboard-ready dicts."""
    from app.commercial.batch_eligibility import get_batch_status

    practice_id = uuid4()
    target_date = date(2025, 6, 15)

    mock_row = MagicMock()
    mock_row.appointment_id = uuid4()
    mock_row.date = target_date
    mock_row.time = time(9, 30)
    mock_row.appt_status = "confirmed"
    mock_row.first_name = "Maria"
    mock_row.last_name = "Garcia"
    mock_row.insurance_carrier = "Aetna"
    mock_row.member_id = "AET456"
    mock_row.verification_status = "success"
    mock_row.insurance_active = True
    mock_row.plan_name = "Gold PPO"
    mock_row.copay = Decimal("25.00")
    mock_row.verified_at = datetime(2025, 6, 14, 22, 0, tzinfo=timezone.utc)

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [mock_row]
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    rows = await get_batch_status(mock_db, practice_id, target_date)

    assert len(rows) == 1
    row = rows[0]
    assert row["patient_name"] == "Maria Garcia"
    assert row["time"] == "09:30"
    assert row["insurance_carrier"] == "Aetna"
    assert row["verification_status"] == "success"
    assert row["copay"] == 25.0
    assert row["insurance_active"] is True
    assert row["plan_name"] == "Gold PPO"


# ---------------------------------------------------------------------------
# roi_service tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_roi_config_defaults():
    """When no DB row exists, get_roi_config returns hard-coded defaults."""
    from app.commercial.roi_service import (
        get_roi_config, DEFAULT_STAFF_HOURLY_COST, DEFAULT_AVG_APPOINTMENT_VALUE,
        DEFAULT_HUMAN_RECEPTIONIST_MONTHLY, DEFAULT_AVG_CALL_DURATION_MIN,
        DEFAULT_NO_SHOW_REDUCTION,
    )
    practice_id = uuid4()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = None
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    config = await get_roi_config(mock_db, practice_id)

    assert config["staff_hourly_cost"] == DEFAULT_STAFF_HOURLY_COST
    assert config["avg_appointment_value"] == DEFAULT_AVG_APPOINTMENT_VALUE
    assert config["human_receptionist_monthly_cost"] == DEFAULT_HUMAN_RECEPTIONIST_MONTHLY
    assert config["avg_call_duration_minutes"] == DEFAULT_AVG_CALL_DURATION_MIN
    assert config["no_show_reduction_rate"] == DEFAULT_NO_SHOW_REDUCTION


@pytest.mark.asyncio
async def test_get_roi_config_from_db():
    """When a DB row exists with custom values, get_roi_config uses them."""
    from app.commercial.roi_service import get_roi_config
    practice_id = uuid4()

    mock_row = MagicMock()
    mock_row.staff_hourly_cost = Decimal("35.00")
    mock_row.avg_appointment_value = Decimal("200.00")
    mock_row.human_receptionist_monthly_cost = Decimal("4200.00")
    mock_row.avg_call_duration_minutes = Decimal("5.00")
    mock_row.no_show_reduction_rate = Decimal("0.50")

    mock_result = MagicMock()
    mock_result.fetchone.return_value = mock_row
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    config = await get_roi_config(mock_db, practice_id)

    assert config["staff_hourly_cost"] == Decimal("35.00")
    assert config["avg_appointment_value"] == Decimal("200.00")
    assert config["human_receptionist_monthly_cost"] == Decimal("4200.00")
    assert config["avg_call_duration_minutes"] == Decimal("5.00")
    assert config["no_show_reduction_rate"] == Decimal("0.50")
