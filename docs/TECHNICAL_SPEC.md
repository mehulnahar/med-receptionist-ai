# AI Medical Receptionist Platform — Complete Build Specification

## Project Overview

Build a full-stack, multi-tenant AI Medical Receptionist SaaS platform. The system answers phone calls for doctor's offices, handles appointment booking in English and Spanish, collects patient data, verifies insurance, and provides a web dashboard for office staff and a super admin panel for platform management.

The platform must be **fully configurable** so that any new medical practice can be onboarded without code changes — just configuration through the super admin panel.

---

## Tech Stack

- **Frontend:** React + Tailwind CSS
- **Backend:** Python (FastAPI)
- **Database:** PostgreSQL
- **Real-time:** WebSockets (for live call monitoring)
- **Auth:** JWT-based authentication with role-based access control
- **Telephony:** Twilio (SIP trunk, SMS)
- **Voice AI:** Vapi.ai (handles STT + TTS + LLM conversation)
- **Insurance Verification:** Stedi API (270/271 eligibility checks)
- **Hosting:** Dockerized, ready for AWS/GCP/DigitalOcean deployment

---

## User Roles & Access

### 1. Super Admin (MindCrew — platform owner)
- Full access to everything
- Can create/edit/delete practices (tenants)
- Can configure Vapi agents, Twilio numbers, Stedi credentials per practice
- Can view all calls, analytics, and system health across all practices
- Can edit conversation prompts/scripts
- Can manage users for any practice
- Can toggle features on/off per practice

### 2. Practice Admin (Doctor / Office Manager)
- Can view their own practice's dashboard and analytics
- Can view call logs, recordings, transcriptions
- Can edit practice settings (schedule, holidays, appointment types)
- Can manage their own users (add/remove secretary accounts)
- Cannot see other practices or super admin settings

### 3. Secretary / Staff
- Can view today's appointment queue
- Can process bookings (mark as entered in EHR)
- Can search patients
- Can view call logs and listen to recordings
- Can toggle Friday schedule
- Cannot edit practice settings or manage users

---

## Database Schema

### Tables

