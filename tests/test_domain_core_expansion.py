"""Targeted unit test suite for Milestone M6: Debt & Multi-Account Banking Domain Core.

Verifies:
1. 5 default Colombian accounts exist (Efectivo, Nequi, Nu, Daviplata, Bancolombia) with dynamic custom account creation.
2. Account-linked transactions debit and credit balances with 100% backward compatibility.
3. Inter-account transfers debit source, credit destination, and preserve net wealth (Delta Net Worth = 0).
4. Debt and receivable tracking, disbursement accounting, partial and full settlements, and balance adjustments.
5. Recurring subscriptions with month-end date clamping (Feb 28/29, Apr 30, etc.) and advance renewals.
6. Unified chronological payment calendar merging subscriptions, debts, and receivables with overdue detection.
"""

import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Generator

import pytest

from app.database.connection import DatabaseManager, seed_default_accounts_for_user
from app.database.repositories.account_repo import AccountRecord, AccountRepository, TransferRecord
from app.database.repositories.debt_repo import (
    DebtPaymentRecord,
    DebtRecord,
    DebtRepository,
    DebtStatus,
    DebtType,
)
from app.database.repositories.finance_repo import FinanceRepository, TransactionType
from app.database.repositories.subscription_repo import (
    SubscriptionRecord,
    SubscriptionRepository,
    calculate_next_renewal_date,
    clamp_day_to_month,
)
from app.services.account_service import AccountService
from app.services.debt_service import DebtService
from app.services.finance_service import FinanceService
from app.services.subscription_service import SubscriptionService


