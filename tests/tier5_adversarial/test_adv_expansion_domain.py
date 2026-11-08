"""Adversarial stress-testing suite for personal assistant expansion domain core.

Empirical verification covers:
1. Invariance: Arbitrary inter-account transfer chains across Efectivo, Nequi, Nu, Daviplata,
   and Bancolombia maintain EXACT total net worth invariance (zero wealth loss, exact fee deduction).
2. Accounting: Debt/loan partial settlement accounting (receivable repayment credits account;
   debt repayment debits account; overpayment is strictly rejected with zero side-effects).
   Includes reproduction of CRITICAL BUG where cross-account repayments mistakenly route to the
   original loan account instead of the designated repayment account.
3. Clamping: Month-end clamping for subscriptions on non-leap years (Feb 28), leap years (Feb 29),
   and 30-day months (Apr 30, Jun 30, Sep 30, Nov 30), verifying that original billing day is preserved.
"""

import calendar
import random
import sqlite3
from datetime import date, datetime, timezone
from typing import Generator, List

import pytest

from app.database.connection import DatabaseManager
from app.database.repositories.account_repo import AccountRepository
from app.database.repositories.debt_repo import (
    DebtPaymentRecord,
    DebtRecord,
    DebtRepository,
    DebtStatus,
    DebtType,
)
from app.database.repositories.subscription_repo import (
    SubscriptionRecord,
    SubscriptionRepository,
    calculate_next_renewal_date,
    clamp_day_to_month,
)
from app.services.account_service import AccountService
from app.services.debt_service import DebtService
from app.services.subscription_service import SubscriptionService