```sql
-- Multi-tenant practices
CREATE TABLE practices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    npi VARCHAR(10) NOT NULL,
    tax_id VARCHAR(9) NOT NULL,
    phone VARCHAR(20),
    address TEXT,
    timezone VARCHAR(50) DEFAULT 'America/New_York',
    status VARCHAR(20) DEFAULT 'setup', -- setup, active, paused, inactive
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Users with role-based access
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    practice_id UUID REFERENCES practices(id) ON DELETE CASCADE,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL, -- super_admin, practice_admin, secretary
    is_active BOOLEAN DEFAULT true,
    last_login TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Practice configuration (all configurable settings)
CREATE TABLE practice_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    practice_id UUID UNIQUE REFERENCES practices(id) ON DELETE CASCADE,
    
    -- Telephony
    twilio_phone_number VARCHAR(20),
    twilio_account_sid VARCHAR(100),
    twilio_auth_token VARCHAR(100),
    vonage_forwarding_enabled BOOLEAN DEFAULT false,
    vonage_forwarding_number VARCHAR(20),
    
    -- Vapi.ai
    vapi_api_key VARCHAR(255),
    vapi_agent_id VARCHAR(100),
    vapi_assistant_id VARCHAR(100),
    
    -- Insurance Verification
    stedi_api_key VARCHAR(255),
    stedi_enabled BOOLEAN DEFAULT false,
    insurance_verification_on_call BOOLEAN DEFAULT true,
    
    -- Languages
    languages JSONB DEFAULT '["en"]', -- ["en", "es", "el"]
    primary_language VARCHAR(5) DEFAULT 'en',
    greek_transfer_to_staff BOOLEAN DEFAULT true,
    
    -- Slot configuration
    slot_duration_minutes INTEGER DEFAULT 15,
    allow_overbooking BOOLEAN DEFAULT false,
    max_overbooking_per_slot INTEGER DEFAULT 2,
    booking_horizon_days INTEGER DEFAULT 90,
    
    -- Greetings (per language)
    greetings JSONB DEFAULT '{}',
    -- Example: {"en": "Thank you for calling...", "es": "Gracias por llamar..."}
    
    -- Transfer settings
    transfer_number VARCHAR(20), -- number to transfer complex calls to staff
    emergency_message TEXT DEFAULT 'If this is a medical emergency, please hang up and call 911.',
    
    -- SMS settings
    sms_confirmation_enabled BOOLEAN DEFAULT true,
    sms_confirmation_template JSONB DEFAULT '{}',
    -- Example: {"en": "Your appointment with Dr. {doctor} is confirmed for {date} at {time}. Please bring your insurance card and photo ID.", "es": "..."}
    
    -- Data fields to collect
    new_patient_fields JSONB DEFAULT '["name","dob","address","phone","insurance_carrier","member_id"]',
    existing_patient_fields JSONB DEFAULT '["name","dob","confirm_address","confirm_phone","insurance_changed"]',
    
    -- Conversation settings
    system_prompt TEXT, -- main LLM system prompt for the AI agent
    fallback_message TEXT DEFAULT 'I apologize, I did not understand that. Could you please repeat?',
    max_retries INTEGER DEFAULT 3, -- how many times to ask before transferring to staff
    
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Weekly schedule template
CREATE TABLE schedule_template (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    practice_id UUID REFERENCES practices(id) ON DELETE CASCADE,
    day_of_week INTEGER NOT NULL, -- 0=Monday, 6=Sunday
    is_enabled BOOLEAN DEFAULT false,
    start_time TIME,
    end_time TIME,
    UNIQUE(practice_id, day_of_week)
);

-- Schedule overrides (specific dates — holidays, special Fridays, etc.)
CREATE TABLE schedule_overrides (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    practice_id UUID REFERENCES practices(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    is_working BOOLEAN NOT NULL, -- true = working, false = day off
    start_time TIME,
    end_time TIME,
    reason VARCHAR(255), -- "Holiday - Christmas", "Dr. vacation", "Special Friday"
    created_by UUID REFERENCES users(id),
    UNIQUE(practice_id, date)
);

-- Appointment types (fully configurable per practice)
CREATE TABLE appointment_types (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    practice_id UUID REFERENCES practices(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    color VARCHAR(7) DEFAULT '#6B7280', -- hex color for UI
    duration_minutes INTEGER DEFAULT 15,
    for_new_patients BOOLEAN DEFAULT false,
    for_existing_patients BOOLEAN DEFAULT true,
    requires_accident_date BOOLEAN DEFAULT false,
    requires_referral BOOLEAN DEFAULT false,
    is_active BOOLEAN DEFAULT true,
    sort_order INTEGER DEFAULT 0,
    -- Detection rules (how AI determines this type)
    detection_rules JSONB DEFAULT '{}',
    -- Example: {"insurance_contains": "GHI", "is_out_of_network": true}
    -- Example: {"is_new_patient": true, "has_accident": true}
    -- Example: {"is_new_patient": false, "has_accident": true, "accident_type": "workers_comp"}
    created_at TIMESTAMP DEFAULT NOW()
);

-- Insurance carriers (configurable per practice)
CREATE TABLE insurance_carriers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    practice_id UUID REFERENCES practices(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL, -- display name "UnitedHealthcare"
    aliases JSONB DEFAULT '[]', -- ["United", "UHC", "United Health"]
    stedi_payer_id VARCHAR(50), -- payer ID for Stedi API
    is_active BOOLEAN DEFAULT true
);

-- Patients
CREATE TABLE patients (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    practice_id UUID REFERENCES practices(id) ON DELETE CASCADE,
    first_name VARCHAR(255),
    last_name VARCHAR(255),
    dob DATE,
    phone VARCHAR(20),
    address TEXT,
    insurance_carrier VARCHAR(255),
    member_id VARCHAR(100),
    group_number VARCHAR(100),
    referring_physician VARCHAR(255),
    accident_date DATE,
    accident_type VARCHAR(50), -- workers_comp, no_fault, null
    is_new BOOLEAN DEFAULT true,
    language_preference VARCHAR(5) DEFAULT 'en',
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Appointments
CREATE TABLE appointments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    practice_id UUID REFERENCES practices(id) ON DELETE CASCADE,
    patient_id UUID REFERENCES patients(id),
    appointment_type_id UUID REFERENCES appointment_types(id),
    date DATE NOT NULL,
    time TIME NOT NULL,
    duration_minutes INTEGER DEFAULT 15,
    status VARCHAR(20) DEFAULT 'booked', -- booked, confirmed, entered_in_ehr, cancelled, no_show, completed
    insurance_verified BOOLEAN DEFAULT false,
    insurance_verification_result JSONB,
    booked_by VARCHAR(20) DEFAULT 'ai', -- ai, staff, manual
    call_id UUID, -- reference to the call that created this
    notes TEXT,
    sms_confirmation_sent BOOLEAN DEFAULT false,
    entered_in_ehr_at TIMESTAMP,
    entered_in_ehr_by UUID REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Call logs
CREATE TABLE calls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    practice_id UUID REFERENCES practices(id) ON DELETE CASCADE,
    vapi_call_id VARCHAR(255), -- Vapi's call ID
    twilio_call_sid VARCHAR(255), -- Twilio's call SID
    caller_phone VARCHAR(20),
    direction VARCHAR(10) DEFAULT 'inbound', -- inbound, outbound
    language VARCHAR(5) DEFAULT 'en',
    duration_seconds INTEGER,
    status VARCHAR(30), -- completed, transferred, abandoned, failed
    outcome VARCHAR(30), -- booked, cancelled, rescheduled, transferred_to_staff, general_inquiry, hung_up
    recording_url TEXT,
    transcription TEXT,
    ai_summary TEXT,
    patient_id UUID REFERENCES patients(id),
    appointment_id UUID REFERENCES appointments(id),
    vapi_cost DECIMAL(10,4),
    twilio_cost DECIMAL(10,4),
    metadata JSONB, -- any extra data from Vapi webhooks
    started_at TIMESTAMP,
    ended_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Insurance verification logs
CREATE TABLE insurance_verifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    practice_id UUID REFERENCES practices(id) ON DELETE CASCADE,
    patient_id UUID REFERENCES patients(id),
    call_id UUID REFERENCES calls(id),
    carrier_name VARCHAR(255),
    member_id VARCHAR(100),
    payer_id VARCHAR(50),
    request_payload JSONB,
    response_payload JSONB,
    is_active BOOLEAN, -- coverage active or not
    copay DECIMAL(10,2),
    plan_name VARCHAR(255),
    status VARCHAR(20), -- success, failed, timeout, error
    verified_at TIMESTAMP DEFAULT NOW()
);

-- US holidays (pre-populated)
CREATE TABLE holidays (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date DATE NOT NULL,
    name VARCHAR(255) NOT NULL,
    year INTEGER NOT NULL,
    UNIQUE(date)
);

-- Audit log (track all changes)
CREATE TABLE audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    practice_id UUID,
    user_id UUID,
    action VARCHAR(50), -- create, update, delete, login, config_change
    entity_type VARCHAR(50), -- practice, appointment, patient, config
    entity_id UUID,
    old_value JSONB,
    new_value JSONB,
    ip_address VARCHAR(45),
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## API Endpoints (FastAPI)

### Auth
```
POST   /api/auth/login              — Login, return JWT
POST   /api/auth/logout             — Invalidate token
POST   /api/auth/refresh            — Refresh JWT token
GET    /api/auth/me                 — Get current user profile
PUT    /api/auth/change-password    — Change password
```

### Super Admin — Practices
```
GET    /api/admin/practices                    — List all practices
POST   /api/admin/practices                    — Create new practice
GET    /api/admin/practices/{id}               — Get practice details
PUT    /api/admin/practices/{id}               — Update practice
DELETE /api/admin/practices/{id}               — Deactivate practice
GET    /api/admin/practices/{id}/config        — Get practice config
PUT    /api/admin/practices/{id}/config        — Update practice config
POST   /api/admin/practices/{id}/config/test   — Test API connections (Vapi, Twilio, Stedi)
```

### Super Admin — Users
```
GET    /api/admin/users                        — List all users
POST   /api/admin/users                        — Create user for any practice
PUT    /api/admin/users/{id}                   — Update user
DELETE /api/admin/users/{id}                   — Deactivate user
```

### Super Admin — System
```
GET    /api/admin/dashboard                    — Global analytics (all practices)
GET    /api/admin/system/health                — API health checks (Vapi, Twilio, Stedi, DB)
GET    /api/admin/system/logs                  — System error logs
GET    /api/admin/system/usage                 — API usage and costs per practice
```

### Super Admin — Conversation Management
```
GET    /api/admin/practices/{id}/prompts       — Get conversation prompts
PUT    /api/admin/practices/{id}/prompts       — Update conversation prompts
GET    /api/admin/practices/{id}/greetings     — Get greetings (per language)
PUT    /api/admin/practices/{id}/greetings     — Update greetings
POST   /api/admin/practices/{id}/test-call     — Trigger a test call to verify setup
```

### Practice Admin — Settings
```
GET    /api/practice/settings                  — Get my practice settings
PUT    /api/practice/settings                  — Update settings (limited fields)
GET    /api/practice/users                     — List users in my practice
POST   /api/practice/users                     — Add secretary to my practice
DELETE /api/practice/users/{id}                — Remove secretary
```

### Practice — Schedule
```
GET    /api/practice/schedule                  — Get weekly schedule template
PUT    /api/practice/schedule                  — Update weekly schedule
GET    /api/practice/schedule/overrides        — Get date overrides (holidays, special days)
POST   /api/practice/schedule/overrides        — Add override (toggle Friday, add holiday)
DELETE /api/practice/schedule/overrides/{id}   — Remove override
GET    /api/practice/schedule/availability?date=2026-02-20  — Get available slots for a date
```

### Practice — Appointment Types
```
GET    /api/practice/appointment-types         — List appointment types
POST   /api/practice/appointment-types         — Create new type
PUT    /api/practice/appointment-types/{id}    — Update type
DELETE /api/practice/appointment-types/{id}    — Deactivate type
```

### Practice — Insurance Carriers
```
GET    /api/practice/insurance-carriers        — List carriers
POST   /api/practice/insurance-carriers        — Add carrier
PUT    /api/practice/insurance-carriers/{id}   — Update carrier (aliases, payer ID)
DELETE /api/practice/insurance-carriers/{id}   — Remove carrier
POST   /api/practice/insurance/verify          — Manual insurance verification check
```

### Practice — Appointments (Queue)
```
GET    /api/practice/appointments?date=2026-02-20&status=booked  — List appointments with filters
GET    /api/practice/appointments/{id}         — Get appointment detail
PUT    /api/practice/appointments/{id}         — Update appointment (status, notes)
PUT    /api/practice/appointments/{id}/status  — Quick status change (entered_in_ehr, cancelled, etc.)
GET    /api/practice/appointments/today        — Today's queue for secretary
GET    /api/practice/appointments/pending      — All unprocessed AI bookings
```

### Practice — Patients
```
GET    /api/practice/patients?search=smith     — Search patients
GET    /api/practice/patients/{id}             — Get patient detail + history
PUT    /api/practice/patients/{id}             — Update patient info
GET    /api/practice/patients/{id}/appointments — Patient's appointment history
GET    /api/practice/patients/{id}/calls       — Patient's call history
```

### Practice — Calls
```
GET    /api/practice/calls?date=2026-02-20&outcome=booked  — List calls with filters
GET    /api/practice/calls/{id}                — Get call detail (transcription, summary, recording)
GET    /api/practice/calls/{id}/recording      — Stream call recording audio
GET    /api/practice/calls/live                — List currently active calls (WebSocket)
```

### Practice — Analytics
```
GET    /api/practice/analytics/overview?period=7d       — Key metrics
GET    /api/practice/analytics/calls?period=30d         — Call volume trends
GET    /api/practice/analytics/bookings?period=30d      — Booking trends
GET    /api/practice/analytics/insurance?period=30d     — Insurance verification stats
GET    /api/practice/analytics/languages?period=30d     — Language breakdown
GET    /api/practice/analytics/appointment-types?period=30d — Appointment type breakdown
GET    /api/practice/analytics/hourly                   — Busiest hours
```

### Webhooks (Vapi.ai sends these to your backend)
```
POST   /api/webhooks/vapi/call-started         — Call started
POST   /api/webhooks/vapi/call-ended           — Call ended (with transcription, summary, recording)
POST   /api/webhooks/vapi/function-call        — Vapi triggers a function (check availability, book appointment, verify insurance, lookup patient)
POST   /api/webhooks/vapi/transfer             — Call transferred to staff
```

---

## Vapi.ai Integration

### How Vapi Works With This System

Vapi.ai handles the voice conversation. Your backend provides the "tools" (functions) that Vapi calls during the conversation.

### Vapi Function Definitions (Configure in Vapi Dashboard or via API)

These are the functions your backend exposes that Vapi can call mid-conversation:

```json
[
  {
    "name": "check_patient_exists",
    "description": "Check if a patient exists in the system by name and date of birth",
    "parameters": {
      "type": "object",
      "properties": {
        "first_name": {"type": "string"},
        "last_name": {"type": "string"},
        "dob": {"type": "string", "description": "Date of birth in YYYY-MM-DD format"}
      },
      "required": ["first_name", "last_name", "dob"]
    }
  },
  {
    "name": "get_patient_details",
    "description": "Get existing patient details to confirm with them",
    "parameters": {
      "type": "object",
      "properties": {
        "patient_id": {"type": "string"}
      },
      "required": ["patient_id"]
    }
  },
  {
    "name": "check_availability",
    "description": "Check available appointment slots for a given date",
    "parameters": {
      "type": "object",
      "properties": {
        "date": {"type": "string", "description": "YYYY-MM-DD"},
        "appointment_type": {"type": "string"}
      },
      "required": ["date"]
    }
  },
  {
    "name": "book_appointment",
    "description": "Book an appointment for a patient",
    "parameters": {
      "type": "object",
      "properties": {
        "patient_id": {"type": "string", "description": "Existing patient ID or null for new"},
        "first_name": {"type": "string"},
        "last_name": {"type": "string"},
        "dob": {"type": "string"},
        "phone": {"type": "string"},
        "address": {"type": "string"},
        "insurance_carrier": {"type": "string"},
        "member_id": {"type": "string"},
        "referring_physician": {"type": "string"},
        "accident_date": {"type": "string"},
        "accident_type": {"type": "string", "enum": ["workers_comp", "no_fault", null]},
        "appointment_type": {"type": "string"},
        "date": {"type": "string"},
        "time": {"type": "string"}
      },
      "required": ["first_name", "last_name", "dob", "date", "time"]
    }
  },
  {
    "name": "verify_insurance",
    "description": "Verify patient insurance eligibility in real-time",
    "parameters": {
      "type": "object",
      "properties": {
        "first_name": {"type": "string"},
        "last_name": {"type": "string"},
        "dob": {"type": "string"},
        "insurance_carrier": {"type": "string"},
        "member_id": {"type": "string"}
      },
      "required": ["first_name", "last_name", "dob", "insurance_carrier", "member_id"]
    }
  },
  {
    "name": "cancel_appointment",
    "description": "Cancel an existing appointment",
    "parameters": {
      "type": "object",
      "properties": {
        "patient_id": {"type": "string"},
        "appointment_date": {"type": "string"}
      },
      "required": ["patient_id"]
    }
  },
  {
    "name": "reschedule_appointment",
    "description": "Reschedule an existing appointment to a new date/time",
    "parameters": {
      "type": "object",
      "properties": {
        "patient_id": {"type": "string"},
        "old_date": {"type": "string"},
        "new_date": {"type": "string"},
        "new_time": {"type": "string"}
      },
      "required": ["patient_id", "new_date", "new_time"]
    }
  },
  {
    "name": "transfer_to_staff",
    "description": "Transfer the call to office staff",
    "parameters": {
      "type": "object",
      "properties": {
        "reason": {"type": "string", "description": "Why transferring — billing, prescription, greek_language, complex_request, emergency"}
      },
      "required": ["reason"]
    }
  }
]
```

### Vapi System Prompt Template (Stored in practice_config.system_prompt)

This is configurable per practice via the super admin panel:

```
You are an AI receptionist for {practice_name}. The doctor is {doctor_name}.

