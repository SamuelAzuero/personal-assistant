"""Empirical Adversarial Stress Test Suite for Milestone M11:
Direct Account Balance Operations (Requirement R2).

Targets:
1. Direct balance operations on all 5 Colombian accounts (Efectivo, Nequi, Nu, Daviplata, Bancolombia)
   via both Service and REST API.
2. Boundary inputs & extreme numbers: zero amounts, negative numbers, floats, odd cent amounts,
   and extreme 64-bit integer values.
3. Overdraft arithmetic: negative account balances, multi-account negative asset allocations,
   zero-crossing transactions, and ledger desynchronization prevention.
4. Spanish NLP robustness: accents, uppercase/lowercase, irregular whitespace, colloquial synonyms
   (añadir, meter, consignar, cargar, abono, retirar, quitar) across parser and router.
5. Net worth conservation invariant: mathematical oracle verification across 200 fuzzing operations.
6. Web API integration, effective user fallback, rapid sequential load, and UI contracts.
"""

import os
import random
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.finance_router import (
    finance_router,
    get_effective_user_id,
    set_account_service,
    set_finance_service,
)
from app.core.intent_parser import IntentParser
from app.core.router import ToolRouter
from app.database.connection import DatabaseManager
from app.integrations.protocols import IntentResult, IntentType, TransactionType
from app.services.account_service import AccountService
from app.services.finance_service import FinanceService

REPO_ROOT = Path(__file__).resolve().parent.parent


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture
def memory_db():
    """Isolated in-memory SQLite database initialized with full schema."""
    db = DatabaseManager(":memory:")
    db.init_db()
    yield db
    db.close()


@pytest.fixture
def account_service(memory_db):
    return AccountService(db_manager=memory_db)


@pytest.fixture
def finance_service(memory_db, account_service):
    return FinanceService(db_manager=memory_db, account_service=account_service)


@pytest.fixture
def intent_parser():
    return IntentParser()


@pytest.fixture
def tool_router(account_service, finance_service):
    return ToolRouter(
        account_service=account_service,
        finance_service=finance_service,
    )


@pytest.fixture
def api_client(memory_db, account_service, finance_service):
    app = FastAPI()
    app.include_router(finance_router)
    set_account_service(account_service)
    set_finance_service(finance_service)
    return TestClient(app)


# ==============================================================================
# 1. Direct Balance Operations Across All Five Colombian Accounts
# ==============================================================================

