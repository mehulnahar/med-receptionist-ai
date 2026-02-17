from app.schemas.common import MessageResponse, HealthResponse
from app.schemas.auth import LoginRequest, LoginResponse, ChangePasswordRequest, TokenPayload
from app.schemas.user import UserBase, UserCreate, UserUpdate, UserResponse, UserListResponse
from app.schemas.practice import (
    PracticeBase, PracticeCreate, PracticeUpdate, PracticeResponse, PracticeListResponse,
)
from app.schemas.practice_config import PracticeConfigResponse, PracticeConfigUpdate
from app.schemas.schedule import (
    ScheduleTemplateResponse, ScheduleTemplateUpdate, ScheduleWeekResponse,
    ScheduleOverrideResponse, ScheduleOverrideCreate, ScheduleOverrideListResponse,
    AvailableSlot, AvailabilityResponse,
)
from app.schemas.appointment_type import (
    AppointmentTypeBase, AppointmentTypeCreate, AppointmentTypeUpdate,
    AppointmentTypeResponse, AppointmentTypeListResponse,
)
from app.schemas.insurance_carrier import (
    InsuranceCarrierBase, InsuranceCarrierCreate, InsuranceCarrierUpdate,
    InsuranceCarrierResponse, InsuranceCarrierListResponse,
)
from app.schemas.patient import (
    PatientBase, PatientCreate, PatientUpdate, PatientResponse,
    PatientSearchRequest, PatientListResponse,
)
from app.schemas.appointment import (
    BookAppointmentRequest, AppointmentResponse, AppointmentListResponse,
    CancelAppointmentRequest, RescheduleAppointmentRequest,
    ConfirmAppointmentRequest, AppointmentStatusUpdate,
)
from app.schemas.insurance_verification import (
    InsuranceVerificationRequest, InsuranceVerificationResponse,
    InsuranceVerificationListResponse, InsuranceEligibilityResult,
    CarrierLookupResponse,
)
from app.schemas.vapi import (
    VapiCallObject, VapiToolCall, VapiToolWithToolCall, VapiArtifact,
    VapiMessage, VapiWebhookRequest, VapiToolCallResult, VapiToolCallResponse,
)

__all__ = [
    # Common
    "MessageResponse",
    "HealthResponse",
    # Auth
    "LoginRequest",
    "LoginResponse",
    "ChangePasswordRequest",
    "TokenPayload",
    # User
    "UserBase",
    "UserCreate",
    "UserUpdate",
    "UserResponse",
    "UserListResponse",
    # Practice
    "PracticeBase",
    "PracticeCreate",
    "PracticeUpdate",
    "PracticeResponse",
    "PracticeListResponse",
    # Practice Config
    "PracticeConfigResponse",
    "PracticeConfigUpdate",
    # Schedule
    "ScheduleTemplateResponse",
    "ScheduleTemplateUpdate",
    "ScheduleWeekResponse",
    "ScheduleOverrideResponse",
    "ScheduleOverrideCreate",
    "ScheduleOverrideListResponse",
    "AvailableSlot",
    "AvailabilityResponse",
    # Appointment Type
    "AppointmentTypeBase",
    "AppointmentTypeCreate",
    "AppointmentTypeUpdate",
    "AppointmentTypeResponse",
    "AppointmentTypeListResponse",
    # Insurance Carrier
    "InsuranceCarrierBase",
    "InsuranceCarrierCreate",
    "InsuranceCarrierUpdate",
    "InsuranceCarrierResponse",
    "InsuranceCarrierListResponse",
    # Patient
    "PatientBase",
    "PatientCreate",
    "PatientUpdate",
    "PatientResponse",
    "PatientSearchRequest",
    "PatientListResponse",
    # Appointment
    "BookAppointmentRequest",
    "AppointmentResponse",
    "AppointmentListResponse",
    "CancelAppointmentRequest",
    "RescheduleAppointmentRequest",
    "ConfirmAppointmentRequest",
    "AppointmentStatusUpdate",
    # Insurance Verification
    "InsuranceVerificationRequest",
    "InsuranceVerificationResponse",
    "InsuranceVerificationListResponse",
    "InsuranceEligibilityResult",
    "CarrierLookupResponse",
    # Vapi Webhooks
    "VapiCallObject",
    "VapiToolCall",
    "VapiToolWithToolCall",
    "VapiArtifact",
    "VapiMessage",
    "VapiWebhookRequest",
    "VapiToolCallResult",
    "VapiToolCallResponse",
]