LANGUAGES:
- You speak {languages}.
- Start every call with the greeting configured for the detected language.
- If the caller speaks Greek, immediately use the transfer_to_staff function with reason "greek_language".

CALL FLOW:
1. Greet the patient
2. Ask: "Are you a new patient or an existing patient?"
3. If they want to cancel, reschedule, or have a non-booking request, handle accordingly.
4. If they need billing, prescriptions, or anything complex, transfer to staff.

NEW PATIENT FLOW:
- Collect: {new_patient_fields}
- Ask if this is related to a work injury or car accident
- If yes: collect accident date and type (workers comp or no fault)
- Verify insurance using verify_insurance function
- Check availability and offer time slots
- Book the appointment
- Remind them: "Please bring your insurance card and photo ID to your first visit."

EXISTING PATIENT FLOW:
- Ask for name and date of birth
- Use check_patient_exists to look them up
- Confirm: address, phone number
- Ask: "Do you have any new injuries since your last visit?"
- Ask: "Has your insurance changed?"
- If insurance changed: collect new carrier and member ID
- Check availability and offer time slots
- Book the appointment

SCHEDULE:
{schedule_description}

APPOINTMENT TYPES:
{appointment_types_description}

INSURANCE CARRIERS ACCEPTED:
{insurance_carriers_list}

