"""
Tests for the enterprise module (Phase 6): billing, payments, patient portal,
recall campaigns, self-service onboarding, and multi-location management.

All database and external-service calls are mocked -- no live connections required.
"""

import pytest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_row(**kwargs):
    """Return a MagicMock whose attributes match **kwargs."""
    row = MagicMock()
    for k, v in kwargs.items():
        setattr(row, k, v)
    return row


def _mock_db(
    *,
    fetchone=None,
    fetchall=None,
    scalar_one=None,
    rowcount=0,
):
    """Build a minimal AsyncMock db session.

    * ``fetchone``  – value returned by result.fetchone()
    * ``fetchall``  – value returned by result.fetchall() (default [])
    * ``scalar_one`` – value returned by result.scalar_one()
    * ``rowcount``  – result.rowcount
    """
    mock_result = MagicMock()
    mock_result.fetchone.return_value = fetchone
    mock_result.fetchall.return_value = fetchall if fetchall is not None else []
    if scalar_one is not None:
        mock_result.scalar_one.return_value = scalar_one
    mock_result.rowcount = rowcount

    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)
    db.commit = AsyncMock()
    return db


# ===================================================================
# 1. BillingService
# ===================================================================


class TestBillingPlans:
    """Validate the PLANS dictionary pricing constants."""

    def test_starter_plan_price(self):
        from app.enterprise.billing_service import PLANS

        assert PLANS["starter"]["base_price"] == Decimal("799.00")

    def test_professional_plan_price(self):
        from app.enterprise.billing_service import PLANS

        assert PLANS["professional"]["base_price"] == Decimal("1499.00")

    def test_enterprise_plan_price(self):
        from app.enterprise.billing_service import PLANS

        assert PLANS["enterprise"]["base_price"] == Decimal("2999.00")

    def test_starter_limits(self):
        from app.enterprise.billing_service import PLANS

        limits = PLANS["starter"]["limits"]
        assert limits["call_handled"] == 500
        assert limits["sms_sent"] == 1000
        assert limits["insurance_check"] == 200

    def test_enterprise_limits_effectively_unlimited(self):
        from app.enterprise.billing_service import PLANS

        limits = PLANS["enterprise"]["limits"]
        assert limits["call_handled"] == 999999
        assert limits["sms_sent"] == 999999
        assert limits["insurance_check"] == 999999

    def test_valid_usage_types(self):
        from app.enterprise.billing_service import VALID_USAGE_TYPES

        expected = {"call_handled", "sms_sent", "insurance_check", "ehr_sync", "survey_sent"}
        assert VALID_USAGE_TYPES == expected


class TestBillingServiceRecordUsage:
    """Tests for BillingService.record_usage."""

    @pytest.mark.asyncio
    async def test_reject_invalid_usage_type(self):
        from app.enterprise.billing_service import BillingService

        db = _mock_db()
        await BillingService.record_usage(db, str(uuid4()), "invalid_type", 1)
        # Invalid type should NOT result in a DB insert
        db.execute.assert_not_awaited()
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_valid_usage_type_inserts(self):
        from app.enterprise.billing_service import BillingService

        db = _mock_db()
        pid = str(uuid4())
        await BillingService.record_usage(db, pid, "call_handled", 3, {"source": "test"})
        db.execute.assert_awaited_once()
        db.commit.assert_awaited_once()


class TestUsageSummaryModel:
    """Test that the Pydantic UsageSummary model can be created."""

    def test_create_usage_summary(self):
        from app.enterprise.billing_service import UsageSummary

        summary = UsageSummary(
            month="2025-06",
            calls=100,
            sms=200,
            insurance_checks=50,
            ehr_syncs=10,
            surveys=5,
            total_cost=899.0,
        )
        assert summary.month == "2025-06"
        assert summary.calls == 100
        assert summary.sms == 200
        assert summary.insurance_checks == 50
        assert summary.ehr_syncs == 10
        assert summary.surveys == 5
        assert summary.total_cost == 899.0


class TestMonthlyBillModel:
    """Test the MonthlyBill Pydantic model."""

    def test_monthly_bill_total_equals_base_plus_overage(self):
        from app.enterprise.billing_service import MonthlyBill

        bill = MonthlyBill(
            month="2025-06",
            plan_name="Starter",
            base_amount=799.0,
            overage_amount=50.0,
            total_amount=849.0,
            usage={"call_handled": 600},
        )
        assert bill.total_amount == bill.base_amount + bill.overage_amount