class TestDirectBalanceAllAccounts:
    """Stress tests verifying deposit and withdrawal across all 5 Colombian accounts."""

    ALL_ACCOUNTS = ["Efectivo", "Nequi", "Nu", "Daviplata", "Bancolombia"]

    def test_deposit_and_withdraw_all_five_accounts_service(self, account_service):
        user_id = "usr_all_accounts_service"
        account_service.ensure_default_accounts(user_id)

        initial_nw = account_service.get_net_worth(user_id)["total_net_worth_cents"]
        assert initial_nw == 0

        # Deposit 100,000 COP into each account
        deposit_cents = 10_000_000  # 100,000 COP
        for acc_name in self.ALL_ACCOUNTS:
            res = account_service.deposit(
                user_id=user_id,
                account_id_or_name=acc_name,
                amount_cents=deposit_cents,
                concept=f"Carga inicial {acc_name}",
                notes="Fondo de prueba",
            )
            assert res["success"] is True
            assert res["operation"] == "deposit"
            assert res["new_balance_cents"] == deposit_cents
            assert res["account"]["name"].lower() == acc_name.lower()

        # Verify net worth is exactly 500,000 COP
        nw_after_deposits = account_service.get_net_worth(user_id)
        assert nw_after_deposits["total_net_worth_cents"] == 5 * deposit_cents
        assert nw_after_deposits["total_net_worth"] == 500_000.0

        # Withdraw 40,000 COP from each account
        withdraw_cents = 4_000_000  # 40,000 COP
        for acc_name in self.ALL_ACCOUNTS:
            res = account_service.withdraw(
                user_id=user_id,
                account_id_or_name=acc_name,
                amount_cents=withdraw_cents,
                concept=f"Retiro parcial {acc_name}",
            )
            assert res["success"] is True
            assert res["operation"] == "withdraw"
            assert res["new_balance_cents"] == deposit_cents - withdraw_cents

        # Verify net worth is exactly 300,000 COP (5 * 60,000 COP)
        nw_after_withdraws = account_service.get_net_worth(user_id)
        assert nw_after_withdraws["total_net_worth_cents"] == 5 * (deposit_cents - withdraw_cents)
        assert nw_after_withdraws["total_net_worth"] == 300_000.0

    def test_deposit_and_withdraw_all_five_accounts_api(self, api_client, account_service):
        user_id = "usr_all_accounts_api"
        account_service.ensure_default_accounts(user_id)
        accounts = account_service.get_accounts(user_id)
        acc_map = {a.name: a.id for a in accounts}

        for acc_name in self.ALL_ACCOUNTS:
            acc_id = acc_map[acc_name]

            # 1. API Deposit by account ID
            res_dep = api_client.post(
                f"/api/finance/accounts/{acc_id}/operations?user_id={user_id}",
                json={
                    "action": "deposit",
                    "amount_cents": 7_500_000,  # 75,000 COP
                    "concept": f"Depósito API {acc_name}",
                    "notes": "Prueba API",
                },
            )
            assert res_dep.status_code == 200, res_dep.text
            dep_data = res_dep.json()
            assert dep_data["success"] is True
            assert dep_data["new_balance_cents"] == 7_500_000

            # 2. API Withdraw by account Name (resolving name via URL)
            res_with = api_client.post(
                f"/api/finance/accounts/{acc_name}/operations?user_id={user_id}",
                json={
                    "action": "withdraw",
                    "amount_cents": 2_500_000,  # 25,000 COP
                    "concept": f"Retiro API {acc_name}",
                },
            )
            assert res_with.status_code == 200, res_with.text
            with_data = res_with.json()
            assert with_data["success"] is True
            assert with_data["new_balance_cents"] == 5_000_000

            # 3. Direct dedicated endpoints (/deposit and /withdraw)
            res_dep_alias = api_client.post(
                f"/api/finance/accounts/{acc_id}/deposit?user_id={user_id}",
                json={"amount_cents": 1_000_000, "concept": "Alias deposit"},
            )
            assert res_dep_alias.status_code == 200
            assert res_dep_alias.json()["new_balance_cents"] == 6_000_000

            res_with_alias = api_client.post(
                f"/api/finance/accounts/{acc_id}/withdraw?user_id={user_id}",
                json={"amount_cents": 1_000_000, "concept": "Alias withdraw"},
            )
            assert res_with_alias.status_code == 200
            assert res_with_alias.json()["new_balance_cents"] == 5_000_000

    def test_case_insensitive_account_resolution(self, account_service):
        user_id = "usr_case_insensitivity"
        account_service.ensure_default_accounts(user_id)

        # Mixed casings
        variations = [
            ("BANCOLOMBIA", 1_000_000),
            ("nequi", 2_000_000),
            ("Nu", 3_000_000),
            ("dAvIpLaTa", 4_000_000),
            ("EFECTIVO", 5_000_000),
        ]
        for name_variation, amount in variations:
            res = account_service.deposit(user_id, name_variation, amount)
            assert res["success"] is True
            assert res["new_balance_cents"] == amount


# ==============================================================================
# 2. Boundary Inputs & Corner Cases
# ==============================================================================