RULES:
- Never give medical advice
- If someone mentions an emergency, say: "{emergency_message}"
- If you cannot understand the caller after {max_retries} attempts, transfer to staff
- Always confirm the appointment details before finalizing
- Be warm, professional, and efficient
- Keep responses concise — this is a phone call, not a chat
```

---

## Frontend Pages & Components

### Layout
- Sidebar navigation (collapsible on mobile)
- Top bar with: practice name, user name, role badge, notifications bell, logout
- For super admin: practice selector dropdown in top bar to switch between practices

### Authentication Pages
```
/login                          — Email + password login
/forgot-password                — Password reset
```

### Super Admin Pages
```
/admin/dashboard                — Global overview (all practices stats)
/admin/practices                — List all practices with status badges
/admin/practices/new            — Create new practice wizard (multi-step form)
/admin/practices/:id/edit       — Edit practice details
/admin/practices/:id/config     — Full configuration panel (all settings)
/admin/practices/:id/prompts    — Edit AI conversation prompts and greetings
/admin/practices/:id/test       — Test call interface (trigger test call, see results)
/admin/users                    — All users across all practices
/admin/system                   — System health, API status, error logs
/admin/billing                  — API usage and costs per practice
```

### Practice Admin Pages
```
/settings                       — Practice settings (schedule, holidays, appointment types)
/settings/users                 — Manage staff accounts
/settings/insurance             — Manage insurance carriers and payer IDs
/settings/notifications         — SMS templates and notification preferences
/analytics                      — Practice analytics dashboard
```

### Secretary / Staff Pages
```
/                               — Today's appointment queue (default landing page)
/queue                          — All pending AI bookings to process
/schedule                       — Calendar view + Friday toggle
/schedule/overrides             — Manage holidays and special dates
/patients                       — Patient search and directory
/patients/:id                   — Patient detail (info, appointments, calls)
/calls                          — Call log with filters
/calls/:id                      — Call detail (recording player, transcription, summary)
```

### Key UI Components

#### Today's Queue (Secretary's main screen)
- Table/card list of today's AI-booked appointments
- Each row shows:
  - Patient name
  - Appointment time
  - Appointment type (with color dot matching practice config)
  - Insurance status icon (green check = verified, red X = failed, yellow clock = pending)
  - Language badge (EN / ES)
  - Status dropdown: New → Reviewed → Entered in EHR
  - Quick actions: View details, Listen to call, Mark as entered
- Filters: status, appointment type, insurance status
- Count badges at top: "12 pending | 8 reviewed | 25 entered"

#### Call Detail View
- Audio player for call recording (play, pause, scrub, speed control)
- Full transcription with timestamps
- AI-generated summary
- Patient data extracted from the call
- Insurance verification result
- Appointment created (if any)
- Call metadata: duration, language, outcome

#### Schedule Calendar
- Week view showing all appointment slots
- Color-coded by appointment type
- Available slots shown in gray
- Overbooked slots shown with warning indicator
- Click to view appointment details
- Friday toggle switch prominently displayed
- Holiday indicators

#### Practice Config Panel (Super Admin)
- Tabbed interface:
  - **General:** Practice name, NPI, Tax ID, phone, address, timezone
  - **Telephony:** Twilio number, Twilio credentials, Vonage forwarding config
  - **AI Agent:** Vapi API key, Agent ID, system prompt editor (large textarea with variable hints)
  - **Languages:** Enable/disable languages, greeting editor per language
  - **Schedule:** Weekly template editor, slot duration, overbooking rules
  - **Appointment Types:** CRUD table with color picker, detection rules editor
  - **Insurance:** Stedi API key, carrier list with aliases and payer IDs, enable/disable verification
  - **Data Fields:** Checkbox list of what to collect for new vs existing patients
  - **SMS:** Templates per language, enable/disable
  - **Advanced:** Transfer number, emergency message, max retries, fallback message
- Each tab has a "Save" button and shows unsaved changes indicator
- "Test Connection" buttons for Twilio, Vapi, and Stedi

#### Analytics Dashboard
- Key metric cards at top:
  - Total calls today / this week / this month
  - Bookings today / this week / this month
  - AI handle rate (% of calls fully handled without transfer)
  - Insurance verification success rate
  - Average call duration
  - Estimated cost savings
- Charts:
  - Line chart: calls per day (last 30 days)
  - Line chart: bookings per day (last 30 days)
  - Pie chart: call outcomes (booked, cancelled, transferred, hung up)
  - Pie chart: language breakdown
  - Bar chart: appointment types distribution
  - Bar chart: busiest hours of the day
  - Bar chart: top insurance carriers

---

## Webhook Handler Logic

When Vapi sends a webhook to your backend:

### /api/webhooks/vapi/function-call

This is the main integration point. Vapi calls your functions mid-conversation.

```python
@app.post("/api/webhooks/vapi/function-call")
async def vapi_function_call(request: Request):
    data = await request.json()
    function_name = data["functionCall"]["name"]
    params = data["functionCall"]["parameters"]
    practice_id = get_practice_from_vapi_agent(data["assistant"]["id"])
    
    if function_name == "check_patient_exists":
        patient = find_patient(practice_id, params["first_name"], params["last_name"], params["dob"])
        if patient:
            return {"result": {"found": True, "patient_id": str(patient.id), "name": patient.full_name}}
        return {"result": {"found": False}}
    
    elif function_name == "verify_insurance":
        config = get_practice_config(practice_id)
        carrier = match_carrier(practice_id, params["insurance_carrier"])
        result = stedi_verify(config.stedi_api_key, {
            "provider_npi": practice.npi,
            "provider_tax_id": practice.tax_id,
            "patient_first_name": params["first_name"],
            "patient_last_name": params["last_name"],
            "patient_dob": params["dob"],
            "payer_id": carrier.stedi_payer_id,
            "member_id": params["member_id"]
        })
        return {"result": {"verified": result.is_active, "plan": result.plan_name, "copay": result.copay}}
    
    elif function_name == "check_availability":
        slots = get_available_slots(practice_id, params["date"], params.get("appointment_type"))
        return {"result": {"available_slots": slots}}
    
    elif function_name == "book_appointment":
        appointment = create_appointment(practice_id, params)
        if config.sms_confirmation_enabled:
            send_sms_confirmation(appointment)
        return {"result": {"booked": True, "appointment_id": str(appointment.id), "date": params["date"], "time": params["time"]}}
    
    elif function_name == "cancel_appointment":
        cancel_appointment(practice_id, params["patient_id"], params.get("appointment_date"))
        return {"result": {"cancelled": True}}
    
    elif function_name == "transfer_to_staff":
        log_transfer(practice_id, data["call"]["id"], params["reason"])
        config = get_practice_config(practice_id)
        return {"result": {"transfer_number": config.transfer_number}}
