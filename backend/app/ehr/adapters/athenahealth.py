"""
athenahealth EHR Adapter — integration via athenahealth Marketplace API.

athenahealth has 160K+ providers — this is the #1 priority integration.
"""

import logging
from datetime import date, time, datetime
from typing import Optional

import httpx

from app.ehr.adapter import (
    EHRAdapter, EHRPatient, EHRAppointment, EHRSlot, EHRProvider,
)

logger = logging.getLogger(__name__)

ATHENA_API_BASE = "https://api.preview.platform.athenahealth.com"
ATHENA_TOKEN_URL = f"{ATHENA_API_BASE}/oauth2/v1/token"


class AthenaHealthAdapter(EHRAdapter):
    """athenahealth integration via their Marketplace API."""

    def __init__(self, **kwargs):
        self.client_id: str = kwargs.get("client_id", "")
        self.client_secret: str = kwargs.get("client_secret", "")
        self.practice_id: str = kwargs.get("practice_id", "")
        self.access_token: str = ""
        self.token_expires_at: Optional[datetime] = None
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=f"{ATHENA_API_BASE}/v1/{self.practice_id}",
                timeout=httpx.Timeout(30.0, connect=5.0),
            )
        return self._client

    async def _ensure_token(self) -> None:
        """Ensure we have a valid access token, refreshing if needed."""
        from datetime import timedelta, timezone as tz

        now = datetime.now(tz.utc)
        if self.access_token and self.token_expires_at and now < self.token_expires_at:
            return

        async with httpx.AsyncClient() as client:
            response = await client.post(
                ATHENA_TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "scope": "athena/service/Athenanet.MDP.*",
                },
                auth=(self.client_id, self.client_secret),
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
            "Content-Type": "application/json",
        }

    async def connect(self, credentials: dict) -> bool:
        self.client_id = credentials.get("client_id", self.client_id)
        self.client_secret = credentials.get("client_secret", self.client_secret)
        self.practice_id = credentials.get("practice_id", self.practice_id)
        try:
            await self._ensure_token()
            logger.info("Connected to athenahealth (practice=%s)", self.practice_id)
            return True
        except Exception as e:
            logger.error("Failed to connect to athenahealth: %s", e)
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
                "/ping",
                headers=await self._headers(),
            )
            return response.status_code == 200
        except Exception:
            return False

    async def search_patients(
        self,
        first_name: str = "",
        last_name: str = "",
        dob: Optional[date] = None,
    ) -> list[EHRPatient]:
        client = await self._get_client()
        params = {}
        if first_name:
            params["firstname"] = first_name
        if last_name:
            params["lastname"] = last_name
        if dob:
            params["dob"] = dob.strftime("%m/%d/%Y")

        response = await client.get(
            "/patients",
            params=params,
            headers=await self._headers(),
        )
        response.raise_for_status()
        data = response.json()

        patients = []
        for p in data.get("patients", []):
            patients.append(EHRPatient(
                ehr_id=str(p.get("patientid", "")),
                first_name=p.get("firstname", ""),
                last_name=p.get("lastname", ""),
                dob=datetime.strptime(p["dob"], "%m/%d/%Y").date() if p.get("dob") else date.today(),
                phone=p.get("mobilephone") or p.get("homephone"),
                email=p.get("email"),
            ))
        return patients

    async def create_patient(self, patient: EHRPatient) -> EHRPatient:
        client = await self._get_client()
        response = await client.post(
            "/patients",
            data={
                "firstname": patient.first_name,
                "lastname": patient.last_name,
                "dob": patient.dob.strftime("%m/%d/%Y"),
                "mobilephone": patient.phone or "",
                "email": patient.email or "",
            },
            headers=await self._headers(),
        )
        response.raise_for_status()
        data = response.json()
        patient.ehr_id = str(data[0].get("patientid", "")) if data else ""
        return patient

    async def update_patient(self, patient: EHRPatient) -> EHRPatient:
        client = await self._get_client()
        response = await client.put(
            f"/patients/{patient.ehr_id}",
            data={
                "firstname": patient.first_name,
                "lastname": patient.last_name,
                "mobilephone": patient.phone or "",
            },
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
            "providerid": provider_id,
            "departmentid": "1",  # Default department
            "date": target_date.strftime("%m/%d/%Y"),
        }
        if appointment_type:
            params["appointmenttypeid"] = appointment_type

        response = await client.get(
            "/appointments/open",
            params=params,
            headers=await self._headers(),
        )
        response.raise_for_status()
        data = response.json()

        slots = []
        for appt in data.get("appointments", []):
            appt_date = appt.get("date", "")
            start_time = appt.get("starttime", "")
            if appt_date and start_time:
                dt = datetime.strptime(f"{appt_date} {start_time}", "%m/%d/%Y %H:%M")
                slots.append(EHRSlot(
                    date=dt.date(),
                    time=dt.time(),
                    duration_minutes=int(appt.get("duration", 30)),
                    provider_ehr_id=provider_id,
                    is_available=True,
                ))
        return slots

    async def book_appointment(
        self,
        patient_id: str,
        slot: EHRSlot,
        appointment_type: str,
        notes: str = "",
    ) -> EHRAppointment:
        client = await self._get_client()
        # In athenahealth, you book by appointment slot ID
        response = await client.put(
            f"/appointments/{appointment_type}",
            data={
                "patientid": patient_id,
                "appointmenttypeid": appointment_type,
                "note": notes,
            },
            headers=await self._headers(),
        )
        response.raise_for_status()
        data = response.json()

        return EHRAppointment(
            ehr_id=str(data.get("appointmentid", "")),
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
        response = await client.put(
            f"/appointments/{appointment_id}/cancel",
            headers=await self._headers(),
        )
        return response.status_code == 200

    async def get_appointments(
        self,
        provider_id: str = "",
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[EHRAppointment]:
        client = await self._get_client()
        params = {}
        if provider_id:
            params["providerid"] = provider_id
        if start_date:
            params["startdate"] = start_date.strftime("%m/%d/%Y")
        if end_date:
            params["enddate"] = end_date.strftime("%m/%d/%Y")

        response = await client.get(
            "/appointments/booked",
            params=params,
            headers=await self._headers(),
        )
        response.raise_for_status()
        data = response.json()

        appointments = []
        for a in data.get("appointments", []):
            appt_date = a.get("date", "")
            start_time = a.get("starttime", "")
            if appt_date and start_time:
                dt = datetime.strptime(f"{appt_date} {start_time}", "%m/%d/%Y %H:%M")
                appointments.append(EHRAppointment(
                    ehr_id=str(a.get("appointmentid", "")),
                    patient_ehr_id=str(a.get("patientid", "")),
                    provider_ehr_id=str(a.get("providerid", "")),
                    appointment_type=str(a.get("appointmenttypeid", "")),
                    date=dt.date(),
                    time=dt.time(),
                    duration_minutes=int(a.get("duration", 30)),
                    status=a.get("appointmentstatus", ""),
                ))
        return appointments

    async def get_providers(self) -> list[EHRProvider]:
        client = await self._get_client()
        response = await client.get(
            "/providers",
            headers=await self._headers(),
        )
        response.raise_for_status()
        data = response.json()

        return [
            EHRProvider(
                ehr_id=str(p.get("providerid", "")),
                name=f"{p.get('firstname', '')} {p.get('lastname', '')}".strip(),
                npi=p.get("npi"),
                specialty=p.get("specialty"),
            )
            for p in data.get("providers", [])
        ]

    async def get_appointment_types(self) -> list[dict]:
        client = await self._get_client()
        response = await client.get(
            "/appointmenttypes",
            headers=await self._headers(),
        )
        response.raise_for_status()
        data = response.json()

        return [
            {
                "id": str(t.get("appointmenttypeid", "")),
                "name": t.get("name", ""),
                "duration": t.get("duration"),
                "generic": t.get("generic"),
            }
            for t in data.get("appointmenttypes", [])
        ]
