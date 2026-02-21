"""
DrChrono EHR Adapter — integration via DrChrono REST API v4.
"""

import logging
from datetime import date, time, datetime
from typing import Optional

import httpx

from app.ehr.adapter import (
    EHRAdapter, EHRPatient, EHRAppointment, EHRSlot, EHRProvider,
)

logger = logging.getLogger(__name__)

DRCHRONO_API_BASE = "https://app.drchrono.com/api"
DRCHRONO_TOKEN_URL = "https://drchrono.com/o/token/"


class DrChronoAdapter(EHRAdapter):
    """DrChrono integration via REST API v4."""

    def __init__(self, **kwargs):
        self.client_id: str = kwargs.get("client_id", "")
        self.client_secret: str = kwargs.get("client_secret", "")
        self.access_token: str = kwargs.get("access_token", "")
        self.refresh_token: str = kwargs.get("refresh_token", "")
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=DRCHRONO_API_BASE,
                timeout=httpx.Timeout(30.0, connect=5.0),
            )
        return self._client

    async def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    async def connect(self, credentials: dict) -> bool:
        self.access_token = credentials.get("access_token", "")
        self.refresh_token = credentials.get("refresh_token", "")
        try:
            client = await self._get_client()
            response = await client.get("/users/current", headers=await self._headers())
            return response.status_code == 200
        except Exception as e:
            logger.error("Failed to connect to DrChrono: %s", e)
            return False

    async def disconnect(self) -> bool:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        return True

    async def health_check(self) -> bool:
        try:
            client = await self._get_client()
            response = await client.get("/users/current", headers=await self._headers())
            return response.status_code == 200
        except Exception:
            return False

    async def search_patients(
        self, first_name: str = "", last_name: str = "", dob: Optional[date] = None,
    ) -> list[EHRPatient]:
        client = await self._get_client()
        params = {}
        if first_name:
            params["first_name"] = first_name
        if last_name:
            params["last_name"] = last_name
        if dob:
            params["date_of_birth"] = dob.isoformat()

        response = await client.get("/patients", params=params, headers=await self._headers())
        response.raise_for_status()
        data = response.json()

        return [
            EHRPatient(
                ehr_id=str(p.get("id", "")),
                first_name=p.get("first_name", ""),
                last_name=p.get("last_name", ""),
                dob=datetime.strptime(p["date_of_birth"], "%Y-%m-%d").date() if p.get("date_of_birth") else date.today(),
                phone=p.get("cell_phone") or p.get("home_phone"),
                email=p.get("email"),
            )
            for p in data.get("results", [])
        ]

    async def create_patient(self, patient: EHRPatient) -> EHRPatient:
        client = await self._get_client()
        response = await client.post(
            "/patients",
            json={
                "first_name": patient.first_name,
                "last_name": patient.last_name,
                "date_of_birth": patient.dob.isoformat(),
                "cell_phone": patient.phone or "",
                "email": patient.email or "",
            },
            headers=await self._headers(),
        )
        response.raise_for_status()
        data = response.json()
        patient.ehr_id = str(data.get("id", ""))
        return patient

    async def update_patient(self, patient: EHRPatient) -> EHRPatient:
        client = await self._get_client()
        response = await client.patch(
            f"/patients/{patient.ehr_id}",
            json={
                "first_name": patient.first_name,
                "last_name": patient.last_name,
                "cell_phone": patient.phone or "",
            },
            headers=await self._headers(),
        )
        response.raise_for_status()
        return patient

    async def get_available_slots(
        self, provider_id: str, target_date: date, appointment_type: str = "",
    ) -> list[EHRSlot]:
        client = await self._get_client()
        params = {
            "doctor": provider_id,
            "date": target_date.isoformat(),
        }
        response = await client.get("/appointments", params=params, headers=await self._headers())
        response.raise_for_status()
        data = response.json()

        # DrChrono doesn't have a direct "open slots" endpoint
        # We need to calculate available slots from the schedule
        booked_times = set()
        for a in data.get("results", []):
            if a.get("scheduled_time"):
                dt = datetime.fromisoformat(a["scheduled_time"].replace("Z", "+00:00"))
                booked_times.add(dt.time())

        # Generate slots (9 AM to 5 PM, 30 min intervals by default)
        slots = []
        for hour in range(9, 17):
            for minute in [0, 30]:
                t = time(hour, minute)
                slots.append(EHRSlot(
                    date=target_date,
                    time=t,
                    duration_minutes=30,
                    provider_ehr_id=provider_id,
                    is_available=t not in booked_times,
                ))
        return slots

    async def book_appointment(
        self, patient_id: str, slot: EHRSlot, appointment_type: str, notes: str = "",
    ) -> EHRAppointment:
        client = await self._get_client()
        scheduled_time = datetime.combine(slot.date, slot.time).isoformat()
        response = await client.post(
            "/appointments",
            json={
                "patient": patient_id,
                "doctor": slot.provider_ehr_id,
                "scheduled_time": scheduled_time,
                "duration": slot.duration_minutes,
                "notes": notes,
                "exam_room": 1,
            },
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
        response = await client.patch(
            f"/appointments/{appointment_id}",
            json={"status": "Cancelled"},
            headers=await self._headers(),
        )
        return response.status_code == 200

    async def get_appointments(
        self, provider_id: str = "", start_date: Optional[date] = None, end_date: Optional[date] = None,
    ) -> list[EHRAppointment]:
        client = await self._get_client()
        params = {}
        if provider_id:
            params["doctor"] = provider_id
        if start_date:
            params["date_range"] = f"{start_date.isoformat()}/{(end_date or start_date).isoformat()}"

        response = await client.get("/appointments", params=params, headers=await self._headers())
        response.raise_for_status()
        data = response.json()

        appointments = []
        for a in data.get("results", []):
            if a.get("scheduled_time"):
                dt = datetime.fromisoformat(a["scheduled_time"].replace("Z", "+00:00"))
                appointments.append(EHRAppointment(
                    ehr_id=str(a.get("id", "")),
                    patient_ehr_id=str(a.get("patient", "")),
                    provider_ehr_id=str(a.get("doctor", "")),
                    appointment_type=str(a.get("profile", "")),
                    date=dt.date(),
                    time=dt.time(),
                    duration_minutes=int(a.get("duration", 30)),
                    status=a.get("status", ""),
                ))
        return appointments

    async def get_providers(self) -> list[EHRProvider]:
        client = await self._get_client()
        response = await client.get("/doctors", headers=await self._headers())
        response.raise_for_status()
        data = response.json()
        return [
            EHRProvider(
                ehr_id=str(d.get("id", "")),
                name=f"{d.get('first_name', '')} {d.get('last_name', '')}".strip(),
                npi=d.get("npi"),
                specialty=d.get("specialty"),
            )
            for d in data.get("results", [])
        ]

    async def get_appointment_types(self) -> list[dict]:
        client = await self._get_client()
        response = await client.get("/appointment_profiles", headers=await self._headers())
        response.raise_for_status()
        data = response.json()
        return [
            {"id": str(t.get("id", "")), "name": t.get("name", ""), "duration": t.get("duration")}
            for t in data.get("results", [])
        ]
