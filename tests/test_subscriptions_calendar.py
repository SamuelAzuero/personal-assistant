"""Unit and Integration Test Suite for Subscriptions & Unified Payment Calendar (R3).

Verifies Features F68–F70:
1. F68_SUBSCRIPTION_CRUD: Subscription lifecycle (creation, status update, advance renewal, deletion)
   with COP amounts, billing cycles, default accounts, and categories.
2. F68 (Clamping): Month-end clamping logic ensuring renewal days like 31 clamp safely to 28/29 in February
   and 30 in April/June/September/November across leap and non-leap years without ValueError.
3. F69_PAYMENT_CALENDAR: Unified chronological calendar aggregating upcoming subscriptions, debts owed,
   and loan collections sorted by due date, with direction (inflow vs outflow) and account tags.
4. F70_SUBSCRIPTION_REMINDERS: Upcoming renewal reminder detection within configurable alert horizons.
"""

from datetime import date
import pytest

from app.database.connection import DatabaseManager
from app.database.repositories.debt_repo import DebtType
from app.database.repositories.subscription_repo import (
    calculate_next_renewal_date,
    clamp_day_to_month,
)
from app.services.account_service import AccountService
from app.services.debt_service import DebtService
from app.services.subscription_service import SubscriptionService


@pytest.fixture
def memory_db():
    """Isolated in-memory SQLite database initialized with full schema."""
    db = DatabaseManager(":memory:")
    db.init_db()
    yield db
    db.close()


@pytest.fixture
def account_service(memory_db):
    """AccountService instance wired to isolated in-memory DB."""
    return AccountService(db_manager=memory_db)


@pytest.fixture
def debt_service(memory_db, account_service):
    """DebtService instance wired to isolated in-memory DB."""
    return DebtService(db_manager=memory_db, account_service=account_service)


@pytest.fixture
def subscription_service(memory_db, account_service, debt_service):
    """SubscriptionService instance wired to isolated in-memory DB."""
    return SubscriptionService(
        db_manager=memory_db,
        debt_repository=debt_service.repo,
        account_repository=account_service.repo,
    )


# ==============================================================================
# 1. Subscription Creation & Parameter Validation (F68)
# ==============================================================================


class TestSubscriptionCreationAndValidation:
    """Tests subscription creation, parameter validation, and lifecycle transitions."""

    def test_create_monthly_subscription_success(self, subscription_service, account_service):
        user_id = "usr_sub_01"
        account_service.ensure_default_accounts(user_id)

        sub = subscription_service.create_subscription(
            user_id=user_id,
            name="Netflix Premium",
            amount_cents=4490000,  # 44,900 COP
            billing_cycle="monthly",
            billing_day=15,
            account_name="Nu",
            category="Entertainment",
            reminder_days_before=3,
            notes="Plan 4 pantallas familiar",
        )

        assert sub.id.startswith("sub_")
        assert sub.user_id == user_id
        assert sub.name == "Netflix Premium"
        assert sub.amount_cents == 4490000
        assert sub.amount == 44900.0
        assert sub.billing_cycle == "monthly"
        assert sub.billing_day == 15
        assert sub.account_name == "Nu"
        assert sub.category == "Entertainment"
        assert sub.status == "active"
        assert sub.reminder_days_before == 3
        assert sub.notes == "Plan 4 pantallas familiar"
        assert sub.next_payment_date != ""

    @pytest.mark.parametrize("cycle", ["weekly", "monthly", "quarterly", "semiannual", "annual"])
    def test_create_subscription_supported_billing_cycles(self, subscription_service, cycle):
        user_id = "usr_cycles"
        sub = subscription_service.create_subscription(
            user_id=user_id,
            name=f"Service {cycle}",
            amount_cents=2000000,
            billing_cycle=cycle,
            billing_day=10,
        )
        assert sub.billing_cycle == cycle
        assert sub.status == "active"

    @pytest.mark.parametrize("invalid_amount", [0, -1, -4490000])
    def test_create_subscription_rejects_non_positive_amount(self, subscription_service, invalid_amount):
        user_id = "usr_sub_bad"
        with pytest.raises(ValueError, match="amount must be greater than zero"):
            subscription_service.create_subscription(
                user_id=user_id,
                name="Spotify",
                amount_cents=invalid_amount,
                billing_day=10,
            )

    @pytest.mark.parametrize("invalid_day", [0, 32, -5, 100])
    def test_create_subscription_rejects_invalid_billing_day(self, subscription_service, invalid_day):
        user_id = "usr_sub_bad"
        with pytest.raises(ValueError, match="between 1 and 31"):
            subscription_service.create_subscription(
                user_id=user_id,
                name="Gimnasio",
                amount_cents=9000000,
                billing_day=invalid_day,
            )

    @pytest.mark.parametrize("invalid_name", ["", "   "])
    def test_create_subscription_rejects_empty_name(self, subscription_service, invalid_name):
        user_id = "usr_sub_bad"
        with pytest.raises(ValueError, match=r"(?i)(service|subscription) name cannot be empty"):
            subscription_service.create_subscription(
                user_id=user_id,
                name=invalid_name,
                amount_cents=1000000,
                billing_day=5,
            )

    def test_subscription_lifecycle_status_transitions(self, subscription_service):
        user_id = "usr_sub_life"
        sub = subscription_service.create_subscription(
            user_id=user_id,
            name="Gym Pass",
            amount_cents=12000000,
            billing_day=1,
        )
        assert sub.status == "active"

        # Pause subscription
        paused = subscription_service.update_subscription(sub.id, status="paused")
        assert paused.status == "paused"

        # Active filter excludes paused
        active_subs = subscription_service.list_subscriptions(user_id, status="active")
        assert len(active_subs) == 0

        # Cancel subscription
        cancelled = subscription_service.update_subscription(sub.id, status="cancelled")
        assert cancelled.status == "cancelled"

        # Delete subscription
        deleted = subscription_service.delete_subscription(sub.id)
        assert deleted is True
        assert subscription_service.get_subscription(sub.id) is None


