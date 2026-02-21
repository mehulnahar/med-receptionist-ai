"""
eClinicalWorks EHR Adapter — integration via FHIR R4 + HL7v2 hybrid.

eCW has 130K+ providers — second priority after athenahealth.
"""

import logging
from datetime import date, time, datetime, timedelta
from typing import Optional

import httpx

from app.ehr.adapter import (
    EHRAdapter, EHRPatient, EHRAppointment, EHRSlot, EHRProvider,
)

logger = logging.getLogger(__name__)

ECW_DEFAULT_FHIR_BASE = "https://fhir.eclinicalworks.com/fhir/r4"
ECW_TOKEN_URL = "https://oauthserver.eclinicalworks.com/oauth/token"


class EClinicalWorksAdapter(EHRAdapter):
    """eClinicalWorks integration via FHIR R4 endpoints."""

    def __init__(self, **kwargs):
        self.client_id: str = kwargs.get("client_id", "")
        self.client_secret: str = kwargs.get("client_secret", "")
        self.practice_id: str = kwargs.get("practice_id", "")
        self.fhir_base_url: str = kwargs.get("fhir_base_url", ECW_DEFAULT_FHIR_BASE)
        self.access_token: str = ""
        self.token_expires_at: Optional[datetime] = None
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.fhir_base_url.rstrip("/"),
                timeout=httpx.Timeout(30.0, connect=5.0),
            )
        return self._client

    async def _ensure_token(self) -> None:
        from datetime import timezone as tz

        now = datetime.now(tz.utc)
        if self.access_token and self.token_expires_at and now < self.token_expires_at:
            return

        async with httpx.AsyncClient() as client:
            response = await client.post(
                ECW_TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "scope": "system/*.read system/*.write",
                },
            )
            response.raise_for_status()
            data = response.json()
            self.access_token = data["access_token"]
            expires_in = data.get("expires_in", 3600)
            self.token_expires_at = now + timedelta(seconds=expires_in - 60)

    async def _headers(self) -> dict:
        await self._ensure_token()
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/fhir+json",
            "Accept": "application/fhir+json",
        }

    async def connect(self, credentials: dict) -> bool:
        self.client_id = credentials.get("client_id", self.client_id)
        self.client_secret = credentials.get("client_secret", self.client_secret)
        self.practice_id = credentials.get("practice_id", self.practice_id)
        if credentials.get("fhir_base_url"):
            self.fhir_base_url = credentials["fhir_base_url"]
        try:
            await self._ensure_token()
            logger.info("Connected to eClinicalWorks (practice=%s)", self.practice_id)
            return True
        except Exception as e:
            logger.error("Failed to connect to eClinicalWorks: %s", e)
            return False

    async def disconnect(self) -> bool:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        self.access_token = ""
        return True

    async def health_check(self) -> bool:
        try:
            client = await self._get_client()
            response = await client.get(
                "/metadata", headers=await self._headers()
            )
            return response.status_code == 200
        except Exception:
            return False

    def _parse_fhir_patient(self, resource: dict) -> EHRPatient:
        """Parse FHIR Patient resource into EHRPatient."""
        names = resource.get("name", [{}])
        name = names[0] if names else {}
        given = name.get("given", [""])
        family = name.get("family", "")

        telecoms = resource.get("telecom", [])
        phone = next(
            (t.get("value") for t in telecoms if t.get("system") == "phone"),
            None,
        )
        email = next(
            (t.get("value") for t in telecoms if t.get("system") == "email"),
            None,
        )

        dob_str = resource.get("birthDate", "")
        dob = (
            datetime.strptime(dob_str, "%Y-%m-%d").date()
            if dob_str
            else date.today()
        )

        return EHRPatient(
            ehr_id=resource.get("id", ""),
            first_name=given[0] if given else "",
            last_name=family,
            dob=dob,
            phone=phone,
            email=email,
        )

    async def search_patients(
        self,
        first_name: str = "",
        last_name: str = "",
        dob: Optional[date] = None,
    ) -> list[EHRPatient]:
        client = await self._get_client()
        params = {}
        if last_name:
            params["family"] = last_name
        if first_name:
            params["given"] = first_name
        if dob:
            params["birthdate"] = dob.isoformat()

        response = await client.get(
            "/Patient", params=params, headers=await self._headers()
        )
        response.raise_for_status()
        bundle = response.json()

        patients = []
        for entry in bundle.get("entry", []):
            resource = entry.get("resource", {})
            if resource.get("resourceType") == "Patient":
                patients.append(self._parse_fhir_patient(resource))
        return patients

    async def create_patient(self, patient: EHRPatient) -> EHRPatient:
        client = await self._get_client()
        fhir_patient = {
            "resourceType": "Patient",
            "name": [
                {
                    "family": patient.last_name,
                    "given": [patient.first_name],
                    "use": "official",
                }
            ],
            "birthDate": patient.dob.isoformat(),
            "telecom": [],
        }
        if patient.phone:
            fhir_patient["telecom"].append(
                {"system": "phone", "value": patient.phone, "use": "mobile"}
            )
        if patient.email:
            fhir_patient["telecom"].append(
                {"system": "email", "value": patient.email}
            )

        response = await client.post(
            "/Patient", json=fhir_patient, headers=await self._headers()
        )
        response.raise_for_status()
        data = response.json()
        patient.ehr_id = data.get("id", "")
        return patient

    async def update_patient(self, patient: EHRPatient) -> EHRPatient:
        client = await self._get_client()
        fhir_patient = {
            "resourceType": "Patient",
            "id": patient.ehr_id,
            "name": [
                {
                    "family": patient.last_name,
                    "given": [patient.first_name],
                }
            ],
            "telecom": [],
        }
        if patient.phone:
            fhir_patient["telecom"].append(
                {"system": "phone", "value": patient.phone}
            )

        response = await client.put(
            f"/Patient/{patient.ehr_id}",
            json=fhir_patient,
            headers=await self._headers(),
        )
        response.raise_for_status()
        return patient

    async def get_available_slots(
        self,
        provider_id: str,
        target_date: date,
        appointment_type: str = "",
    ) -> list[EHRSlot]:
        client = await self._get_client()
        params = {
            "schedule.actor": f"Practitioner/{provider_id}",
            "start": target_date.isoformat(),
            "status": "free",
        }
        if appointment_type:
            params["service-type"] = appointment_type

        response = await client.get(
            "/Slot", params=params, headers=await self._headers()
        )
        response.raise_for_status()
        bundle = response.json()

        slots = []
        for entry in bundle.get("entry", []):
            resource = entry.get("resource", {})
            if resource.get("resourceType") != "Slot":
                continue
            start = resource.get("start", "")
            if start:
                dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                end_str = resource.get("end", "")
                duration = 30
                if end_str:
                    end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                    duration = int((end_dt - dt).total_seconds() / 60)
                slots.append(
                    EHRSlot(
                        date=dt.date(),
                        time=dt.time(),
                        duration_minutes=duration,
                        provider_ehr_id=provider_id,
                        is_available=True,
                    )
                )
        return slots

    async def book_appointment(
        self,
        patient_id: str,
        slot: EHRSlot,
        appointment_type: str,
        notes: str = "",
    ) -> EHRAppointment:
        client = await self._get_client()
        start_dt = datetime.combine(slot.date, slot.time)
        end_dt = start_dt + timedelta(minutes=slot.duration_minutes)

        fhir_appt = {
            "resourceType": "Appointment",
            "status": "booked",
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "participant": [
                {
                    "actor": {"reference": f"Patient/{patient_id}"},
                    "status": "accepted",
                },
                {
                    "actor": {"reference": f"Practitioner/{slot.provider_ehr_id}"},
                    "status": "accepted",
                },
            ],
        }
        if appointment_type:
            fhir_appt["appointmentType"] = {
                "coding": [{"code": appointment_type}]
            }
        if notes:
            fhir_appt["comment"] = notes

        response = await client.post(
            "/Appointment", json=fhir_appt, headers=await self._headers()
        )
        response.raise_for_status()
        data = response.json()

        return EHRAppointment(
            ehr_id=data.get("id", ""),
            patient_ehr_id=patient_id,
            provider_ehr_id=slot.provider_ehr_id,
            appointment_type=appointment_type,
            date=slot.date,
            time=slot.time,
            duration_minutes=slot.duration_minutes,
            status="booked",
            notes=notes,
        )

    async def cancel_appointment(self, appointment_id: str) -> bool:
        client = await self._get_client()
        patch = [{"op": "replace", "path": "/status", "value": "cancelled"}]
        response = await client.patch(
            f"/Appointment/{appointment_id}",
            json=patch,
            headers={
                **(await self._headers()),
                "Content-Type": "application/json-patch+json",
            },
        )
        return response.status_code in (200, 204)

    async def get_appointments(
        self,
        provider_id: str = "",
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[EHRAppointment]:
        client = await self._get_client()
        params = {}
        if provider_id:
            params["actor"] = f"Practitioner/{provider_id}"
        if start_date:
            params["date"] = f"ge{start_date.isoformat()}"
        if end_date:
            if "date" in params:
                # FHIR supports multiple date params
                params["date"] = [params["date"], f"le{end_date.isoformat()}"]
            else:
                params["date"] = f"le{end_date.isoformat()}"

        response = await client.get(
            "/Appointment", params=params, headers=await self._headers()
        )
        response.raise_for_status()
        bundle = response.json()

        appointments = []
        for entry in bundle.get("entry", []):
            resource = entry.get("resource", {})
            if resource.get("resourceType") != "Appointment":
                continue

            start = resource.get("start", "")
            if not start:
                continue
            dt = datetime.fromisoformat(start.replace("Z", "+00:00"))

            # Extract participant references
            patient_ref = ""
            provider_ref = ""
            for p in resource.get("participant", []):
                ref = p.get("actor", {}).get("reference", "")
                if ref.startswith("Patient/"):
                    patient_ref = ref.replace("Patient/", "")
                elif ref.startswith("Practitioner/"):
                    provider_ref = ref.replace("Practitioner/", "")

            end_str = resource.get("end", "")
            duration = 30
            if end_str:
                end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                duration = int((end_dt - dt).total_seconds() / 60)

            appt_type = ""
            type_data = resource.get("appointmentType", {})
            codings = type_data.get("coding", [])
            if codings:
                appt_type = codings[0].get("code", "")

            appointments.append(
                EHRAppointment(
                    ehr_id=resource.get("id", ""),
                    patient_ehr_id=patient_ref,
                    provider_ehr_id=provider_ref,
                    appointment_type=appt_type,
                    date=dt.date(),
                    time=dt.time(),
                    duration_minutes=duration,
                    status=resource.get("status", ""),
                )
            )
        return appointments

    async def get_providers(self) -> list[EHRProvider]:
        client = await self._get_client()
        response = await client.get(
            "/Practitioner", headers=await self._headers()
        )
        response.raise_for_status()
        bundle = response.json()

        providers = []
        for entry in bundle.get("entry", []):
            resource = entry.get("resource", {})
            if resource.get("resourceType") != "Practitioner":
                continue
            names = resource.get("name", [{}])
            name = names[0] if names else {}
            given = name.get("given", [""])
            family = name.get("family", "")
            full_name = f"{given[0] if given else ''} {family}".strip()

            # Extract NPI from identifiers
            npi = None
            for ident in resource.get("identifier", []):
                if ident.get("system") == "http://hl7.org/fhir/sid/us-npi":
                    npi = ident.get("value")
                    break

            # Specialty from qualification
            specialty = None
            for qual in resource.get("qualification", []):
                code = qual.get("code", {})
                texts = code.get("text")
                if texts:
                    specialty = texts
                    break

            providers.append(
                EHRProvider(
                    ehr_id=resource.get("id", ""),
                    name=full_name,
                    npi=npi,
                    specialty=specialty,
                )
            )
        return providers

    async def get_appointment_types(self) -> list[dict]:
        client = await self._get_client()
        response = await client.get(
            "/ValueSet/appointment-type", headers=await self._headers()
        )
        if response.status_code != 200:
            return []

        data = response.json()
        compose = data.get("compose", {})
        types = []
        for include in compose.get("include", []):
            for concept in include.get("concept", []):
                types.append(
                    {
                        "id": concept.get("code", ""),
                        "name": concept.get("display", ""),
                        "duration": None,
                        "generic": True,
                    }
                )
        return types