@pytest.fixture
def isolated_db() -> Generator[sqlite3.Connection, None, None]:
    """In-memory SQLite connection with full expanded schema applied."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")

    schema_path = "app/database/schema.sql"
    with open(schema_path, "r", encoding="utf-8") as f:
        conn.executescript(f.read())

    yield conn
    conn.close()


@pytest.fixture
def db_manager(isolated_db: sqlite3.Connection) -> DatabaseManager:
    return DatabaseManager(conn=isolated_db)


@pytest.fixture
def account_service(isolated_db: sqlite3.Connection) -> AccountService:
    return AccountService(conn=isolated_db)


@pytest.fixture
def debt_service(isolated_db: sqlite3.Connection, account_service: AccountService) -> DebtService:
    return DebtService(conn=isolated_db, account_service=account_service)


@pytest.fixture
def subscription_service(isolated_db: sqlite3.Connection) -> SubscriptionService:
    return SubscriptionService(conn=isolated_db)


@pytest.fixture
def finance_service(isolated_db: sqlite3.Connection, account_service: AccountService) -> FinanceService:
    repo = FinanceRepository(db_manager=DatabaseManager(conn=isolated_db))
    return FinanceService(repository=repo, account_service=account_service)


# ============================================================================
# 1. Multi-Account Banking Core Tests
# ============================================================================

def test_default_accounts_seeding(account_service: AccountService):
    """Verify that the 5 standard Colombian accounts are created with zero balance."""
    user_id = "user_bank_001"
    accounts = account_service.ensure_default_accounts(user_id)

    names = {a.name for a in accounts}
    expected = {"Efectivo", "Nequi", "Nu", "Daviplata", "Bancolombia"}
    assert expected.issubset(names), f"Missing default accounts: {expected - names}"

    for a in accounts:
        assert a.balance_cents == 0
        assert a.currency == "COP"
        assert a.is_active is True

    # Idempotent call must not duplicate accounts
    re_seeded = account_service.ensure_default_accounts(user_id)
    assert len(re_seeded) == len(accounts)


def test_custom_account_creation_and_uniqueness(account_service: AccountService):
    """Verify dynamic custom account creation and case-insensitive uniqueness check."""
    user_id = "user_bank_002"
    acc = account_service.create_account(
        user_id=user_id,
        name="Lulo Bank",
        account_type="digital_wallet",
        initial_balance_cents=5000000,  # 50,000 COP
        currency="COP",
    )
    assert acc.name == "Lulo Bank"
    assert acc.balance_cents == 5000000
    assert acc.balance == 50000.0

    # Duplicate name (case-insensitive) must be rejected
    with pytest.raises(ValueError, match="already exists"):
        account_service.create_account(user_id=user_id, name="lulo bank")

    # Empty name must be rejected
    with pytest.raises(ValueError, match="cannot be empty"):
        account_service.create_account(user_id=user_id, name="   ")


def test_account_linked_transactions_credit_and_debit(
    finance_service: FinanceService,
    account_service: AccountService,
):
    """Verify transactions link to accounts, updating individual balances while maintaining backward compatibility."""
    user_id = "user_bank_003"
    account_service.ensure_default_accounts(user_id)

    # 1. Income transaction into Nequi: +$200,000 COP
    tx1 = finance_service.record_transaction(
        user_id=user_id,
        amount_cents=20000000,
        t_type="income",
        category="Income",
        description="Salary advance",
        account_name="Nequi",
    )
    assert tx1.account_name == "Nequi"
    nequi = account_service.get_account_by_name(user_id, "Nequi")
    assert nequi is not None
    assert nequi.balance_cents == 20000000
    assert nequi.balance == 200000.0

    # 2. Expense transaction from Nequi: -$45,000 COP
    tx2 = finance_service.record_transaction(
        user_id=user_id,
        amount_cents=4500000,
        t_type="expense",
        category="Groceries",
        description="Supermarket groceries",
        account_name="Nequi",
    )
    assert tx2.account_name == "Nequi"
    nequi_updated = account_service.get_account_by_name(user_id, "Nequi")
    assert nequi_updated is not None
    assert nequi_updated.balance_cents == 15500000  # 200,000 - 45,000 = 155,000 COP
    assert nequi_updated.balance == 155000.0

    # 3. Backward compatibility: record_transaction without account_name must succeed without modifying accounts
    tx_legacy = finance_service.record_transaction(
        user_id=user_id,
        amount_cents=1000000,
        t_type="expense",
        category="Transportation",
        description="Taxi ride",
    )
    assert tx_legacy.account_name is None
    # Nequi balance unchanged
    assert account_service.get_account_by_name(user_id, "Nequi").balance_cents == 15500000


def test_inter_account_transfers_and_net_worth_invariance(account_service: AccountService):
    """Verify transfers debit source, credit destination, and preserve net wealth (Delta Net Worth = 0)."""
    user_id = "user_bank_004"
    account_service.ensure_default_accounts(user_id)

    # Fund Bancolombia with $1,000,000 COP
    bancolombia = account_service.get_account_by_name(user_id, "Bancolombia")
    assert bancolombia is not None
    account_service.adjust_balance(bancolombia.id, 100000000)

    # Initial net worth check
    net_worth_initial = account_service.get_net_worth(user_id)
    assert net_worth_initial["total_net_worth_cents"] == 100000000
    assert net_worth_initial["total_net_worth"] == 1000000.0

    # Transfer $350,000 COP from Bancolombia to Nequi (zero fee)
    transfer = account_service.transfer(
        user_id=user_id,
        from_account_name_or_id="Bancolombia",
        to_account_name_or_id="Nequi",
        amount_cents=35000000,
        fee_cents=0,
        description="Pocket money transfer",
    )
    assert transfer.amount_cents == 35000000
    assert transfer.amount == 350000.0
    assert transfer.fee_cents == 0

    # Check updated balances
    banco_after = account_service.get_account_by_name(user_id, "Bancolombia")
    nequi_after = account_service.get_account_by_name(user_id, "Nequi")
    assert banco_after.balance_cents == 65000000  # 1,000,000 - 350,000 = 650,000
    assert nequi_after.balance_cents == 35000000   # 0 + 350,000 = 350,000

    # Net wealth invariance: Delta Net Worth = 0
    net_worth_final = account_service.get_net_worth(user_id)
    assert net_worth_final["total_net_worth_cents"] == net_worth_initial["total_net_worth_cents"]
    assert net_worth_final["total_net_worth"] == 1000000.0

    # Transfer with fee: $100,000 with $2,000 fee
    account_service.transfer(
        user_id=user_id,
        from_account_name_or_id="Nequi",
        to_account_name_or_id="Daviplata",
        amount_cents=10000000,
        fee_cents=200000,
        description="Transfer to friend via Daviplata",
    )
    net_worth_with_fee = account_service.get_net_worth(user_id)
    assert net_worth_with_fee["total_net_worth_cents"] == 100000000 - 200000

    # Transfer validation errors
    with pytest.raises(ValueError, match="must be distinct"):
        account_service.transfer(
            user_id=user_id,
            from_account_name_or_id="Nequi",
            to_account_name_or_id="Nequi",
            amount_cents=5000000,
        )

    with pytest.raises(ValueError, match="greater than zero"):
        account_service.transfer(
            user_id=user_id,
            from_account_name_or_id="Nequi",
            to_account_name_or_id="Efectivo",
            amount_cents=0,
        )

    with pytest.raises(ValueError, match="cannot be negative"):
        account_service.transfer(
            user_id=user_id,
            from_account_name_or_id="Nequi",
            to_account_name_or_id="Efectivo",
            amount_cents=500000,
            fee_cents=-100,
        )


# ============================================================================
# 2. Debt & Receivable Lifecycle Tests
# ============================================================================

def test_debt_and_receivable_creation_with_accounting_links(
    debt_service: DebtService,
    account_service: AccountService,
):
    """Verify that recording a receivable debits account, and recording a debt credits account."""
    user_id = "user_debt_001"
    account_service.ensure_default_accounts(user_id)

    # Fund Nequi with $150,000 COP
    nequi = account_service.get_account_by_name(user_id, "Nequi")
    account_service.adjust_balance(nequi.id, 15000000)

    # 1. Receivable (User lends $50,000 COP to Juan from Nequi)
    # Lending money is an outflow -> Nequi balance decreases by $50,000
    loan = debt_service.record_debt(
        user_id=user_id,
        counterparty="Juan",
        amount_cents=5000000,
        debt_type=DebtType.RECEIVABLE,
        reason="Lunch money loan",
        due_date="2026-11-20T18:00:00Z",
        account_name="Nequi",
    )
    assert loan.debt_type == DebtType.RECEIVABLE
    assert loan.amount_cents == 5000000
    assert loan.remaining_cents == 5000000
    assert loan.status == DebtStatus.ACTIVE
    assert loan.counterparty == "Juan"

    nequi_after_loan = account_service.get_account_by_name(user_id, "Nequi")
    assert nequi_after_loan.balance_cents == 10000000  # 150,000 - 50,000 = 100,000 COP

    # 2. Debt (User borrows $80,000 COP from Carlos into Daviplata)
    # Borrowing money is an inflow -> Daviplata balance increases by $80,000
    davi = account_service.get_account_by_name(user_id, "Daviplata")
    assert davi.balance_cents == 0

    borrow = debt_service.record_debt(
        user_id=user_id,
        counterparty="Carlos",
        amount_cents=8000000,
        debt_type=DebtType.DEBT,
        reason="Borrowed for concert ticket",
        due_date="2026-11-25T12:00:00Z",
        account_name="Daviplata",
    )
    assert borrow.debt_type == DebtType.DEBT
    assert borrow.amount_cents == 8000000
    assert borrow.remaining_cents == 8000000
    assert borrow.status == DebtStatus.ACTIVE

    davi_after_borrow = account_service.get_account_by_name(user_id, "Daviplata")
    assert davi_after_borrow.balance_cents == 8000000  # 0 + 80,000 = 80,000 COP

    # Summary check
    summary = debt_service.get_debt_summary(user_id)
    assert summary["total_receivable_cents"] == 5000000
    assert summary["total_debt_cents"] == 8000000
    assert summary["net_position_cents"] == -3000000  # Net debtor of 30,000 COP


def test_debt_settlements_partial_and_full(
    debt_service: DebtService,
    account_service: AccountService,
):
    """Verify partial settlement transitions to 'partially_paid' and full settlement to 'settled' with account updates."""
    user_id = "user_debt_002"
    account_service.ensure_default_accounts(user_id)

    # Fund Nequi with $100,000 COP and lend $60,000 to Andres
    nequi = account_service.get_account_by_name(user_id, "Nequi")
    account_service.adjust_balance(nequi.id, 10000000)

    loan = debt_service.record_debt(
        user_id=user_id,
        counterparty="Andres",
        amount_cents=6000000,
        debt_type=DebtType.RECEIVABLE,
        reason="Concert ticket",
        account_name="Nequi",
    )
    assert account_service.get_account_by_name(user_id, "Nequi").balance_cents == 4000000

    # 1. Partial Settlement: Andres pays back $25,000 COP
    # Repayment of a receivable is an inflow -> Nequi balance increases by $25,000
    res_partial = debt_service.record_payment(
        user_id=user_id,
        debt_id=loan.id,
        amount_cents=2500000,
        account_name="Nequi",
        notes="First installment",
    )
    assert res_partial["success"] is True
    assert res_partial["settled"] is False
    assert res_partial["debt"]["status"] == "partially_paid"
    assert res_partial["debt"]["remaining_cents"] == 3500000
    assert res_partial["debt"]["paid_amount_cents"] == 2500000

    nequi_partial = account_service.get_account_by_name(user_id, "Nequi")
    assert nequi_partial.balance_cents == 6500000  # 40,000 + 25,000 = 65,000 COP

    # 2. Overpayment rejection: trying to pay $40,000 when only $35,000 is remaining
    with pytest.raises(ValueError, match="exceeds remaining balance"):
        debt_service.record_payment(
            user_id=user_id,
            debt_id=loan.id,
            amount_cents=4000000,
            account_name="Nequi",
        )

    # 3. Full Settlement: Andres pays remaining $35,000 COP via settle_debt
    res_full = debt_service.settle_debt(
        user_id=user_id,
        debt_id=loan.id,
        account_name="Nequi",
        notes="Final payment",
    )
    assert res_full["success"] is True
    assert res_full["settled"] is True
    assert res_full["debt"]["status"] == "settled"
    assert res_full["debt"]["remaining_cents"] == 0
    assert res_full["debt"]["settled_at"] is not None

    nequi_full = account_service.get_account_by_name(user_id, "Nequi")
    assert nequi_full.balance_cents == 10000000  # Restored back to original 100,000 COP!

    # 4. Attempting to settle an already settled loan must raise ValueError
    with pytest.raises(ValueError, match="already settled"):
        debt_service.record_payment(
            user_id=user_id,
            debt_id=loan.id,
            amount_cents=100000,
        )


# ============================================================================
# 3. Recurring Subscriptions with Month-End Clamping Tests
# ============================================================================

def test_month_end_clamping_calculations():
    """Verify month-end clamping engine handles Feb 28/29, Apr 30, and year rollovers."""
    # Day clamping unit check
    assert clamp_day_to_month(2025, 2, 31) == 28  # Non-leap year
    assert clamp_day_to_month(2024, 2, 31) == 29  # Leap year
    assert clamp_day_to_month(2026, 4, 31) == 30  # April has 30 days
    assert clamp_day_to_month(2026, 1, 31) == 31  # January has 31 days

    # Next renewal from Jan 31 in non-leap year (2025) -> Feb 28
    d_jan31_2025 = date(2025, 1, 31)
    next_feb_2025 = calculate_next_renewal_date(d_jan31_2025, billing_day=31, billing_cycle="monthly")
    assert next_feb_2025 == date(2025, 2, 28)

    # Next renewal from Jan 31 in leap year (2024) -> Feb 29
    d_jan31_2024 = date(2024, 1, 31)
    next_feb_2024 = calculate_next_renewal_date(d_jan31_2024, billing_day=31, billing_cycle="monthly")
    assert next_feb_2024 == date(2024, 2, 29)

    # Next renewal from March 31 -> April 30
    d_mar31 = date(2026, 3, 31)
    next_apr = calculate_next_renewal_date(d_mar31, billing_day=31, billing_cycle="monthly")
    assert next_apr == date(2026, 4, 30)

    # December 31 -> January 31 (year rollover)
    d_dec31 = date(2025, 12, 31)
    next_jan = calculate_next_renewal_date(d_dec31, billing_day=31, billing_cycle="monthly")
    assert next_jan == date(2026, 1, 31)


def test_subscription_crud_and_renewal_advance(subscription_service: SubscriptionService):
    """Verify subscription CRUD and advance renewal with clamped dates."""
    user_id = "user_sub_001"

    # Create Netflix monthly subscription due on the 31st
    sub = subscription_service.create_subscription(
        user_id=user_id,
        name="Netflix",
        amount_cents=4500000,
        billing_cycle="monthly",
        billing_day=31,
        next_payment_date="2026-01-31",
        account_name="Nu",
        category="Entertainment",
    )
    assert sub.name == "Netflix"
    assert sub.amount_cents == 4500000
    assert sub.amount == 45000.0
    assert sub.billing_day == 31
    assert sub.next_payment_date == "2026-01-31"

    # Advance renewal: 2026-01-31 monthly on day 31 -> 2026-02-28 (2026 is non-leap year)
    advanced = subscription_service.advance_subscription_renewal(sub.id)
    assert advanced is not None
    assert advanced.next_payment_date == "2026-02-28"

    # Advance again: 2026-02-28 -> 2026-03-31
    advanced_mar = subscription_service.advance_subscription_renewal(sub.id)
    assert advanced_mar.next_payment_date == "2026-03-31"

    # List subscriptions
    subs = subscription_service.list_subscriptions(user_id)
    assert len(subs) == 1
    assert subs[0].name == "Netflix"


# ============================================================================
# 4. Unified Payment Calendar & Upcoming Reminders Tests
# ============================================================================

def test_unified_payment_calendar_aggregation_and_ordering(
    subscription_service: SubscriptionService,
    debt_service: DebtService,
):
    """Verify the payment calendar aggregates subscriptions, debts, and receivables sorted chronologically."""
    user_id = "user_cal_001"
    ref_date = date(2026, 11, 10)

    # 1. Create subscription due 2026-11-15
    subscription_service.create_subscription(
        user_id=user_id,
        name="Spotify",
        amount_cents=1800000,
        next_payment_date="2026-11-15",
        account_name="Nu",
    )

    # 2. Create debt (owed to Maria) due 2026-11-12
    debt_service.record_debt(
        user_id=user_id,
        counterparty="Maria",
        amount_cents=7000000,
        debt_type=DebtType.DEBT,
        reason="Laptop loan",
        due_date="2026-11-12T12:00:00Z",
    )

    # 3. Create receivable (owed by Carlos) due 2026-11-20
    debt_service.record_debt(
        user_id=user_id,
        counterparty="Carlos",
        amount_cents=3000000,
        debt_type=DebtType.RECEIVABLE,
        reason="Bicycle repair",
        due_date="2026-11-20T12:00:00Z",
    )

    # 4. Create an overdue debt from 2026-11-05
    debt_service.record_debt(
        user_id=user_id,
        counterparty="Pedro",
        amount_cents=2000000,
        debt_type=DebtType.DEBT,
        reason="Dinner",
        due_date="2026-11-05T12:00:00Z",
    )

    # Query 30 days ahead from ref_date (2026-11-10)
    calendar_events = subscription_service.get_upcoming_payments(
        user_id=user_id,
        days_ahead=30,
        reference_date=ref_date,
    )

    # 4 items expected
    assert len(calendar_events) == 4

    # Verify chronological ordering
    dates = [e["due_date"] for e in calendar_events]
    assert dates == sorted(dates), f"Calendar items not sorted: {dates}"

    # Item 1: Overdue debt from 2026-11-05
    assert calendar_events[0]["title"] == "Pedro"
    assert calendar_events[0]["item_type"] == "debt"
    assert calendar_events[0]["is_overdue"] is True
    assert calendar_events[0]["urgency"] == "overdue"
    assert calendar_events[0]["direction"] == "outflow"

    # Item 2: Maria debt on 2026-11-12
    assert calendar_events[1]["title"] == "Maria"
    assert calendar_events[1]["item_type"] == "debt"
    assert calendar_events[1]["days_remaining"] == 2
    assert calendar_events[1]["urgency"] == "soon"
    assert calendar_events[1]["direction"] == "outflow"

    # Item 3: Spotify subscription on 2026-11-15
    assert calendar_events[2]["title"] == "Spotify"
    assert calendar_events[2]["item_type"] == "subscription"
    assert calendar_events[2]["direction"] == "outflow"

    # Item 4: Carlos receivable on 2026-11-20
    assert calendar_events[3]["title"] == "Carlos"
    assert calendar_events[3]["item_type"] == "receivable"
    assert calendar_events[3]["direction"] == "inflow"


def test_subscription_renewal_reminders(subscription_service: SubscriptionService):
    """Verify reminders trigger for subscriptions due within the alert horizon."""
    user_id = "user_remind_001"
    ref_date = date(2026, 11, 10)

    # Due in 2 days (within 3-day horizon)
    subscription_service.create_subscription(
        user_id=user_id,
        name="Gym Membership",
        amount_cents=12000000,
        next_payment_date="2026-11-12",
        reminder_days_before=3,
        account_name="Bancolombia",
    )

    # Due in 15 days (outside horizon)
    subscription_service.create_subscription(
        user_id=user_id,
        name="Amazon Prime",
        amount_cents=2500000,
        next_payment_date="2026-11-25",
        reminder_days_before=3,
        account_name="Nu",
    )

    reminders = subscription_service.get_subscription_reminders(
        user_id=user_id,
        alert_horizon_days=3,
        reference_date=ref_date,
    )
    assert len(reminders) == 1
    assert reminders[0]["name"] == "Gym Membership"
    assert reminders[0]["days_remaining"] == 2
    assert "Gym Membership" in reminders[0]["message"]


# ============================================================================
# 5. Additional Boundary & Edge Case Tests
# ============================================================================

def test_multiple_partial_payments_accumulate_to_settled(
    debt_service: DebtService,
    account_service: AccountService,
):
    """Verify that multiple successive payments accurately track remaining amounts until fully settled."""
    user_id = "user_debt_multi"
    account_service.ensure_default_accounts(user_id)

    debt = debt_service.record_debt(
        user_id=user_id,
        counterparty="Supermarket Credit",
        amount_cents=10000000,  # 100,000 COP
        debt_type=DebtType.DEBT,
        reason="Weekly groceries credit",
        account_name="Efectivo",
        adjust_account_balance=False,
    )
    assert debt.status == DebtStatus.ACTIVE
    assert debt.remaining_cents == 10000000

    # Payment 1: 30,000 COP
    p1 = debt_service.record_payment(user_id, debt.id, 3000000, adjust_account_balance=False)
    assert p1["debt"]["status"] == "partially_paid"
    assert p1["debt"]["remaining_cents"] == 7000000
    assert p1["debt"]["paid_amount_cents"] == 3000000

    # Payment 2: 40,000 COP
    p2 = debt_service.record_payment(user_id, debt.id, 4000000, adjust_account_balance=False)
    assert p2["debt"]["status"] == "partially_paid"
    assert p2["debt"]["remaining_cents"] == 3000000
    assert p2["debt"]["paid_amount_cents"] == 7000000

    # Payment 3: 30,000 COP (Exact remaining)
    p3 = debt_service.record_payment(user_id, debt.id, 3000000, adjust_account_balance=False)
    assert p3["debt"]["status"] == "settled"
    assert p3["debt"]["remaining_cents"] == 0
    assert p3["debt"]["paid_amount_cents"] == 10000000
    assert p3["settled"] is True


def test_debt_filtering_by_status_and_type(debt_service: DebtService):
    """Verify list_debts filters by debt_type, status, and counterparty."""
    user_id = "user_filter_001"

    d1 = debt_service.record_debt(user_id, "Juan Perez", 5000000, "debt", "Dinner", adjust_account_balance=False)
    d2 = debt_service.record_debt(user_id, "Maria Gomez", 8000000, "receivable", "Project", adjust_account_balance=False)
    d3 = debt_service.record_debt(user_id, "Juan Rodriguez", 2000000, "receivable", "Coffee", adjust_account_balance=False)

    # Filter by debt_type = 'receivable'
    receivables = debt_service.list_debts(user_id, debt_type=DebtType.RECEIVABLE)
    assert len(receivables) == 2
    assert {r.id for r in receivables} == {d2.id, d3.id}

    # Filter by counterparty matching 'Juan'
    juans = debt_service.list_debts(user_id, counterparty="Juan")
    assert len(juans) == 2
    assert {r.id for r in juans} == {d1.id, d3.id}

    # Settle d1 and filter by status = 'active'
    debt_service.settle_debt(user_id, d1.id)
    actives = debt_service.list_debts(user_id, status=DebtStatus.ACTIVE)
    assert len(actives) == 2
    assert d1.id not in {r.id for r in actives}

    settled = debt_service.list_debts(user_id, status=DebtStatus.SETTLED)
    assert len(settled) == 1
    assert settled[0].id == d1.id


def test_subscription_non_monthly_cycles():
    """Verify weekly, quarterly, semiannual, and annual cycle renewal calculations."""
    start_dt = date(2026, 1, 15)

    # Weekly: +7 days
    weekly = calculate_next_renewal_date(start_dt, billing_day=15, billing_cycle="weekly")
    assert weekly == date(2026, 1, 22)

    # Quarterly: +3 months
    quarterly = calculate_next_renewal_date(start_dt, billing_day=15, billing_cycle="quarterly")
    assert quarterly == date(2026, 4, 15)

    # Semiannual: +6 months
    semi = calculate_next_renewal_date(start_dt, billing_day=15, billing_cycle="semiannual")
    assert semi == date(2026, 7, 15)

    # Annual: +1 year
    annual = calculate_next_renewal_date(start_dt, billing_day=15, billing_cycle="annual")
    assert annual == date(2027, 1, 15)


def test_subscription_deletion(subscription_service: SubscriptionService):
    """Verify deleting a subscription removes it from queries."""
    user_id = "user_sub_del"
    sub = subscription_service.create_subscription(
        user_id=user_id,
        name="Temporary Service",
        amount_cents=1000000,
        billing_day=10,
    )
    assert subscription_service.get_subscription(sub.id) is not None
    deleted = subscription_service.delete_subscription(sub.id)
    assert deleted is True
    assert subscription_service.get_subscription(sub.id) is None


def test_net_worth_with_overdraft(account_service: AccountService):
    """Verify net worth computation handles negative/overdraft balances gracefully."""
    user_id = "user_overdraft"
    account_service.ensure_default_accounts(user_id)

    nequi = account_service.get_account_by_name(user_id, "Nequi")
    banco = account_service.get_account_by_name(user_id, "Bancolombia")

    # Bancolombia: +100,000 COP, Nequi: -30,000 COP
    account_service.adjust_balance(banco.id, 10000000)
    account_service.adjust_balance(nequi.id, -3000000)

    summary = account_service.get_net_worth(user_id)
    assert summary["total_net_worth_cents"] == 7000000  # 100,000 - 30,000 = 70,000 COP
    assert summary["total_net_worth"] == 70000.0
