"""
Phase 5 & 6 startup migrations — creates tables for surveys, locations,
billing, payments, patient portal, recall campaigns, and self-service signups.
"""

import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def run_phase5_6_migrations(session: AsyncSession) -> None:
    """Idempotent DDL — safe to run on every startup."""

    # 1. Surveys table
    try:
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS surveys (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                practice_id UUID NOT NULL REFERENCES practices(id),
                appointment_id UUID REFERENCES appointments(id),
                patient_id UUID REFERENCES patients(id),
                patient_phone VARCHAR(20),
                token_hash VARCHAR(64),
                rating INTEGER CHECK (rating BETWEEN 1 AND 5),
                feedback TEXT,
                message_sent TEXT,
                status VARCHAR(20) NOT NULL DEFAULT 'sent',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                responded_at TIMESTAMPTZ
            )
        """))
        await session.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_surveys_practice ON surveys(practice_id)"
        ))
        await session.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_surveys_appointment ON surveys(appointment_id)"
        ))
        await session.commit()
        logger.info("phase5_6_migrations: surveys table ensured")
    except Exception as e:
        await session.rollback()
        logger.warning("phase5_6_migrations: surveys table skipped: %s", e)

    # 2. Practice locations table
    try:
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS practice_locations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                practice_id UUID NOT NULL REFERENCES practices(id),
                name VARCHAR(255) NOT NULL,
                address_line1 VARCHAR(255) DEFAULT '',
                address_line2 VARCHAR(255) DEFAULT '',
                city VARCHAR(100) DEFAULT '',
                state VARCHAR(2) DEFAULT '',
                zip_code VARCHAR(10) DEFAULT '',
                phone VARCHAR(20) DEFAULT '',
                fax VARCHAR(20) DEFAULT '',
                timezone VARCHAR(50) DEFAULT 'America/New_York',
                is_primary BOOLEAN DEFAULT FALSE,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        await session.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_locations_practice ON practice_locations(practice_id)"
        ))
        await session.commit()
        logger.info("phase5_6_migrations: practice_locations table ensured")
    except Exception as e:
        await session.rollback()
        logger.warning("phase5_6_migrations: practice_locations skipped: %s", e)

    # 3. Provider-location assignments
    try:
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS provider_locations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                provider_id UUID NOT NULL REFERENCES users(id),
                location_id UUID NOT NULL REFERENCES practice_locations(id),
                is_primary BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(provider_id, location_id)
            )
        """))
        await session.commit()
        logger.info("phase5_6_migrations: provider_locations table ensured")
    except Exception as e:
        await session.rollback()
        logger.warning("phase5_6_migrations: provider_locations skipped: %s", e)

    # 4. Usage events (billing)
    try:
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS usage_events (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                practice_id UUID NOT NULL REFERENCES practices(id),
                usage_type VARCHAR(30) NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                metadata JSONB DEFAULT '{}',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        await session.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_usage_events_practice_date "
            "ON usage_events(practice_id, created_at)"
        ))
        await session.commit()
        logger.info("phase5_6_migrations: usage_events table ensured")
    except Exception as e:
        await session.rollback()
        logger.warning("phase5_6_migrations: usage_events skipped: %s", e)

    # 5. Monthly bills
    try:
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS monthly_bills (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                practice_id UUID NOT NULL REFERENCES practices(id),
                month VARCHAR(7) NOT NULL,
                plan_name VARCHAR(50),
                base_amount DECIMAL(10, 2) DEFAULT 0,
                overage_amount DECIMAL(10, 2) DEFAULT 0,
                total_amount DECIMAL(10, 2) DEFAULT 0,
                status VARCHAR(20) DEFAULT 'pending',
                stripe_invoice_id VARCHAR(255),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                paid_at TIMESTAMPTZ,
                UNIQUE(practice_id, month)
            )
        """))
        await session.commit()
        logger.info("phase5_6_migrations: monthly_bills table ensured")
    except Exception as e:
        await session.rollback()
        logger.warning("phase5_6_migrations: monthly_bills skipped: %s", e)

    # 6. Payments (Stripe)
    try:
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS payments (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                practice_id UUID NOT NULL REFERENCES practices(id),
                patient_id UUID REFERENCES patients(id),
                patient_phone VARCHAR(20),
                amount_cents INTEGER NOT NULL,
                description VARCHAR(500),
                stripe_payment_intent_id VARCHAR(255),
                stripe_checkout_session_id VARCHAR(255),
                status VARCHAR(20) DEFAULT 'pending',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                paid_at TIMESTAMPTZ
            )
        """))
        await session.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_payments_practice ON payments(practice_id)"
        ))
        await session.commit()
        logger.info("phase5_6_migrations: payments table ensured")
    except Exception as e:
        await session.rollback()
        logger.warning("phase5_6_migrations: payments skipped: %s", e)

    # 7. Intake links (patient portal)
    try:
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS intake_links (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                practice_id UUID NOT NULL REFERENCES practices(id),
                patient_phone VARCHAR(20),
                patient_name VARCHAR(255),
                appointment_id UUID REFERENCES appointments(id),
                token_hash VARCHAR(64),
                status VARCHAR(20) DEFAULT 'sent',
                sent_at TIMESTAMPTZ,
                opened_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ,
                expires_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        await session.commit()
        logger.info("phase5_6_migrations: intake_links table ensured")
    except Exception as e:
        await session.rollback()
        logger.warning("phase5_6_migrations: intake_links skipped: %s", e)

    # 8. Intake submissions
    try:
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS intake_submissions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                practice_id UUID NOT NULL REFERENCES practices(id),
                intake_link_id UUID REFERENCES intake_links(id),
                patient_phone VARCHAR(20),
                demographics JSONB DEFAULT '{}',
                insurance_info JSONB DEFAULT '{}',
                medical_history JSONB DEFAULT '{}',
                medications JSONB DEFAULT '{}',
                allergies JSONB DEFAULT '{}',
                emergency_contact JSONB DEFAULT '{}',
                consent_signatures JSONB DEFAULT '{}',
                status VARCHAR(20) DEFAULT 'submitted',
                reviewed_by UUID REFERENCES users(id),
                reviewed_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        await session.commit()
        logger.info("phase5_6_migrations: intake_submissions table ensured")
    except Exception as e:
        await session.rollback()
        logger.warning("phase5_6_migrations: intake_submissions skipped: %s", e)

    # 9. Recall campaigns
    try:
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS recall_campaigns (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                practice_id UUID NOT NULL REFERENCES practices(id),
                name VARCHAR(255) NOT NULL,
                recall_type VARCHAR(50) NOT NULL,
                params JSONB DEFAULT '{}',
                status VARCHAR(20) DEFAULT 'draft',
                scheduled_at TIMESTAMPTZ,
                started_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ,
                created_by UUID REFERENCES users(id),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        await session.commit()
        logger.info("phase5_6_migrations: recall_campaigns table ensured")
    except Exception as e:
        await session.rollback()
        logger.warning("phase5_6_migrations: recall_campaigns skipped: %s", e)

    # 10. Recall contacts
    try:
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS recall_contacts (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                campaign_id UUID NOT NULL REFERENCES recall_campaigns(id),
                practice_id UUID NOT NULL REFERENCES practices(id),
                patient_id UUID REFERENCES patients(id),
                patient_name VARCHAR(255),
                patient_phone VARCHAR(20),
                last_visit_date DATE,
                message_sent TEXT,
                status VARCHAR(20) DEFAULT 'pending',
                sent_at TIMESTAMPTZ,
                responded_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        await session.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_recall_contacts_campaign "
            "ON recall_contacts(campaign_id)"
        ))
        await session.commit()
        logger.info("phase5_6_migrations: recall_contacts table ensured")
    except Exception as e:
        await session.rollback()
        logger.warning("phase5_6_migrations: recall_contacts skipped: %s", e)

    # 11. Add opted_out_recall to patients
    try:
        await session.execute(text(
            "ALTER TABLE patients ADD COLUMN IF NOT EXISTS "
            "opted_out_recall BOOLEAN DEFAULT FALSE"
        ))
        await session.commit()
        logger.info("phase5_6_migrations: patients.opted_out_recall ensured")
    except Exception as e:
        await session.rollback()
        logger.warning("phase5_6_migrations: opted_out_recall skipped: %s", e)

    # 12. Practice signups (self-service)
    try:
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS practice_signups (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                email VARCHAR(255) NOT NULL,
                practice_name VARCHAR(255) NOT NULL,
                phone VARCHAR(20) DEFAULT '',
                plan VARCHAR(20) DEFAULT 'starter',
                verification_code VARCHAR(6),
                code_expires_at TIMESTAMPTZ,
                email_verified BOOLEAN DEFAULT FALSE,
                onboarding_step INTEGER DEFAULT 0,
                onboarding_data JSONB DEFAULT '{}',
                status VARCHAR(20) DEFAULT 'pending',
                completed_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        await session.commit()
        logger.info("phase5_6_migrations: practice_signups table ensured")
    except Exception as e:
        await session.rollback()
        logger.warning("phase5_6_migrations: practice_signups skipped: %s", e)

    # 13. Practice API keys
    try:
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS practice_api_keys (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                practice_id UUID NOT NULL REFERENCES practices(id),
                key_hash VARCHAR(64) NOT NULL,
                key_prefix VARCHAR(8),
                name VARCHAR(100),
                is_active BOOLEAN DEFAULT TRUE,
                last_used_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                revoked_at TIMESTAMPTZ
            )
        """))
        await session.commit()
        logger.info("phase5_6_migrations: practice_api_keys table ensured")
    except Exception as e:
        await session.rollback()
        logger.warning("phase5_6_migrations: practice_api_keys skipped: %s", e)

    logger.info("phase5_6_migrations: all Phase 5 & 6 tables complete")
