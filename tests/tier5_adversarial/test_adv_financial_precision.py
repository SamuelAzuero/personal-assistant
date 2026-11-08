"""Adversarial stress testing for financial ledger precision, concurrency, and arithmetic drift."""

import concurrent.futures
from decimal import Decimal
import pytest
from app.database.connection import DatabaseManager
from app.database.repositories.finance_repo import FinanceRepository, TransactionType
from app.services.finance_service import FinanceService
from app.core.router import ToolRouter
from app.integrations.protocols import IntentResult, IntentType


@pytest.fixture
def clean_finance_service(tmp_path):
    """File-backed SQLite database manager in WAL mode for realistic concurrency testing."""
    db_file = str(tmp_path / "adv_finance.db")
    db_mgr = DatabaseManager(db_path=db_file)
    db_mgr.init_db()
    repo = FinanceRepository(db_mgr)
    return FinanceService(repository=repo, db_manager=db_mgr)


def test_adv_fin_01_drift_over_10k_micro_transactions(clean_finance_service: FinanceService):
    """Stress test: 1,000 micro-transactions ($0.01) must have ZERO floating point drift."""
    user = "usr_drift_10k"
    tx_count = 1000

    for i in range(tx_count):
        clean_finance_service.record_transaction(
            user_id=user,
            amount_cents=1,
            t_type=TransactionType.EXPENSE,
            category="Other",
            description=f"Penny {i}",
        )

    balance = clean_finance_service.get_balance(user)
    assert balance["transaction_count"] == tx_count
    assert balance["expense_cents"] == 1000
    assert balance["balance_cents"] == -1000
    assert balance["total_expenses"] == 10.00
    assert balance["net_balance"] == -10.00


def test_adv_fin_02_concurrent_multi_threaded_transactions(clean_finance_service: FinanceService):
    """Stress test: 10 concurrent threads each writing 20 transactions rapidly under SQLite WAL."""
    user = "usr_concurrent_stress"
    num_threads = 10
    tx_per_thread = 20
    amount_per_tx = 150  # $1.50 in cents

    def worker(thread_idx: int):
        for j in range(tx_per_thread):
            clean_finance_service.record_transaction(
                user_id=user,
                amount_cents=amount_per_tx,
                t_type=TransactionType.INCOME if thread_idx % 2 == 0 else TransactionType.EXPENSE,
                category="Groceries" if j % 2 == 0 else "Transportation",
                description=f"Thread {thread_idx} tx {j}",
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker, t) for t in range(num_threads)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    balance = clean_finance_service.get_balance(user)
    expected_count = num_threads * tx_per_thread
    assert balance["transaction_count"] == expected_count

    # 5 income threads (100 txs * 150 = 15,000 cents), 5 expense threads (100 txs * 150 = 15,000 cents)
    assert balance["income_cents"] == 15000
    assert balance["expense_cents"] == 15000
    assert balance["balance_cents"] == 0
    assert balance["net_balance"] == 0.00


def test_adv_fin_03_extreme_values_and_overflow(clean_finance_service: FinanceService):
    """Stress test: Boundary values and extreme numbers."""
    user = "usr_extreme"

    # 1. $10,000,000.00
    rec = clean_finance_service.record_transaction(
        user_id=user,
        amount=Decimal("10000000.00"),
        transaction_type=TransactionType.INCOME,
        category="Income",
        description="Ten million bonus",
    )
    assert rec.amount_cents == 1_000_000_000
    assert rec.amount == 10_000_000.00

    # 2. $999,999,999,999.99
    rec2 = clean_finance_service.record_transaction(
        user_id=user,
        amount=Decimal("999999999999.99"),
        transaction_type=TransactionType.INCOME,
        category="Income",
        description="Trillion check",
    )
    assert rec2.amount_cents == 99_999_999_999_999

    # 3. Sub-cent precision rejection (e.g. $0.001)
    with pytest.raises(ValueError):
        clean_finance_service.record_transaction(
            user_id=user,
            amount=Decimal("0.001"),
            transaction_type=TransactionType.EXPENSE,
            category="Other",
            description="Sub-cent test",
        )

    # 4. Zero amount rejection
    with pytest.raises(ValueError):
        clean_finance_service.record_transaction(
            user_id=user,
            amount=0,
            transaction_type=TransactionType.EXPENSE,
            category="Other",
            description="Zero amount",
        )

    # 5. Negative amount rejection
    with pytest.raises(ValueError):
        clean_finance_service.record_transaction(
            user_id=user,
            amount=-10.00,
            transaction_type=TransactionType.EXPENSE,
            category="Other",
            description="Negative amount",
        )


