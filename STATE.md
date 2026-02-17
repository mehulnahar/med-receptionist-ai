# Project State — AI Medical Receptionist

## Current Status
- **Milestone:** 1 (MVP)
- **Phase:** Not started
- **Next Action:** Run `/gsd:discuss-phase 1` to begin Phase 1 (Project Setup & Database)

## Completed
- [x] GSD installed and configured
- [x] Git repository initialized
- [x] PROJECT.md created (client details, practice profile, architecture)
- [x] REQUIREMENTS.md created (V1 + V2 requirements, data model)
- [x] ROADMAP.md created (11 phases for Milestone 1, 4 phases for Milestone 2)
- [x] Technical spec copied to docs/TECHNICAL_SPEC.md (full DB schema, API endpoints, Vapi integration, frontend pages)

## Key Decisions Made
1. **Voice AI:** Using Vapi.ai (handles STT + TTS + LLM) instead of separate Deepgram + ElevenLabs + LLM
2. **Architecture:** Multi-tenant SaaS platform (not single-client build)
3. **Insurance:** Stedi API for eligibility verification (Claim.MD not directly accessible)
4. **Backend:** FastAPI (Python)
5. **Frontend:** React + Tailwind CSS
6. **Auth:** JWT with RBAC (super_admin, practice_admin, secretary)
7. **Deployment:** Dockerized
8. **Greek calls:** Transfer to staff (no AI for Greek)
9. **Friday schedule:** Toggle-based via schedule_overrides (pattern varies)
10. **MedicsCloud integration:** Phase 1 = dashboard (manual entry), Phase 2 = Playwright automation

## Blockers
- Need Vonage admin access from Dr. Stefanides (for call forwarding)
- Need Stedi provider enrollment (requires doctor's authorization)
- Need to confirm Vapi.ai account setup

## Client Contacts
- **Dr. Neofitos Stefanides** — decision maker
- **Jennie** — secretary, daily operations contact
- **NPI:** 1689880429
- **Tax ID:** 263551213
- **MedicsCloud URL:** apps.medicscloud.com/MedicsCloud/CL/NEOSTEFANIDESMD