class TestBillingServiceCalculateMonthlyBill:
    """Tests for BillingService.calculate_monthly_bill."""

    @pytest.mark.asyncio
    async def test_starter_plan_overage_on_calls(self):
        """600 calls on starter plan = 100 excess * $0.50 = $50 overage."""
        from app.enterprise.billing_service import BillingService

        pid = str(uuid4())

        # Mock for plan query: practices.config
        plan_row = _mock_row(config={"billing_plan": "starter"})
        plan_result = MagicMock()
        plan_result.fetchone.return_value = plan_row

        # Mock for usage query: usage_events aggregation
        usage_rows = [
            _mock_row(usage_type="call_handled", total=600),
            _mock_row(usage_type="sms_sent", total=100),
            _mock_row(usage_type="insurance_check", total=50),
        ]
        usage_result = MagicMock()
        usage_result.fetchall.return_value = usage_rows

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[plan_result, usage_result])
        db.commit = AsyncMock()

        bill = await BillingService.calculate_monthly_bill(db, pid, "2025-06")

        assert bill.plan_name == "Starter"
        assert bill.base_amount == 799.0
        assert bill.overage_amount == 50.0  # 100 * $0.50
        assert bill.total_amount == 849.0

    @pytest.mark.asyncio
    async def test_enterprise_plan_no_overage(self):
        """Enterprise plan should have $0 overage regardless of usage."""
        from app.enterprise.billing_service import BillingService

        pid = str(uuid4())

        plan_row = _mock_row(config={"billing_plan": "enterprise"})
        plan_result = MagicMock()
        plan_result.fetchone.return_value = plan_row

        usage_rows = [
            _mock_row(usage_type="call_handled", total=50000),
            _mock_row(usage_type="sms_sent", total=99999),
            _mock_row(usage_type="insurance_check", total=99999),
        ]
        usage_result = MagicMock()
        usage_result.fetchall.return_value = usage_rows

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[plan_result, usage_result])
        db.commit = AsyncMock()

        bill = await BillingService.calculate_monthly_bill(db, pid, "2025-06")

        assert bill.plan_name == "Enterprise"
        assert bill.base_amount == 2999.0
        assert bill.overage_amount == 0.0
        assert bill.total_amount == 2999.0


class TestBillingServiceGenerateInvoice:
    """Tests for BillingService.generate_invoice."""

    @pytest.mark.asyncio
    async def test_generate_invoice_returns_existing(self):
        """When an invoice already exists, it should be returned without creating a new one."""
        from app.enterprise.billing_service import BillingService

        pid = str(uuid4())
        existing_id = uuid4()

        existing_row = _mock_row(
            id=existing_id,
            total_amount=Decimal("849.00"),
            status="paid",
        )
        existing_result = MagicMock()
        existing_result.fetchone.return_value = existing_row

        db = AsyncMock()
        db.execute = AsyncMock(return_value=existing_result)
        db.commit = AsyncMock()

        result = await BillingService.generate_invoice(db, pid, "2025-06")

        assert result["already_exists"] is True
        assert result["invoice_id"] == str(existing_id)
        assert result["total_amount"] == float(Decimal("849.00"))
        assert result["status"] == "paid"


# ===================================================================
# 2. StripePaymentService
# ===================================================================


class TestStripePaymentServiceStatus:
    """Tests for StripePaymentService.check_payment_status."""

    @pytest.mark.asyncio
    async def test_check_payment_status_unknown_session(self):
        """Unknown session ID should return error dict."""
        from app.enterprise.payment_service import StripePaymentService

        db = _mock_db(fetchone=None)
        result = await StripePaymentService.check_payment_status(db, "cs_unknown_123")
        assert result == {"error": "Payment not found"}


class TestStripePaymentServiceStats:
    """Tests for StripePaymentService.get_payment_stats."""

    @pytest.mark.asyncio
    async def test_payment_stats_collection_rate(self):
        """Collection rate should be (paid / total) * 100."""
        from app.enterprise.payment_service import StripePaymentService

        pid = str(uuid4())
        stats_row = _mock_row(
            total=10,
            paid_count=7,
            pending_count=3,
            total_collected=150000,    # $1500.00
            total_pending=60000,       # $600.00
            avg_hours_to_pay=4.5,
        )
        db = _mock_db(fetchone=stats_row)

        result = await StripePaymentService.get_payment_stats(db, pid)

        assert result["total_payments"] == 10
        assert result["paid_count"] == 7
        assert result["pending_count"] == 3
        assert result["total_collected_cents"] == 150000
        assert result["total_collected_dollars"] == 1500.0
        assert result["total_pending_cents"] == 60000
        assert result["collection_rate_pct"] == 70.0
        assert result["avg_hours_to_pay"] == 4.5

    @pytest.mark.asyncio
    async def test_payment_stats_zero_total(self):
        """When no payments exist, collection_rate_pct should be 0."""
        from app.enterprise.payment_service import StripePaymentService

        pid = str(uuid4())
        stats_row = _mock_row(
            total=0,
            paid_count=0,
            pending_count=0,
            total_collected=0,
            total_pending=0,
            avg_hours_to_pay=None,
        )
        db = _mock_db(fetchone=stats_row)

        result = await StripePaymentService.get_payment_stats(db, pid)
        assert result["collection_rate_pct"] == 0