class TestBoundaryAndCornerCases:
    """Stress tests on zero amounts, negative numbers, extreme ranges, and odd cents."""

    def test_zero_amount_rejection_service_and_api(self, account_service, api_client):
        user_id = "usr_zero_rejection"
        account_service.ensure_default_accounts(user_id)

        # Service level rejection
        with pytest.raises(ValueError, match="Deposit amount must be greater than zero"):
            account_service.deposit(user_id, "Nequi", 0)

        with pytest.raises(ValueError, match="Withdrawal amount must be greater than zero"):
            account_service.withdraw(user_id, "Nequi", 0)

        # API level rejection (returns 400 or 422 validation failure)
        res1 = api_client.post(
            f"/api/finance/accounts/Nequi/operations?user_id={user_id}",
            json={"action": "deposit", "amount_cents": 0},
        )
        assert res1.status_code in (400, 422)

        res2 = api_client.post(
            f"/api/finance/accounts/Nequi/operations?user_id={user_id}",
            json={"action": "withdraw", "amount_cents": 0},
        )
        assert res2.status_code in (400, 422)

    def test_negative_amount_rejection_service_and_api(self, account_service, api_client):
        user_id = "usr_negative_rejection"
        account_service.ensure_default_accounts(user_id)

        # Service level
        with pytest.raises(ValueError, match="greater than zero"):
            account_service.deposit(user_id, "Bancolombia", -50_000)

        with pytest.raises(ValueError, match="greater than zero"):
            account_service.withdraw(user_id, "Bancolombia", -50_000)

        # API level rejection
        res = api_client.post(
            f"/api/finance/accounts/Bancolombia/operations?user_id={user_id}",
            json={"action": "deposit", "amount_cents": -50_000},
        )
        assert res.status_code in (400, 422)

    def test_non_integer_cents_type_safety(self, account_service):
        user_id = "usr_type_safety"
        account_service.ensure_default_accounts(user_id)

        # Floating point cent rejection
        with pytest.raises(ValueError, match="must be an integer"):
            account_service.record_operation(
                user_id=user_id,
                account_id_or_name="Nu",
                amount_cents=100.5,  # float instead of int
                action="deposit",
            )

    def test_invalid_action_rejection(self, account_service, api_client):
        user_id = "usr_invalid_action"
        account_service.ensure_default_accounts(user_id)

        # Service
        with pytest.raises(ValueError, match="must be 'deposit' or 'withdraw'"):
            account_service.record_operation(
                user_id=user_id,
                account_id_or_name="Daviplata",
                amount_cents=50_000,
                action="transfer",
            )

        # API
        res = api_client.post(
            f"/api/finance/accounts/Daviplata/operations?user_id={user_id}",
            json={"action": "unsupported_action", "amount_cents": 50_000},
        )
        assert res.status_code in (400, 422)

    def test_nonexistent_account_returns_404(self, api_client, account_service):
        user_id = "usr_not_found"
        account_service.ensure_default_accounts(user_id)

        res = api_client.post(
            f"/api/finance/accounts/acc_nonexistent_9999/operations?user_id={user_id}",
            json={"action": "deposit", "amount_cents": 50_000},
        )
        assert res.status_code == 404
        assert "not found" in res.json()["detail"].lower()

    def test_odd_cents_precision(self, account_service):
        user_id = "usr_odd_cents"
        account_service.ensure_default_accounts(user_id)

        # 1 cent ($0.01 COP)
        r1 = account_service.deposit(user_id, "Efectivo", 1)
        assert r1["new_balance_cents"] == 1

        # 33 cents
        r2 = account_service.deposit(user_id, "Efectivo", 33)
        assert r2["new_balance_cents"] == 34

        # 1,234,567 cents
        r3 = account_service.deposit(user_id, "Efectivo", 1_234_567)
        assert r3["new_balance_cents"] == 1_234_601

        # Withdraw 34 cents
        r4 = account_service.withdraw(user_id, "Efectivo", 34)
        assert r4["new_balance_cents"] == 1_234_567

        # Verify net worth matches exact cents
        nw = account_service.get_net_worth(user_id)
        assert nw["total_net_worth_cents"] == 1_234_567

    def test_extreme_magnitude_numbers(self, account_service):
        user_id = "usr_extreme_magnitudes"
        account_service.ensure_default_accounts(user_id)

        # 1 trillion cents (10 billion COP)
        large_amount = 1_000_000_000_000
        r1 = account_service.deposit(user_id, "Bancolombia", large_amount)
        assert r1["new_balance_cents"] == large_amount

        # 2^48 cents (well within 64-bit SQLite integer)
        huge_amount = 2**48
        r2 = account_service.deposit(user_id, "Bancolombia", huge_amount)
        expected = large_amount + huge_amount
        assert r2["new_balance_cents"] == expected

        nw = account_service.get_net_worth(user_id)
        assert nw["total_net_worth_cents"] == expected


