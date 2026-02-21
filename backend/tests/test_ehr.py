"""
Tests for the EHR module: adapter factory, dataclasses, athenahealth, drchrono.
All HTTP calls are mocked -- no live EHR connections required.
"""
import pytest
from datetime import date, time, datetime
from unittest.mock import patch, AsyncMock, MagicMock
import httpx

from app.ehr.adapter import (
    EHRAdapter, EHRPatient, EHRSlot, EHRAppointment, EHRProvider, get_adapter,
)

# ---------------------------------------------------------------------------
# adapter.py -- factory + dataclass tests
# ---------------------------------------------------------------------------

def test_get_adapter_athenahealth():
    """get_adapter('athenahealth') should return an AthenaHealthAdapter instance."""
    adapter = get_adapter("athenahealth")
    from app.ehr.adapters.athenahealth import AthenaHealthAdapter
    assert isinstance(adapter, AthenaHealthAdapter)
    assert isinstance(adapter, EHRAdapter)


def test_get_adapter_drchrono():
    """get_adapter('drchrono') should return a DrChronoAdapter instance."""
    adapter = get_adapter("drchrono")
    from app.ehr.adapters.drchrono import DrChronoAdapter
    assert isinstance(adapter, DrChronoAdapter)
    assert isinstance(adapter, EHRAdapter)


def test_get_adapter_unknown_raises():
    """get_adapter with an unsupported type should raise ValueError."""
    with pytest.raises(ValueError, match="Unsupported EHR type"):
        get_adapter("some_unknown_ehr")


def test_ehr_patient_dataclass():
    """EHRPatient should store required fields and default optionals to None."""
    patient = EHRPatient(
        ehr_id="P100", first_name="Maria", last_name="Lopez", dob=date(1988, 3, 12),
    )
    assert patient.ehr_id == "P100"
    assert patient.first_name == "Maria"
    assert patient.last_name == "Lopez"
    assert patient.dob == date(1988, 3, 12)
    assert patient.phone is None
    assert patient.email is None
    assert patient.insurance_carrier is None
    assert patient.member_id is None


def test_ehr_slot_dataclass():
    """EHRSlot should default is_available to True."""
    slot = EHRSlot(
        date=date(2025, 7, 1), time=time(10, 0),
        duration_minutes=30, provider_ehr_id="DR1",
    )
    assert slot.is_available is True
    assert slot.duration_minutes == 30
    assert slot.provider_ehr_id == "DR1"


# ---------------------------------------------------------------------------
# athenahealth adapter tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_athena_connect_success():
    """Successful OAuth token exchange should make connect() return True."""
    from app.ehr.adapters.athenahealth import AthenaHealthAdapter
    adapter = AthenaHealthAdapter(
        client_id="cid", client_secret="csecret", practice_id="195900",
    )
    token_response = httpx.Response(
        200, json={"access_token": "tok_abc", "expires_in": 3600},
        request=httpx.Request("POST", "https://example.com"),
    )
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=token_response):
        result = await adapter.connect({
            "client_id": "cid", "client_secret": "csecret", "practice_id": "195900",
        })
    assert result is True
    assert adapter.access_token == "tok_abc"


@pytest.mark.asyncio
async def test_athena_connect_failure():
    """When the token endpoint raises an error, connect() should return False."""
    from app.ehr.adapters.athenahealth import AthenaHealthAdapter
    adapter = AthenaHealthAdapter(
        client_id="bad_id", client_secret="bad_secret", practice_id="195900",
    )
    with patch(
        "httpx.AsyncClient.post", new_callable=AsyncMock,
        side_effect=httpx.HTTPStatusError(
            "401 Unauthorized",
            request=httpx.Request("POST", "https://example.com"),
            response=httpx.Response(401),
        ),
    ):
        result = await adapter.connect({
            "client_id": "bad_id", "client_secret": "bad_secret", "practice_id": "195900",
        })
    assert result is False


