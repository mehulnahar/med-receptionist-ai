"""
Abstract EHR Adapter — standard interface for all EHR integrations.

Adding a new EHR requires only implementing this interface in a new file.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, time
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class EHRPatient:
    ehr_id: str
    first_name: str
    last_name: str
    dob: date
    phone: Optional[str] = None
    email: Optional[str] = None
    insurance_carrier: Optional[str] = None
    member_id: Optional[str] = None


@dataclass
class EHRAppointment:
    ehr_id: str
    patient_ehr_id: str
    provider_ehr_id: str
    appointment_type: str
    date: date
    time: time
    duration_minutes: int
    status: str
    notes: Optional[str] = None


@dataclass
class EHRSlot:
    date: date
    time: time
    duration_minutes: int
    provider_ehr_id: str
    is_available: bool = True


@dataclass
class EHRProvider:
    ehr_id: str
    name: str
    npi: Optional[str] = None
    specialty: Optional[str] = None


class EHRAdapter(ABC):
    """Abstract base class for EHR integrations.

    Each EHR (athenahealth, DrChrono, etc.) implements this interface.
    The adapter handles all EHR-specific API calls and data mapping.
    """

    @abstractmethod
    async def connect(self, credentials: dict) -> bool:
        """Establish connection and authenticate with the EHR."""

    @abstractmethod
    async def disconnect(self) -> bool:
        """Disconnect from the EHR."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the connection is healthy."""

    # --- Patient operations ---

    @abstractmethod
    async def search_patients(
        self,
        first_name: str = "",
        last_name: str = "",
        dob: Optional[date] = None,
    ) -> list[EHRPatient]:
        """Search for patients in the EHR."""

    @abstractmethod
    async def create_patient(self, patient: EHRPatient) -> EHRPatient:
        """Create a new patient in the EHR."""

    @abstractmethod
    async def update_patient(self, patient: EHRPatient) -> EHRPatient:
        """Update an existing patient in the EHR."""

    # --- Appointment operations ---

    @abstractmethod
    async def get_available_slots(
        self,
        provider_id: str,
        target_date: date,
        appointment_type: str = "",
    ) -> list[EHRSlot]:
        """Get available appointment slots from the EHR."""

    @abstractmethod
    async def book_appointment(
        self,
        patient_id: str,
        slot: EHRSlot,
        appointment_type: str,
        notes: str = "",
    ) -> EHRAppointment:
        """Book an appointment in the EHR."""

    @abstractmethod
    async def cancel_appointment(self, appointment_id: str) -> bool:
        """Cancel an appointment in the EHR."""

    @abstractmethod
    async def get_appointments(
        self,
        provider_id: str = "",
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[EHRAppointment]:
        """List appointments from the EHR."""

    # --- Provider operations ---

    @abstractmethod
    async def get_providers(self) -> list[EHRProvider]:
        """List providers/doctors from the EHR."""

    # --- Appointment types ---

    @abstractmethod
    async def get_appointment_types(self) -> list[dict]:
        """List available appointment types from the EHR."""


def get_adapter(ehr_type: str, **kwargs) -> EHRAdapter:
    """Factory: get the appropriate adapter for an EHR type."""
    adapters = {
        "athenahealth": "app.ehr.adapters.athenahealth.AthenaHealthAdapter",
        "drchrono": "app.ehr.adapters.drchrono.DrChronoAdapter",
        "medicscloud": "app.ehr.adapters.medicscloud.MedicsCloudAdapter",
        "fhir_generic": "app.ehr.adapters.fhir_generic.GenericFHIRAdapter",
        "eclinicalworks": "app.ehr.adapters.eclinicalworks.EClinicalWorksAdapter",
        "elation": "app.ehr.adapters.elation.ElationHealthAdapter",
    }

    adapter_path = adapters.get(ehr_type)
    if not adapter_path:
        raise ValueError(f"Unsupported EHR type: {ehr_type}")

    # Dynamic import
    module_path, class_name = adapter_path.rsplit(".", 1)
    import importlib
    module = importlib.import_module(module_path)
    adapter_class = getattr(module, class_name)
    return adapter_class(**kwargs)