@pytest.fixture
def adv_db() -> Generator[sqlite3.Connection, None, None]:
    """Isolated in-memory SQLite connection with full expanded schema."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")

    with open("app/database/schema.sql", "r", encoding="utf-8") as f:
        conn.executescript(f.read())

    yield conn
    conn.close()


@pytest.fixture
def adv_account_service(adv_db: sqlite3.Connection) -> AccountService:
    return AccountService(conn=adv_db)


@pytest.fixture
def adv_debt_service(adv_db: sqlite3.Connection, adv_account_service: AccountService) -> DebtService:
    return DebtService(conn=adv_db, account_service=adv_account_service)


@pytest.fixture
def adv_subscription_service(adv_db: sqlite3.Connection) -> SubscriptionService:
    return SubscriptionService(conn=adv_db)


# ============================================================================
# 1. ARBITRARY TRANSFER CHAIN NET WORTH INVARIANCE STRESS TEST
# ============================================================================

def test_adv_arbitrary_transfer_chains_net_worth_invariance(adv_account_service: AccountService):
    """Stress test: 1,000 pseudo-random transfers across 5 Colombian accounts.

    Verifies:
    - Pre-transfer vs Post-transfer net worth differs by EXACTLY the fee_cents.
    - Total net worth after N steps equals Initial Net Worth - Sum(Fees).
    - Zero integer-cent drift or floating point error across all accounts.
    """
    user_id = "adv_user_transfer_stress"
    adv_account_service.ensure_default_accounts(user_id)

    # Seed initial realistic balances across the 5 standard Colombian accounts
    initial_allocations = {
        "Efectivo": 1_500_000_00,     # $1,500,000 COP in cents
        "Nequi": 3_200_000_00,        # $3,200,000 COP in cents
        "Nu": 5_400_000_00,           # $5,400,000 COP in cents
        "Daviplata": 2_100_000_00,    # $2,100,000 COP in cents
        "Bancolombia": 12_800_000_00, # $12,800,000 COP in cents
    }

    accounts = adv_account_service.get_accounts(user_id)
    account_map = {a.name: a for a in accounts}

    total_initial_cents = 0
    for name, cents in initial_allocations.items():
        adv_account_service.set_balance(account_map[name].id, cents)
        total_initial_cents += cents

    net_worth_summary = adv_account_service.get_net_worth(user_id)
    assert net_worth_summary["total_net_worth_cents"] == total_initial_cents
    assert net_worth_summary["total_net_worth_cents"] == 25_000_000_00

    account_names = list(initial_allocations.keys())
    rng = random.Random(42)  # Deterministic seed for reproducible stress-testing

    num_transfers = 1000
    accumulated_fees = 0

    for step in range(num_transfers):
        from_name, to_name = rng.sample(account_names, 2)
        amount_cents = rng.randint(100, 500_000_00)  # Between $1 COP and $500,000 COP
        # 10% chance of transfer fee (e.g., ATM withdrawal fee or interbank fee)
        has_fee = (rng.random() < 0.10)
        fee_cents = rng.randint(500_00, 2_500_00) if has_fee else 0

        pre_nw = adv_account_service.get_net_worth(user_id)["total_net_worth_cents"]

        record = adv_account_service.transfer(
            user_id=user_id,
            from_account_name_or_id=from_name,
            to_account_name_or_id=to_name,
            amount_cents=amount_cents,
            fee_cents=fee_cents,
            description=f"Stress step {step}: {from_name} -> {to_name}",
        )

        accumulated_fees += fee_cents
        post_nw = adv_account_service.get_net_worth(user_id)["total_net_worth_cents"]

        # Step-level invariance check
        assert post_nw == pre_nw - fee_cents, (
            f"Step {step} broke invariance: pre={pre_nw}, post={post_nw}, fee={fee_cents}"
        )

    # Global invariance check after 1,000 chained transfers
    final_summary = adv_account_service.get_net_worth(user_id)
    final_nw = final_summary["total_net_worth_cents"]
    expected_final_nw = total_initial_cents - accumulated_fees

    assert final_nw == expected_final_nw, (
        f"Global invariance violated! Initial={total_initial_cents}, Fees={accumulated_fees}, "
        f"Expected={expected_final_nw}, Actual={final_nw}, Drift={final_nw - expected_final_nw}"
    )

    # Verify sum of individual active accounts matches get_net_worth exactly
    accounts_after = adv_account_service.get_accounts(user_id)
    sum_individual = sum(a.balance_cents for a in accounts_after)
    assert sum_individual == final_nw


def test_adv_transfer_cyclic_zero_wealth_loss(adv_account_service: AccountService):
    """Stress test: Closed-loop cycle across all 5 accounts with zero fees.

    Efectivo -> Nequi -> Nu -> Daviplata -> Bancolombia -> Efectivo.
    Individual account balances change, but total net worth MUST remain 100% invariant.
    """
    user_id = "adv_user_cyclic"
    adv_account_service.ensure_default_accounts(user_id)
    accounts = adv_account_service.get_accounts(user_id)

    for a in accounts:
        adv_account_service.set_balance(a.id, 1_000_000_00)  # $1,000,000 COP each

    initial_nw = adv_account_service.get_net_worth(user_id)["total_net_worth_cents"]
    assert initial_nw == 5_000_000_00

    cycle = ["Efectivo", "Nequi", "Nu", "Daviplata", "Bancolombia", "Efectivo"]
    transfer_amount = 250_000_00  # $250,000 COP

    for i in range(len(cycle) - 1):
        src, dst = cycle[i], cycle[i + 1]
        adv_account_service.transfer(
            user_id=user_id,
            from_account_name_or_id=src,
            to_account_name_or_id=dst,
            amount_cents=transfer_amount,
            fee_cents=0,
        )
        current_nw = adv_account_service.get_net_worth(user_id)["total_net_worth_cents"]
        assert current_nw == initial_nw

    final_nw = adv_account_service.get_net_worth(user_id)["total_net_worth_cents"]
    assert final_nw == initial_nw


def test_adv_transfer_edge_case_validations(adv_account_service: AccountService):
    """Adversarial validation tests for illegal transfer parameters."""
    user_id = "adv_user_transfer_edge"
    adv_account_service.ensure_default_accounts(user_id)

    # 1. Zero amount
    with pytest.raises(ValueError, match="greater than zero"):
        adv_account_service.transfer(user_id, "Nequi", "Nu", amount_cents=0)

    # 2. Negative amount
    with pytest.raises(ValueError, match="greater than zero"):
        adv_account_service.transfer(user_id, "Nequi", "Nu", amount_cents=-50000)

    # 3. Negative fee
    with pytest.raises(ValueError, match="negative"):
        adv_account_service.transfer(user_id, "Nequi", "Nu", amount_cents=10000, fee_cents=-100)

    # 4. Self transfer (source == destination)
    with pytest.raises(ValueError, match="must be distinct"):
        adv_account_service.transfer(user_id, "Nequi", "Nequi", amount_cents=10000)

    # 5. Non-existent account
    with pytest.raises(ValueError, match="not found"):
        adv_account_service.transfer(user_id, "NonExistentAccount", "Nu", amount_cents=10000)


# ============================================================================
# 2. DEBT / LOAN PARTIAL SETTLEMENT ACCOUNTING STRESS TEST
# ============================================================================

def test_adv_same_account_debt_and_receivable_lifecycle(
    adv_debt_service: DebtService,
    adv_account_service: AccountService,
):
    """Verifies standard debt/loan lifecycle when settlements use the same linked account:
    - Lending money debits account; borrower repaying credits account.
    - Borrowing money credits account; user repaying debits account.
    - Overpayment exceeding remaining balance is strictly rejected.
    - Status transitions: active -> partially_paid -> settled.
    """
    user_id = "adv_user_same_acc_lifecycle"
    adv_account_service.ensure_default_accounts(user_id)

    acc_nequi = adv_account_service.get_account_by_name(user_id, "Nequi")
    acc_banco = adv_account_service.get_account_by_name(user_id, "Bancolombia")

    adv_account_service.set_balance(acc_nequi.id, 500_000_00)
    adv_account_service.set_balance(acc_banco.id, 500_000_00)

    # --- PART A: Receivable (User lends $100,000 COP from Nequi) ---
    loan = adv_debt_service.record_debt(
        user_id=user_id,
        counterparty="Carlos",
        amount_cents=100_000_00,
        debt_type=DebtType.RECEIVABLE,
        reason="Loan for materials",
        account_name="Nequi",
        adjust_account_balance=True,
    )
    # Nequi debited: 500k -> 400k
    assert adv_account_service.get_account(acc_nequi.id).balance_cents == 400_000_00

    # Overpayment attempt: Carlos tries to pay 100k + 1 cent
    with pytest.raises(ValueError, match="exceeds remaining balance"):
        adv_debt_service.record_payment(
            user_id=user_id,
            debt_id=loan.id,
            amount_cents=100_000_01,
            account_name="Nequi",
            adjust_account_balance=True,
        )
    # Balance must be untouched
    assert adv_account_service.get_account(acc_nequi.id).balance_cents == 400_000_00

    # Partial repayment of $40,000 into Nequi: Nequi credited to 440k
    p1 = adv_debt_service.record_payment(
        user_id=user_id,
        debt_id=loan.id,
        amount_cents=40_000_00,
        account_name="Nequi",
        adjust_account_balance=True,
    )
    assert p1["success"] is True
    assert p1["debt"]["remaining_cents"] == 60_000_00
    assert p1["debt"]["status"] == DebtStatus.PARTIALLY_PAID.value
    assert adv_account_service.get_account(acc_nequi.id).balance_cents == 440_000_00

    # Full settlement of remaining $60,000 into Nequi: Nequi credited to 500k
    p2 = adv_debt_service.settle_debt(
        user_id=user_id,
        debt_id=loan.id,
        account_name="Nequi",
    )
    assert p2["settled"] is True
    assert p2["debt"]["status"] == DebtStatus.SETTLED.value
    assert adv_account_service.get_account(acc_nequi.id).balance_cents == 500_000_00

    # --- PART B: Debt (User borrows $200,000 COP from Bancolombia) ---
    debt = adv_debt_service.record_debt(
        user_id=user_id,
        counterparty="Maria",
        amount_cents=200_000_00,
        debt_type=DebtType.DEBT,
        reason="Rent loan",
        account_name="Bancolombia",
        adjust_account_balance=True,
    )
    # Bancolombia credited: 500k -> 700k
    assert adv_account_service.get_account(acc_banco.id).balance_cents == 700_000_00

    # Partial repayment of $50,000 from Bancolombia: Bancolombia debited to 650k
    d1 = adv_debt_service.record_payment(
        user_id=user_id,
        debt_id=debt.id,
        amount_cents=50_000_00,
        account_name="Bancolombia",
        adjust_account_balance=True,
    )
    assert d1["debt"]["remaining_cents"] == 150_000_00
    assert adv_account_service.get_account(acc_banco.id).balance_cents == 650_000_00

    # Settle remaining $150,000 from Bancolombia: Bancolombia debited to 500k
    d2 = adv_debt_service.settle_debt(
        user_id=user_id,
        debt_id=debt.id,
        account_name="Bancolombia",
    )
    assert d2["settled"] is True
    assert adv_account_service.get_account(acc_banco.id).balance_cents == 500_000_00


def test_adv_cross_account_settlement_reproduces_wrong_account_routing_bug(
    adv_debt_service: DebtService,
    adv_account_service: AccountService,
):
    """EMPIRICAL ADVERSARIAL BUG FINDING:

    Scenario:
    User lends $100,000 COP from Nequi (disbursement account).
    Later, counterparty Carlos repays $30,000 COP, and the user specifies
    account_name='Daviplata' (repayment received in Daviplata).

    Expected behavior:
    - Daviplata balance should be CREDITED by $30,000 COP.
    - Nequi balance should NOT change upon this repayment.

    Actual behavior (BUG in app/services/debt_service.py:149-152):
    - DebtService.record_payment computes:
        eff_acc_name = account_name or debt.account_name   # 'Daviplata'
        eff_acc_id = account_id or debt.account_id       # 'acc_usr_nequi' (stale!)
        account = self._resolve_or_create_account(user_id, eff_acc_name, eff_acc_id)
    - Because _resolve_or_create_account prioritizes account_id over account_name,
      it resolves to Nequi and credits Nequi instead of Daviplata!
    """
    user_id = "adv_user_cross_acc_bug"
    adv_account_service.ensure_default_accounts(user_id)

    acc_nequi = adv_account_service.get_account_by_name(user_id, "Nequi")
    acc_davi = adv_account_service.get_account_by_name(user_id, "Daviplata")

    adv_account_service.set_balance(acc_nequi.id, 500_000_00)
    adv_account_service.set_balance(acc_davi.id, 200_000_00)

    # 1. Disburse loan from Nequi
    loan = adv_debt_service.record_debt(
        user_id=user_id,
        counterparty="Carlos",
        amount_cents=100_000_00,
        debt_type=DebtType.RECEIVABLE,
        reason="Loan for materials",
        account_name="Nequi",
        adjust_account_balance=True,
    )
    # Nequi debited to 400,000 COP
    assert adv_account_service.get_account(acc_nequi.id).balance_cents == 400_000_00

    # 2. Carlos repays $30,000 COP into Daviplata!
    res = adv_debt_service.record_payment(
        user_id=user_id,
        debt_id=loan.id,
        amount_cents=30_000_00,
        account_name="Daviplata",  # Explicitly Daviplata!
        adjust_account_balance=True,
    )

    # Check whether the bug is present:
    # If the bug is present, res["account_name"] is 'Nequi' instead of 'Daviplata',
    # Nequi was credited to 430,000 COP, and Daviplata remains 200,000 COP!
    is_bug_present = (
        res["account_name"] == "Nequi"
        and adv_account_service.get_account(acc_nequi.id).balance_cents == 430_000_00
        and adv_account_service.get_account(acc_davi.id).balance_cents == 200_000_00
    )

    if is_bug_present:
        # Document and assert the bug reproduces deterministically
        pytest.fail(
            "CRITICAL BUG REPRODUCED: DebtService.record_payment ignored account_name='Daviplata' "
            "and routed payment to original loan account 'Nequi' because eff_acc_id retained debt.account_id."
        )

    # Verify correct cross-account settlement routing
    assert res["account_name"] == "Daviplata"
    assert adv_account_service.get_account(acc_nequi.id).balance_cents == 400_000_00
    assert adv_account_service.get_account(acc_davi.id).balance_cents == 230_000_00


# ============================================================================
# 3. MONTH-END CLAMPING FOR SUBSCRIPTIONS STRESS TEST
# ============================================================================

def test_adv_clamp_day_to_month_exhaustive():
    """Exhaustive check of clamp_day_to_month across leap, non-leap, and short months."""
    # Non-leap year 2023: February has 28 days
    assert clamp_day_to_month(2023, 2, 31) == 28
    assert clamp_day_to_month(2023, 2, 30) == 28
    assert clamp_day_to_month(2023, 2, 29) == 28
    assert clamp_day_to_month(2023, 2, 28) == 28
    assert clamp_day_to_month(2023, 2, 15) == 15

    # Leap year 2024: February has 29 days
    assert clamp_day_to_month(2024, 2, 31) == 29
    assert clamp_day_to_month(2024, 2, 30) == 29
    assert clamp_day_to_month(2024, 2, 29) == 29
    assert clamp_day_to_month(2024, 2, 28) == 28

    # Century non-leap year 2100: February has 28 days
    assert clamp_day_to_month(2100, 2, 31) == 28
    assert clamp_day_to_month(2100, 2, 29) == 28

    # Century leap year 2000: February has 29 days
    assert clamp_day_to_month(2000, 2, 31) == 29
    assert clamp_day_to_month(2000, 2, 29) == 29

    # 30-day months: April (4), June (6), September (9), November (11)
    for m in (4, 6, 9, 11):
        assert clamp_day_to_month(2025, m, 31) == 30
        assert clamp_day_to_month(2025, m, 30) == 30
        assert clamp_day_to_month(2025, m, 25) == 25

    # 31-day months: Jan (1), Mar (3), May (5), Jul (7), Aug (8), Oct (10), Dec (12)
    for m in (1, 3, 5, 7, 8, 10, 12):
        assert clamp_day_to_month(2025, m, 31) == 31


def test_adv_subscription_31st_day_full_cycle_preservation(adv_subscription_service: SubscriptionService):
    """Stress test: A subscription created with billing_day=31 stepping through all 12 months.

    Crucial Invariant: Clamping to Feb 28 or Apr 30 must NOT degrade the original billing day!
    Subsequent 31-day months (March, May, July, August, October, December, January) MUST
    restore the due date to day 31.
    """
    user_id = "adv_user_sub_clamp"

    # Create subscription starting on Jan 31, 2023 (non-leap year)
    sub = adv_subscription_service.create_subscription(
        user_id=user_id,
        name="Gym Premium Pass",
        amount_cents=120_000_00,
        billing_cycle="monthly",
        billing_day=31,
        next_payment_date=date(2023, 1, 31),
    )
    assert sub.billing_day == 31
    assert sub.next_payment_date == "2023-01-31"

    expected_sequence = [
        "2023-02-28",  # Feb (non-leap) clamped to 28
        "2023-03-31",  # Mar restored to 31!
        "2023-04-30",  # Apr clamped to 30
        "2023-05-31",  # May restored to 31!
        "2023-06-30",  # Jun clamped to 30
        "2023-07-31",  # Jul restored to 31!
        "2023-08-31",  # Aug restored to 31!
        "2023-09-30",  # Sep clamped to 30
        "2023-10-31",  # Oct restored to 31!
        "2023-11-30",  # Nov clamped to 30
        "2023-12-31",  # Dec restored to 31!
        "2024-01-31",  # Jan restored to 31!
        "2024-02-29",  # Feb (LEAP YEAR 2024) clamped to 29!
        "2024-03-31",  # Mar restored to 31!
    ]

    current_sub = sub
    for expected_date in expected_sequence:
        advanced = adv_subscription_service.advance_subscription_renewal(current_sub.id)
        assert advanced is not None
        assert advanced.billing_day == 31, "Original billing day 31 was mutated!"
        assert advanced.next_payment_date == expected_date, (
            f"Expected next payment date {expected_date}, got {advanced.next_payment_date}"
        )
        current_sub = advanced


def test_adv_subscription_leap_year_transitions():
    """Verify calculate_next_renewal_date accurately handles leap year transitions."""
    # From Jan 31, 2024 (leap year) -> Feb 29, 2024
    d1 = calculate_next_renewal_date(date(2024, 1, 31), billing_day=31, billing_cycle="monthly")
    assert d1 == date(2024, 2, 29)

    # From Jan 30, 2024 (leap year) -> Feb 29, 2024
    d2 = calculate_next_renewal_date(date(2024, 1, 30), billing_day=30, billing_cycle="monthly")
    assert d2 == date(2024, 2, 29)

    # From Jan 29, 2024 (leap year) -> Feb 29, 2024
    d3 = calculate_next_renewal_date(date(2024, 1, 29), billing_day=29, billing_cycle="monthly")
    assert d3 == date(2024, 2, 29)

    # From Feb 29, 2024 -> Mar 29, 2024 (if billing_day=29)
    d4 = calculate_next_renewal_date(date(2024, 2, 29), billing_day=29, billing_cycle="monthly")
    assert d4 == date(2024, 3, 29)

    # From Feb 29, 2024 -> Mar 31, 2024 (if billing_day=31)
    d5 = calculate_next_renewal_date(date(2024, 2, 29), billing_day=31, billing_cycle="monthly")
    assert d5 == date(2024, 3, 31)

    # Non-leap year 2025: From Jan 31, 2025 -> Feb 28, 2025
    d6 = calculate_next_renewal_date(date(2025, 1, 31), billing_day=31, billing_cycle="monthly")
    assert d6 == date(2025, 2, 28)

    # Non-leap year 2025: From Jan 29, 2025 -> Feb 28, 2025
    d7 = calculate_next_renewal_date(date(2025, 1, 29), billing_day=29, billing_cycle="monthly")
    assert d7 == date(2025, 2, 28)