@pytest.mark.asyncio
async def test_athena_search_patients():
    """search_patients should map athenahealth JSON to EHRPatient objects."""
    from app.ehr.adapters.athenahealth import AthenaHealthAdapter
    adapter = AthenaHealthAdapter()
    adapter.access_token = "tok_test"
    adapter.token_expires_at = datetime(2099, 1, 1)

    api_response = httpx.Response(
        200,
        json={"patients": [
            {
                "patientid": "12345", "firstname": "Carlos", "lastname": "Rivera",
                "dob": "03/15/1975", "mobilephone": "5551234567",
                "email": "carlos@example.com",
            },
            {
                "patientid": "12346", "firstname": "Carlos",
                "lastname": "Rivera Jr", "dob": "11/20/2000",
            },
        ]},
        request=httpx.Request("GET", "https://example.com"),
    )
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.is_closed = False
    mock_client.get = AsyncMock(return_value=api_response)
    adapter._client = mock_client

    patients = await adapter.search_patients(first_name="Carlos", last_name="Rivera")

    assert len(patients) == 2
    assert patients[0].ehr_id == "12345"
    assert patients[0].first_name == "Carlos"
    assert patients[0].last_name == "Rivera"
    assert patients[0].dob == date(1975, 3, 15)
    assert patients[0].phone == "5551234567"
    assert patients[0].email == "carlos@example.com"
    assert patients[1].ehr_id == "12346"
    assert patients[1].phone is None


# ---------------------------------------------------------------------------
# drchrono adapter tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_drchrono_connect_success():
    """When /users/current returns 200, connect() should return True."""
    from app.ehr.adapters.drchrono import DrChronoAdapter
    adapter = DrChronoAdapter()
    ok_response = httpx.Response(
        200, json={"id": 1, "username": "doc@example.com"},
        request=httpx.Request("GET", "https://example.com"),
    )
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.is_closed = False
    mock_client.get = AsyncMock(return_value=ok_response)
    adapter._client = mock_client

    result = await adapter.connect({
        "access_token": "drc_tok_abc", "refresh_token": "drc_ref_xyz",
    })
    assert result is True
    assert adapter.access_token == "drc_tok_abc"
    assert adapter.refresh_token == "drc_ref_xyz"


@pytest.mark.asyncio
async def test_drchrono_search_patients():
    """search_patients should map DrChrono JSON results to EHRPatient objects."""
    from app.ehr.adapters.drchrono import DrChronoAdapter
    adapter = DrChronoAdapter(access_token="drc_tok")
    api_response = httpx.Response(
        200,
        json={"results": [{
            "id": 777, "first_name": "Ana", "last_name": "Martinez",
            "date_of_birth": "1992-08-25", "cell_phone": "5559876543",
            "email": "ana@example.com",
        }]},
        request=httpx.Request("GET", "https://example.com"),
    )
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.is_closed = False
    mock_client.get = AsyncMock(return_value=api_response)
    adapter._client = mock_client

    patients = await adapter.search_patients(last_name="Martinez")
    assert len(patients) == 1
    assert patients[0].ehr_id == "777"
    assert patients[0].first_name == "Ana"
    assert patients[0].last_name == "Martinez"
    assert patients[0].dob == date(1992, 8, 25)
    assert patients[0].phone == "5559876543"


@pytest.mark.asyncio
async def test_drchrono_get_available_slots():
    """Available slots = all 30-min blocks 9AM-5PM minus booked appointments."""
    from app.ehr.adapters.drchrono import DrChronoAdapter
    adapter = DrChronoAdapter(access_token="drc_tok")
    target = date(2025, 7, 10)

    # Two booked appointments: 10:00 and 14:30
    api_response = httpx.Response(
        200,
        json={"results": [
            {"id": 1, "scheduled_time": "2025-07-10T10:00:00Z", "status": "Confirmed"},
            {"id": 2, "scheduled_time": "2025-07-10T14:30:00Z", "status": "Confirmed"},
        ]},
        request=httpx.Request("GET", "https://example.com"),
    )
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.is_closed = False
    mock_client.get = AsyncMock(return_value=api_response)
    adapter._client = mock_client

    slots = await adapter.get_available_slots(provider_id="DR5", target_date=target)

    # 9AM-5PM in 30-min intervals = 16 total slots
    assert len(slots) == 16
    slot_map = {s.time: s for s in slots}

    # 10:00 and 14:30 should be marked unavailable
    assert slot_map[time(10, 0)].is_available is False
    assert slot_map[time(14, 30)].is_available is False
    # Other slots should be available
    assert slot_map[time(9, 0)].is_available is True
    assert slot_map[time(9, 30)].is_available is True
    assert slot_map[time(11, 0)].is_available is True
    assert slot_map[time(16, 30)].is_available is True
    # All slots reference correct provider and date
    for s in slots:
        assert s.provider_ehr_id == "DR5"
        assert s.date == target
        assert s.duration_minutes == 30