# ==============================================================================
# 3. Overdraft Arithmetic & Ledger Integrity
# ==============================================================================

class TestOverdraftArithmeticAndLedgerIntegrity:
    """Stress tests verifying negative balances do not cause data corruption or desynchronization."""

    def test_overdraft_multi_step_zero_crossing(self, account_service):
        user_id = "usr_overdraft_steps"
        account_service.ensure_default_accounts(user_id)

        # Initial: 0
        acc = account_service.get_account_by_name(user_id, "Nequi")
        assert acc.balance_cents == 0

        # Step 1: Overdraft by 500,000 COP
        r1 = account_service.withdraw(user_id, "Nequi", 50_000_000)
        assert r1["new_balance_cents"] == -50_000_000
        assert r1["total_net_worth_cents"] == -50_000_000

        # Step 2: Partial repayment of 200,000 COP
        r2 = account_service.deposit(user_id, "Nequi", 20_000_000)
        assert r2["new_balance_cents"] == -30_000_000
        assert r2["total_net_worth_cents"] == -30_000_000

        # Step 3: Further overdraft by 150,000 COP
        r3 = account_service.withdraw(user_id, "Nequi", 15_000_000)
        assert r3["new_balance_cents"] == -45_000_000
        assert r3["total_net_worth_cents"] == -45_000_000

        # Step 4: Payoff crossing zero to positive (+150,000 COP)
        r4 = account_service.deposit(user_id, "Nequi", 60_000_000)
        assert r4["new_balance_cents"] == 15_000_000
        assert r4["total_net_worth_cents"] == 15_000_000

    def test_mixed_positive_and_negative_accounts_allocation(self, account_service):
        user_id = "usr_mixed_alloc"
        account_service.ensure_default_accounts(user_id)

        # Overdraw Daviplata and Nequi
        account_service.withdraw(user_id, "Daviplata", 20_000_000)  # -200,000 COP
        account_service.withdraw(user_id, "Nequi", 10_000_000)      # -100,000 COP

        # Credit Bancolombia and Nu
        account_service.deposit(user_id, "Bancolombia", 50_000_000) # +500,000 COP
        account_service.deposit(user_id, "Nu", 10_000_000)          # +100,000 COP

        # Net worth should be: -200k - 100k + 500k + 100k = +300,000 COP (30,000,000 cents)
        nw = account_service.get_net_worth(user_id)
        assert nw["total_net_worth_cents"] == 30_000_000
        assert nw["total_net_worth"] == 300_000.0

        # Check percentage shares: negative accounts must have 0.0 share, positive accounts must not crash
        acc_dict = {a["name"]: a for a in nw["accounts"]}
        assert acc_dict["Daviplata"]["percentage_share"] == 0.0
        assert acc_dict["Nequi"]["percentage_share"] == 0.0
        assert acc_dict["Bancolombia"]["percentage_share"] > 0.0

    def test_all_accounts_negative_net_worth(self, account_service):
        user_id = "usr_all_negative"
        account_service.ensure_default_accounts(user_id)

        # Overdraw all 5 accounts
        for acc in ["Efectivo", "Nequi", "Nu", "Daviplata", "Bancolombia"]:
            account_service.withdraw(user_id, acc, 10_000_000)

        # Net worth should be -500,000 COP (-50,000,000 cents)
        nw = account_service.get_net_worth(user_id)
        assert nw["total_net_worth_cents"] == -50_000_000
        assert nw["total_net_worth"] == -500_000.0

        # When total_net_worth <= 0, percentage share should default to 0.0 without ZeroDivisionError
        for a in nw["accounts"]:
            assert a["percentage_share"] == 0.0


