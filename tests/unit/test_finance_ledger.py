"""Unit test suite for Milestone 2: Personal Finance Ledger & Analytical Engine.

Verifies F11–F22, F59, SQLite WAL connection manager, foreign keys, and REST API router.
"""

import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database.connection import DatabaseManager, create_connection
from app.database.repositories.finance_repo import (
    FinanceRepository,
    TransactionRecord,
    TransactionType,
)
from app.services.finance_service import FinanceService, validate_iso_date
from app.api.finance_router import router as finance_router, set_finance_service


@pytest.fixture
def memory_db():
    """Isolated in-memory SQLite database initialized with full 7-table schema."""
    db = DatabaseManager(":memory:")
    db.init_db()
    yield db
    db.close()


@pytest.fixture
def finance_service(memory_db):
    """Isolated FinanceService instance with in-memory persistence."""
    return FinanceService(db_manager=memory_db)


@pytest.fixture
def api_client(finance_service):
    """FastAPI TestClient wired to the test FinanceService."""
    app = FastAPI()
    app.include_router(finance_router)
    set_finance_service(finance_service)
    return TestClient(app)


# ==============================================================================
# 1. Database Connection & Schema DDL Verification
# ==============================================================================


class TestDatabaseConnectionAndSchema:
    """Verifies SQLite connection manager, WAL mode, foreign keys, and schema DDL."""

    def test_schema_creates_all_seven_tables_and_indexes(self, memory_db):
        with memory_db.connection() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
            ).fetchall()
            table_names = [r["name"] for r in rows]

        expected_tables = [
            "budgets",
            "calendar_events",
            "conversation_sessions",
            "email_messages",
            "tasks",
            "transactions",
            "users",
        ]
        for tbl in expected_tables:
            assert tbl in table_names, f"Table {tbl} must be present in schema"

    def test_wal_mode_enabled_on_disk_database(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test_wal.db")
            db = DatabaseManager(db_path)
            db.init_db()

            with db.connection() as conn:
                journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
                assert journal_mode.lower() == "wal"

            db.close()

    def test_foreign_keys_pragma_enforced(self, memory_db):
        with memory_db.connection() as conn:
            fk_status = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
            assert fk_status == 1

            # Attempt inserting a transaction for non-existent user should fail when foreign keys are ON
            with pytest.raises(Exception):
                conn.execute(
                    """
                    INSERT INTO transactions (
                        transaction_id, user_id, amount_cents, transaction_type,
                        category, description, timestamp
                    ) VALUES ('tx_orphan', 'non_existent_user', 500, 'expense', 'Food', 'Orphan', '2026-11-04T12:00:00Z');
                    """
                )

    def test_concurrent_multithreaded_access(self, memory_db):
        """Verify thread-safe connection manager handles concurrent writes cleanly."""
        repo = FinanceRepository(memory_db)
        repo.ensure_user("thread_user")

        def write_tx(index: int):
            repo.add_transaction(
                user_id="thread_user",
                amount_cents=100 + index,
                transaction_type="expense",
                category="General",
                description=f"Thread tx {index}",
                transaction_id=f"tx_thread_{index}",
            )

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(write_tx, i) for i in range(40)]
            for f in futures:
                f.result()

        bal = repo.get_balance("thread_user")
        assert bal["transaction_count"] == 40


# ==============================================================================
# 2. Features F11 & F12: Expense & Income Recording
# ==============================================================================