# ==============================================================================
# 2. Month-End Clamping Engine (Feb 28/29, Apr 30, Day 31) (F68)
# ==============================================================================


class TestMonthEndClamping:
    """Tests that subscription billing days like 31 clamp to valid month-ends without raising ValueError."""

    def test_clamp_day_to_month_short_months(self):
        """April, June, September, November have 30 days; 31 clamps to 30."""
        assert clamp_day_to_month(2026, 4, 31) == 30   # April
        assert clamp_day_to_month(2026, 6, 31) == 30   # June
        assert clamp_day_to_month(2026, 9, 31) == 30   # September
        assert clamp_day_to_month(2026, 11, 31) == 30  # November

    def test_clamp_day_to_month_february_non_leap_year(self):
        """February in non-leap years (2023, 2025, 2026) has 28 days."""
        for yr in (2023, 2025, 2026, 2027):
            assert clamp_day_to_month(yr, 2, 31) == 28
            assert clamp_day_to_month(yr, 2, 30) == 28
            assert clamp_day_to_month(yr, 2, 29) == 28
            assert clamp_day_to_month(yr, 2, 28) == 28
            assert clamp_day_to_month(yr, 2, 15) == 15

    def test_clamp_day_to_month_february_leap_year(self):
        """February in leap years (2024, 2028, 2032) has 29 days."""
        for yr in (2024, 2028, 2032):
            assert clamp_day_to_month(yr, 2, 31) == 29
            assert clamp_day_to_month(yr, 2, 30) == 29
            assert clamp_day_to_month(yr, 2, 29) == 29
            assert clamp_day_to_month(yr, 2, 28) == 28

    def test_calculate_next_renewal_date_monthly_leap_year_rollover(self):
        """From Jan 31 in leap year 2024, billing_day 31 rolls over to Feb 29 (NOT Feb 28 or March 3)."""
        ref_date = date(2024, 1, 31)
        next_date = calculate_next_renewal_date(ref_date, billing_day=31, billing_cycle="monthly")
        assert next_date == date(2024, 2, 29)

    def test_calculate_next_renewal_date_monthly_non_leap_year_rollover(self):
        """From Jan 31 in non-leap year 2025, billing_day 31 rolls over to Feb 28."""
        ref_date = date(2025, 1, 31)
        next_date = calculate_next_renewal_date(ref_date, billing_day=31, billing_cycle="monthly")
        assert next_date == date(2025, 2, 28)

    def test_calculate_next_renewal_date_from_feb_to_march(self):
        """From Feb 28 with billing_day 31, rolls over to March 31."""
        ref_date = date(2025, 2, 28)
        next_date = calculate_next_renewal_date(ref_date, billing_day=31, billing_cycle="monthly")
        assert next_date == date(2025, 3, 31)

    def test_calculate_next_renewal_date_from_march_to_april(self):
        """From March 31 with billing_day 31, rolls over to April 30."""
        ref_date = date(2026, 3, 31)
        next_date = calculate_next_renewal_date(ref_date, billing_day=31, billing_cycle="monthly")
        assert next_date == date(2026, 4, 30)

    def test_advance_subscription_renewal_service_integration(self, subscription_service):
        """Advancing renewal updates the persisted next_payment_date with clamping applied."""
        user_id = "usr_clamp_svc"
        # Seed subscription starting on Jan 31 in 2026 (non-leap)
        sub = subscription_service.create_subscription(
            user_id=user_id,
            name="End of Month Service",
            amount_cents=1000000,
            billing_cycle="monthly",
            billing_day=31,
            next_payment_date="2026-01-31",
        )
        assert sub.next_payment_date == "2026-01-31"

        # Advance renewal: Jan 31 -> Feb 28
        advanced = subscription_service.advance_subscription_renewal(sub.id)
        assert advanced is not None
        assert advanced.next_payment_date == "2026-02-28"

        # Advance again: Feb 28 -> March 31
        advanced2 = subscription_service.advance_subscription_renewal(sub.id)
        assert advanced2 is not None
        assert advanced2.next_payment_date == "2026-03-31"

        # Advance again: March 31 -> April 30
        advanced3 = subscription_service.advance_subscription_renewal(sub.id)
        assert advanced3 is not None
        assert advanced3.next_payment_date == "2026-04-30"


