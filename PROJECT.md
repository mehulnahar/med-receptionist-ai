# AI Receptionist for Dr. Neofitos Stefanides, MD PC

## Overview

An AI-powered voice receptionist system that answers incoming phone calls for a medical practice, handles appointment booking, insurance verification, and call routing — in English and Spanish — replacing 2-3 phone staff and saving ~$80,000+/year.

## Client

- **Practice:** Dr. Neofitos Stefanides, MD PC
- **Secretary:** Jennie (primary operational contact)
- **Location:** New York area
- **EHR/PM System:** MedicsCloud v11.0.54.0 (cloud-based at `apps.medicscloud.com`)
- **Phone System:** Vonage (VoIP)
- **NPI:** 1689880429
- **Tax ID:** 263551213
- **Clearinghouse:** Claim.MD (accessed through MedicsPremier, not standalone)

## Practice Profile

- **Daily Call Volume:** 500-600 calls/day
- **Daily Bookings:** ~50 appointments/day
- **Daily Patients:** ~110 patients/day
- **Languages:** English (40%), Spanish (60%), Greek (staff handles)
- **Providers:** 1 doctor, 1 calendar
- **Slot Duration:** 15 minutes (all types)

## Schedule

| Day | Hours |
|-----|-------|
| Monday | 9:00 AM - 7:00 PM |
| Tuesday | 10:00 AM - 5:00 PM |
| Wednesday | 9:00 AM - 7:00 PM |
| Thursday | 10:00 AM - 5:00 PM |
| Friday | 9:00 AM - 3:00 PM (every other, pattern varies) |
| Saturday/Sunday | Closed |

- No blocked times (lunch, admin)
- No booking limit (sometimes overbooks)
- Standard US holidays off

## Appointment Types

| Type | When Used |
|------|-----------|
| NEW PATIENT COMPLETE | New patient, no accident |
| FOLLOW UP VISIT | Existing patient, regular follow-up |
| WORKERS COMP FOLLOW UP | Existing patient, work injury related |
| WC INITIAL | New patient, work injury |
| NO FAULT FOLLOW UP | Existing patient, car accident related |
| GHI OUT OF NETWORK | GHI insurance, out of network |

## Top Insurance Carriers

1. MetroPlus
2. Healthfirst
3. Fidelis Care
4. UnitedHealthcare
5. Medicare

Also accepts: Medicaid, Workers' Comp, No-Fault, all major carriers.

## Architecture

This is a **multi-tenant SaaS platform** — built to onboard Dr. Stefanides first, then sell to more medical practices without code changes.

### Tech Stack

- **Frontend:** React + Tailwind CSS
- **Backend:** Python (FastAPI)
- **Database:** PostgreSQL
- **Real-time:** WebSockets (live call monitoring)
- **Auth:** JWT with role-based access control (super_admin, practice_admin, secretary)
- **Telephony:** Twilio (SIP trunk, SMS)
- **Voice AI:** Vapi.ai (handles STT + TTS + LLM conversation in one platform)
- **Insurance Verification:** Stedi API (270/271 eligibility checks)
- **Hosting:** Dockerized (AWS/GCP/DigitalOcean)

### Key Integration: Vapi.ai

Vapi.ai replaces the Deepgram + ElevenLabs + LLM stack with a single platform. Your backend exposes webhook functions that Vapi calls mid-conversation (check_patient_exists, verify_insurance, check_availability, book_appointment, cancel_appointment, reschedule_appointment, transfer_to_staff).

### Full Technical Spec

See `docs/TECHNICAL_SPEC.md` for complete database schema, API endpoints, Vapi function definitions, webhook handlers, frontend pages, and build order.

## Budget

- **Implementation:** $28,000
- **Monthly (post-launch):** $500-700 (client-facing) / actual API costs ~$1,300-1,500/month
- **Timeline:** 2 months
- **On-site visit:** 1-2 days required

## Key Constraints

- MedicsCloud has NO public scheduling API
- Claim.MD is not directly accessible (accessed through MedicsPremier)
- Phase 1: Dashboard → secretary enters into MedicsCloud manually
- Phase 2: Playwright automation into MedicsCloud (future)
- Greek calls must transfer to staff (AI not reliable for Greek)
- 60% of calls are in Spanish — bilingual is mandatory, not optional