# ==============================================================================
# 4. Spanish NLP Variations: Parsing & Router Execution
# ==============================================================================

class TestSpanishNLPAndRouterVariations:
    """Stress tests on Spanish syntax, irregular whitespace, uppercase, accents, and colloquial phrases."""

    NLP_CASES = [
        # (raw_phrase, expected_account, expected_cents, expected_action, expected_type)
        ("añadir 50 mil a Nequi", "Nequi", 5_000_000, "deposit", "income"),
        ("Añadir 50 mil a Nequi", "Nequi", 5_000_000, "deposit", "income"),
        ("AÑADIR 50 MIL A NEQUI", "Nequi", 5_000_000, "deposit", "income"),
        ("anadir 50 mil a nequi", "Nequi", 5_000_000, "deposit", "income"),
        ("  añadir   50 mil   a   Nequi  ", "Nequi", 5_000_000, "deposit", "income"),
        ("meter 100k a Bancolombia", "Bancolombia", 10_000_000, "deposit", "income"),
        ("Meter 100k a Bancolombia", "Bancolombia", 10_000_000, "deposit", "income"),
        ("METER 100K A BANCOLOMBIA", "Bancolombia", 10_000_000, "deposit", "income"),
        ("meter $100.000 a Bancolombia", "Bancolombia", 10_000_000, "deposit", "income"),
        ("retirar 30k de Daviplata", "Daviplata", 3_000_000, "withdraw", "expense"),
        ("Retirar 30k de Daviplata", "Daviplata", 3_000_000, "withdraw", "expense"),
        ("RETIRAR 30K DE DAVIPLATA", "Daviplata", 3_000_000, "withdraw", "expense"),
        ("retirar 30 mil de Daviplata", "Daviplata", 3_000_000, "withdraw", "expense"),
        ("quitar 20 mil de Efectivo", "Efectivo", 2_000_000, "withdraw", "expense"),
        ("Quitar 20 mil de Efectivo", "Efectivo", 2_000_000, "withdraw", "expense"),
        ("QUITAR 20 MIL DE EFECTIVO", "Efectivo", 2_000_000, "withdraw", "expense"),
        ("quitar 20k de Efectivo", "Efectivo", 2_000_000, "withdraw", "expense"),
        ("quitar 100 mil de Bancolombia", "Bancolombia", 10_000_000, "withdraw", "expense"),
        ("retirar 50.000 de Nu", "Nu", 5_000_000, "withdraw", "expense"),
        ("consignar 200k en Nu", "Nu", 20_000_000, "deposit", "income"),
        ("consigné 80.000 a Daviplata", "Daviplata", 8_000_000, "deposit", "income"),
        ("cargar 100 mil a Nu", "Nu", 10_000_000, "deposit", "income"),
        ("cargué 50k en Nequi", "Nequi", 5_000_000, "deposit", "income"),
        ("abono de 70k a Bancolombia", "Bancolombia", 7_000_000, "deposit", "income"),
        ("depósito de 45k en Efectivo", "Efectivo", 4_500_000, "deposit", "income"),
    ]

    @pytest.mark.parametrize("phrase,expected_account,expected_cents,expected_action,expected_type", NLP_CASES)
    def test_nlp_parsing_variations(self, intent_parser, phrase, expected_account, expected_cents, expected_action, expected_type):
        res = intent_parser.parse(phrase)
        assert res.intent == IntentType.FINANCE_ENTRY, f"Failed for phrase: {phrase}"
        slots = res.slots
        assert slots.get("account_name") == expected_account
        assert slots.get("amount_cents") == expected_cents
        assert slots.get("action") == expected_action
        assert slots.get("transaction_type") == expected_type

    def test_router_end_to_end_execution_spanish(self, tool_router, account_service, intent_parser):
        user_id = "usr_router_e2e"
        account_service.ensure_default_accounts(user_id)

        # 1. Deposit 100k to Bancolombia via phrase
        p1 = intent_parser.parse("meter 100k a Bancolombia")
        msg1 = tool_router.dispatch(user_id=user_id, intent_result=p1)
        assert "Bancolombia" in msg1

        banco = account_service.get_account_by_name(user_id, "Bancolombia")
        assert banco.balance_cents == 10_000_000

        # 2. Withdraw 30k from Bancolombia via phrase
        p2 = intent_parser.parse("quitar 30 mil de Bancolombia")
        msg2 = tool_router.dispatch(user_id=user_id, intent_result=p2)
        assert "Bancolombia" in msg2

        banco_after = account_service.get_account_by_name(user_id, "Bancolombia")
        assert banco_after.balance_cents == 7_000_000

        # Net worth should be 70,000 COP
        nw = account_service.get_net_worth(user_id)
        assert nw["total_net_worth_cents"] == 7_000_000