```

### /api/webhooks/vapi/call-ended

```python
@app.post("/api/webhooks/vapi/call-ended")
async def vapi_call_ended(request: Request):
    data = await request.json()
    # Save call record with transcription, recording URL, summary, duration, cost
    save_call_record(data)
```

---

## Stedi Insurance Verification Integration

```python
import httpx

async def stedi_verify(api_key: str, params: dict) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://healthcare.stedi.com/2024-04-01/change/medicalnetwork/eligibility/v3",
            headers={
                "Authorization": f"Key {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "controlNumber": generate_control_number(),
                "tradingPartnerServiceId": params["payer_id"],
                "provider": {
                    "npi": params["provider_npi"],
                    "taxId": params["provider_tax_id"]
                },
                "subscriber": {
                    "memberId": params["member_id"],
                    "firstName": params["patient_first_name"],
                    "lastName": params["patient_last_name"],
                    "dateOfBirth": params["patient_dob"]
                },
                "encounter": {
                    "serviceTypeCodes": ["30"]  # Health Benefit Plan Coverage
                }
            }
        )
        return parse_eligibility_response(response.json())
```

### Carrier Name Fuzzy Matching

Build a matching function that maps what patients say to the correct carrier:

```python
def match_carrier(practice_id: str, spoken_name: str) -> InsuranceCarrier:
    """
    Patient says "Blue Cross" or "United" or "Metro Plus" 
    Match to the configured carrier with aliases
    """
    carriers = get_practice_carriers(practice_id)
    spoken_lower = spoken_name.lower().strip()
    
    for carrier in carriers:
        # Check exact name match
        if carrier.name.lower() == spoken_lower:
            return carrier
        # Check aliases
        for alias in carrier.aliases:
            if alias.lower() == spoken_lower:
                return carrier
            # Fuzzy match using contains
            if alias.lower() in spoken_lower or spoken_lower in alias.lower():
                return carrier
    
    return None  # Unknown carrier — AI should collect info and flag for manual review