class TestStripePaymentServiceHistory:
    """Tests for StripePaymentService.get_payment_history."""

    @pytest.mark.asyncio
    async def test_payment_history_with_phone_filter(self):
        """get_payment_history with phone filter should include the phone param."""
        from app.enterprise.payment_service import StripePaymentService

        pid = str(uuid4())
        payment_id = uuid4()
        now = datetime.now(timezone.utc)

        rows = [
            _mock_row(
                id=payment_id,
                patient_phone="+15551234567",
                amount_cents=5000,
                description="Copay",
                status="paid",
                created_at=now,
                paid_at=now,
            )
        ]
        db = _mock_db(fetchall=rows)

        result = await StripePaymentService.get_payment_history(
            db, pid, patient_phone="+15551234567", limit=10
        )

        assert len(result) == 1
        assert result[0]["patient_phone"] == "+15551234567"
        assert result[0]["amount_cents"] == 5000
        assert result[0]["amount_dollars"] == 50.0
        assert result[0]["status"] == "paid"

    @pytest.mark.asyncio
    async def test_payment_history_without_phone_filter(self):
        """get_payment_history without phone should return all for the practice."""
        from app.enterprise.payment_service import StripePaymentService

        pid = str(uuid4())
        db = _mock_db(fetchall=[])

        result = await StripePaymentService.get_payment_history(db, pid)
        assert result == []


# ===================================================================
# 3. PatientPortalService
# ===================================================================


@pytest.fixture
def _portal_jwt_env(monkeypatch):
    """Set JWT_SECRET for portal token tests and clear settings cache."""
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret-for-portal-tests")
    monkeypatch.setenv("APP_URL", "https://test.example.com")
    # Clear cached settings so the new env var is picked up
    from app.config import clear_settings_cache
    clear_settings_cache()
    yield
    clear_settings_cache()


class TestPatientPortalTokens:
    """Token generation / validation round-trip tests."""

    @pytest.mark.asyncio
    async def test_token_generation_and_validation_roundtrip(self, _portal_jwt_env):
        """send_intake_link should produce a token that validate_intake_token decodes."""
        from app.enterprise.patient_portal import PatientPortalService

        pid = str(uuid4())
        db = _mock_db()

        with patch("app.enterprise.patient_portal._send_portal_sms", new_callable=AsyncMock, return_value=True):
            token = await PatientPortalService.send_intake_link(
                db, pid, "+15551234567", "Maria Garcia", str(uuid4())
            )

        payload = PatientPortalService.validate_intake_token(token)
        assert payload is not None
        assert payload["type"] == "intake"
        assert payload["practice_id"] == pid
        assert payload["patient_phone"] == "+15551234567"
        assert payload["patient_name"] == "Maria Garcia"

    def test_expired_token_returns_none(self, _portal_jwt_env):
        """An expired JWT should be rejected."""
        import jwt as pyjwt
        from app.enterprise.patient_portal import PatientPortalService
        from app.config import get_settings

        settings = get_settings()
        expired_payload = {
            "type": "intake",
            "practice_id": str(uuid4()),
            "patient_phone": "+15551234567",
            "patient_name": "Test",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        }
        token = pyjwt.encode(expired_payload, settings.JWT_SECRET, algorithm="HS256")
        result = PatientPortalService.validate_intake_token(token)
        assert result is None

    def test_invalid_token_returns_none(self, _portal_jwt_env):
        """A completely invalid string should return None."""
        from app.enterprise.patient_portal import PatientPortalService

        result = PatientPortalService.validate_intake_token("not.a.valid.jwt.token")
        assert result is None

    def test_wrong_type_token_returns_none(self, _portal_jwt_env):
        """A JWT with type='survey' instead of 'intake' should return None."""
        import jwt as pyjwt
        from app.enterprise.patient_portal import PatientPortalService
        from app.config import get_settings

        settings = get_settings()
        payload = {
            "type": "survey",
            "practice_id": str(uuid4()),
            "patient_phone": "+15551234567",
            "patient_name": "Test",
            "exp": datetime.now(timezone.utc) + timedelta(hours=24),
        }
        token = pyjwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")
        result = PatientPortalService.validate_intake_token(token)
        assert result is None