class TestTransactionRecording:
    """Verifies F11 (Expense) and F12 (Income) recording in exact integer cents."""

    def test_record_expense_with_exact_cents(self, finance_service):
        rec = finance_service.record_transaction(
            user_id="user_1",
            amount=Decimal("45.50"),
            transaction_type=TransactionType.EXPENSE,
            category="Food & Dining",
            description="Lunch with team",
        )
        assert isinstance(rec, TransactionRecord)
        assert rec.amount_cents == 4550
        assert rec.amount == 45.50
        assert rec.transaction_type == TransactionType.EXPENSE
        assert rec.category == "Food & Dining"
        assert rec.description == "Lunch with team"
        assert rec.id.startswith("tx_")

    def test_record_income_with_exact_cents(self, finance_service):
        rec = finance_service.record_transaction(
            user_id="user_1",
            amount_cents=250000,
            t_type="income",
            category="Income",
            description="Monthly salary",
        )
        assert rec.amount_cents == 250000
        assert rec.amount == 2500.00
        assert rec.transaction_type == TransactionType.INCOME
        assert rec.category == "Income"

    def test_record_transaction_with_custom_timestamp(self, finance_service):
        custom_ts = "2026-11-04T15:30:00Z"
        rec = finance_service.record_transaction(
            user_id="user_1",
            amount=Decimal("12.00"),
            t_type=TransactionType.EXPENSE,
            category="Transportation",
            description="Subway fare",
            timestamp=custom_ts,
        )
        assert rec.timestamp.year == 2026
        assert rec.timestamp.month == 11
        assert rec.timestamp.day == 4
        assert rec.timestamp.hour == 15
        assert rec.timestamp.minute == 30


# ==============================================================================
# 3. Feature F13: Input Validation & Boundary Checks
# ==============================================================================


class TestTransactionValidation:
    """Verifies strict validation of positive amounts, descriptions, categories, and dates."""

    def test_reject_zero_amount(self, finance_service):
        with pytest.raises(ValueError, match="greater than zero"):
            finance_service.record_transaction(
                user_id="user_1",
                amount=Decimal("0.00"),
                transaction_type="expense",
                category="Food",
                description="Zero amount test",
            )

    def test_reject_negative_amount(self, finance_service):
        with pytest.raises(ValueError, match="Amount must be positive"):
            finance_service.record_transaction(
                user_id="user_1",
                amount=Decimal("-15.00"),
                transaction_type="expense",
                category="Food",
                description="Negative test",
            )

    def test_reject_fractional_cents_beyond_two_decimal_places(self, finance_service):
        with pytest.raises(ValueError, match="more than 2 decimal places"):
            finance_service.record_transaction(
                user_id="user_1",
                amount=Decimal("12.345"),
                transaction_type="expense",
                category="Food",
                description="Sub-cent test",
            )

    def test_reject_empty_description(self, finance_service):
        with pytest.raises(ValueError, match="description cannot be empty"):
            finance_service.record_transaction(
                user_id="user_1",
                amount=Decimal("10.00"),
                transaction_type="expense",
                category="Food",
                description="   ",
            )

    def test_reject_invalid_date_format(self, finance_service):
        with pytest.raises(ValueError, match="Invalid date format"):
            finance_service.record_transaction(
                user_id="user_1",
                amount=Decimal("10.00"),
                transaction_type="expense",
                category="Food",
                description="Invalid date",
                timestamp="2026-02-31",  # Invalid calendar day
            )

        with pytest.raises(ValueError, match="Invalid date format"):
            finance_service.record_transaction(
                user_id="user_1",
                amount=Decimal("10.00"),
                transaction_type="expense",
                category="Food",
                description="Not a date",
                timestamp="not-a-date",
            )

    def test_reject_invalid_transaction_type(self, finance_service):
        with pytest.raises(ValueError, match="Invalid transaction type"):
            finance_service.record_transaction(
                user_id="user_1",
                amount=Decimal("10.00"),
                transaction_type="invalid_type",
                category="Food",
                description="Invalid type test",
            )


# ==============================================================================
# 4. Feature F14: Zero-Drift Cumulative Balance Calculation
# ==============================================================================


