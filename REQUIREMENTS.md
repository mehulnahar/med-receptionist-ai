# Requirements — AI Receptionist for Dr. Stefanides

## V1 Requirements (Phase 1 — MVP)

### R1: Telephony & Call Handling
- R1.1: Forward calls from Vonage to Twilio SIP trunk
- R1.2: Answer on the same Vonage number patients already know
- R1.3: Support concurrent calls (multiple patients calling simultaneously)
- R1.4: Call recording for every call
- R1.5: Call timeout handling (patient goes silent, call drops)
- R1.6: DTMF detection for language selection (Press 1 English, 2 Spanish, 3 Greek)

### R2: Language Support
- R2.1: Full English conversation flow
- R2.2: Full Spanish conversation flow (60% of callers)
- R2.3: Greek callers → immediate transfer to staff
- R2.4: Language detection at call start via DTMF menu
- R2.5: Mid-call language switching if patient switches language

### R3: New Patient Flow
- R3.1: Collect full name
- R3.2: Collect date of birth
- R3.3: Collect address
- R3.4: Collect phone number
- R3.5: Collect referring physician name
- R3.6: Collect insurance carrier name
- R3.7: Collect insurance member ID
- R3.8: Ask if related to work injury or accident
- R3.9: If accident/injury → collect date of accident
- R3.10: Determine appointment type from insurance + injury status
- R3.11: Inform patient to bring insurance card and photo ID to visit
- R3.12: Confirmation loops for critical data ("You said X, is that correct?")

### R4: Existing Patient Flow
- R4.1: Look up patient by name + date of birth
- R4.2: Confirm address is still the same
- R4.3: Confirm phone number is still the same
- R4.4: Ask about any new injuries since last visit
- R4.5: Ask if insurance has changed
- R4.6: If insurance changed → collect new carrier + member ID
- R4.7: Determine appointment type from context

### R5: Appointment Booking
- R5.1: Check available slots based on doctor's schedule
- R5.2: Monday/Wednesday: 9 AM - 7 PM
- R5.3: Tuesday/Thursday: 10 AM - 5 PM
- R5.4: Alternating Fridays: 9 AM - 3 PM (toggle-controlled)
- R5.5: All slots = 15 minutes
- R5.6: No hard booking limit (overbooking allowed per practice policy)
- R5.7: US holiday blocking
- R5.8: Offer patient preferred date/time, confirm and book
- R5.9: When schedule is full → offer next available day

### R6: Appointment Types
- R6.1: NEW PATIENT COMPLETE — new patient, no accident
- R6.2: WC INITIAL — new patient, work injury
- R6.3: FOLLOW UP VISIT — existing patient, regular
- R6.4: WORKERS COMP FOLLOW UP — existing patient, work injury
- R6.5: NO FAULT FOLLOW UP — existing patient, car accident
- R6.6: GHI OUT OF NETWORK — GHI insurance, out of network

### R7: Insurance Verification
- R7.1: Real-time eligibility check via Stedi API during the call
- R7.2: Send: patient name, DOB, member ID, payer ID, NPI, Tax ID
- R7.3: Receive: active/inactive status, copay, plan name
- R7.4: Carrier name fuzzy matching ("United" → UnitedHealthcare)
- R7.5: Map top carriers to Stedi payer IDs (MetroPlus, Healthfirst, Fidelis, UHC, Medicare)
- R7.6: Handle API timeouts gracefully (< 20 seconds)
- R7.7: If valid → "Your insurance is verified"
- R7.8: If invalid → "We'll confirm coverage before your visit"
- R7.9: If patient doesn't know member ID → "Please bring your card to the visit"

### R8: Cancel & Reschedule
- R8.1: Look up appointment by patient name + DOB
- R8.2: Cancel appointment (no fee, no reason required)
- R8.3: Reschedule to new time slot
- R8.4: Simple flow — no complex policies

### R9: Call Routing & Transfer
- R9.1: Non-booking calls (billing, Rx, questions) → transfer to staff
- R9.2: Greek-speaking callers → transfer to staff
- R9.3: Emergency → "Call 911" message + option to transfer to staff
- R9.4: Transfer via Vonage back to staff phone system

### R10: SMS Confirmations
- R10.1: Send SMS after booking with appointment details
- R10.2: Include: date, time, doctor name
- R10.3: New patients: include "bring insurance card and photo ID"
- R10.4: Send in call language (English or Spanish)

### R11: Dashboard (Jennie's Interface)
- R11.1: Today's appointment queue — all AI-booked appointments
- R11.2: Each entry: patient name, DOB, phone, type, time, insurance status
- R11.3: Status tracking: New → Reviewed → Entered in MedicsCloud
- R11.4: Patient detail view with all collected data
- R11.5: Call recording player
- R11.6: Call transcription viewer
- R11.7: AI-generated call summary
- R11.8: Schedule calendar view
- R11.9: Friday toggle (mark which Fridays doctor is working)
- R11.10: Call log with filters (date, language, outcome, type)
- R11.11: Patient search by name, DOB, phone
- R11.12: Cancellation/reschedule list

### R12: Doctor's Analytics Dashboard
- R12.1: Total calls, bookings, cancellations, transfers per day
- R12.2: Weekly/monthly trends
- R12.3: Language breakdown (English vs Spanish vs Greek)
- R12.4: Appointment type breakdown
- R12.5: Insurance verification success rate
- R12.6: Busiest hours chart
- R12.7: AI handled vs transferred to staff ratio

### R13: Admin Panel (MindCrew Internal)
- R13.1: System health monitoring (API statuses)
- R13.2: Conversation prompt/script editor
- R13.3: Payer ID mapping management
- R13.4: Client account settings (NPI, Tax ID, schedule, hours)
- R13.5: Error/alert dashboard

## V2 Requirements (Phase 2 — Future)

- V2.1: Direct MedicsCloud automation via Playwright (zero manual entry)
- V2.2: Automated appointment reminders (text + call, 24hrs + 2hrs before)
- V2.3: No-show follow-up calls (next day auto-call to reschedule)
- V2.4: Day-before insurance batch verification (overnight eligibility checks)
- V2.5: Waitlist management (auto-call next person when cancellation occurs)
- V2.6: Post-visit satisfaction survey + Google review collection
- V2.7: Outbound recall campaigns ("6 months since last visit")
- V2.8: Payment collection over the phone (copays, balances via Stripe)
- V2.9: Full analytics dashboard with trends and insights
- V2.10: Multi-doctor/multi-location support (productized SaaS)
- V2.11: Digital patient intake form via text link (pre-visit)
- V2.12: Referral management (notify referring physician)

## Out of Scope

- Replacing the secretary entirely (human fallback always needed)
- 100% insurance verification coverage (Workers' Comp, small regional carriers may fail)
- Direct EHR clinical data write-back without API
- Greek language AI (too unreliable — staff handles)
- Medical advice of any kind
- HIPAA compliance consulting (client's responsibility)

## Data Model

### Patient
- name, DOB, address, phone, insurance_carrier, member_id, group_number, referring_physician, accident_date, patient_type (new/existing)

### Appointment
- patient_id, date, time, type, status, booked_by (AI/staff), language

### Call
- recording_url, transcription, summary, language, duration, outcome (booked/cancelled/transferred/hung_up)

### Insurance
- patient_id, carrier, member_id, status (active/inactive), last_verified, copay, plan_name

### Schedule
- date, available (bool), start_time, end_time, is_friday_override

### Holiday
- date, name
