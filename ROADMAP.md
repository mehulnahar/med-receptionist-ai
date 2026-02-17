# Roadmap — AI Medical Receptionist Platform

## Milestone 1: MVP (Phase 1 Delivery)

### Phase 1: Project Setup & Database
**Goal:** Docker environment, database schema, migrations, seed data
- Set up Docker Compose (FastAPI backend, PostgreSQL, React frontend, Nginx)
- Create all database tables (practices, users, practice_config, schedule_template, schedule_overrides, appointment_types, insurance_carriers, patients, appointments, calls, insurance_verifications, holidays, audit_log)
- Create Alembic migration scripts
- Seed Dr. Stefanides' practice data (schedule, appointment types, carriers, greetings)
- Pre-populate US holidays for 2026-2027
- Set up environment variables / .env template

### Phase 2: Authentication & User Management
**Goal:** JWT auth, role-based access, user CRUD
- Implement JWT login/logout/refresh endpoints
- Role-based access control middleware (super_admin, practice_admin, secretary)
- Multi-tenancy middleware (practice_id extraction from JWT, query filtering)
- User CRUD for super admin (create users for any practice)
- User CRUD for practice admin (manage own staff)
- Password hashing, change password endpoint

### Phase 3: Practice Configuration (Super Admin)
**Goal:** Full practice management and configuration CRUD
- Practice CRUD endpoints (create, list, get, update, deactivate)
- Practice config CRUD (telephony, Vapi, Stedi, languages, slots, greetings, SMS, prompts)
- Test connection endpoints (Twilio, Vapi, Stedi)
- Appointment types CRUD per practice
- Insurance carriers CRUD per practice (with aliases for fuzzy matching)
- Schedule template CRUD (weekly template)
- Schedule overrides CRUD (holidays, special Fridays, vacation days)

### Phase 4: Scheduling Engine
**Goal:** Slot availability calculation, booking logic, overbooking support
- Available slot calculation from schedule_template + overrides + existing appointments
- Overbooking rules per practice config
- Booking horizon enforcement
- Appointment CRUD (create, read, update status, cancel)
- Appointment status workflow (booked → confirmed → entered_in_ehr → completed / cancelled / no_show)
- Friday toggle logic (schedule_overrides for alternating Fridays)

### Phase 5: Vapi.ai Webhook Integration
**Goal:** Connect Vapi voice agent to backend via webhooks
- Implement /api/webhooks/vapi/function-call endpoint
- Function: check_patient_exists (lookup by name + DOB)
- Function: get_patient_details (return patient info for confirmation)
- Function: check_availability (return available slots for a date)
- Function: book_appointment (create patient + appointment, determine type)
- Function: verify_insurance (call Stedi API, return result)
- Function: cancel_appointment
- Function: reschedule_appointment
- Function: transfer_to_staff (log reason, return transfer number)
- Implement /api/webhooks/vapi/call-started
- Implement /api/webhooks/vapi/call-ended (save recording, transcription, summary, duration, cost)
- Vapi agent auto-configuration from practice config (system prompt generation)

### Phase 6: Stedi Insurance Verification
**Goal:** Real-time 270/271 eligibility checks during calls
- Stedi API integration (POST to eligibility endpoint)
- Carrier name fuzzy matching (aliases, contains, case-insensitive)
- Map top carriers to Stedi payer IDs (MetroPlus, Healthfirst, Fidelis, UHC, Medicare)
- Parse eligibility response (active/inactive, copay, plan name)
- Timeout and error handling (graceful fallback message)
- Cache recent verification results (same patient+carrier within 24hrs)
- Insurance verification log table

### Phase 7: Twilio SMS Confirmations
**Goal:** Send appointment confirmation texts after booking
- Twilio SMS integration
- Bilingual templates (English + Spanish) from practice_config
- Send confirmation after AI books appointment
- Template variable substitution ({doctor}, {date}, {time}, {address})
- Delivery status tracking

### Phase 8: Secretary Dashboard (React Frontend)
**Goal:** Jennie's daily operations interface
- Login page
- Today's Queue page (list of AI-booked appointments, status tracking)
- Patient detail view (all collected data, call recording, transcription, summary)
- Status workflow buttons (New → Reviewed → Entered in EHR)
- Schedule calendar view (week view, color-coded by type)
- Friday toggle switch
- Call log with filters (date, language, outcome, type)
- Patient search (by name, DOB, phone)
- Cancellation/reschedule list
- Audio player for call recordings
- WebSocket integration for real-time updates

### Phase 9: Practice Admin & Analytics Dashboard
**Goal:** Doctor's analytics view + practice settings management
- Overview dashboard (total calls, bookings, cancellations, transfers)
- Weekly/monthly trends (line charts)
- Call outcome breakdown (pie chart)
- Language breakdown (pie chart)
- Appointment type distribution (bar chart)
- Busiest hours chart
- Insurance verification success rate
- Estimated cost savings display
- Practice settings editor (schedule, holidays, appointment types)
- Staff user management

### Phase 10: Super Admin Panel
**Goal:** Platform-wide management interface
- Global dashboard (all practices stats)
- Practice list with status badges
- Practice onboarding wizard (8-step multi-step form)
- Practice config editor (full tabbed interface)
- AI prompt/greeting editor per practice
- Test call trigger
- System health monitoring (API statuses)
- Error logs viewer
- API usage and cost tracking per practice
- User management across all practices

### Phase 11: Testing, Deployment & Go-Live
**Goal:** End-to-end testing, deployment, staff training
- End-to-end call flow testing (English + Spanish)
- Edge case testing (accent handling, unknown carriers, schedule full, API timeouts)
- Vonage → Twilio call forwarding setup
- Number porting (if needed, runs in parallel)
- Docker deployment to cloud (AWS/GCP/DigitalOcean)
- Nginx SSL/reverse proxy configuration
- 1-2 day on-site visit (observe workflow, test with real calls, train Jennie)
- Monitoring and alerting setup
- Go live

---

## Milestone 2: Phase 2 Enhancements (Post Go-Live)

### Phase 12: MedicsCloud Automation (Playwright)
- Reverse-engineer MedicsCloud web UI at apps.medicscloud.com
- Playwright automation for patient creation + appointment booking
- Existing patient lookup automation
- Error handling and retry logic

### Phase 13: Automated Reminders & Follow-ups
- Appointment reminders (text + call, 24hrs + 2hrs before)
- No-show follow-up calls (next day auto-call)
- Day-before insurance batch verification

### Phase 14: Advanced Features
- Waitlist management (auto-call on cancellation)
- Post-visit satisfaction survey + Google review collection
- Outbound recall campaigns ("6 months since last visit")
- Payment collection over the phone (Stripe)
- Digital patient intake form via text link

### Phase 15: Multi-Tenant Scaling
- Multi-doctor/multi-location support
- Per-practice billing and usage metering
- Practice self-service onboarding
- Marketing site and demo environment