class TestCumulativeBalanceAndZeroDrift:
    """Verifies zero floating-point drift across cumulative additions and subtractions."""

    def test_zero_floating_point_drift_scenario(self, finance_service):
        """Classic IEEE 754 float drift: 0.10 + 0.20 - 0.30 in float gives 5.5511e-17.

        In exact integer cents, this MUST be precisely 0.00.
        """
        finance_service.record_transaction(
            user_id="drift_user",
            amount=Decimal("0.10"),
            transaction_type="income",
            category="Income",
            description="Ten cents income",
        )
        finance_service.record_transaction(
            user_id="drift_user",
            amount=Decimal("0.20"),
            transaction_type="income",
            category="Income",
            description="Twenty cents income",
        )
        finance_service.record_transaction(
            user_id="drift_user",
            amount=Decimal("0.30"),
            transaction_type="expense",
            category="Food",
            description="Thirty cents expense",
        )

        bal = finance_service.get_balance("drift_user")
        assert bal["balance_cents"] == 0
        assert bal["net_balance"] == 0.00
        assert bal["income_cents"] == 30
        assert bal["expense_cents"] == 30

    def test_cumulative_balance_multi_transaction_set(self, finance_service):
        # Income: $1000.00
        finance_service.record_transaction(
            user_id="bal_user", amount=Decimal("1000.00"), transaction_type="income",
            category="Salary", description="Paycheck"
        )
        # Expenses: $200.00, $150.00, $50.00 = $400.00
        finance_service.record_transaction(
            user_id="bal_user", amount=Decimal("200.00"), transaction_type="expense",
            category="Food", description="Groceries"
        )
        finance_service.record_transaction(
            user_id="bal_user", amount=Decimal("150.00"), transaction_type="expense",
            category="Utilities", description="Electricity"
        )
        finance_service.record_transaction(
            user_id="bal_user", amount=Decimal("50.00"), transaction_type="expense",
            category="Transport", description="Gas"
        )

        bal = finance_service.get_balance("bal_user")
        assert bal["total_income"] == 1000.00
        assert bal["total_expenses"] == 400.00
        assert bal["net_balance"] == 600.00
        assert bal["balance_cents"] == 60000
        assert bal["transaction_count"] == 4


# ==============================================================================
# 5. Features F15 & F16: Category Taxonomy & Deterministic Auto-Categorization
# ==============================================================================


class TestAutoCategorization:
    """Verifies deterministic rule & keyword heuristics for transaction categorization."""

    @pytest.mark.parametrize(
        "note,expected_category",
        [
            ("Chipotle burrito bowl for lunch", "Food & Dining"),
            ("Starbucks iced latte and croissant", "Food & Dining"),
            ("Dinner at sushi restaurant with friends", "Food & Dining"),
            ("Trader Joe's weekly grocery run", "Groceries"),
            ("Bought milk and bread at Safeway supermarket", "Groceries"),
            ("Uber ride to downtown office", "Transportation"),
            ("Shell gas station fuel refill", "Transportation"),
            ("Monthly rent payment for apartment", "Housing & Utilities"),
            ("Electric utility bill payment", "Housing & Utilities"),
            ("Netflix monthly subscription", "Entertainment"),
            ("Cinema tickets for weekend movie", "Entertainment"),
            ("Prescription refill at pharmacy", "Health & Wellness"),
            ("Dentist checkup and cleaning", "Health & Wellness"),
            ("Amazon order for winter jacket", "Shopping"),
            ("Bi-weekly company payroll paycheck", "Income"),
            ("Random miscellaneous expense item", "Other"),
        ],
    )
    def test_auto_categorization_heuristics(self, finance_service, note, expected_category):
        cat = finance_service.auto_categorize(note)
        assert cat == expected_category

    def test_auto_categorization_applied_on_empty_category(self, finance_service):
        rec = finance_service.record_transaction(
            user_id="u_auto",
            amount=Decimal("4.50"),
            transaction_type="expense",
            category="auto",
            description="Starbucks coffee",
        )
        assert rec.category == "Food & Dining"


# ==============================================================================
# 6. Feature F18: Category Spending Share & Empty Ledger Guard
# ==============================================================================


