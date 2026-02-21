"""
Elation Health EHR Adapter — integration via Elation REST API v2.

Elation serves primary care practices with a modern API.
"""

import logging
from datetime import date, time, datetime, timedelta
from typing import Optional

import httpx

from app.ehr.adapter import (
    EHRAdapter, EHRPatient, EHRAppointment, EHRSlot, EHRProvider,
)

logger = logging.getLogger(__name__)

ELATION_API_BASE = "https://api.elationhealth.com/api/2.0"
ELATION_TOKEN_URL = "https://api.elationhealth.com/oauth2/token"


class ElationHealthAdapter(EHRAdapter):
    """Elation Health integration via their REST API v2."""

    def __init__(self, **kwargs):
        self.client_id: str = kwargs.get("client_id", "")
        self.client_secret: str = kwargs.get("client_secret", "")
        self.access_token: str = ""
        self.token_expires_at: Optional[datetime] = None
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=ELATION_API_BASE,
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
                ELATION_TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
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
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def connect(self, credentials: dict) -> bool:
        self.client_id = credentials.get("client_id", self.client_id)
        self.client_secret = credentials.get("client_secret", self.client_secret)
        try:
            await self._ensure_token()
            logger.info("Connected to Elation Health")
            return True
        except Exception as e:
            logger.error("Failed to connect to Elation Health: %s", e)
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
                "/providers", params={"limit": 1}, headers=await self._headers()
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
            params["first_name"] = first_name
        if last_name:
            params["last_name"] = last_name
        if dob:
            params["date_of_birth"] = dob.isoformat()

        response = await client.get(
            "/patients", params=params, headers=await self._headers()
        )
        response.raise_for_status()
        data = response.json()

        patients = []
        for p in data.get("results", []):
            dob_str = p.get("date_of_birth", "")
            patients.append(
                EHRPatient(
                    ehr_id=str(p.get("id", "")),
                    first_name=p.get("first_name", ""),
                    last_name=p.get("last_name", ""),
                    dob=(
                        datetime.strptime(dob_str, "%Y-%m-%d").date()
                        if dob_str
                        else date.today()
                    ),
                    phone=p.get("primary_phone") or p.get("mobile_phone"),
                    email=p.get("email"),
                )
            )
        return patients

    async def create_patient(self, patient: EHRPatient) -> EHRPatient:
        client = await self._get_client()
        body = {
            "first_name": patient.first_name,
            "last_name": patient.last_name,
            "date_of_birth": patient.dob.isoformat(),
        }
        if patient.phone:
            body["primary_phone"] = patient.phone
        if patient.email:
            body["email"] = patient.email

        response = await client.post(
            "/patients", json=body, headers=await self._headers()
        )
        response.raise_for_status()
        data = response.json()
        patient.ehr_id = str(data.get("id", ""))
        return patient

    async def update_patient(self, patient: EHRPatient) -> EHRPatient:
        client = await self._get_client()
        body = {
            "first_name": patient.first_name,
            "last_name": patient.last_name,
        }
        if patient.phone:
            body["primary_phone"] = patient.phone

        response = await client.patch(
            f"/patients/{patient.ehr_id}",
            json=body,
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
            "provider": provider_id,
            "date": target_date.isoformat(),
            "available": "true",
        }
        if appointment_type:
            params["appointment_type"] = appointment_type

        response = await client.get(
            "/scheduling/slots", params=params, headers=await self._headers()
        )
        response.raise_for_status()
        data = response.json()

        slots = []
        for s in data.get("results", []):
            start = s.get("start_time", "")
            if start:
                dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                slots.append(
                    EHRSlot(
                        date=dt.date(),
                        time=dt.time(),
                        duration_minutes=int(s.get("duration", 30)),
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

        body = {
            "patient": int(patient_id),
            "provider": int(slot.provider_ehr_id),
            "start_time": start_dt.isoformat(),
            "duration": slot.duration_minutes,
        }
        if appointment_type:
            body["appointment_type"] = appointment_type
        if notes:
            body["reason"] = notes

        response = await client.post(
            "/scheduling/appointments",
            json=body,
            headers=await self._headers(),
        )
        response.raise_for_status()
        data = response.json()

        return EHRAppointment(
            ehr_id=str(data.get("id", "")),
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
        response = await client.delete(
            f"/scheduling/appointments/{appointment_id}",
            headers=await self._headers(),
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
            params["provider"] = provider_id
        if start_date:
            params["from_date"] = start_date.isoformat()
        if end_date:
            params["to_date"] = end_date.isoformat()

        response = await client.get(
            "/scheduling/appointments",
            params=params,
            headers=await self._headers(),
        )
        response.raise_for_status()
        data = response.json()

        appointments = []
        for a in data.get("results", []):
            start = a.get("start_time", "")
            if not start:
                continue
            dt = datetime.fromisoformat(start.replace("Z", "+00:00"))

            appointments.append(
                EHRAppointment(
                    ehr_id=str(a.get("id", "")),
                    patient_ehr_id=str(a.get("patient", "")),
                    provider_ehr_id=str(a.get("provider", "")),
                    appointment_type=str(a.get("appointment_type", "")),
                    date=dt.date(),
                    time=dt.time(),
                    duration_minutes=int(a.get("duration", 30)),
                    status=a.get("status", ""),
                    notes=a.get("reason"),
                )
            )
        return appointments

    async def get_providers(self) -> list[EHRProvider]:
        client = await self._get_client()
        response = await client.get(
            "/providers", headers=await self._headers()
        )
        response.raise_for_status()
        data = response.json()

        return [
            EHRProvider(
                ehr_id=str(p.get("id", "")),
                name=f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(),
                npi=p.get("npi"),
                specialty=p.get("specialty"),
            )
            for p in data.get("results", [])
        ]

    async def get_appointment_types(self) -> list[dict]:
        client = await self._get_client()
        response = await client.get(
            "/scheduling/appointment_types",
            headers=await self._headers(),
        )
        if response.status_code != 200:
            return []

        data = response.json()
        return [
            {
                "id": str(t.get("id", "")),
                "name": t.get("name", ""),
                "duration": t.get("duration"),
                "generic": t.get("is_default", False),
            }
            for t in data.get("results", [])
        ]