```

---

## SMS Confirmation

```python
from twilio.rest import Client

def send_sms_confirmation(appointment, language="en"):
    config = get_practice_config(appointment.practice_id)
    template = config.sms_confirmation_template.get(language, config.sms_confirmation_template.get("en"))
    
    message = template.format(
        doctor=practice.name,
        date=appointment.date.strftime("%B %d, %Y"),
        time=appointment.time.strftime("%I:%M %p"),
        address=practice.address
    )
    
    client = Client(config.twilio_account_sid, config.twilio_auth_token)
    client.messages.create(
        body=message,
        from_=config.twilio_phone_number,
        to=appointment.patient.phone
    )
```

---

## New Practice Onboarding Wizard (Super Admin)

Multi-step form in the super admin panel:

### Step 1: Basic Info
- Practice name
- Doctor name
- NPI
- Tax ID
- Phone
- Address
- Timezone

### Step 2: Schedule
- Weekly template (Mon-Sun, start/end time, enabled toggle)
- Slot duration
- Holiday preset (load US holidays for current year)

### Step 3: Appointment Types
- Pre-populated with common types (New Patient, Follow Up, Workers Comp, No Fault)
- Admin can add/edit/remove
- Color picker for each
- Detection rules configuration

### Step 4: Languages & Greetings
- Select languages (English, Spanish, Greek, etc.)
- Enter greeting message for each language
- Configure Greek/other → transfer to staff

### Step 5: Insurance
- Add insurance carriers accepted by this practice
- Enter aliases for fuzzy matching
- Enter Stedi payer IDs
- Enable/disable real-time verification

### Step 6: Telephony
- Enter Twilio credentials (or use platform's shared Twilio account)
- Assign phone number
- Configure call forwarding from existing phone system
- Enter staff transfer number

### Step 7: AI Agent
- Auto-generate Vapi agent with all the configuration from previous steps
- Or enter existing Vapi agent ID
- Edit system prompt
- Configure fallback behavior

### Step 8: Test
- Make a test call to verify everything works
- Review AI conversation
- Approve and go live

---

## Environment Variables

```env
# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/medical_receptionist