class TestCategoryBreakdownAndShare:
    """Verifies percentage calculation across categories and zero-division guard."""

    def test_empty_ledger_zero_division_guard(self, finance_service):
        breakdown = finance_service.get_category_breakdown("empty_user")
        assert breakdown == []

    def test_category_share_percentages(self, finance_service):
        # Food: $120.00 (48%), Utilities: $80.00 (32%), Transport: $50.00 (20%) -> Total $250.00
        finance_service.record_transaction(
            user_id="pct_user", amount=Decimal("120.00"), transaction_type="expense",
            category="Food & Dining", description="Dinner & lunches"
        )
        finance_service.record_transaction(
            user_id="pct_user", amount=Decimal("80.00"), transaction_type="expense",
            category="Housing & Utilities", description="Water & electricity"
        )
        finance_service.record_transaction(
            user_id="pct_user", amount=Decimal("50.00"), transaction_type="expense",
            category="Transportation", description="Metro card"
        )

        breakdown = finance_service.get_category_breakdown("pct_user")
        assert len(breakdown) == 3

        cat_map = {item["category"]: item for item in breakdown}
        assert cat_map["Food & Dining"]["percentage"] == 48.0
        assert cat_map["Housing & Utilities"]["percentage"] == 32.0
        assert cat_map["Transportation"]["percentage"] == 20.0

        total_pct = sum(item["percentage"] for item in breakdown)
        assert abs(total_pct - 100.0) < 0.01


# ==============================================================================
# 7. Features F19 & F20: Spending Threshold & High-Value Alerts
# ==============================================================================


class TestBudgetAndSpendingAlerts:
    """Verifies warning triggers for exceeding category limits (80%, 100%) and high values."""

    def test_budget_exceeded_alert(self, finance_service):
        period = "2026-11"
        finance_service.set_budget(
            user_id="alert_user",
            category="Dining",
            monthly_limit=Decimal("200.00"),
            period=period,
        )

        finance_service.record_transaction(
            user_id="alert_user",
            amount=Decimal("180.00"),
            transaction_type="expense",
            category="Dining",
            description="Fine dining",
            timestamp=f"{period}-02T12:00:00Z",
        )
        finance_service.record_transaction(
            user_id="alert_user",
            amount=Decimal("35.00"),
            transaction_type="expense",
            category="Dining",
            description="Lunch out",
            timestamp=f"{period}-03T12:00:00Z",
        )

        alerts = finance_service.check_budget_alerts("alert_user", period=period)
        assert len(alerts) >= 1
        expected = "Budget exceeded: Dining spending is now $215.00 of $200.00 limit"
        assert any(expected in a for a in alerts)

    def test_budget_warning_at_eighty_percent(self, finance_service):
        period = "2026-11"
        finance_service.set_budget(
            user_id="warn_user",
            category="Shopping",
            monthly_limit=Decimal("100.00"),
            period=period,
        )
        finance_service.record_transaction(
            user_id="warn_user",
            amount=Decimal("85.00"),
            transaction_type="expense",
            category="Shopping",
            description="Shoes",
            timestamp=f"{period}-05T12:00:00Z",
        )

        alerts = finance_service.check_budget_alerts("warn_user", period=period)
        assert any("Budget warning: Shopping spending is at 85.0%" in a for a in alerts)

    def test_high_value_transaction_alert(self, finance_service):
        period = "2026-11"
        # High value default threshold is $500.00 (50000 cents)
        finance_service.record_transaction(
            user_id="hv_user",
            amount=Decimal("650.00"),
            transaction_type="expense",
            category="Shopping",
            description="Laptop display monitor",
            timestamp=f"{period}-04T12:00:00Z",
        )

        alerts = finance_service.check_budget_alerts("hv_user", period=period)
        assert any("High-value expense recorded: $650.00" in a for a in alerts)


# ==============================================================================
# 8. Feature F17 & F21: Summaries, Filtering & Querying
# ==============================================================================