# ==============================================================================
# 5. Net Worth Conservation Invariant (200-Operation Fuzzing Oracle)
# ==============================================================================

class TestNetWorthConservationInvariant:
    """Rigorous property-based oracle: verify Net Worth = sum(Accounts) after every step."""

    def test_200_random_operations_invariant_oracle(self, account_service, memory_db):
        user_id = "usr_oracle_fuzzing"
        account_service.ensure_default_accounts(user_id)

        accounts = ["Efectivo", "Nequi", "Nu", "Daviplata", "Bancolombia"]
        oracle_balances = {a: 0 for a in accounts}
        oracle_net_worth = 0

        rng = random.Random(42)  # Deterministic seed for reproducible testing
        num_operations = 200

        for i in range(num_operations):
            target_acc = rng.choice(accounts)
            action = rng.choice(["deposit", "withdraw"])
            # Generate varied amounts: odd cents, small amounts, large COP amounts
            amount_cents = rng.choice([
                1, 33, 99, 100, 500, 1_000, 15_000, 50_000, 250_000,
                1_000_000, 5_000_000, 12_345_678,
            ])

            if action == "deposit":
                res = account_service.deposit(user_id, target_acc, amount_cents)
                oracle_balances[target_acc] += amount_cents
                oracle_net_worth += amount_cents
            else:
                res = account_service.withdraw(user_id, target_acc, amount_cents)
                oracle_balances[target_acc] -= amount_cents
                oracle_net_worth -= amount_cents

            # INVARIANT 1: Account balance matches Oracle exactly
            assert res["new_balance_cents"] == oracle_balances[target_acc]

            # INVARIANT 2: Net worth in response matches Oracle exactly
            assert res["total_net_worth_cents"] == oracle_net_worth

            # INVARIANT 3: Service-level net worth matches sum of all individual accounts
            live_accounts = account_service.get_accounts(user_id)
            sum_balances = sum(a.balance_cents for a in live_accounts)
            live_nw = account_service.get_net_worth(user_id)["total_net_worth_cents"]
            assert live_nw == sum_balances
            assert live_nw == oracle_net_worth

        # DIRECT SQL AUDIT: Check SQLite accounts and transactions tables
        with memory_db.connection() as conn:
            # Check sum of accounts table directly
            row_sum = conn.execute(
                "SELECT SUM(balance_cents) FROM accounts WHERE user_id = ?;",
                (user_id,),
            ).fetchone()[0]
            assert row_sum == oracle_net_worth

            # Check transaction count equals total operations
            tx_count = conn.execute(
                "SELECT COUNT(*) FROM transactions WHERE user_id = ?;",
                (user_id,),
            ).fetchone()[0]
            assert tx_count == num_operations

            # Check net cash flow from transactions equals net worth change
            tx_flow = conn.execute(
                """
                SELECT SUM(CASE WHEN transaction_type = 'income' THEN amount_cents ELSE -amount_cents END)
                FROM transactions WHERE user_id = ?;
                """,
                (user_id,),
            ).fetchone()[0]
            assert tx_flow == oracle_net_worth