class TestPatientPortalSaveIntake:
    """Tests for PatientPortalService.save_intake_form."""

    @pytest.mark.asyncio
    async def test_save_intake_form_invalid_token_returns_error(self, _portal_jwt_env):
        """save_intake_form with a bad token should return error dict."""
        from app.enterprise.patient_portal import PatientPortalService

        db = _mock_db()
        result = await PatientPortalService.save_intake_form(
            db, "invalid-token", {"demographics": {"first_name": "Test"}}
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_save_intake_form_extracts_sections(self, _portal_jwt_env):
        """Verify that form_data sections are extracted and the insert executes."""
        import jwt as pyjwt
        from app.enterprise.patient_portal import PatientPortalService
        from app.config import get_settings

        settings = get_settings()
        pid = str(uuid4())
        payload = {
            "type": "intake",
            "practice_id": pid,
            "patient_phone": "+15559876543",
            "patient_name": "Test Patient",
            "appointment_id": "",
            "exp": datetime.now(timezone.utc) + timedelta(hours=24),
        }
        token = pyjwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")

        # First execute: link lookup; second execute: insert; third execute: update link
        link_row = _mock_row(id=uuid4())
        link_result = MagicMock()
        link_result.fetchone.return_value = link_row

        insert_result = MagicMock()
        insert_result.fetchone.return_value = _mock_row(id=uuid4())

        update_result = MagicMock()

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[link_result, insert_result, update_result])
        db.commit = AsyncMock()

        form_data = {
            "demographics": {"first_name": "Maria", "last_name": "Garcia"},
            "insurance_info": {"carrier": "Aetna"},
            "medical_history": {"conditions": ["diabetes"]},
            "medications": {"current": ["metformin"]},
            "allergies": {"list": ["penicillin"]},
            "emergency_contact": {"name": "John Garcia"},
            "consent_signatures": {"hipaa": True},
        }

        result = await PatientPortalService.save_intake_form(db, token, form_data)

        assert result["status"] == "submitted"
        assert result["practice_id"] == pid
        assert result["patient_phone"] == "+15559876543"
        # Should have executed 3 queries: SELECT link, INSERT submission, UPDATE link
        assert db.execute.await_count == 3
        db.commit.assert_awaited_once()


class TestPatientPortalListAndStats:
    """Tests for list_intake_submissions and get_intake_stats."""

    @pytest.mark.asyncio
    async def test_list_intake_submissions(self):
        from app.enterprise.patient_portal import PatientPortalService

        pid = str(uuid4())
        sub_id = uuid4()
        now = datetime.now(timezone.utc)

        rows = [
            _mock_row(
                id=sub_id,
                patient_phone="+15551234567",
                status="submitted",
                created_at=now,
                first_name="Maria",
                last_name="Garcia",
            )
        ]
        db = _mock_db(fetchall=rows)

        result = await PatientPortalService.list_intake_submissions(db, pid, status="submitted")
        assert len(result) == 1
        assert result[0]["patient_name"] == "Maria Garcia"
        assert result[0]["status"] == "submitted"

    @pytest.mark.asyncio
    async def test_get_intake_stats_completion_rate(self):
        from app.enterprise.patient_portal import PatientPortalService

        pid = str(uuid4())
        stats_row = _mock_row(
            total_sent=20,
            total_completed=15,
            avg_minutes=12.5,
        )
        db = _mock_db(fetchone=stats_row)

        result = await PatientPortalService.get_intake_stats(db, pid)
        assert result["total_sent"] == 20
        assert result["total_completed"] == 15
        assert result["completion_rate"] == 75.0
        assert result["avg_completion_time_minutes"] == 12.5


# ===================================================================
# 4. RecallService
# ===================================================================


class TestRecallTypes:
    """Validate RECALL_TYPES constants."""

    def test_recall_types_count(self):
        from app.enterprise.recall_service import RECALL_TYPES

        assert len(RECALL_TYPES) == 4

    def test_preventive_care_days(self):
        from app.enterprise.recall_service import RECALL_TYPES

        assert RECALL_TYPES["preventive_care"]["default_days"] == 180

    def test_annual_physical_days(self):
        from app.enterprise.recall_service import RECALL_TYPES

        assert RECALL_TYPES["annual_physical"]["default_days"] == 365

    def test_follow_up_days(self):
        from app.enterprise.recall_service import RECALL_TYPES

        assert RECALL_TYPES["follow_up"]["default_days"] == 90

    def test_vaccination_days(self):
        from app.enterprise.recall_service import RECALL_TYPES

        assert RECALL_TYPES["vaccination"]["default_days"] == 365


