"""
Generic FHIR R4 client — works with any FHIR-compliant EHR.

Supports SMART on FHIR OAuth2, basic auth, and bearer token auth.
This is the fallback adapter for EHRs that support standard FHIR.
"""

import logging
from datetime import date, time, datetime, timedelta
from typing import Optional

import httpx

from app.ehr.adapter import (
    EHRAdapter, EHRPatient, EHRAppointment, EHRSlot, EHRProvider,
)

logger = logging.getLogger(__name__)


class GenericFHIRAdapter(EHRAdapter):
    """Generic FHIR R4 adapter for any FHIR-compliant EHR."""

    def __init__(self, **kwargs):
        self.base_url: str = kwargs.get("base_url", "").rstrip("/")
        self.auth_type: str = kwargs.get("auth_type", "bearer")  # smart, basic, bearer
        self.client_id: str = kwargs.get("client_id", "")
        self.client_secret: str = kwargs.get("client_secret", "")
        self.username: str = kwargs.get("username", "")
        self.password: str = kwargs.get("password", "")
        self.bearer_token: str = kwargs.get("bearer_token", "")
        self.access_token: str = ""
        self.token_expires_at: Optional[datetime] = None
        self._token_endpoint: str = ""
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(30.0, connect=5.0),
            )
        return self._client

    async def _discover_smart_endpoints(self) -> None:
        """Discover OAuth2 endpoints from SMART configuration."""
        if self._token_endpoint:
            return

        async with httpx.AsyncClient() as client:
            # Try .well-known first
            try:
                response = await client.get(
                    f"{self.base_url}/.well-known/smart-configuration"
                )
                if response.status_code == 200:
                    data = response.json()
                    self._token_endpoint = data.get("token_endpoint", "")
                    return
            except Exception:
                pass

            # Fallback to metadata
            try:
                response = await client.get(
                    f"{self.base_url}/metadata",
                    headers={"Accept": "application/fhir+json"},
                )
                if response.status_code == 200:
                    data = response.json()
                    rest = data.get("rest", [{}])
                    if rest:
                        security = rest[0].get("security", {})
                        for ext in security.get("extension", []):
                            if "oauth-uris" in ext.get("url", ""):
                                for sub in ext.get("extension", []):
                                    if sub.get("url") == "token":
                                        self._token_endpoint = sub.get("valueUri", "")
            except Exception:
                pass

    async def _ensure_token(self) -> None:
        from datetime import timezone as tz

        if self.auth_type == "bearer":
            self.access_token = self.bearer_token
            return

        if self.auth_type == "basic":
            return  # No token needed

        # SMART on FHIR OAuth2
        now = datetime.now(tz.utc)
        if self.access_token and self.token_expires_at and now < self.token_expires_at:
            return

        await self._discover_smart_endpoints()
        if not self._token_endpoint:
            raise ValueError("Could not discover SMART token endpoint")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self._token_endpoint,
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
        headers = {
            "Content-Type": "application/fhir+json",
            "Accept": "application/fhir+json",
        }
        if self.auth_type == "basic":
            import base64
            creds = base64.b64encode(
                f"{self.username}:{self.password}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {creds}"
        else:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    async def connect(self, credentials: dict) -> bool:
        self.base_url = credentials.get("base_url", self.base_url).rstrip("/")
        self.auth_type = credentials.get("auth_type", self.auth_type)
        self.client_id = credentials.get("client_id", self.client_id)
        self.client_secret = credentials.get("client_secret", self.client_secret)
        self.username = credentials.get("username", self.username)
        self.password = credentials.get("password", self.password)
        self.bearer_token = credentials.get("bearer_token", self.bearer_token)
        try:
            await self._ensure_token()
            logger.info("Connected to FHIR server at %s", self.base_url)
            return True
        except Exception as e:
            logger.error("Failed to connect to FHIR server: %s", e)
            return False

    async def disconnect(self) -> bool:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        self.access_token = ""
        return True

    async def health_check(self) -> bool:
        try:
            client = await self._get_client()
            response = await client.get("/metadata", headers=await self._headers())
            return response.status_code == 200
        except Exception:
            return False

    def _parse_patient(self, resource: dict) -> EHRPatient:
        names = resource.get("name", [{}])
        name = names[0] if names else {}
        given = name.get("given", [""])
        family = name.get("family", "")

        telecoms = resource.get("telecom", [])
        phone = next(
            (t.get("value") for t in telecoms if t.get("system") == "phone"), None
        )
        email = next(
            (t.get("value") for t in telecoms if t.get("system") == "email"), None
        )

        dob_str = resource.get("birthDate", "")
        dob = (
            datetime.strptime(dob_str, "%Y-%m-%d").date() if dob_str else date.today()
        )

        return EHRPatient(
            ehr_id=resource.get("id", ""),
            first_name=given[0] if given else "",
            last_name=family,
            dob=dob,
            phone=phone,
            email=email,
        )

    def _get_bundle_entries(self, bundle: dict, resource_type: str) -> list[dict]:
        """Extract entries of a specific type from a FHIR Bundle."""
        return [
            entry["resource"]
            for entry in bundle.get("entry", [])
            if entry.get("resource", {}).get("resourceType") == resource_type
        ]

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
        return [self._parse_patient(r) for r in self._get_bundle_entries(bundle, "Patient")]

    async def create_patient(self, patient: EHRPatient) -> EHRPatient:
        client = await self._get_client()
        resource = {
            "resourceType": "Patient",
            "name": [{"family": patient.last_name, "given": [patient.first_name]}],
            "birthDate": patient.dob.isoformat(),
            "telecom": [],
        }
        if patient.phone:
            resource["telecom"].append({"system": "phone", "value": patient.phone})
        if patient.email:
            resource["telecom"].append({"system": "email", "value": patient.email})

        response = await client.post(
            "/Patient", json=resource, headers=await self._headers()
        )
        response.raise_for_status()
        data = response.json()
        patient.ehr_id = data.get("id", "")
        return patient

    async def update_patient(self, patient: EHRPatient) -> EHRPatient:
        client = await self._get_client()
        resource = {
            "resourceType": "Patient",
            "id": patient.ehr_id,
            "name": [{"family": patient.last_name, "given": [patient.first_name]}],
            "telecom": [],
        }
        if patient.phone:
            resource["telecom"].append({"system": "phone", "value": patient.phone})

        response = await client.put(
            f"/Patient/{patient.ehr_id}", json=resource, headers=await self._headers()
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

        response = await client.get(
            "/Slot", params=params, headers=await self._headers()
        )
        response.raise_for_status()
        bundle = response.json()

        slots = []
        for resource in self._get_bundle_entries(bundle, "Slot"):
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

        resource = {
            "resourceType": "Appointment",
            "status": "booked",
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "participant": [
                {"actor": {"reference": f"Patient/{patient_id}"}, "status": "accepted"},
                {"actor": {"reference": f"Practitioner/{slot.provider_ehr_id}"}, "status": "accepted"},
            ],
        }
        if notes:
            resource["comment"] = notes

        response = await client.post(
            "/Appointment", json=resource, headers=await self._headers()
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
        # Try JSON Patch first, fall back to PUT
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
            params["date"] = f"le{end_date.isoformat()}"

        response = await client.get(
            "/Appointment", params=params, headers=await self._headers()
        )
        response.raise_for_status()
        bundle = response.json()

        appointments = []
        for resource in self._get_bundle_entries(bundle, "Appointment"):
            start = resource.get("start", "")
            if not start:
                continue
            dt = datetime.fromisoformat(start.replace("Z", "+00:00"))

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

            appointments.append(
                EHRAppointment(
                    ehr_id=resource.get("id", ""),
                    patient_ehr_id=patient_ref,
                    provider_ehr_id=provider_ref,
                    appointment_type="",
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
        for resource in self._get_bundle_entries(bundle, "Practitioner"):
            names = resource.get("name", [{}])
            name = names[0] if names else {}
            given = name.get("given", [""])
            family = name.get("family", "")
            full_name = f"{given[0] if given else ''} {family}".strip()

            npi = None
            for ident in resource.get("identifier", []):
                if ident.get("system") == "http://hl7.org/fhir/sid/us-npi":
                    npi = ident.get("value")
                    break

            providers.append(
                EHRProvider(
                    ehr_id=resource.get("id", ""),
                    name=full_name,
                    npi=npi,
                    specialty=None,
                )
            )
        return providers

    async def get_appointment_types(self) -> list[dict]:
        """FHIR doesn't have a standard appointment types endpoint."""
        return []