# JWT
JWT_SECRET=your-secret-key
JWT_EXPIRY_HOURS=24

# Twilio (Platform-level — can be overridden per practice)
TWILIO_ACCOUNT_SID=ACxxxx
TWILIO_AUTH_TOKEN=xxxx

# Vapi.ai (Platform-level)
VAPI_API_KEY=xxxx
VAPI_WEBHOOK_SECRET=xxxx

# Stedi (Platform-level — can be overridden per practice)
STEDI_API_KEY=xxxx

# App
APP_URL=https://app.yourdomain.com
CORS_ORIGINS=https://app.yourdomain.com
```

---

## Docker Setup

```
project/
├── docker-compose.yml
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── models/
│   │   ├── routes/
│   │   ├── services/
│   │   │   ├── vapi_service.py
│   │   │   ├── stedi_service.py
│   │   │   ├── twilio_service.py
│   │   │   ├── scheduling_service.py
│   │   │   └── insurance_service.py
│   │   ├── webhooks/
│   │   │   └── vapi_webhooks.py
│   │   └── middleware/
│   │       ├── auth.py
│   │       └── tenant.py
│   └── alembic/          (database migrations)
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   └── src/
│       ├── pages/
│       ├── components/
│       ├── hooks/
│       ├── services/
│       └── contexts/
└── nginx/
    └── nginx.conf