class TestRecallServiceCreateCampaign:
    """Tests for RecallService.create_campaign."""

    @pytest.mark.asyncio
    async def test_invalid_recall_type_raises_value_error(self):
        from app.enterprise.recall_service import RecallService

        db = _mock_db()
        with pytest.raises(ValueError, match="Invalid recall type"):
            await RecallService.create_campaign(
                db, str(uuid4()), "Test Campaign", "nonexistent_type"
            )

    @pytest.mark.asyncio
    async def test_valid_recall_type_preventive_care(self):
        from app.enterprise.recall_service import RecallService

        pid = str(uuid4())
        campaign_id = uuid4()
        now = datetime.now(timezone.utc)

        row = _mock_row(id=campaign_id, created_at=now)
        result_mock = MagicMock()
        result_mock.fetchone.return_value = row

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)
        db.commit = AsyncMock()

        result = await RecallService.create_campaign(
            db, pid, "Preventive Care", "preventive_care"
        )
        assert result["recall_type"] == "preventive_care"
        assert result["status"] == "draft"
        assert result["name"] == "Preventive Care"

    @pytest.mark.asyncio
    async def test_valid_recall_type_annual_physical(self):
        from app.enterprise.recall_service import RecallService

        pid = str(uuid4())
        row = _mock_row(id=uuid4(), created_at=datetime.now(timezone.utc))
        result_mock = MagicMock()
        result_mock.fetchone.return_value = row

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)
        db.commit = AsyncMock()

        result = await RecallService.create_campaign(
            db, pid, "Annuals", "annual_physical"
        )
        assert result["recall_type"] == "annual_physical"

    @pytest.mark.asyncio
    async def test_valid_recall_type_follow_up(self):
        from app.enterprise.recall_service import RecallService

        pid = str(uuid4())
        row = _mock_row(id=uuid4(), created_at=datetime.now(timezone.utc))
        result_mock = MagicMock()
        result_mock.fetchone.return_value = row

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)
        db.commit = AsyncMock()

        result = await RecallService.create_campaign(
            db, pid, "Follow-ups", "follow_up"
        )
        assert result["recall_type"] == "follow_up"

    @pytest.mark.asyncio
    async def test_valid_recall_type_vaccination(self):
        from app.enterprise.recall_service import RecallService

        pid = str(uuid4())
        row = _mock_row(id=uuid4(), created_at=datetime.now(timezone.utc))
        result_mock = MagicMock()
        result_mock.fetchone.return_value = row

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)
        db.commit = AsyncMock()

        result = await RecallService.create_campaign(
            db, pid, "Vaccinations", "vaccination"
        )
        assert result["recall_type"] == "vaccination"

    @pytest.mark.asyncio
    async def test_default_days_since_last_visit_auto_populated(self):
        """When params omit days_since_last_visit, the default from RECALL_TYPES is used."""
        from app.enterprise.recall_service import RecallService
        import json

        pid = str(uuid4())
        row = _mock_row(id=uuid4(), created_at=datetime.now(timezone.utc))
        result_mock = MagicMock()
        result_mock.fetchone.return_value = row

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)
        db.commit = AsyncMock()

        await RecallService.create_campaign(
            db, pid, "Test", "follow_up", params={}
        )

        # Inspect the params dict that was passed to db.execute
        call_args = db.execute.call_args_list[0]
        query_params = call_args[0][1]  # second positional arg is the params dict
        inserted_params = json.loads(query_params["params"])
        assert inserted_params["days_since_last_visit"] == 90


class TestRecallServiceProcessResponse:
    """Tests for RecallService.process_recall_response."""

    @pytest.mark.asyncio
    async def test_yes_response(self):
        from app.enterprise.recall_service import RecallService

        db = _mock_db()
        result = await RecallService.process_recall_response(db, "+15551234567", "YES")
        assert result["status"] == "responded_yes"
        assert result["phone"] == "+15551234567"

    @pytest.mark.asyncio
    async def test_si_response(self):
        """Spanish 'SI' should also be responded_yes."""
        from app.enterprise.recall_service import RecallService

        db = _mock_db()
        result = await RecallService.process_recall_response(db, "+15551234567", "SI")
        assert result["status"] == "responded_yes"

    @pytest.mark.asyncio
    async def test_stop_response(self):
        from app.enterprise.recall_service import RecallService

        db = _mock_db()
        result = await RecallService.process_recall_response(db, "+15551234567", "STOP")
        assert result["status"] == "opted_out"

    @pytest.mark.asyncio
    async def test_unsubscribe_response(self):
        from app.enterprise.recall_service import RecallService

        db = _mock_db()
        result = await RecallService.process_recall_response(db, "+15551234567", "UNSUBSCRIBE")
        assert result["status"] == "opted_out"

    @pytest.mark.asyncio
    async def test_random_text_response(self):
        """Any text that's not YES/SI/STOP should be responded_no."""
        from app.enterprise.recall_service import RecallService

        db = _mock_db()
        result = await RecallService.process_recall_response(
            db, "+15551234567", "Maybe next week"
        )
        assert result["status"] == "responded_no"

    @pytest.mark.asyncio
    async def test_lowercase_yes_response(self):
        """Responses should be case-insensitive."""
        from app.enterprise.recall_service import RecallService

        db = _mock_db()
        result = await RecallService.process_recall_response(db, "+15551234567", "yes")
        assert result["status"] == "responded_yes"


class TestRecallServiceCampaignStats:
    """Tests for RecallService.get_campaign_stats."""

    @pytest.mark.asyncio
    async def test_campaign_stats_response_rate(self):
        from app.enterprise.recall_service import RecallService

        cid = str(uuid4())
        stats_row = _mock_row(
            total=100,
            sent=60,
            responded_yes=20,
            responded_no=10,
            opted_out=5,
            errors=5,
        )
        db = _mock_db(fetchone=stats_row)

        result = await RecallService.get_campaign_stats(db, cid)

        assert result["total_contacts"] == 100
        assert result["responded_yes"] == 20
        assert result["responded_no"] == 10
        assert result["opted_out"] == 5
        # response_rate = (20+10+5)/100 * 100 = 35.0
        assert result["response_rate"] == 35.0