# ==============================================================================
# 3. Unified Payment Calendar (F69)
# ==============================================================================


class TestUnifiedPaymentCalendar:
    """Tests chronological aggregation of subscriptions, debts due, and loan receivables."""

    def test_unified_calendar_aggregates_and_sorts_all_financial_commitments(
        self, subscription_service, debt_service
    ):
        user_id = "usr_calendar_full"
        ref_date = "2026-11-04"

        # 1. Subscription renewing on 2026-11-10
        subscription_service.create_subscription(
            user_id=user_id,
            name="Spotify Premium",
            amount_cents=1990000,  # 19,900 COP
            billing_cycle="monthly",
            billing_day=10,
            next_payment_date="2026-11-10",
            account_name="Nu",
        )

        # 2. Subscription renewing on 2026-11-20
        subscription_service.create_subscription(
            user_id=user_id,
            name="Universidad Matrícula",
            amount_cents=150000000,  # 1,500,000 COP
            billing_cycle="monthly",
            billing_day=20,
            next_payment_date="2026-11-20",
            account_name="Bancolombia",
        )

        # 3. Debt user owes to Carlos due on 2026-11-06 (outflow)
        debt_service.record_debt(
            user_id=user_id,
            counterparty="Carlos",
            amount_cents=8000000,  # 80,000 COP
            debt_type=DebtType.DEBT,
            reason="Cena compartida",
            due_date="2026-11-06",
            account_name="Daviplata",
            adjust_account_balance=False,
        )

        # 4. Receivable owed to user by Juan due on 2026-11-15 (inflow)
        debt_service.record_debt(
            user_id=user_id,
            counterparty="Juan",
            amount_cents=5000000,  # 50,000 COP
            debt_type=DebtType.RECEIVABLE,
            reason="Préstamo almuerzo",
            due_date="2026-11-15",
            account_name="Nequi",
            adjust_account_balance=False,
        )

        # 5. Settled debt (should be omitted from upcoming active schedule)
        settled_debt = debt_service.record_debt(
            user_id=user_id,
            counterparty="Andres",
            amount_cents=3000000,
            debt_type=DebtType.DEBT,
            reason="Taxi",
            due_date="2026-11-05",
            adjust_account_balance=False,
        )
        debt_service.settle_debt(user_id=user_id, debt_id=settled_debt.id)

        # Query 30-day upcoming calendar
        calendar = subscription_service.get_upcoming_payments(
            user_id=user_id,
            days_ahead=30,
            reference_date=ref_date,
        )

        # Expected items in strict chronological order:
        # 1. 2026-11-06: Carlos (debt, outflow, 80k)
        # 2. 2026-11-10: Spotify (subscription, outflow, 19.9k)
        # 3. 2026-11-15: Juan (receivable, inflow, 50k)
        # 4. 2026-11-20: Universidad (subscription, outflow, 1.5M)
        assert len(calendar) == 4, f"Expected 4 active upcoming items, got {len(calendar)}"

        dates = [item["due_date"] for item in calendar]
        assert dates == ["2026-11-06", "2026-11-10", "2026-11-15", "2026-11-20"], "Schedule must be sorted ASC"

        # Check item 1: Debt to Carlos
        item1 = calendar[0]
        assert item1["item_type"] == "debt"
        assert item1["title"] == "Carlos"
        assert item1["amount_cents"] == 8000000
        assert item1["direction"] == "outflow"
        assert item1["account_name"] == "Daviplata"
        assert item1["days_remaining"] == 2

        # Check item 2: Spotify Subscription
        item2 = calendar[1]
        assert item2["item_type"] == "subscription"
        assert item2["title"] == "Spotify Premium"
        assert item2["amount_cents"] == 1990000
        assert item2["direction"] == "outflow"
        assert item2["account_name"] == "Nu"
        assert item2["days_remaining"] == 6

        # Check item 3: Loan to Juan (Inflow)
        item3 = calendar[2]
        assert item3["item_type"] == "receivable"
        assert item3["title"] == "Juan"
        assert item3["amount_cents"] == 5000000
        assert item3["direction"] == "inflow"
        assert item3["account_name"] == "Nequi"
        assert item3["days_remaining"] == 11

    def test_unified_calendar_window_filtering(self, subscription_service):
        user_id = "usr_window_test"
        ref_date = "2026-11-04"

        # Due in 5 days (2026-11-09)
        subscription_service.create_subscription(
            user_id=user_id,
            name="Near Sub",
            amount_cents=1000000,
            next_payment_date="2026-11-09",
        )

        # Due in 20 days (2026-11-24)
        subscription_service.create_subscription(
            user_id=user_id,
            name="Far Sub",
            amount_cents=1000000,
            next_payment_date="2026-11-24",
        )

        # 7-day window should only include Near Sub
        window_7 = subscription_service.get_upcoming_payments(user_id, days_ahead=7, reference_date=ref_date)
        assert len(window_7) == 1
        assert window_7[0]["title"] == "Near Sub"

        # 30-day window should include both
        window_30 = subscription_service.get_upcoming_payments(user_id, days_ahead=30, reference_date=ref_date)
        assert len(window_30) == 2