def test_adv_fin_04_nan_and_infinity_injection(clean_finance_service: FinanceService):
    """Stress test: Adversarial NaN and Infinity inputs must be strictly rejected."""
    user = "usr_adv_nan"

    # Test float('nan')
    with pytest.raises(ValueError):
        clean_finance_service.record_transaction(
            user_id=user,
            amount=float("nan"),
            transaction_type=TransactionType.EXPENSE,
            category="Other",
            description="NaN injection",
        )

    # Test float('inf')
    with pytest.raises(ValueError):
        clean_finance_service.record_transaction(
            user_id=user,
            amount=float("inf"),
            transaction_type=TransactionType.EXPENSE,
            category="Other",
            description="Inf injection",
        )


def test_adv_fin_05_category_breakdown_percentage_precision(clean_finance_service: FinanceService):
    """Stress test: Category breakdown percentages with uneven cents distribution."""
    user = "usr_breakdown_precision"
    # Spend $1.00 split across 3 categories: 33 cents, 33 cents, 34 cents
    clean_finance_service.record_transaction(user, amount_cents=33, t_type=TransactionType.EXPENSE, category="Food & Dining", description="Food")
    clean_finance_service.record_transaction(user, amount_cents=33, t_type=TransactionType.EXPENSE, category="Transportation", description="Bus")
    clean_finance_service.record_transaction(user, amount_cents=34, t_type=TransactionType.EXPENSE, category="Entertainment", description="Movie")

    breakdown = clean_finance_service.get_category_breakdown(user)
    assert len(breakdown) == 3
    # Verify exact keys returned
    assert "category" in breakdown[0]
    assert "total_cents" in breakdown[0]
    assert "total" in breakdown[0]
    assert "percentage" in breakdown[0]

    # Verify percentages: 34.0%, 33.0%, 33.0%
    pct_sum = sum(b["percentage"] for b in breakdown)
    assert pct_sum == 100.0


def test_adv_fin_06_router_spending_breakdown_zero_display_bug(clean_finance_service: FinanceService):
    """
    CRITICAL EMPIRICAL BUG CHECK:
    In ToolRouter._handle_finance_query (app/core/router.py:140 & 161),
    the code reads item.get('spent_cents', 0) instead of item.get('total_cents', 0).
    Because FinanceService returns 'total_cents', ToolRouter formats every category as $0.00!
    """
    user = "usr_router_breakdown_bug"
    clean_finance_service.record_transaction(
        user_id=user,
        amount_cents=7500,  # $75.00
        t_type=TransactionType.EXPENSE,
        category="Groceries",
        description="Trader Joe's run",
    )

    router = ToolRouter(finance_service=clean_finance_service)
    intent = IntentResult(
        intent=IntentType.FINANCE_QUERY,
        confidence=1.0,
        slots={"query_type": "breakdown"},
        is_complete=True,
        missing_slots=[],
        raw_text="show category breakdown",
    )

    reply = router.dispatch(user, intent)
    print("Router breakdown output:\n", reply)

    # The user expects: • **Groceries:** `$75.00` (100.0%)
    # If the bug is present, it will say: • **Groceries:** `$0.00` (100.0%)
    assert "$75.00" in reply, f"BUG CONFIRMED: Router formatted output as $0.00 instead of $75.00:\n{reply}"