class TestRecallServiceListCampaigns:
    """Tests for RecallService.list_campaigns."""

    @pytest.mark.asyncio
    async def test_list_campaigns(self):
        from app.enterprise.recall_service import RecallService

        pid = str(uuid4())
        cid = uuid4()
        now = datetime.now(timezone.utc)

        rows = [
            _mock_row(
                id=cid,
                name="Spring Recall",
                recall_type="preventive_care",
                status="completed",
                scheduled_at=None,
                started_at=now,
                completed_at=now,
                created_at=now,
            )
        ]
        db = _mock_db(fetchall=rows)

        result = await RecallService.list_campaigns(db, pid, status="completed")
        assert len(result) == 1
        assert result[0]["name"] == "Spring Recall"
        assert result[0]["status"] == "completed"


# ===================================================================
# 5. SelfServiceOnboardingService
# ===================================================================


class TestOnboardingSteps:
    """Validate ONBOARDING_STEPS and constants."""

    def test_six_onboarding_steps_defined(self):
        from app.enterprise.self_service_onboarding import ONBOARDING_STEPS

        assert len(ONBOARDING_STEPS) == 6

    def test_onboarding_steps_names(self):
        from app.enterprise.self_service_onboarding import ONBOARDING_STEPS

        expected = [
            "email_verification",
            "practice_info",
            "admin_account",
            "schedule_setup",
            "ai_preferences",
            "review_launch",
        ]
        assert ONBOARDING_STEPS == expected

    def test_verification_code_expiry(self):
        from app.enterprise.self_service_onboarding import VERIFICATION_CODE_EXPIRY_MINUTES

        assert VERIFICATION_CODE_EXPIRY_MINUTES == 15

    def test_max_signups_per_email_per_day(self):
        from app.enterprise.self_service_onboarding import MAX_SIGNUPS_PER_EMAIL_PER_DAY

        assert MAX_SIGNUPS_PER_EMAIL_PER_DAY == 3


class TestSelfServiceCreateSignup:
    """Tests for SelfServiceOnboardingService.create_signup."""

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded_returns_error(self):
        """When >= MAX_SIGNUPS_PER_EMAIL_PER_DAY, create_signup returns error."""
        from app.enterprise.self_service_onboarding import SelfServiceOnboardingService

        # Simulate the count query returning 3 (at the limit)
        db = _mock_db(scalar_one=3)

        with patch("app.enterprise.self_service_onboarding.get_settings") as mock_gs:
            mock_settings = MagicMock()
            mock_settings.TWILIO_ACCOUNT_SID = ""
            mock_gs.return_value = mock_settings

            result = await SelfServiceOnboardingService.create_signup(
                db, "test@example.com", "Test Practice", "+15551234567"
            )

        assert "error" in result
        assert "Too many signup attempts" in result["error"]

    @pytest.mark.asyncio
    async def test_create_signup_success(self):
        """Normal signup should return signup_id and email."""
        from app.enterprise.self_service_onboarding import SelfServiceOnboardingService

        signup_id = uuid4()

        # First call: scalar_one for count check
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0

        # Second call: fetchone for the INSERT RETURNING
        insert_row = _mock_row(id=signup_id)
        insert_result = MagicMock()
        insert_result.fetchone.return_value = insert_row

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[count_result, insert_result])
        db.commit = AsyncMock()

        with patch("app.enterprise.self_service_onboarding.get_settings") as mock_gs:
            mock_settings = MagicMock()
            mock_settings.TWILIO_ACCOUNT_SID = ""
            mock_gs.return_value = mock_settings

            result = await SelfServiceOnboardingService.create_signup(
                db, "test@example.com", "Test Practice"
            )

        assert "signup_id" in result
        assert result["signup_id"] == str(signup_id)
        assert result["email"] == "test@example.com"