# ==============================================================================
# 4. Subscription Renewal Reminder Detection (F70)
# ==============================================================================


class TestSubscriptionRenewalReminders:
    """Tests identification of subscriptions nearing renewal within alert horizons."""

    def test_subscription_reminder_horizon_detection(self, subscription_service):
        user_id = "usr_reminders"
        ref_date = "2026-11-04"

        # Due in 2 days (2026-11-06) - Should alert
        subscription_service.create_subscription(
            user_id=user_id,
            name="Disney+",
            amount_cents=3500000,
            next_payment_date="2026-11-06",
            reminder_days_before=3,
            account_name="Nu",
        )

        # Due today (2026-11-04) - Should alert
        subscription_service.create_subscription(
            user_id=user_id,
            name="iCloud Storage",
            amount_cents=490000,
            next_payment_date="2026-11-04",
            reminder_days_before=1,
            account_name="Nu",
        )

        # Due in 15 days (2026-11-19) - Should NOT alert
        subscription_service.create_subscription(
            user_id=user_id,
            name="Gym Pass",
            amount_cents=10000000,
            next_payment_date="2026-11-19",
            reminder_days_before=3,
            account_name="Bancolombia",
        )

        reminders = subscription_service.get_subscription_reminders(
            user_id=user_id,
            alert_horizon_days=3,
            reference_date=ref_date,
        )

        assert len(reminders) == 2, f"Expected 2 reminders within 3-day horizon, got {len(reminders)}"
        names = [r["name"] for r in reminders]
        assert "iCloud Storage" in names
        assert "Disney+" in names
        assert "Gym Pass" not in names

        # Verify reminder payload structure
        icloud = next(r for r in reminders if r["name"] == "iCloud Storage")
        assert icloud["days_remaining"] == 0
        assert "Reminder: iCloud Storage renewal" in icloud["message"]

        disney = next(r for r in reminders if r["name"] == "Disney+")
        assert disney["days_remaining"] == 2
        assert "Reminder: Disney+ renewal" in disney["message"]

    def test_subscription_reminders_empty_when_no_commitments_due(self, subscription_service):
        user_id = "usr_no_reminders"
        subscription_service.create_subscription(
            user_id=user_id,
            name="AWS Cloud",
            amount_cents=50000000,
            next_payment_date="2026-12-25",
        )

        reminders = subscription_service.get_subscription_reminders(
            user_id=user_id,
            alert_horizon_days=3,
            reference_date="2026-11-04",
        )
        assert len(reminders) == 0