class TestPeriodicSummaryAndFiltering:
    """Verifies monthly/periodic summaries and transaction querying by date range."""

    def test_filter_transactions_by_date_range(self, finance_service):
        finance_service.record_transaction(
            user_id="query_user", amount=Decimal("10.00"), transaction_type="expense",
            category="Food", description="October lunch", timestamp="2026-10-15T12:00:00Z"
        )
        finance_service.record_transaction(
            user_id="query_user", amount=Decimal("20.00"), transaction_type="expense",
            category="Food", description="November lunch 1", timestamp="2026-11-01T12:00:00Z"
        )
        finance_service.record_transaction(
            user_id="query_user", amount=Decimal("30.00"), transaction_type="expense",
            category="Food", description="November lunch 2", timestamp="2026-11-03T12:00:00Z"
        )

        nov_txs = finance_service.list_transactions(
            user_id="query_user",
            start_date="2026-11-01T00:00:00Z",
            end_date="2026-11-30T23:59:59Z",
        )
        assert len(nov_txs) == 2
        descriptions = [t.description for t in nov_txs]
        assert "October lunch" not in descriptions
        assert "November lunch 1" in descriptions
        assert "November lunch 2" in descriptions

    def test_periodic_summary_aggregation(self, finance_service):
        finance_service.record_transaction(
            user_id="sum_user", amount=Decimal("2000.00"), transaction_type="income",
            category="Salary", description="November salary", timestamp="2026-11-01T09:00:00Z"
        )
        finance_service.record_transaction(
            user_id="sum_user", amount=Decimal("500.00"), transaction_type="expense",
            category="Housing & Utilities", description="Rent", timestamp="2026-11-02T10:00:00Z"
        )

        summary = finance_service.get_summary("sum_user", period="2026-11")
        assert summary["total_income"] == 2000.00
        assert summary["total_expenses"] == 500.00
        assert summary["net_balance"] == 1500.00
        assert "Housing & Utilities" in summary["categories"]


# ==============================================================================
# 9. Features F22 & F59: Voiding Transactions & Idempotency Deduplication
# ==============================================================================


class TestVoidAndIdempotency:
    """Verifies idempotent reversal (voiding) and deduplication via idempotency keys."""

    def test_void_transaction_reverses_balance(self, finance_service):
        tx = finance_service.record_transaction(
            user_id="void_user",
            amount=Decimal("50.00"),
            transaction_type="expense",
            category="Food",
            description="Errant charge",
        )
        bal_before = finance_service.get_balance("void_user")
        assert bal_before["total_expenses"] == 50.00

        deleted = finance_service.void_transaction(tx.id, user_id="void_user")
        assert deleted is True

        bal_after = finance_service.get_balance("void_user")
        assert bal_after["total_expenses"] == 0.00
        assert bal_after["transaction_count"] == 0

        # Subsequent void is safe and idempotent
        deleted_again = finance_service.void_transaction(tx.id, user_id="void_user")
        assert deleted_again is False

    def test_idempotency_deduplication_prevents_duplicate_records(self, finance_service):
        key = "idemp_webhook_test_123"

        tx1 = finance_service.record_transaction(
            user_id="dedup_user",
            amount=Decimal("35.00"),
            transaction_type="expense",
            category="Transportation",
            description="Uber ride",
            idempotency_key=key,
        )

        # Replayed webhook with same key
        tx2 = finance_service.record_transaction(
            user_id="dedup_user",
            amount=Decimal("35.00"),
            transaction_type="expense",
            category="Transportation",
            description="Uber ride",
            idempotency_key=key,
        )

        assert tx1.id == tx2.id
        bal = finance_service.get_balance("dedup_user")
        assert bal["transaction_count"] == 1
        assert bal["total_expenses"] == 35.00


# ==============================================================================
# 10. REST API Router Endpoints Verification (TestClient)
# ==============================================================================