class TestSelfServiceVerifyEmail:
    """Tests for SelfServiceOnboardingService.verify_email."""

    @pytest.mark.asyncio
    async def test_verify_email_expired_code_returns_false(self):
        """An expired verification code should return False."""
        from app.enterprise.self_service_onboarding import SelfServiceOnboardingService

        expired_time = datetime.now(timezone.utc) - timedelta(hours=1)
        row = _mock_row(
            verification_code="123456",
            code_expires_at=expired_time,
            email_verified=False,
        )
        db = _mock_db(fetchone=row)

        result = await SelfServiceOnboardingService.verify_email(db, str(uuid4()), "123456")
        assert result is False

    @pytest.mark.asyncio
    async def test_verify_email_already_verified_returns_true(self):
        """When email_verified is already True, verify_email returns True immediately."""
        from app.enterprise.self_service_onboarding import SelfServiceOnboardingService

        row = _mock_row(
            verification_code="123456",
            code_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            email_verified=True,
        )
        db = _mock_db(fetchone=row)

        result = await SelfServiceOnboardingService.verify_email(db, str(uuid4()), "123456")
        assert result is True

    @pytest.mark.asyncio
    async def test_verify_email_wrong_code_returns_false(self):
        """A wrong code should return False."""
        from app.enterprise.self_service_onboarding import SelfServiceOnboardingService

        row = _mock_row(
            verification_code="123456",
            code_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            email_verified=False,
        )
        db = _mock_db(fetchone=row)

        result = await SelfServiceOnboardingService.verify_email(db, str(uuid4()), "999999")
        assert result is False

    @pytest.mark.asyncio
    async def test_verify_email_correct_code_returns_true(self):
        """Correct code within expiry should return True and update DB."""
        from app.enterprise.self_service_onboarding import SelfServiceOnboardingService

        row = _mock_row(
            verification_code="654321",
            code_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            email_verified=False,
        )
        # First execute: SELECT; Second execute: UPDATE
        select_result = MagicMock()
        select_result.fetchone.return_value = row

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[select_result, MagicMock()])
        db.commit = AsyncMock()

        result = await SelfServiceOnboardingService.verify_email(db, str(uuid4()), "654321")
        assert result is True
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_verify_email_nonexistent_signup_returns_false(self):
        """If the signup does not exist, verify_email returns False."""
        from app.enterprise.self_service_onboarding import SelfServiceOnboardingService

        db = _mock_db(fetchone=None)
        result = await SelfServiceOnboardingService.verify_email(db, str(uuid4()), "123456")
        assert result is False


class TestSelfServiceOnboardingProgress:
    """Tests for SelfServiceOnboardingService.get_onboarding_progress."""

    @pytest.mark.asyncio
    async def test_onboarding_progress_step_0(self):
        """Step 0 => 0% progress."""
        from app.enterprise.self_service_onboarding import SelfServiceOnboardingService

        row = _mock_row(
            onboarding_step=0,
            email_verified=False,
            status="pending",
            created_at=datetime.now(timezone.utc),
        )
        db = _mock_db(fetchone=row)

        result = await SelfServiceOnboardingService.get_onboarding_progress(db, str(uuid4()))

        assert result["current_step"] == 0
        assert result["current_step_name"] == "email_verification"
        assert result["email_verified"] is False
        assert result["progress_pct"] == 0.0
        assert len(result["completed_steps"]) == 0
        assert len(result["remaining_steps"]) == 6

    @pytest.mark.asyncio
    async def test_onboarding_progress_step_3(self):
        """Step 3 => 50% progress, 3 completed / 3 remaining."""
        from app.enterprise.self_service_onboarding import SelfServiceOnboardingService

        row = _mock_row(
            onboarding_step=3,
            email_verified=True,
            status="verified",
            created_at=datetime.now(timezone.utc),
        )
        db = _mock_db(fetchone=row)

        result = await SelfServiceOnboardingService.get_onboarding_progress(db, str(uuid4()))

        assert result["current_step"] == 3
        assert result["current_step_name"] == "schedule_setup"
        assert result["progress_pct"] == 50.0
        assert len(result["completed_steps"]) == 3
        assert len(result["remaining_steps"]) == 3

    @pytest.mark.asyncio
    async def test_onboarding_progress_not_found(self):
        """Non-existent signup returns error dict."""
        from app.enterprise.self_service_onboarding import SelfServiceOnboardingService

        db = _mock_db(fetchone=None)
        result = await SelfServiceOnboardingService.get_onboarding_progress(db, str(uuid4()))
        assert "error" in result


# ===================================================================
# 6. LocationService (multi_location)
# ===================================================================


class TestLocationServiceUpdate:
    """Tests for LocationService.update_location."""

    @pytest.mark.asyncio
    async def test_update_location_no_valid_fields(self):
        """update_location with no allowed fields should return error."""
        from app.enterprise.multi_location import LocationService

        db = _mock_db()
        result = await LocationService.update_location(
            db, str(uuid4()), uuid4(),
            invalid_field="value",
            another_bad_field=42,
        )
        assert "error" in result
        assert "No valid fields" in result["error"]

    @pytest.mark.asyncio
    async def test_update_location_filters_allowed_fields(self):
        """Only allowed fields should be included in the UPDATE query."""
        from app.enterprise.multi_location import LocationService

        db = _mock_db()
        loc_id = str(uuid4())
        practice_id = uuid4()

        result = await LocationService.update_location(
            db, loc_id, practice_id,
            name="New Name",
            city="New York",
            hacker_field="drop_table",
        )

        assert result["success"] is True
        assert "name" in result["updated"]
        assert "city" in result["updated"]
        assert "hacker_field" not in result["updated"]
        db.execute.assert_awaited()
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_location_none_values_filtered(self):
        """Fields set to None should be filtered out."""
        from app.enterprise.multi_location import LocationService

        db = _mock_db()
        result = await LocationService.update_location(
            db, str(uuid4()), uuid4(),
            name=None,
            city=None,
        )
        assert "error" in result
        assert "No valid fields" in result["error"]