```

---

## Key Implementation Notes

1. **Multi-tenancy:** Every database query MUST filter by practice_id. Use middleware to extract practice_id from the JWT token and inject it into all queries. Super admin bypasses this filter.

2. **Vapi agent per practice:** Each practice gets its own Vapi assistant with a unique system prompt generated from their configuration. When config changes, regenerate and update the Vapi assistant via Vapi API.

3. **Real-time updates:** Use WebSockets to push new call events and appointment bookings to the secretary's dashboard in real-time. When a call ends and an appointment is created, the secretary sees it immediately without refreshing.

4. **Timezone handling:** All times stored in UTC in the database. Convert to practice timezone for display and Vapi interactions.

5. **Insurance carrier matching:** The fuzzy matching must be robust. Patients say carriers differently — "United", "UHC", "United Healthcare", "United Health Care" should all match to UnitedHealthcare. Store multiple aliases per carrier.

6. **Appointment slot calculation:** Calculate available slots dynamically from the schedule template + overrides + existing appointments. Account for overbooking rules if enabled.

7. **Call recording storage:** Vapi provides recording URLs. Store the URL in the database. Optionally download and store in S3/GCS for long-term retention.

8. **Audit trail:** Log all configuration changes, appointment status changes, and user actions in the audit_log table.

9. **Error handling in Vapi functions:** If your webhook returns an error, Vapi will tell the patient something went wrong. Always return graceful fallback messages. Never let the patient experience a silent failure.

10. **Rate limiting:** Stedi API has rate limits. Cache recent verification results (same patient + carrier within 24 hours = return cached result).

---

## First Practice Configuration (Dr. Stefanides)

Pre-populate this data when seeding the database:

```json
{
  "name": "Stefanides Neofitos, MD PC",
  "npi": "1689880429",
  "taxId": "263551213",
  "timezone": "America/New_York",
  "languages": ["en", "es"],
  "greekTransferToStaff": true,
  "schedule": {
    "monday": {"start": "09:00", "end": "19:00"},
    "tuesday": {"start": "10:00", "end": "17:00"},
    "wednesday": {"start": "09:00", "end": "19:00"},
    "thursday": {"start": "10:00", "end": "17:00"},
    "friday": "alternating — use overrides",
    "saturday": "off",
    "sunday": "off"
  },
  "slotDuration": 15,
  "appointmentTypes": [
    {"name": "New Patient Complete", "color": "#DC2626", "forNew": true, "rules": {"is_new": true, "has_accident": false}},
    {"name": "Follow Up Visit", "color": "#6B7280", "forNew": false, "rules": {"is_new": false, "has_accident": false}},
    {"name": "Workers Comp Follow Up", "color": "#EC4899", "forNew": false, "rules": {"is_new": false, "accident_type": "workers_comp"}},
    {"name": "GHI Out of Network", "color": "#2563EB", "rules": {"insurance_contains": "GHI"}},
    {"name": "No Fault Follow Up", "color": "#06B6D4", "forNew": false, "rules": {"is_new": false, "accident_type": "no_fault"}},
    {"name": "WC Initial", "color": "#EAB308", "forNew": true, "rules": {"is_new": true, "accident_type": "workers_comp"}}
  ],
  "insuranceCarriers": [
    {"name": "MetroPlus", "aliases": ["Metro Plus", "Metro", "MetroPlus Health"]},
    {"name": "Healthfirst", "aliases": ["Health First", "HF"]},
    {"name": "Fidelis Care", "aliases": ["Fidelis", "Fidelis NY"]},
    {"name": "UnitedHealthcare", "aliases": ["United", "UHC", "United Health Care", "United Healthcare"]},
    {"name": "Medicare", "aliases": ["Medicare Part A", "Medicare Part B", "CMS"]}
  ],
  "newPatientFields": ["name", "dob", "address", "phone", "insurance_carrier", "member_id", "referring_physician", "accident_date"],
  "existingPatientFields": ["name", "dob", "confirm_address", "confirm_phone", "new_injuries", "insurance_changed"],
  "greeting": {
    "en": "Thank you for calling Dr. Stefanides' office. How can I help you today?",
    "es": "Gracias por llamar a la oficina del Dr. Stefanides. ¿Cómo puedo ayudarle hoy?"
  },
  "emergencyMessage": "If this is a medical emergency, please hang up and call 911.",
  "smsTemplate": {
    "en": "Your appointment with Dr. Stefanides is confirmed for {date} at {time}. Please bring your insurance card and photo ID.",
    "es": "Su cita con el Dr. Stefanides está confirmada para el {date} a las {time}. Por favor traiga su tarjeta de seguro y una identificación con foto."
  }
}
```

---

## Build Order

1. Database setup + migrations
2. Auth system (JWT, roles, login)
3. Practice CRUD + config (super admin)
4. Schedule management
5. Appointment types CRUD
6. Insurance carriers CRUD
7. Vapi webhook handlers (function calls)
8. Appointment booking logic
9. Patient management
10. Stedi insurance verification integration
11. Twilio SMS integration
12. Call logging
13. Secretary dashboard (Today's queue)
14. Call detail view (recording, transcription)
15. Patient search and detail
16. Schedule calendar view
17. Analytics dashboard
18. Super admin panel
19. Practice onboarding wizard
20. Testing and deployment