class TestFinanceRouterEndpoints:
    """Verifies all FastAPI REST endpoints under /api/finance/*."""

    def test_api_create_transaction_and_get_summary(self, api_client):
        # 1. POST /api/finance/transactions
        res = api_client.post(
            "/api/finance/transactions",
            json={
                "amount": 65.25,
                "category": "Groceries",
                "type": "expense",
                "description": "Weekly market",
                "user_id": "api_user",
            },
        )
        assert res.status_code == 201
        data = res.json()
        assert data["amount"] == 65.25
        assert data["amount_cents"] == 6525
        assert data["category"] == "Groceries"

        # 2. GET /api/finance/summary
        res_sum = api_client.get("/api/finance/summary?user_id=api_user")
        assert res_sum.status_code == 200
        summary = res_sum.json()
        assert summary["total_expenses"] == 65.25
        assert summary["net_balance"] == -65.25
        assert summary["transaction_count"] == 1

    def test_api_singular_route_post_transaction(self, api_client):
        res = api_client.post(
            "/api/finance/transaction",
            json={
                "amount": 2500.00,
                "category": "Income",
                "type": "income",
                "description": "Bi-weekly paycheck",
                "user_id": "api_user_2",
            },
        )
        assert res.status_code == 201
        assert res.json()["amount"] == 2500.00

    def test_api_get_categories_breakdown(self, api_client):
        api_client.post(
            "/api/finance/transactions",
            json={
                "amount": 100.00,
                "category": "Food",
                "type": "expense",
                "description": "Dinner",
                "user_id": "cat_user",
            },
        )
        api_client.post(
            "/api/finance/transactions",
            json={
                "amount": 100.00,
                "category": "Utilities",
                "type": "expense",
                "description": "Electric",
                "user_id": "cat_user",
            },
        )

        res = api_client.get("/api/finance/categories?user_id=cat_user")
        assert res.status_code == 200
        cats = res.json()
        assert len(cats) == 2
        for c in cats:
            assert c["percentage"] == 50.0

    def test_api_delete_transaction(self, api_client):
        post_res = api_client.post(
            "/api/finance/transactions",
            json={
                "amount": 15.00,
                "category": "Food",
                "type": "expense",
                "description": "Snack",
                "user_id": "del_user",
            },
        )
        tx_id = post_res.json()["id"]

        del_res = api_client.delete(f"/api/finance/transactions/{tx_id}?user_id=del_user")
        assert del_res.status_code == 200
        assert del_res.json()["success"] is True

        sum_res = api_client.get("/api/finance/summary?user_id=del_user")
        assert sum_res.json()["total_expenses"] == 0.00

    def test_api_validation_errors_return_422(self, api_client):
        # 1. Zero amount
        res1 = api_client.post(
            "/api/finance/transactions",
            json={"amount": 0.0, "category": "Food", "type": "expense", "description": "Zero"},
        )
        assert res1.status_code == 422

        # 2. Negative amount
        res2 = api_client.post(
            "/api/finance/transactions",
            json={"amount": -20.0, "category": "Food", "type": "expense", "description": "Negative"},
        )
        assert res2.status_code == 422

        # 3. Invalid date query param
        res3 = api_client.get("/api/finance/transactions?start_date=not-a-date")
        assert res3.status_code == 422

        # 4. Missing required description
        res4 = api_client.post(
            "/api/finance/transactions",
            json={"amount": 25.0, "category": "Food", "type": "expense", "description": "   "},
        )
        assert res4.status_code == 422

    def test_api_empty_database_cold_start(self, api_client):
        res = api_client.get("/api/finance/summary?user_id=brand_new_cold_user")
        assert res.status_code == 200
        data = res.json()
        assert data["net_balance"] == 0.00
        assert data["total_income"] == 0.00
        assert data["total_expenses"] == 0.00
        assert data["transaction_count"] == 0
        assert data["category_breakdown"] == []

    def test_api_budget_management_endpoints(self, api_client):
        res_create = api_client.post(
            "/api/finance/budgets",
            json={
                "category": "Dining",
                "monthly_limit": 300.00,
                "period": "2026-11",
                "user_id": "budget_api_user",
            },
        )
        assert res_create.status_code == 201
        assert res_create.json()["monthly_limit"] == 300.00
        assert res_create.json()["monthly_limit_cents"] == 30000

        res_list = api_client.get("/api/finance/budgets?user_id=budget_api_user&period=2026-11")
        assert res_list.status_code == 200
        budgets = res_list.json()
        assert len(budgets) == 1
        assert budgets[0]["category"] == "Dining"