class TestLocationServiceDeactivate:
    """Tests for LocationService.deactivate_location."""

    @pytest.mark.asyncio
    async def test_deactivate_primary_location_fails(self):
        """Primary locations (is_primary=TRUE) cannot be deactivated.

        The SQL WHERE clause includes ``is_primary = FALSE``, so if the
        location is primary the UPDATE matches 0 rows and rowcount == 0.
        """
        from app.enterprise.multi_location import LocationService

        db = _mock_db(rowcount=0)
        success = await LocationService.deactivate_location(
            db, str(uuid4()), uuid4()
        )
        assert success is False

    @pytest.mark.asyncio
    async def test_deactivate_non_primary_location_succeeds(self):
        """Non-primary locations can be deactivated."""
        from app.enterprise.multi_location import LocationService

        db = _mock_db(rowcount=1)
        success = await LocationService.deactivate_location(
            db, str(uuid4()), uuid4()
        )
        assert success is True
        db.commit.assert_awaited_once()


class TestLocationServiceCreateAndList:
    """Tests for create_location, list_locations, get_location."""

    @pytest.mark.asyncio
    async def test_create_location(self):
        from app.enterprise.multi_location import LocationService

        loc_id = uuid4()
        now = datetime.now(timezone.utc)

        row = _mock_row(id=loc_id, name="Main Office", is_primary=True, created_at=now)
        result_mock = MagicMock()
        result_mock.fetchone.return_value = row

        # Two execute calls: one to unset existing primary, one to INSERT
        unset_result = MagicMock()

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[unset_result, result_mock])
        db.commit = AsyncMock()

        result = await LocationService.create_location(
            db, uuid4(), "Main Office",
            address_line1="123 Main St",
            city="New York",
            state="NY",
            is_primary=True,
        )

        assert result["name"] == "Main Office"
        assert result["is_primary"] is True

    @pytest.mark.asyncio
    async def test_list_locations(self):
        from app.enterprise.multi_location import LocationService

        loc_id = uuid4()
        now = datetime.now(timezone.utc)
        rows = [
            _mock_row(
                id=loc_id,
                name="Downtown",
                address_line1="100 Broadway",
                address_line2="Suite 200",
                city="New York",
                state="NY",
                zip_code="10001",
                phone="+15551234567",
                fax="+15557654321",
                timezone="America/New_York",
                is_primary=True,
                is_active=True,
                created_at=now,
            )
        ]
        db = _mock_db(fetchall=rows)

        result = await LocationService.list_locations(db, uuid4())
        assert len(result) == 1
        assert result[0]["name"] == "Downtown"
        assert result[0]["city"] == "New York"
        assert result[0]["is_primary"] is True

    @pytest.mark.asyncio
    async def test_get_location_found(self):
        from app.enterprise.multi_location import LocationService

        loc_id = uuid4()
        now = datetime.now(timezone.utc)
        row = _mock_row(
            id=loc_id,
            name="Uptown",
            address_line1="500 5th Ave",
            address_line2="",
            city="New York",
            state="NY",
            zip_code="10036",
            phone="+15551112222",
            fax="",
            timezone="America/New_York",
            is_primary=False,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        db = _mock_db(fetchone=row)

        result = await LocationService.get_location(db, str(loc_id), uuid4())
        assert result is not None
        assert result["name"] == "Uptown"
        assert result["is_primary"] is False

    @pytest.mark.asyncio
    async def test_get_location_not_found(self):
        from app.enterprise.multi_location import LocationService

        db = _mock_db(fetchone=None)
        result = await LocationService.get_location(db, str(uuid4()), uuid4())
        assert result is None


class TestLocationServiceAssignProvider:
    """Tests for LocationService.assign_provider_to_location."""

    @pytest.mark.asyncio
    async def test_assign_provider_location_not_found(self):
        """When the location does not exist, assign should return False."""
        from app.enterprise.multi_location import LocationService

        # First execute: location lookup returns None
        loc_result = MagicMock()
        loc_result.fetchone.return_value = None

        db = AsyncMock()
        db.execute = AsyncMock(return_value=loc_result)
        db.commit = AsyncMock()

        success = await LocationService.assign_provider_to_location(
            db, str(uuid4()), str(uuid4()), uuid4(), is_primary=False
        )
        assert success is False

    @pytest.mark.asyncio
    async def test_assign_provider_success(self):
        """Valid location should result in successful assignment."""
        from app.enterprise.multi_location import LocationService

        loc_row = _mock_row(id=uuid4())
        loc_result = MagicMock()
        loc_result.fetchone.return_value = loc_row

        insert_result = MagicMock()

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[loc_result, insert_result])
        db.commit = AsyncMock()

        success = await LocationService.assign_provider_to_location(
            db, str(uuid4()), str(uuid4()), uuid4(), is_primary=True
        )
        assert success is True
        db.commit.assert_awaited_once()