# ==============================================================================
# 6. Web API Concurrency, Fallback & UI Contracts
# ==============================================================================

class TestWebAPIIntegrationAndUIContracts:
    """Stress tests on rapid sequential API operations, user fallback, and web UI contracts."""

    def test_rapid_sequential_api_operations(self, api_client, account_service):
        user_id = "usr_rapid_api"
        account_service.ensure_default_accounts(user_id)

        # 50 rapid sequential deposits of 10,000 COP (1,000,000 cents)
        total_cents = 0
        for i in range(50):
            res = api_client.post(
                f"/api/finance/accounts/Nu/operations?user_id={user_id}",
                json={"action": "deposit", "amount_cents": 1_000_000, "concept": f"Rapid {i}"},
            )
            assert res.status_code == 200
            total_cents += 1_000_000
            assert res.json()["new_balance_cents"] == total_cents

        nu = account_service.get_account_by_name(user_id, "Nu")
        assert nu.balance_cents == 50_000_000

    def test_effective_user_fallback_and_custom_user(self, api_client, account_service):
        # 1. Fallback to active telegram user when user_id is omitted
        res_default = api_client.post(
            "/api/finance/accounts/Efectivo/operations",
            json={"action": "deposit", "amount_cents": 5_000_000, "concept": "Default user deposit"},
        )
        assert res_default.status_code == 200
        eff_user = get_effective_user_id(None)
        acc_default = account_service.get_account_by_name(eff_user, "Efectivo")
        assert acc_default.balance_cents >= 5_000_000

        # 2. Explicit custom user ID
        custom_user = "usr_custom_isolated_99"
        res_custom = api_client.post(
            f"/api/finance/accounts/Efectivo/operations?user_id={custom_user}",
            json={"action": "deposit", "amount_cents": 3_000_000, "concept": "Custom user deposit"},
        )
        assert res_custom.status_code == 200
        acc_custom = account_service.get_account_by_name(custom_user, "Efectivo")
        assert acc_custom.balance_cents == 3_000_000

    def test_index_html_contains_account_op_dialog_and_attributes(self):
        index_path = REPO_ROOT / "app" / "static" / "index.html"
        assert index_path.exists(), "app/static/index.html must exist"
        content = index_path.read_text(encoding="utf-8")

        # Dialog exists with closedby="any"
        assert 'id="account-op-dialog"' in content
        assert 'closedby="any"' in content

        # Required form controls
        assert 'id="account-op-form"' in content
        assert 'id="account-op-type"' in content
        assert 'id="account-op-amount"' in content
        assert 'id="account-op-concept"' in content
        assert 'id="btn-submit-account-op"' in content
        assert 'id="btn-close-account-op-dialog"' in content

    def test_app_js_contains_account_action_buttons_and_isolation(self):
        js_path = REPO_ROOT / "app" / "static" / "js" / "app.js"
        assert js_path.exists(), "app/static/js/app.js must exist"
        content = js_path.read_text(encoding="utf-8")

        # Buttons rendered on account cards
        assert 'btn-account-op' in content
        assert 'data-action="deposit"' in content
        assert 'data-action="withdraw"' in content

        # Backdrop target isolation includes accountOpDialog
        assert 'accountOpDialog' in content
        assert '/api/finance/accounts/' in content
        assert '/operations' in content

        # Form submission debouncing and dashboard refresh
        assert 'refreshDashboard' in content

    def test_styles_css_contains_account_actions_classes(self):
        css_path = REPO_ROOT / "app" / "static" / "css" / "styles.css"
        assert css_path.exists(), "app/static/css/styles.css must exist"
        content = css_path.read_text(encoding="utf-8")

        assert '.account-actions' in content
        assert '.btn-outline-success' in content
        assert '.btn-outline-danger' in content
