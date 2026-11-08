"""Tier 2: Boundary & Corner Cases — R2: Personal Finance Ledger & Analytical Engine.

Tests T2-R2-01 to T2-R2-06 verifying zero/negative amount rejection,
IEEE 754 floating-point drift elimination, extreme values, malformed dates, and idempotency deduplication.
"""

from decimal import Decimal
import pytest
from fastapi.testclient import TestClient

from app.database.connection import DatabaseManager
from app.database.repositories.finance_repo import FinanceRepository, TransactionType
from app.services.finance_service import FinanceService


@pytest.fixture
def finance_service() -> FinanceService:
    db_mgr = DatabaseManager(db_path=":memory:")
    db_mgr.init_db()
    repo = FinanceRepository(db_mgr)
    return FinanceService(repository=repo)


def test_t2_r2_01_zero_amount_transaction_rejected(finance_service: FinanceService, test_client: TestClient):
    """T2-R2-01: Zero amount transaction is strictly rejected by service and API."""
    # Service layer validation
    with pytest.raises(ValueError) as excinfo:
        finance_service.record_transaction(
            user_id="usr_test_default",
            amount=0.00,
            transaction_type=TransactionType.EXPENSE,
            category="Food & Dining",
            description="Free sample",
        )
    assert "greater than zero" in str(excinfo.value).lower() or "positive" in str(excinfo.value).lower()

    # REST API validation
    resp = test_client.post("/api/finance/transactions", json={
        "amount": 0.00,
        "category": "Food & Dining",
        "type": "expense",
        "description": "Zero test",
    })
    assert resp.status_code in [400, 422]


def test_t2_r2_02_negative_amount_transaction_rejected(finance_service: FinanceService, test_client: TestClient):
    """T2-R2-02: Negative amount transaction is rejected (direction must be income or expense)."""
    with pytest.raises(ValueError) as excinfo:
        finance_service.record_transaction(
            user_id="usr_test_default",
            amount=-45.00,
            transaction_type=TransactionType.EXPENSE,
            category="Dining",
            description="Negative expense",
        )
    assert "positive" in str(excinfo.value).lower() or "greater than zero" in str(excinfo.value).lower()

    resp = test_client.post("/api/finance/transactions", json={
        "amount": -45.00,
        "category": "Dining",
        "type": "expense",
        "description": "Negative test",
    })
    assert resp.status_code in [400, 422]


def test_t2_r2_03_decimal_precision_drift_bug_prevention(finance_service: FinanceService):
    """T2-R2-03: IEEE 754 precision drift ($0.10 + $0.20 - $0.30 == 0.00) is strictly eliminated."""
    user = "usr_precision_test"
    finance_service.record_transaction(user, amount=0.10, transaction_type=TransactionType.INCOME, category="Other", description="Dime 1")
    finance_service.record_transaction(user, amount=0.20, transaction_type=TransactionType.INCOME, category="Other", description="Dimes 2")
    finance_service.record_transaction(user, amount=0.30, transaction_type=TransactionType.EXPENSE, category="Other", description="Expense 3")

    balance = finance_service.get_balance(user)
    assert balance["net_balance"] == 0.00
    assert balance["total_income"] == 0.30
    assert balance["total_expenses"] == 0.30


def test_t2_r2_04_extreme_numerical_bounds(finance_service: FinanceService):
    """T2-R2-04: Extreme financial numbers ($999,999,999,999.99) are stored without integer overflow."""
    user = "usr_extreme_test"
    extreme_amount = Decimal("999999999999.99")
    record = finance_service.record_transaction(
        user_id=user,
        amount=extreme_amount,
        transaction_type=TransactionType.INCOME,
        category="Other",
        description="Trillion check",
    )

    assert record.amount_cents == 99999999999999
    balance = finance_service.get_balance(user)
    assert balance["total_income"] == float(extreme_amount)


def test_t2_r2_05_malformed_date_string(finance_service: FinanceService, test_client: TestClient):
    """T2-R2-05: Non-existent dates like 2026-02-31 are strictly rejected with descriptive error."""
    with pytest.raises(ValueError) as excinfo:
        finance_service.record_transaction(
            user_id="usr_test_default",
            amount=25.00,
            transaction_type=TransactionType.EXPENSE,
            category="Food & Dining",
            description="Leap day error",
            timestamp="2026-02-31",
        )
    assert "invalid date" in str(excinfo.value).lower()

    resp = test_client.post("/api/finance/transactions", json={
        "amount": 25.00,
        "category": "Food & Dining",
        "type": "expense",
        "description": "Leap day error",
        "date": "2026-02-31",
    })
    assert resp.status_code in [400, 422]


def test_t2_r2_06_rapid_duplicate_submission(finance_service: FinanceService):
    """T2-R2-06: Identical transaction submitted with same idempotency key is deduplicated."""
    user = "usr_dedup_test"
    key = "idem_key_unique_12345"

    rec1 = finance_service.record_transaction(
        user_id=user,
        amount=35.00,
        transaction_type=TransactionType.EXPENSE,
        category="Transportation",
        description="Gas refill",
        idempotency_key=key,
    )
    assert rec1 is not None

    # Resubmission with same key should return existing record or raise handled error without inserting duplicate
    try:
        rec2 = finance_service.record_transaction(
            user_id=user,
            amount=35.00,
            transaction_type=TransactionType.EXPENSE,
            category="Transportation",
            description="Gas refill",
            idempotency_key=key,
        )
        assert rec2.id == rec1.id
    except ValueError as e:
        assert "duplicate" in str(e).lower()

    # Total expenses must remain exactly $35.00, NOT $70.00
    balance = finance_service.get_balance(user)
    assert balance["total_expenses"] == 35.00
