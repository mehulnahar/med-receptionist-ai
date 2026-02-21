"""
HIPAA startup migrations — creates required tables for HIPAA compliance.

Called from main.py lifespan on application startup.
All migrations are idempotent (safe to re-run).
"""

import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def run_hipaa_migrations(session: AsyncSession) -> None:
    """Run all HIPAA-related table creation migrations."""

    # 1. Audit Read Logs table (append-only — HIPAA requirement)
    try:
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS audit_read_logs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id VARCHAR(255),
                user_role VARCHAR(50),
                patient_id VARCHAR(255),
                practice_id VARCHAR(255),
                endpoint VARCHAR(500) NOT NULL,
                method VARCHAR(10) NOT NULL DEFAULT 'GET',
                query_params TEXT,
                ip_address VARCHAR(45),
                request_id VARCHAR(255),
                accessed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        await session.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_audit_read_user "
            "ON audit_read_logs(user_id, accessed_at DESC)"
        ))
        await session.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_audit_read_patient "
            "ON audit_read_logs(patient_id, accessed_at DESC)"
        ))
        await session.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_audit_read_practice "
            "ON audit_read_logs(practice_id, accessed_at DESC)"
        ))
        await session.commit()
        logger.info("hipaa_migrations: audit_read_logs table ensured")
    except Exception as e:
        await session.rollback()
        logger.warning("hipaa_migrations: audit_read_logs skipped: %s", e)

    # 2. Password History table
    try:
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS password_history (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                password_hash VARCHAR(255) NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        await session.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_password_history_user "
            "ON password_history(user_id, created_at DESC)"
        ))
        await session.commit()
        logger.info("hipaa_migrations: password_history table ensured")
    except Exception as e:
        await session.rollback()
        logger.warning("hipaa_migrations: password_history skipped: %s", e)

    # 3. User Session tracking table
    try:
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS user_sessions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
                last_activity TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        await session.commit()
        logger.info("hipaa_migrations: user_sessions table ensured")
    except Exception as e:
        await session.rollback()
        logger.warning("hipaa_migrations: user_sessions skipped: %s", e)

    # 4. Add HIPAA columns to users table
    hipaa_user_columns = [
        ("failed_login_attempts", "INTEGER NOT NULL DEFAULT 0"),
        ("locked_until", "TIMESTAMPTZ"),
        ("last_password_change", "TIMESTAMPTZ"),
    ]
    for col_name, col_type in hipaa_user_columns:
        try:
            await session.execute(text(
                f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col_name} {col_type}"
            ))
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.warning("hipaa_migrations: users.%s skipped: %s", col_name, e)

    # 5. Add PHI search hash columns to patients table
    phi_hash_columns = [
        ("first_name_hash", "VARCHAR(64)"),
        ("last_name_hash", "VARCHAR(64)"),
        ("phone_hash", "VARCHAR(64)"),
        ("dob_hash", "VARCHAR(64)"),
    ]
    for col_name, col_type in phi_hash_columns:
        try:
            await session.execute(text(
                f"ALTER TABLE patients ADD COLUMN IF NOT EXISTS {col_name} {col_type}"
            ))
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.warning("hipaa_migrations: patients.%s skipped: %s", col_name, e)

    # Create indexes on hash columns for searchable encrypted fields
    try:
        await session.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_patients_name_hash "
            "ON patients(practice_id, last_name_hash, first_name_hash)"
        ))
        await session.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_patients_dob_hash "
            "ON patients(practice_id, dob_hash)"
        ))
        await session.commit()
        logger.info("hipaa_migrations: PHI hash indexes ensured")
    except Exception as e:
        await session.rollback()
        logger.warning("hipaa_migrations: PHI hash indexes skipped: %s", e)

    # 6. SMS opt-out table
    try:
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS sms_opt_outs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                practice_id UUID NOT NULL REFERENCES practices(id),
                phone_number VARCHAR(20) NOT NULL,
                opted_out_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                reason VARCHAR(100) DEFAULT 'STOP',
                UNIQUE(practice_id, phone_number)
            )
        """))
        await session.commit()
        logger.info("hipaa_migrations: sms_opt_outs table ensured")
    except Exception as e:
        await session.rollback()
        logger.warning("hipaa_migrations: sms_opt_outs skipped: %s", e)

    # 7. ROI configuration table
    try:
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS roi_config (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                practice_id UUID NOT NULL UNIQUE REFERENCES practices(id),
                staff_hourly_cost NUMERIC(10,2) DEFAULT 25.00,
                avg_appointment_value NUMERIC(10,2) DEFAULT 150.00,
                human_receptionist_monthly_cost NUMERIC(10,2) DEFAULT 3500.00,
                avg_call_duration_minutes NUMERIC(5,2) DEFAULT 4.50,
                no_show_reduction_rate NUMERIC(5,4) DEFAULT 0.40,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        await session.commit()
        logger.info("hipaa_migrations: roi_config table ensured")
    except Exception as e:
        await session.rollback()
        logger.warning("hipaa_migrations: roi_config skipped: %s", e)

    # 8. Post-call survey responses table
    try:
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS call_surveys (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                practice_id UUID NOT NULL REFERENCES practices(id),
                call_id UUID REFERENCES calls(id),
                patient_phone VARCHAR(20),
                score INTEGER CHECK (score >= 1 AND score <= 5),
                message_sid VARCHAR(100),
                responded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        await session.commit()
        logger.info("hipaa_migrations: call_surveys table ensured")
    except Exception as e:
        await session.rollback()
        logger.warning("hipaa_migrations: call_surveys skipped: %s", e)

    # 9. EHR connection tables
    try:
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS ehr_connections (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                practice_id UUID NOT NULL UNIQUE REFERENCES practices(id),
                ehr_type VARCHAR(50) NOT NULL,
                ehr_base_url VARCHAR(500),
                ehr_practice_id VARCHAR(255),
                access_token TEXT,
                refresh_token TEXT,
                token_expires_at TIMESTAMPTZ,
                is_connected BOOLEAN DEFAULT FALSE,
                last_sync_at TIMESTAMPTZ,
                sync_enabled BOOLEAN DEFAULT TRUE,
                connection_metadata JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS ehr_sync_log (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                practice_id UUID NOT NULL REFERENCES practices(id),
                direction VARCHAR(20) NOT NULL,
                resource_type VARCHAR(50) NOT NULL,
                resource_id VARCHAR(255),
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                details JSONB,
                error_message TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS ehr_type_mappings (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                practice_id UUID NOT NULL REFERENCES practices(id),
                our_type_id UUID REFERENCES appointment_types(id),
                ehr_type_id VARCHAR(255) NOT NULL,
                ehr_type_name VARCHAR(255),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(practice_id, our_type_id)
            )
        """))
        await session.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_ehr_sync_log_practice "
            "ON ehr_sync_log(practice_id, created_at DESC)"
        ))
        await session.commit()
        logger.info("hipaa_migrations: EHR tables ensured")
    except Exception as e:
        await session.rollback()
        logger.warning("hipaa_migrations: EHR tables skipped: %s", e)

    # 10. Escalation events table (used by voice triage system)
    try:
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS escalation_events (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                practice_id UUID NOT NULL REFERENCES practices(id),
                call_id VARCHAR(255),
                urgency_level VARCHAR(20) NOT NULL,
                matched_keyword VARCHAR(255),
                transcript_snippet TEXT,
                detection_time_ms NUMERIC(8,2),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        await session.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_escalation_events_practice "
            "ON escalation_events(practice_id, created_at DESC)"
        ))
        await session.commit()
        logger.info("hipaa_migrations: escalation_events table ensured")
    except Exception as e:
        await session.rollback()
        logger.warning("hipaa_migrations: escalation_events skipped: %s", e)

    logger.info("hipaa_migrations: all HIPAA migrations completed")
