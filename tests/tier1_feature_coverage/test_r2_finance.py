"""Tier 1: Feature Coverage — R2: Personal Finance Ledger & Analytical Engine.

Tests T1-R2-01 to T1-R2-06 verifying nominal transaction recording,
exact integer cents calculations, category breakdowns, budget alerts, and date filtering.
"""

from datetime import datetime, timezone
import pytest

from app.database.connection import DatabaseManager
from app.database.repositories.finance_repo import FinanceRepository, TransactionType
from app.services.finance_service import FinanceService


@pytest.fixture
def finance_service() -> FinanceService:
    db_mgr = DatabaseManager(db_path=":memory:")
    db_mgr.init_db()
    repo = FinanceRepository(db_mgr)
    return FinanceService(repository=repo)


def test_t1_r2_01_expense_logging(finance_service: FinanceService):
    """T1-R2-01: Expense record creates transaction with exact integer cents and updates balance."""
    record = finance_service.record_transaction(
        user_id="usr_test_default",
        amount=65.25,
        transaction_type=TransactionType.EXPENSE,
        category="Groceries",
        description="Weekly market",
        timestamp="2026-11-04T12:00:00Z",
    )

    assert record.amount_cents == 6525
    assert record.transaction_type == TransactionType.EXPENSE
    assert record.category == "Groceries"

    balance = finance_service.get_balance("usr_test_default")
    assert balance["total_expenses"] == 65.25
    assert balance["net_balance"] == -65.25


def test_t1_r2_02_income_logging(finance_service: FinanceService):
    """T1-R2-02: Income record increases running net balance."""
    record = finance_service.record_transaction(
        user_id="usr_test_default",
        amount=2500.00,
        transaction_type=TransactionType.INCOME,
        category="Salary",
        description="Bi-weekly paycheck",
        timestamp="2026-11-04T12:00:00Z",
    )

    assert record.amount_cents == 250000
    assert record.transaction_type == TransactionType.INCOME

    balance = finance_service.get_balance("usr_test_default")
    assert balance["total_income"] == 2500.00
    assert balance["net_balance"] == 2500.00


def test_t1_r2_03_cumulative_balance_query(finance_service: FinanceService):
    """T1-R2-03: Multi-transaction cumulative balance has zero floating-point drift."""
    user = "usr_test_default"
    finance_service.record_transaction(user, amount=1000.00, transaction_type=TransactionType.INCOME, category="Salary", description="Income")
    finance_service.record_transaction(user, amount=200.00, transaction_type=TransactionType.EXPENSE, category="Housing & Utilities", description="Rent")
    finance_service.record_transaction(user, amount=150.00, transaction_type=TransactionType.EXPENSE, category="Groceries", description="Expense 2")
    finance_service.record_transaction(user, amount=50.00, transaction_type=TransactionType.EXPENSE, category="Housing & Utilities", description="Expense 3")

    summary = finance_service.get_balance(user)
    assert summary["total_income"] == 1000.00
    assert summary["total_expenses"] == 400.00
    assert summary["net_balance"] == 600.00


def test_t1_r2_04_category_spending_breakdown(finance_service: FinanceService):
    """T1-R2-04: Category spending breakdown computes exact percentages summing to 100%."""
    user = "usr_test_default"
    finance_service.record_transaction(user, amount=120.00, transaction_type=TransactionType.EXPENSE, category="Food & Dining", description="Food spend")
    finance_service.record_transaction(user, amount=80.00, transaction_type=TransactionType.EXPENSE, category="Housing & Utilities", description="Utility spend")
    finance_service.record_transaction(user, amount=50.00, transaction_type=TransactionType.EXPENSE, category="Transportation", description="Transport spend")

    breakdown = finance_service.get_category_breakdown(user)
    cat_map = {item["category"]: item for item in breakdown}

    assert "Food & Dining" in cat_map
    assert "Housing & Utilities" in cat_map
    assert "Transportation" in cat_map

    assert cat_map["Food & Dining"]["total"] == 120.00
    assert cat_map["Food & Dining"]["percentage"] == 48.0

    assert cat_map["Housing & Utilities"]["total"] == 80.00
    assert cat_map["Housing & Utilities"]["percentage"] == 32.0

    assert cat_map["Transportation"]["total"] == 50.00
    assert cat_map["Transportation"]["percentage"] == 20.0

    total_pct = sum(item["percentage"] for item in breakdown)
    assert round(total_pct, 1) == 100.0


def test_t1_r2_05_monthly_budget_alert(finance_service: FinanceService):
    """T1-R2-05: Spending exceeding category budget emits warning alert."""
    user = "usr_test_default"
    # Set monthly budget of $200 for Dining in current month (2026-11)
    current_period = datetime.now(timezone.utc).strftime("%Y-%m")
    finance_service.repo.set_budget(user, "Food & Dining", 20000, current_period)

    # Log $180 initial spend
    finance_service.record_transaction(
        user, amount=180.00, transaction_type=TransactionType.EXPENSE,
        category="Food & Dining", description="Initial dining"
    )

    # Log additional $35 spend (total $215 > $200)
    finance_service.record_transaction(
        user, amount=35.00, transaction_type=TransactionType.EXPENSE,
        category="Food & Dining", description="Exceeding dining"
    )

    alerts = finance_service.check_budget_alerts(user)
    assert len(alerts) >= 1
    alert_text = alerts[0].lower()
    assert "food & dining" in alert_text or "dining" in alert_text
    assert "exceeded" in alert_text or "215" in alert_text


def test_t1_r2_06_date_range_filtering(finance_service: FinanceService):
    """T1-R2-06: Date range filtering returns only transactions within specified bounds."""
    user = "usr_test_default"
    finance_service.record_transaction(user, amount=50.00, transaction_type=TransactionType.EXPENSE, category="Other", description="Oct bill", timestamp="2026-10-15T12:00:00Z")
    finance_service.record_transaction(user, amount=60.00, transaction_type=TransactionType.EXPENSE, category="Other", description="Nov bill 1", timestamp="2026-11-01T12:00:00Z")
    finance_service.record_transaction(user, amount=70.00, transaction_type=TransactionType.EXPENSE, category="Other", description="Nov bill 2", timestamp="2026-11-03T12:00:00Z")

    results = finance_service.list_transactions(user, start_date="2026-11-01T00:00:00Z")
    assert len(results) == 2
    descs = [r.description for r in results]
    assert "Oct bill" not in descs
    assert "Nov bill 1" in descs
    assert "Nov bill 2" in descs
