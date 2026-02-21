"""
Tests for EHR adapter modules: factory, dataclasses, eClinicalWorks,
Elation Health, Generic FHIR, and MedicsCloud.

All HTTP calls are mocked -- no live EHR connections required.
"""
import pytest
from datetime import date, time, datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock, MagicMock

import httpx

from app.ehr.adapter import (
    EHRAdapter,
    EHRPatient,
    EHRAppointment,
    EHRSlot,
    EHRProvider,
    get_adapter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fhir_bundle(entries: list[dict]) -> dict:
    """Build a standard FHIR Bundle response wrapping a list of resources."""
    return {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": len(entries),
        "entry": [{"resource": r} for r in entries],
    }


def _make_fhir_patient(
    patient_id: str = "fhir-p1",
    given: str = "Maria",
    family: str = "Lopez",
    birth_date: str = "1988-03-12",
    phone: str | None = "5551234567",
    email: str | None = "maria@example.com",
) -> dict:
    """Create a standard FHIR Patient resource dict."""
    telecom = []
    if phone:
        telecom.append({"system": "phone", "value": phone, "use": "mobile"})
    if email:
        telecom.append({"system": "email", "value": email})
    return {
        "resourceType": "Patient",
        "id": patient_id,
        "name": [{"family": family, "given": [given], "use": "official"}],
        "birthDate": birth_date,
        "telecom": telecom,
    }


def _make_fhir_appointment(
    appt_id: str = "fhir-a1",
    patient_id: str = "fhir-p1",
    provider_id: str = "fhir-dr1",
    status: str = "booked",
    start: str = "2025-07-10T10:00:00+00:00",
    end: str = "2025-07-10T10:30:00+00:00",
    appt_type_code: str = "followup",
) -> dict:
    """Create a standard FHIR Appointment resource dict."""
    return {
        "resourceType": "Appointment",
        "id": appt_id,
        "status": status,
        "start": start,
        "end": end,
        "appointmentType": {"coding": [{"code": appt_type_code}]},
        "participant": [
            {"actor": {"reference": f"Patient/{patient_id}"}, "status": "accepted"},
            {"actor": {"reference": f"Practitioner/{provider_id}"}, "status": "accepted"},
        ],
    }


def _mock_httpx_response(status_code: int, json_data: dict) -> httpx.Response:
    """Build an httpx.Response suitable for mocking."""
    return httpx.Response(
        status_code,
        json=json_data,
        request=httpx.Request("GET", "https://mock.test"),
    )


def _make_mock_client(get_resp=None, post_resp=None) -> AsyncMock:
    """Create a mock httpx.AsyncClient with preset GET/POST responses."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.is_closed = False
    if get_resp is not None:
        mock_client.get = AsyncMock(return_value=get_resp)
    if post_resp is not None:
        mock_client.post = AsyncMock(return_value=post_resp)
    return mock_client


# ===========================================================================
# 1. adapter.py — Factory + Dataclasses
# ===========================================================================


class TestAdapterFactory:
    """Tests for get_adapter() and the adapter registry."""

    def test_get_adapter_raises_for_unsupported_type(self):
        """get_adapter should raise ValueError for an unknown EHR type."""
        with pytest.raises(ValueError, match="Unsupported EHR type: epic"):
            get_adapter("epic")

    def test_get_adapter_athenahealth(self):
        adapter = get_adapter("athenahealth")
        assert type(adapter).__name__ == "AthenaHealthAdapter"
        assert isinstance(adapter, EHRAdapter)

    def test_get_adapter_drchrono(self):
        adapter = get_adapter("drchrono")
        assert type(adapter).__name__ == "DrChronoAdapter"
        assert isinstance(adapter, EHRAdapter)

    def test_get_adapter_medicscloud(self):
        adapter = get_adapter("medicscloud")
        assert type(adapter).__name__ == "MedicsCloudAdapter"
        assert isinstance(adapter, EHRAdapter)

    def test_get_adapter_fhir_generic(self):
        adapter = get_adapter("fhir_generic")
        assert type(adapter).__name__ == "GenericFHIRAdapter"
        assert isinstance(adapter, EHRAdapter)

    def test_get_adapter_eclinicalworks(self):
        adapter = get_adapter("eclinicalworks")
        assert type(adapter).__name__ == "EClinicalWorksAdapter"
        assert isinstance(adapter, EHRAdapter)

    def test_get_adapter_elation(self):
        adapter = get_adapter("elation")
        assert type(adapter).__name__ == "ElationHealthAdapter"
        assert isinstance(adapter, EHRAdapter)

    def test_all_six_supported_types_resolve(self):
        """All six registered types should instantiate without error."""
        supported = [
            "athenahealth", "drchrono", "medicscloud",
            "fhir_generic", "eclinicalworks", "elation",
        ]
        for ehr_type in supported:
            adapter = get_adapter(ehr_type)
            assert isinstance(adapter, EHRAdapter), (
                f"get_adapter('{ehr_type}') did not return an EHRAdapter"
            )


class TestDataclasses:
    """Tests for the EHR dataclasses defined in adapter.py."""

    def test_ehr_patient_required_fields(self):
        patient = EHRPatient(
            ehr_id="P100",
            first_name="Maria",
            last_name="Lopez",
            dob=date(1988, 3, 12),
        )
        assert patient.ehr_id == "P100"
        assert patient.first_name == "Maria"
        assert patient.last_name == "Lopez"
        assert patient.dob == date(1988, 3, 12)

    def test_ehr_patient_optional_fields_default_none(self):
        patient = EHRPatient(
            ehr_id="P200", first_name="John", last_name="Doe",
            dob=date(1990, 1, 1),
        )
        assert patient.phone is None
        assert patient.email is None
        assert patient.insurance_carrier is None
        assert patient.member_id is None

    def test_ehr_patient_with_all_fields(self):
        patient = EHRPatient(
            ehr_id="P300",
            first_name="Ana",
            last_name="Garcia",
            dob=date(1975, 5, 20),
            phone="5551112222",
            email="ana@example.com",
            insurance_carrier="Aetna",
            member_id="AET-99887766",
        )
        assert patient.phone == "5551112222"
        assert patient.email == "ana@example.com"
        assert patient.insurance_carrier == "Aetna"
        assert patient.member_id == "AET-99887766"

    def test_ehr_appointment_creation(self):
        appt = EHRAppointment(
            ehr_id="A1",
            patient_ehr_id="P1",
            provider_ehr_id="DR1",
            appointment_type="new_patient",
            date=date(2025, 7, 10),
            time=time(9, 30),
            duration_minutes=30,
            status="booked",
        )
        assert appt.ehr_id == "A1"
        assert appt.patient_ehr_id == "P1"
        assert appt.provider_ehr_id == "DR1"
        assert appt.appointment_type == "new_patient"
        assert appt.date == date(2025, 7, 10)
        assert appt.time == time(9, 30)
        assert appt.duration_minutes == 30
        assert appt.status == "booked"
        assert appt.notes is None

    def test_ehr_appointment_with_notes(self):
        appt = EHRAppointment(
            ehr_id="A2",
            patient_ehr_id="P2",
            provider_ehr_id="DR2",
            appointment_type="followup",
            date=date(2025, 8, 1),
            time=time(14, 0),
            duration_minutes=15,
            status="booked",
            notes="Follow-up for blood work results",
        )
        assert appt.notes == "Follow-up for blood work results"

    def test_ehr_slot_default_is_available(self):
        slot = EHRSlot(
            date=date(2025, 7, 1),
            time=time(10, 0),
            duration_minutes=30,
            provider_ehr_id="DR1",
        )
        assert slot.is_available is True

    def test_ehr_slot_explicit_unavailable(self):
        slot = EHRSlot(
            date=date(2025, 7, 1),
            time=time(10, 0),
            duration_minutes=30,
            provider_ehr_id="DR1",
            is_available=False,
        )
        assert slot.is_available is False

    def test_ehr_provider_required_fields(self):
        provider = EHRProvider(ehr_id="DR1", name="Dr. Smith")
        assert provider.ehr_id == "DR1"
        assert provider.name == "Dr. Smith"

    def test_ehr_provider_optional_fields_default_none(self):
        provider = EHRProvider(ehr_id="DR2", name="Dr. Jones")
        assert provider.npi is None
        assert provider.specialty is None

    def test_ehr_provider_with_optional_fields(self):
        provider = EHRProvider(
            ehr_id="DR3",
            name="Dr. Neofitos Stefanides",
            npi="1689880429",
            specialty="Internal Medicine",
        )
        assert provider.npi == "1689880429"
        assert provider.specialty == "Internal Medicine"


# ===========================================================================
# 2. eClinicalWorks Adapter
# ===========================================================================


class TestEClinicalWorksAdapter:
    """Tests for EClinicalWorksAdapter (FHIR R4 based)."""

    def setup_method(self):
        from app.ehr.adapters.eclinicalworks import EClinicalWorksAdapter
        self.adapter = EClinicalWorksAdapter()

    def test_initial_state(self):
        """Adapter should start with empty tokens and no client."""
        assert self.adapter.access_token == ""
        assert self.adapter.token_expires_at is None
        assert self.adapter._client is None

    def test_default_urls(self):
        from app.ehr.adapters.eclinicalworks import ECW_DEFAULT_FHIR_BASE, ECW_TOKEN_URL
        assert ECW_DEFAULT_FHIR_BASE == "https://fhir.eclinicalworks.com/fhir/r4"
        assert ECW_TOKEN_URL == "https://oauthserver.eclinicalworks.com/oauth/token"
        assert self.adapter.fhir_base_url == ECW_DEFAULT_FHIR_BASE

    async def test_connect_success(self):
        """connect() should return True and store token on successful OAuth."""
        token_resp = _mock_httpx_response(200, {
            "access_token": "ecw_tok_123",
            "expires_in": 3600,
        })
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=token_resp):
            result = await self.adapter.connect({
                "client_id": "test_cid",
                "client_secret": "test_csecret",
                "practice_id": "ecw_practice_1",
            })
        assert result is True
        assert self.adapter.access_token == "ecw_tok_123"
        assert self.adapter.client_id == "test_cid"
        assert self.adapter.client_secret == "test_csecret"
        assert self.adapter.practice_id == "ecw_practice_1"

    async def test_connect_failure_bad_credentials(self):
        """connect() should return False when OAuth token request fails."""
        with patch(
            "httpx.AsyncClient.post",
            new_callable=AsyncMock,
            side_effect=httpx.HTTPStatusError(
                "401 Unauthorized",
                request=httpx.Request("POST", "https://mock.test"),
                response=httpx.Response(401),
            ),
        ):
            result = await self.adapter.connect({
                "client_id": "bad_id",
                "client_secret": "bad_secret",
                "practice_id": "ecw_practice_1",
            })
        assert result is False

    async def test_connect_stores_custom_fhir_base_url(self):
        """connect() should accept and store a custom FHIR base URL."""
        token_resp = _mock_httpx_response(200, {
            "access_token": "tok_custom",
            "expires_in": 3600,
        })
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=token_resp):
            await self.adapter.connect({
                "client_id": "cid",
                "client_secret": "cs",
                "practice_id": "p1",
                "fhir_base_url": "https://custom.ecw.test/fhir/r4",
            })
        assert self.adapter.fhir_base_url == "https://custom.ecw.test/fhir/r4"

    async def test_health_check_connected(self):
        """health_check() should return True when /metadata returns 200."""
        self.adapter.access_token = "valid_token"
        self.adapter.token_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)

        metadata_resp = _mock_httpx_response(200, {"resourceType": "CapabilityStatement"})
        mock_client = _make_mock_client(get_resp=metadata_resp)
        self.adapter._client = mock_client

        result = await self.adapter.health_check()
        assert result is True
        mock_client.get.assert_called_once()

    async def test_health_check_not_connected(self):
        """health_check() should return False when no connection exists."""
        # No token, no client -- _ensure_token will fail inside _headers
        result = await self.adapter.health_check()
        assert result is False

    async def test_disconnect_clears_state(self):
        """disconnect() should clear token and close client."""
        self.adapter.access_token = "some_token"
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.aclose = AsyncMock()
        self.adapter._client = mock_client

        result = await self.adapter.disconnect()
        assert result is True
        assert self.adapter.access_token == ""
        mock_client.aclose.assert_called_once()

    def test_parse_fhir_patient_standard(self):
        """_parse_fhir_patient should parse a standard FHIR Patient resource."""
        fhir_resource = _make_fhir_patient(
            patient_id="ecw-p1",
            given="Carlos",
            family="Rivera",
            birth_date="1975-03-15",
            phone="5551234567",
            email="carlos@example.com",
        )
        patient = self.adapter._parse_fhir_patient(fhir_resource)
        assert isinstance(patient, EHRPatient)
        assert patient.ehr_id == "ecw-p1"
        assert patient.first_name == "Carlos"
        assert patient.last_name == "Rivera"
        assert patient.dob == date(1975, 3, 15)
        assert patient.phone == "5551234567"
        assert patient.email == "carlos@example.com"

    def test_parse_fhir_patient_no_telecom(self):
        """_parse_fhir_patient should handle missing telecom gracefully."""
        fhir_resource = _make_fhir_patient(
            patient_id="ecw-p2",
            given="Ana",
            family="Martinez",
            birth_date="1992-08-25",
            phone=None,
            email=None,
        )
        patient = self.adapter._parse_fhir_patient(fhir_resource)
        assert patient.phone is None
        assert patient.email is None

    def test_parse_fhir_patient_missing_birth_date(self):
        """_parse_fhir_patient should default DOB to today if missing."""
        fhir_resource = {
            "resourceType": "Patient",
            "id": "ecw-p3",
            "name": [{"family": "Test", "given": ["No"]}],
            "birthDate": "",
        }
        patient = self.adapter._parse_fhir_patient(fhir_resource)
        assert patient.dob == date.today()

    def test_parse_fhir_patient_empty_name(self):
        """_parse_fhir_patient should handle empty name arrays."""
        fhir_resource = {
            "resourceType": "Patient",
            "id": "ecw-p4",
            "name": [],
            "birthDate": "2000-01-01",
        }
        patient = self.adapter._parse_fhir_patient(fhir_resource)
        assert patient.first_name == ""
        assert patient.last_name == ""

    async def test_search_patients_returns_list(self):
        """search_patients should parse FHIR Bundle into EHRPatient list."""
        self.adapter.access_token = "tok_test"
        self.adapter.token_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)

        bundle = _make_fhir_bundle([
            _make_fhir_patient("ecw-p10", "Maria", "Lopez", "1988-03-12"),
            _make_fhir_patient("ecw-p11", "Juan", "Garcia", "1995-06-01"),
        ])
        bundle_resp = _mock_httpx_response(200, bundle)
        mock_client = _make_mock_client(get_resp=bundle_resp)
        self.adapter._client = mock_client

        patients = await self.adapter.search_patients(last_name="Lopez")
        assert len(patients) == 2
        assert patients[0].ehr_id == "ecw-p10"
        assert patients[0].first_name == "Maria"
        assert patients[0].last_name == "Lopez"
        assert patients[1].ehr_id == "ecw-p11"
        assert patients[1].first_name == "Juan"

    async def test_search_patients_empty_bundle(self):
        """search_patients should return empty list for Bundle with no entries."""
        self.adapter.access_token = "tok_test"
        self.adapter.token_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)

        empty_bundle = {"resourceType": "Bundle", "type": "searchset", "total": 0}
        bundle_resp = _mock_httpx_response(200, empty_bundle)
        mock_client = _make_mock_client(get_resp=bundle_resp)
        self.adapter._client = mock_client

        patients = await self.adapter.search_patients(first_name="Nobody")
        assert patients == []

    async def test_get_providers_parses_npi_and_specialty(self):
        """get_providers should extract NPI from identifiers and specialty from qualification."""
        self.adapter.access_token = "tok_test"
        self.adapter.token_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)

        practitioner = {
            "resourceType": "Practitioner",
            "id": "dr-100",
            "name": [{"family": "Stefanides", "given": ["Neofitos"]}],
            "identifier": [
                {"system": "http://hl7.org/fhir/sid/us-npi", "value": "1689880429"},
            ],
            "qualification": [
                {"code": {"text": "Internal Medicine"}},
            ],
        }
        bundle = _make_fhir_bundle([practitioner])
        bundle_resp = _mock_httpx_response(200, bundle)
        mock_client = _make_mock_client(get_resp=bundle_resp)
        self.adapter._client = mock_client

        providers = await self.adapter.get_providers()
        assert len(providers) == 1
        assert providers[0].ehr_id == "dr-100"
        assert providers[0].name == "Neofitos Stefanides"
        assert providers[0].npi == "1689880429"
        assert providers[0].specialty == "Internal Medicine"

    async def test_get_available_slots_parses_fhir_slots(self):
        """get_available_slots should parse FHIR Slot resources."""
        self.adapter.access_token = "tok_test"
        self.adapter.token_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)

        slot_resource = {
            "resourceType": "Slot",
            "id": "slot-1",
            "start": "2025-07-10T09:00:00+00:00",
            "end": "2025-07-10T09:30:00+00:00",
            "status": "free",
        }
        bundle = _make_fhir_bundle([slot_resource])
        bundle_resp = _mock_httpx_response(200, bundle)
        mock_client = _make_mock_client(get_resp=bundle_resp)
        self.adapter._client = mock_client

        slots = await self.adapter.get_available_slots("DR1", date(2025, 7, 10))
        assert len(slots) == 1
        assert slots[0].date == date(2025, 7, 10)
        assert slots[0].time == time(9, 0)
        assert slots[0].duration_minutes == 30
        assert slots[0].provider_ehr_id == "DR1"
        assert slots[0].is_available is True

    async def test_book_appointment_returns_appointment(self):
        """book_appointment should POST FHIR Appointment and return EHRAppointment."""
        self.adapter.access_token = "tok_test"
        self.adapter.token_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)

        post_resp = _mock_httpx_response(201, {"id": "appt-new-1", "resourceType": "Appointment"})
        mock_client = _make_mock_client(post_resp=post_resp)
        self.adapter._client = mock_client

        slot = EHRSlot(
            date=date(2025, 7, 10),
            time=time(9, 0),
            duration_minutes=30,
            provider_ehr_id="DR1",
        )
        appt = await self.adapter.book_appointment("P1", slot, "new_patient", "First visit")
        assert isinstance(appt, EHRAppointment)
        assert appt.ehr_id == "appt-new-1"
        assert appt.patient_ehr_id == "P1"
        assert appt.provider_ehr_id == "DR1"
        assert appt.appointment_type == "new_patient"
        assert appt.status == "booked"
        assert appt.notes == "First visit"


# ===========================================================================
# 3. Elation Health Adapter
# ===========================================================================


class TestElationHealthAdapter:
    """Tests for ElationHealthAdapter (REST API v2)."""

    def setup_method(self):
        from app.ehr.adapters.elation import ElationHealthAdapter
        self.adapter = ElationHealthAdapter()

    def test_initial_state(self):
        assert self.adapter.access_token == ""
        assert self.adapter.token_expires_at is None
        assert self.adapter._client is None

    def test_default_urls(self):
        from app.ehr.adapters.elation import ELATION_API_BASE, ELATION_TOKEN_URL
        assert ELATION_API_BASE == "https://api.elationhealth.com/api/2.0"
        assert ELATION_TOKEN_URL == "https://api.elationhealth.com/oauth2/token"

    async def test_connect_success(self):
        """connect() should return True and store token on successful OAuth."""
        token_resp = _mock_httpx_response(200, {
            "access_token": "elation_tok_abc",
            "expires_in": 7200,
        })
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=token_resp):
            result = await self.adapter.connect({
                "client_id": "el_cid",
                "client_secret": "el_csecret",
            })
        assert result is True
        assert self.adapter.access_token == "elation_tok_abc"
        assert self.adapter.client_id == "el_cid"
        assert self.adapter.client_secret == "el_csecret"

    async def test_connect_failure(self):
        """connect() should return False when token request fails."""
        with patch(
            "httpx.AsyncClient.post",
            new_callable=AsyncMock,
            side_effect=httpx.HTTPStatusError(
                "403 Forbidden",
                request=httpx.Request("POST", "https://mock.test"),
                response=httpx.Response(403),
            ),
        ):
            result = await self.adapter.connect({
                "client_id": "bad",
                "client_secret": "bad",
            })
        assert result is False

    async def test_health_check_connected(self):
        """health_check() should return True when /providers returns 200."""
        self.adapter.access_token = "valid_token"
        self.adapter.token_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)

        providers_resp = _mock_httpx_response(200, {"results": []})
        mock_client = _make_mock_client(get_resp=providers_resp)
        self.adapter._client = mock_client

        result = await self.adapter.health_check()
        assert result is True

    async def test_health_check_not_connected(self):
        """health_check() should return False when no valid token."""
        result = await self.adapter.health_check()
        assert result is False

    async def test_disconnect_clears_state(self):
        """disconnect() should clear token and close client."""
        self.adapter.access_token = "some_token"
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.aclose = AsyncMock()
        self.adapter._client = mock_client

        result = await self.adapter.disconnect()
        assert result is True
        assert self.adapter.access_token == ""
        mock_client.aclose.assert_called_once()

    async def test_disconnect_when_no_client(self):
        """disconnect() should succeed even when _client is None."""
        self.adapter._client = None
        result = await self.adapter.disconnect()
        assert result is True
        assert self.adapter.access_token == ""

    async def test_search_patients(self):
        """search_patients should parse Elation REST response into EHRPatient list."""
        self.adapter.access_token = "tok_test"
        self.adapter.token_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)

        api_resp = _mock_httpx_response(200, {
            "results": [
                {
                    "id": 42,
                    "first_name": "Elena",
                    "last_name": "Vasquez",
                    "date_of_birth": "1985-11-22",
                    "primary_phone": "5559876543",
                    "email": "elena@example.com",
                },
            ],
        })
        mock_client = _make_mock_client(get_resp=api_resp)
        self.adapter._client = mock_client

        patients = await self.adapter.search_patients(last_name="Vasquez")
        assert len(patients) == 1
        assert patients[0].ehr_id == "42"
        assert patients[0].first_name == "Elena"
        assert patients[0].last_name == "Vasquez"
        assert patients[0].dob == date(1985, 11, 22)
        assert patients[0].phone == "5559876543"
        assert patients[0].email == "elena@example.com"

    async def test_get_providers(self):
        """get_providers should return EHRProvider list from Elation REST response."""
        self.adapter.access_token = "tok_test"
        self.adapter.token_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)

        api_resp = _mock_httpx_response(200, {
            "results": [
                {
                    "id": 99,
                    "first_name": "Jane",
                    "last_name": "Doe",
                    "npi": "1234567890",
                    "specialty": "Family Medicine",
                },
            ],
        })
        mock_client = _make_mock_client(get_resp=api_resp)
        self.adapter._client = mock_client

        providers = await self.adapter.get_providers()
        assert len(providers) == 1
        assert providers[0].ehr_id == "99"
        assert providers[0].name == "Jane Doe"
        assert providers[0].npi == "1234567890"
        assert providers[0].specialty == "Family Medicine"

    async def test_get_appointment_types(self):
        """get_appointment_types should return list of dicts from REST response."""
        self.adapter.access_token = "tok_test"
        self.adapter.token_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)

        api_resp = _mock_httpx_response(200, {
            "results": [
                {"id": 1, "name": "New Patient", "duration": 30, "is_default": True},
                {"id": 2, "name": "Follow-Up", "duration": 15, "is_default": False},
            ],
        })
        mock_client = _make_mock_client(get_resp=api_resp)
        self.adapter._client = mock_client

        types = await self.adapter.get_appointment_types()
        assert len(types) == 2
        assert types[0]["name"] == "New Patient"
        assert types[0]["duration"] == 30
        assert types[0]["generic"] is True
        assert types[1]["name"] == "Follow-Up"
        assert types[1]["generic"] is False


# ===========================================================================
# 4. Generic FHIR Adapter
# ===========================================================================


class TestGenericFHIRAdapter:
    """Tests for GenericFHIRAdapter with multiple auth types."""

    def setup_method(self):
        from app.ehr.adapters.fhir_generic import GenericFHIRAdapter
        self.adapter = GenericFHIRAdapter()

    def test_initial_state(self):
        assert self.adapter.access_token == ""
        assert self.adapter.auth_type == "bearer"
        assert self.adapter._client is None
        assert self.adapter._token_endpoint == ""

    async def test_connect_bearer_auth(self):
        """Bearer auth connect should simply store the token and succeed."""
        result = await self.adapter.connect({
            "base_url": "https://fhir.example.com",
            "auth_type": "bearer",
            "bearer_token": "my_static_token",
        })
        assert result is True
        assert self.adapter.access_token == "my_static_token"
        assert self.adapter.base_url == "https://fhir.example.com"

    async def test_connect_basic_auth(self):
        """Basic auth connect should succeed without token exchange."""
        result = await self.adapter.connect({
            "base_url": "https://fhir.example.com",
            "auth_type": "basic",
            "username": "user",
            "password": "pass123",
        })
        assert result is True
        assert self.adapter.auth_type == "basic"
        assert self.adapter.username == "user"
        assert self.adapter.password == "pass123"

    async def test_connect_basic_auth_headers(self):
        """Basic auth should produce a valid Authorization header."""
        import base64
        self.adapter.auth_type = "basic"
        self.adapter.username = "testuser"
        self.adapter.password = "testpass"
        headers = await self.adapter._headers()
        expected_creds = base64.b64encode(b"testuser:testpass").decode()
        assert headers["Authorization"] == f"Basic {expected_creds}"

    async def test_connect_smart_auth_discovery(self):
        """SMART auth connect should discover token endpoint from .well-known."""
        smart_config_resp = _mock_httpx_response(200, {
            "token_endpoint": "https://auth.fhir.example.com/token",
            "authorization_endpoint": "https://auth.fhir.example.com/authorize",
        })
        token_resp = _mock_httpx_response(200, {
            "access_token": "smart_tok_xyz",
            "expires_in": 3600,
        })

        call_count = 0

        async def side_effect_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return smart_config_resp

        async def side_effect_post(*args, **kwargs):
            return token_resp

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=side_effect_get):
            with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=side_effect_post):
                result = await self.adapter.connect({
                    "base_url": "https://fhir.example.com",
                    "auth_type": "smart",
                    "client_id": "smart_cid",
                    "client_secret": "smart_cs",
                })
        assert result is True
        assert self.adapter.access_token == "smart_tok_xyz"
        assert self.adapter._token_endpoint == "https://auth.fhir.example.com/token"

    async def test_health_check_hits_metadata(self):
        """health_check() should GET /metadata and return True on 200."""
        self.adapter.auth_type = "bearer"
        self.adapter.bearer_token = "tok_test"
        self.adapter.access_token = "tok_test"

        metadata_resp = _mock_httpx_response(200, {"resourceType": "CapabilityStatement"})
        mock_client = _make_mock_client(get_resp=metadata_resp)
        self.adapter._client = mock_client

        result = await self.adapter.health_check()
        assert result is True
        mock_client.get.assert_called_once()
        call_args = mock_client.get.call_args
        assert call_args[0][0] == "/metadata"

    async def test_health_check_returns_false_on_error(self):
        """health_check() should return False when /metadata fails."""
        result = await self.adapter.health_check()
        assert result is False

    def test_get_bundle_entries_standard(self):
        """_get_bundle_entries should extract resources of the given type."""
        bundle = _make_fhir_bundle([
            _make_fhir_patient("p1"),
            _make_fhir_patient("p2"),
            {"resourceType": "OperationOutcome", "id": "err-1"},
        ])
        patients = self.adapter._get_bundle_entries(bundle, "Patient")
        assert len(patients) == 2
        assert patients[0]["id"] == "p1"
        assert patients[1]["id"] == "p2"

    def test_get_bundle_entries_empty_bundle(self):
        """_get_bundle_entries should return [] for an empty Bundle."""
        empty_bundle = {"resourceType": "Bundle", "type": "searchset", "total": 0}
        result = self.adapter._get_bundle_entries(empty_bundle, "Patient")
        assert result == []

    def test_get_bundle_entries_missing_entry_key(self):
        """_get_bundle_entries should handle missing 'entry' key gracefully."""
        bundle_no_entry = {"resourceType": "Bundle", "type": "searchset"}
        result = self.adapter._get_bundle_entries(bundle_no_entry, "Patient")
        assert result == []

    def test_get_bundle_entries_filters_by_resource_type(self):
        """_get_bundle_entries should only return matching resourceType."""
        bundle = _make_fhir_bundle([
            _make_fhir_patient("p1"),
            _make_fhir_appointment("a1"),
            _make_fhir_patient("p2"),
        ])
        appointments = self.adapter._get_bundle_entries(bundle, "Appointment")
        assert len(appointments) == 1
        assert appointments[0]["id"] == "a1"

    async def test_search_patients(self):
        """search_patients should use _get_bundle_entries to parse results."""
        self.adapter.auth_type = "bearer"
        self.adapter.bearer_token = "tok_test"
        self.adapter.access_token = "tok_test"

        bundle = _make_fhir_bundle([
            _make_fhir_patient("fp1", "Jane", "Smith", "1990-05-15", "5551112222"),
        ])
        bundle_resp = _mock_httpx_response(200, bundle)
        mock_client = _make_mock_client(get_resp=bundle_resp)
        self.adapter._client = mock_client

        patients = await self.adapter.search_patients(last_name="Smith")
        assert len(patients) == 1
        assert patients[0].ehr_id == "fp1"
        assert patients[0].first_name == "Jane"
        assert patients[0].last_name == "Smith"
        assert patients[0].dob == date(1990, 5, 15)

    async def test_disconnect_clears_token(self):
        """disconnect() should clear access_token and close client."""
        self.adapter.access_token = "should_be_cleared"
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.aclose = AsyncMock()
        self.adapter._client = mock_client

        result = await self.adapter.disconnect()
        assert result is True
        assert self.adapter.access_token == ""
        mock_client.aclose.assert_called_once()

    async def test_get_appointment_types_returns_empty(self):
        """Generic FHIR adapter always returns empty list for appointment types."""
        result = await self.adapter.get_appointment_types()
        assert result == []

    async def test_get_appointments_parses_bundle(self):
        """get_appointments should parse FHIR Appointment resources from Bundle."""
        self.adapter.auth_type = "bearer"
        self.adapter.bearer_token = "tok_test"
        self.adapter.access_token = "tok_test"

        bundle = _make_fhir_bundle([
            _make_fhir_appointment(
                appt_id="ga-1",
                patient_id="gp-1",
                provider_id="gdr-1",
                status="booked",
                start="2025-08-01T14:00:00+00:00",
                end="2025-08-01T14:30:00+00:00",
            ),
        ])
        bundle_resp = _mock_httpx_response(200, bundle)
        mock_client = _make_mock_client(get_resp=bundle_resp)
        self.adapter._client = mock_client

        appointments = await self.adapter.get_appointments(provider_id="gdr-1")
        assert len(appointments) == 1
        assert appointments[0].ehr_id == "ga-1"
        assert appointments[0].patient_ehr_id == "gp-1"
        assert appointments[0].provider_ehr_id == "gdr-1"
        assert appointments[0].status == "booked"
        assert appointments[0].date == date(2025, 8, 1)
        assert appointments[0].time == time(14, 0)
        assert appointments[0].duration_minutes == 30


# ===========================================================================
# 5. MedicsCloud Adapter
# ===========================================================================


class TestMedicsCloudAdapter:
    """Tests for MedicsCloudAdapter (Playwright browser automation).

    Since MedicsCloud uses Playwright for headless browser automation, we
    test only structure, constants, and error handling here -- no actual
    browser automation.
    """

    def setup_method(self):
        from app.ehr.adapters.medicscloud import MedicsCloudAdapter
        self.adapter = MedicsCloudAdapter()

    def test_adapter_class_exists_and_interface(self):
        """MedicsCloudAdapter should be an instance of EHRAdapter."""
        assert isinstance(self.adapter, EHRAdapter)

    def test_adapter_class_name(self):
        assert type(self.adapter).__name__ == "MedicsCloudAdapter"

    def test_selectors_dict_exists(self):
        """SELECTORS dict should be defined at module level."""
        from app.ehr.adapters.medicscloud import SELECTORS
        assert isinstance(SELECTORS, dict)

    def test_selectors_contains_required_keys(self):
        """SELECTORS should contain keys for all automated UI interactions."""
        from app.ehr.adapters.medicscloud import SELECTORS
        required_keys = [
            "login_username",
            "login_password",
            "login_button",
            "dashboard_indicator",
            "patient_search_input",
            "patient_results_table",
            "new_patient_btn",
            "scheduler_nav",
            "appointment_list",
            "provider_list",
            "cancel_btn",
            "confirm_dialog",
        ]
        for key in required_keys:
            assert key in SELECTORS, f"Missing SELECTORS key: {key}"

    def test_operation_delay_is_two_seconds(self):
        """OPERATION_DELAY should be 2.0 seconds."""
        from app.ehr.adapters.medicscloud import OPERATION_DELAY
        assert OPERATION_DELAY == 2.0

    def test_initial_state(self):
        """Adapter should start disconnected with no browser resources."""
        assert self.adapter._browser is None
        assert self.adapter._context is None
        assert self.adapter._page is None
        assert self.adapter._connected is False

    def test_default_base_url(self):
        assert self.adapter.base_url == "https://app.medicscloud.com"

    def test_kwargs_override_defaults(self):
        from app.ehr.adapters.medicscloud import MedicsCloudAdapter
        adapter = MedicsCloudAdapter(
            username="testuser",
            password="testpass",
            base_url="https://custom.medicscloud.com",
        )
        assert adapter.username == "testuser"
        assert adapter.password == "testpass"
        assert adapter.base_url == "https://custom.medicscloud.com"

    async def test_connect_raises_when_playwright_not_available(self):
        """connect() should return False when playwright is not importable."""
        with patch.object(
            self.adapter,
            "_ensure_playwright",
            new_callable=AsyncMock,
            side_effect=RuntimeError("playwright is not installed"),
        ):
            result = await self.adapter.connect({
                "username": "user",
                "password": "pass",
            })
        assert result is False

    async def test_health_check_when_not_connected(self):
        """health_check() should return False when not connected."""
        assert self.adapter._connected is False
        result = await self.adapter.health_check()
        assert result is False

    async def test_health_check_when_no_page(self):
        """health_check() should return False when _page is None."""
        self.adapter._connected = True
        self.adapter._page = None
        result = await self.adapter.health_check()
        assert result is False

    async def test_disconnect_resets_state(self):
        """disconnect() should reset all browser references and _connected."""
        self.adapter._connected = True
        self.adapter._browser = MagicMock()
        self.adapter._browser.close = AsyncMock()
        self.adapter._context = MagicMock()
        self.adapter._context.close = AsyncMock()
        self.adapter._page = MagicMock()
        self.adapter._page.close = AsyncMock()

        result = await self.adapter.disconnect()
        assert result is True
        assert self.adapter._connected is False
        assert self.adapter._page is None
        assert self.adapter._context is None
        assert self.adapter._browser is None

    async def test_search_patients_returns_empty_when_no_page(self):
        """search_patients should return [] when _page is None."""
        self.adapter._page = None
        patients = await self.adapter.search_patients(last_name="Test")
        assert patients == []

    async def test_get_available_slots_returns_empty_when_no_page(self):
        """get_available_slots should return [] when _page is None."""
        self.adapter._page = None
        slots = await self.adapter.get_available_slots("DR1", date(2025, 7, 10))
        assert slots == []

    async def test_get_appointments_returns_empty_when_no_page(self):
        """get_appointments should return [] when _page is None."""
        self.adapter._page = None
        appts = await self.adapter.get_appointments()
        assert appts == []

    async def test_get_providers_returns_empty_when_no_page(self):
        """get_providers should return [] when _page is None."""
        self.adapter._page = None
        providers = await self.adapter.get_providers()
        assert providers == []

    async def test_get_appointment_types_returns_empty(self):
        """get_appointment_types always returns empty list for MedicsCloud."""
        result = await self.adapter.get_appointment_types()
        assert result == []

    async def test_create_patient_raises_when_not_connected(self):
        """create_patient should raise RuntimeError when _page is None."""
        self.adapter._page = None
        patient = EHRPatient(
            ehr_id="", first_name="Test", last_name="User", dob=date(2000, 1, 1),
        )
        with pytest.raises(RuntimeError, match="Not connected"):
            await self.adapter.create_patient(patient)

    async def test_update_patient_raises_when_not_connected(self):
        """update_patient should raise RuntimeError when _page is None."""
        self.adapter._page = None
        patient = EHRPatient(
            ehr_id="P1", first_name="Test", last_name="User", dob=date(2000, 1, 1),
        )
        with pytest.raises(RuntimeError, match="Not connected"):
            await self.adapter.update_patient(patient)

    async def test_book_appointment_raises_when_not_connected(self):
        """book_appointment should raise RuntimeError when _page is None."""
        self.adapter._page = None
        slot = EHRSlot(
            date=date(2025, 7, 10), time=time(9, 0),
            duration_minutes=30, provider_ehr_id="DR1",
        )
        with pytest.raises(RuntimeError, match="Not connected"):
            await self.adapter.book_appointment("P1", slot, "new_patient")

    async def test_cancel_appointment_returns_false_when_no_page(self):
        """cancel_appointment should return False when _page is None."""
        self.adapter._page = None
        result = await self.adapter.cancel_appointment("A1")
        assert result is False


# ===========================================================================
# Cross-cutting concerns
# ===========================================================================


class TestAdapterStateTransitions:
    """Test that adapters correctly manage internal state across operations."""

    async def test_ecw_token_stored_after_connect(self):
        """eClinicalWorks token should be stored after successful connect."""
        from app.ehr.adapters.eclinicalworks import EClinicalWorksAdapter
        adapter = EClinicalWorksAdapter()
        assert adapter.access_token == ""

        token_resp = _mock_httpx_response(200, {
            "access_token": "ecw_new_tok",
            "expires_in": 3600,
        })
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=token_resp):
            await adapter.connect({
                "client_id": "c", "client_secret": "s", "practice_id": "p",
            })
        assert adapter.access_token == "ecw_new_tok"
        assert adapter.token_expires_at is not None

    async def test_ecw_token_cleared_after_disconnect(self):
        """eClinicalWorks token should be cleared after disconnect."""
        from app.ehr.adapters.eclinicalworks import EClinicalWorksAdapter
        adapter = EClinicalWorksAdapter()
        adapter.access_token = "stale_token"
        await adapter.disconnect()
        assert adapter.access_token == ""

    async def test_elation_token_stored_after_connect(self):
        """Elation token should be stored after successful connect."""
        from app.ehr.adapters.elation import ElationHealthAdapter
        adapter = ElationHealthAdapter()
        assert adapter.access_token == ""

        token_resp = _mock_httpx_response(200, {
            "access_token": "el_new_tok",
            "expires_in": 7200,
        })
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=token_resp):
            await adapter.connect({
                "client_id": "c", "client_secret": "s",
            })
        assert adapter.access_token == "el_new_tok"
        assert adapter.token_expires_at is not None

    async def test_elation_token_cleared_after_disconnect(self):
        """Elation token should be cleared after disconnect."""
        from app.ehr.adapters.elation import ElationHealthAdapter
        adapter = ElationHealthAdapter()
        adapter.access_token = "stale_token"
        await adapter.disconnect()
        assert adapter.access_token == ""

    async def test_fhir_generic_bearer_token_set_on_connect(self):
        """Generic FHIR bearer auth should set access_token from bearer_token."""
        from app.ehr.adapters.fhir_generic import GenericFHIRAdapter
        adapter = GenericFHIRAdapter()
        await adapter.connect({
            "base_url": "https://fhir.test.com",
            "auth_type": "bearer",
            "bearer_token": "my_bearer_tok",
        })
        assert adapter.access_token == "my_bearer_tok"

    async def test_fhir_generic_token_cleared_after_disconnect(self):
        """Generic FHIR adapter should clear access_token after disconnect."""
        from app.ehr.adapters.fhir_generic import GenericFHIRAdapter
        adapter = GenericFHIRAdapter()
        adapter.access_token = "old_token"
        await adapter.disconnect()
        assert adapter.access_token == ""


class TestFHIRBundleHelper:
    """Test the _make_fhir_bundle test helper itself for correctness."""

    def test_bundle_structure(self):
        entries = [_make_fhir_patient("p1"), _make_fhir_patient("p2")]
        bundle = _make_fhir_bundle(entries)
        assert bundle["resourceType"] == "Bundle"
        assert bundle["type"] == "searchset"
        assert bundle["total"] == 2
        assert len(bundle["entry"]) == 2
        assert bundle["entry"][0]["resource"]["id"] == "p1"
        assert bundle["entry"][1]["resource"]["id"] == "p2"

    def test_empty_bundle(self):
        bundle = _make_fhir_bundle([])
        assert bundle["total"] == 0
        assert bundle["entry"] == []
