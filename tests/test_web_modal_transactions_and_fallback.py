"""Test suite for Web Transaction modal account linking, balance synchronization, and effective user resolution."""

import re
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database.connection import DatabaseManager
from app.services.finance_service import FinanceService
from app.services.account_service import AccountService
from app.services.debt_service import DebtService
from app.services.subscription_service import SubscriptionService
from app.api.finance_router import (
    finance_router,
    set_finance_service,
    set_account_service,
    set_debt_service,
    set_subscription_service,
    get_effective_user_id,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


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
def debt_service(memory_db, account_service):
    return DebtService(db_manager=memory_db, account_service=account_service)


@pytest.fixture
def subscription_service(memory_db):
    return SubscriptionService(db_manager=memory_db)


@pytest.fixture
def api_client(memory_db, account_service, finance_service, debt_service, subscription_service):
    app = FastAPI()
    app.include_router(finance_router)
    set_finance_service(finance_service)
    set_account_service(account_service)
    set_debt_service(debt_service)
    set_subscription_service(subscription_service)
    with TestClient(app) as client:
        yield client
    set_finance_service(None)
    set_debt_service(None)
    set_subscription_service(None)


class TestWebTransactionAccountLinking:
    """Verifies R2: Account selection in web transaction creation immediately adjusts account balances."""

    def test_create_expense_transaction_debits_designated_account(self, api_client, account_service):
        user_id = "test_user_web"
        account_service.ensure_default_accounts(user_id)
        # Seed Nequi with initial 200,000 COP
        nequi = account_service.get_account_by_name(user_id, "Nequi")
        account_service.set_balance(nequi.id, 20000000)  # 200,000 COP in cents

        payload = {
            "amount": 50000.0,
            "type": "expense",
            "category": "Food & Dining",
            "description": "Almuerzo de trabajo",
            "user_id": user_id,
            "account": "Nequi",
        }
        resp = api_client.post("/api/finance/transactions", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["account_name"] == "Nequi"
        assert data["amount_cents"] == 5000000

        # Verify Nequi balance was debited by 50,000 COP -> remaining 150,000 COP
        updated_acc = account_service.get_account(nequi.id)
        assert updated_acc.balance_cents == 15000000
        assert updated_acc.balance == 150000.0

        # Verify via GET /api/finance/accounts endpoint
        acc_resp = api_client.get(f"/api/finance/accounts?user_id={user_id}")
        assert acc_resp.status_code == 200
        accounts = acc_resp.json()["accounts"]
        nequi_item = next(a for a in accounts if a["name"] == "Nequi")
        assert nequi_item["balance_cents"] == 15000000

    def test_create_income_transaction_credits_designated_account(self, api_client, account_service):
        user_id = "test_user_web_income"
        account_service.ensure_default_accounts(user_id)
        bancolombia = account_service.get_account_by_name(user_id, "Bancolombia")
        account_service.set_balance(bancolombia.id, 10000000)  # 100,000 COP

        payload = {
            "amount": 750000.0,
            "type": "income",
            "category": "Income",
            "description": "Pago de nómina parcial",
            "user_id": user_id,
            "account": "Bancolombia",
        }
        resp = api_client.post("/api/finance/transactions", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["account_name"] == "Bancolombia"

        # Verify Bancolombia balance was credited by 750,000 COP -> 850,000 COP
        updated_acc = account_service.get_account(bancolombia.id)
        assert updated_acc.balance_cents == 85000000
        assert updated_acc.balance == 850000.0

    @pytest.mark.parametrize("acc_name", ["Efectivo", "Nequi", "Nu", "Daviplata", "Bancolombia"])
    def test_all_five_colombian_accounts_can_be_selected(self, api_client, account_service, acc_name):
        user_id = f"user_{acc_name.lower()}"
        payload = {
            "amount": 25000.0,
            "type": "expense",
            "category": "Shopping",
            "description": f"Compra pagada con {acc_name}",
            "user_id": user_id,
            "account": acc_name,
        }
        resp = api_client.post("/api/finance/transactions", json=payload)
        assert resp.status_code == 201
        acc = account_service.get_account_by_name(user_id, acc_name)
        assert acc is not None
        assert acc.balance_cents == -2500000

    def test_account_name_alias_in_request_payload(self, api_client, account_service):
        """Verify both 'account' and 'account_name' fields work identically in payload."""
        user_id = "user_alias_test"
        payload = {
            "amount": 10000.0,
            "type": "expense",
            "category": "Transportation",
            "description": "Pasaje TransMilenio",
            "user_id": user_id,
            "account_name": "Nu",
        }
        resp = api_client.post("/api/finance/transactions", json=payload)
        assert resp.status_code == 201
        assert resp.json()["account_name"] == "Nu"
        acc = account_service.get_account_by_name(user_id, "Nu")
        assert acc.balance_cents == -1000000


class TestEffectiveUserResolutionAndFallback:
    """Verifies R2/R3: get_effective_user_id() resolution across transactions, summary, categories."""

    def test_fallback_to_active_telegram_user(self, api_client, memory_db, account_service):
        """When user_id is default_user, falls back to the user with active telegram_chat_id."""
        with memory_db.connection() as conn:
            conn.execute(
                "INSERT INTO users (user_id, telegram_chat_id, full_name) VALUES (?, ?, ?);",
                ("tg_samuel", 987654321, "Samuel Azuero"),
            )

        # 1. Create transaction without user_id (defaults to default_user -> should resolve to tg_samuel)
        resp = api_client.post(
            "/api/finance/transactions",
            json={
                "amount": 35000.0,
                "type": "expense",
                "category": "Groceries",
                "description": "Mercado frutas",
                "account": "Daviplata",
            },
        )
        assert resp.status_code == 201
        tx = resp.json()
        assert tx["user_id"] == "tg_samuel"
        assert tx["account_name"] == "Daviplata"

        # 2. Query /api/finance/transactions without user_id -> resolves to tg_samuel
        list_resp = api_client.get("/api/finance/transactions")
        assert list_resp.status_code == 200
        txs = list_resp.json()
        assert len(txs) == 1
        assert txs[0]["id"] == tx["id"]
        assert txs[0]["user_id"] == "tg_samuel"

        # 3. Query /api/finance/summary without user_id -> reflects the expense
        sum_resp = api_client.get("/api/finance/summary")
        assert sum_resp.status_code == 200
        summary = sum_resp.json()
        assert summary["total_expenses"] == 35000.0
        assert summary["transaction_count"] == 1

        # 4. Query /api/finance/categories without user_id -> reflects Groceries
        cat_resp = api_client.get("/api/finance/categories")
        assert cat_resp.status_code == 200
        cats = cat_resp.json()
        assert any(c["category"] == "Groceries" for c in cats)

        # 5. Query /api/finance/accounts without user_id -> reflects Daviplata debit
        acc_resp = api_client.get("/api/finance/accounts")
        assert acc_resp.status_code == 200
        accounts = acc_resp.json()["accounts"]
        davi = next(a for a in accounts if a["name"] == "Daviplata")
        assert davi["balance_cents"] == -3500000

    def test_fallback_to_user_with_transactions_when_no_telegram_user(self, api_client, memory_db):
        """When no telegram user exists, fall back to user who has existing transactions."""
        # Insert transaction under custom user
        api_client.post(
            "/api/finance/transactions",
            json={
                "amount": 12000.0,
                "type": "expense",
                "category": "Entertainment",
                "description": "Cine",
                "user_id": "usr_external_batch",
                "account": "Efectivo",
            },
        )

        # Query endpoints without user_id parameter -> should find usr_external_batch data
        list_resp = api_client.get("/api/finance/transactions")
        assert list_resp.status_code == 200
        txs = list_resp.json()
        assert len(txs) >= 1
        assert txs[0]["user_id"] == "usr_external_batch"

        sum_resp = api_client.get("/api/finance/summary")
        assert sum_resp.status_code == 200
        assert sum_resp.json()["total_expenses"] == 12000.0


    def test_effective_user_whitespace_and_empty_string_handling(self, api_client, memory_db):
        """Edge case: get_effective_user_id with whitespace or empty strings falls back to default_user safely."""
        assert get_effective_user_id(None) == "default_user"
        assert get_effective_user_id("") == "default_user"
        assert get_effective_user_id("   ") == "default_user"
        assert get_effective_user_id("custom_explicit_id") == "custom_explicit_id"

    def test_transfer_debt_subscription_fallback_to_active_telegram_user(self, api_client, memory_db, account_service):
        """Verify that transfer, debt, and subscription endpoints properly resolve active telegram user."""
        with memory_db.connection() as conn:
            conn.execute(
                "INSERT INTO users (user_id, telegram_chat_id, full_name) VALUES (?, ?, ?);",
                ("tg_samuel_fin", 11223344, "Samuel Fin"),
            )

        account_service.ensure_default_accounts("tg_samuel_fin")
        banco = account_service.get_account_by_name("tg_samuel_fin", "Bancolombia")
        account_service.set_balance(banco.id, 50000000)  # 500,000 COP

        # 1. Execute inter-account transfer without user_id -> resolves to tg_samuel_fin
        tf_resp = api_client.post(
            "/api/finance/transfers",
            json={
                "from_account": "Bancolombia",
                "to_account": "Nequi",
                "amount": 100000.0,
                "note": "Ahorro",
            },
        )
        assert tf_resp.status_code == 201

        # Check Bancolombia debited and Nequi credited for tg_samuel_fin
        accs_resp = api_client.get("/api/finance/accounts")
        assert accs_resp.status_code == 200
        accs = accs_resp.json()["accounts"]
        banco_acc = next(a for a in accs if a["name"] == "Bancolombia")
        nequi_acc = next(a for a in accs if a["name"] == "Nequi")
        assert banco_acc["balance_cents"] == 40000000
        assert nequi_acc["balance_cents"] == 10000000

        # 2. Create debt without user_id -> recorded under tg_samuel_fin
        debt_resp = api_client.post(
            "/api/finance/debts",
            json={
                "counterparty": "Carlos Gomez",
                "amount": 60000.0,
                "debt_type": "receivable",
                "reason": "Almuerzo grupal",
                "account": "Nequi",
            },
        )
        assert debt_resp.status_code == 201

        list_debts_resp = api_client.get("/api/finance/debts")
        assert list_debts_resp.status_code == 200
        debts = list_debts_resp.json()["debts"]
        assert len(debts) == 1
        assert debts[0]["user_id"] == "tg_samuel_fin"
        assert debts[0]["counterparty"] == "Carlos Gomez"

        # 3. Create subscription without user_id -> recorded under tg_samuel_fin
        sub_resp = api_client.post(
            "/api/finance/subscriptions",
            json={
                "name": "Spotify Premium",
                "amount": 16900.0,
                "billing_cycle": "monthly",
                "billing_day": 10,
                "account": "Nu",
            },
        )
        assert sub_resp.status_code == 201

        list_subs_resp = api_client.get("/api/finance/subscriptions")
        assert list_subs_resp.status_code == 200
        subs = list_subs_resp.json()["subscriptions"]
        assert len(subs) == 1
        assert subs[0]["user_id"] == "tg_samuel_fin"
        assert subs[0]["name"] == "Spotify Premium"

    def test_budget_creation_and_deletion_fallback_to_active_telegram_user(self, api_client, memory_db):
        """Verify budget creation and transaction deletion properly resolve effective user."""
        with memory_db.connection() as conn:
            conn.execute(
                "INSERT INTO users (user_id, telegram_chat_id, full_name) VALUES (?, ?, ?);",
                ("tg_samuel_budget", 55443322, "Samuel Budget"),
            )

        # 1. Create budget with default user -> resolves to tg_samuel_budget
        b_resp = api_client.post(
            "/api/finance/budgets",
            json={
                "category": "Food & Dining",
                "monthly_limit": 600000.0,
            },
        )
        assert b_resp.status_code == 201

        # Check list budgets returns budget under tg_samuel_budget
        list_b = api_client.get("/api/finance/budgets")
        assert list_b.status_code == 200
        budgets = list_b.json()
        assert len(budgets) == 1
        assert budgets[0]["user_id"] == "tg_samuel_budget"

        # 2. Record a transaction under default user (resolves to tg_samuel_budget)
        tx_resp = api_client.post(
            "/api/finance/transactions",
            json={
                "amount": 20000.0,
                "type": "expense",
                "category": "Food & Dining",
                "description": "Cena",
            },
        )
        assert tx_resp.status_code == 201
        tx_id = tx_resp.json()["id"]

        # Void transaction specifying user_id="default_user" -> resolves to tg_samuel_budget
        del_resp = api_client.delete(f"/api/finance/transactions/{tx_id}?user_id=default_user")
        assert del_resp.status_code == 200
        assert del_resp.json()["deleted"] is True


class TestWebFrontendMarkupAndScriptIntegrity:
    """Verifies R1 & R2: Static HTML & JavaScript files satisfy event isolation and account selector rules."""

    def test_index_html_has_account_selector_in_transaction_form(self):
        index_file = REPO_ROOT / "app" / "static" / "index.html"
        assert index_file.exists()
        content = index_file.read_text(encoding="utf-8")

        # Find #transaction-form and verify account selector
        tx_form_match = re.search(r'<form id="transaction-form"[^>]*>(.*?)</form>', content, re.DOTALL)
        assert tx_form_match is not None, "Expected #transaction-form in index.html"
        form_content = tx_form_match.group(1)

        assert 'name="account"' in form_content or 'id="tx-account"' in form_content
        for acc in ["Efectivo", "Nequi", "Nu", "Daviplata", "Bancolombia"]:
            assert f'value="{acc}"' in form_content, f"Expected option value='{acc}' in #transaction-form"

    def test_index_html_contains_all_six_dialog_modals(self):
        index_file = REPO_ROOT / "app" / "static" / "index.html"
        content = index_file.read_text(encoding="utf-8")
        expected_dialogs = [
            "transaction-dialog",
            "task-dialog",
            "transfer-dialog",
            "debt-dialog",
            "settle-dialog",
            "sub-dialog",
        ]
        for dialog_id in expected_dialogs:
            assert f'id="{dialog_id}"' in content, f"Missing dialog with id='{dialog_id}'"

    def test_app_js_event_target_isolation_implementation(self):
        js_file = REPO_ROOT / "app" / "static" / "js" / "app.js"
        assert js_file.exists()
        content = js_file.read_text(encoding="utf-8")

        # Must check e.target === dialog (event target isolation)
        assert "e.target === dialog" in content

        # Must not rely on buggy boundingClientRect backdrop checks
        assert "rect.top <= e.clientY" not in content
        assert "rect.left <= e.clientX" not in content

        # Must include account in POST /api/finance/transactions
        assert "payload.account" in content or "account: account" in content or "tx-account" in content

    def test_app_js_touch_scroll_and_submission_debounce(self):
        js_file = REPO_ROOT / "app" / "static" / "js" / "app.js"
        assert js_file.exists()
        content = js_file.read_text(encoding="utf-8")

        # Mobile scroll touchmove handling
        assert "touchmove" in content
        assert "touchMoved" in content

        # Keyboard / synthetic click support
        assert "e.detail === 0" in content

        # Submit button debounce & loading state
        assert "dataset.submitting" in content
        assert "Guardando..." in content

        # Client-side idempotency key generation
        assert "idempotency_key" in content

    def test_index_html_has_closedby_any_and_noscript_notice(self):
        index_file = REPO_ROOT / "app" / "static" / "index.html"
        content = index_file.read_text(encoding="utf-8")
        assert "<noscript>" in content, "Expected <noscript> banner for accessible JS-disabled environments"
        for dialog_id in [
            "transaction-dialog",
            "task-dialog",
            "transfer-dialog",
            "debt-dialog",
            "settle-dialog",
            "sub-dialog",
        ]:
            pattern = rf'<dialog[^>]*id="{dialog_id}"[^>]*closedby="any"'
            alt_pattern = rf'<dialog[^>]*closedby="any"[^>]*id="{dialog_id}"'
            assert re.search(pattern, content) or re.search(alt_pattern, content), (
                f"Expected closedby='any' on dialog id='{dialog_id}' for light-dismiss compliance"
            )

    def test_app_js_safe_dialog_helpers_for_legacy_engines(self):
        js_file = REPO_ROOT / "app" / "static" / "js" / "app.js"
        content = js_file.read_text(encoding="utf-8")
        assert "showModalSafe" in content
        assert "closeModalSafe" in content
        # Ensure showModalSafe guards against already open dialogs to prevent InvalidStateError
        assert "dialog.open" in content
        # Ensure closeModalSafe dispatches close event fallback
        assert 'dispatchEvent(new Event("close"))' in content

    def test_styles_css_contains_dialog_not_open_fallback_and_scroll_containment(self):
        css_file = REPO_ROOT / "app" / "static" / "css" / "styles.css"
        assert css_file.exists()
        content = css_file.read_text(encoding="utf-8")
        assert "dialog:not([open])" in content
        assert "display: none !important" in content
        assert "max-height: 90vh" in content

    def test_void_transaction_with_linked_account_reverses_balance(self, api_client, account_service):
        """Verify that voiding an account-linked transaction automatically restores the account balance."""
        user_id = "test_user_void_acc"
        account_service.ensure_default_accounts(user_id)
        nequi = account_service.get_account_by_name(user_id, "Nequi")
        account_service.set_balance(nequi.id, 10000000)  # 100,000 COP

        # 1. Create 40,000 COP expense linked to Nequi
        tx_resp = api_client.post(
            "/api/finance/transactions",
            json={
                "amount": 40000.0,
                "type": "expense",
                "category": "Food & Dining",
                "description": "Cena restaurante",
                "user_id": user_id,
                "account": "Nequi",
            },
        )
        assert tx_resp.status_code == 201
        tx_id = tx_resp.json()["id"]

        # Check Nequi debited -> 60,000 COP
        acc = account_service.get_account(nequi.id)
        assert acc.balance_cents == 6000000
        assert acc.balance == 60000.0

        # 2. Void the transaction
        del_resp = api_client.delete(f"/api/finance/transactions/{tx_id}?user_id={user_id}")
        assert del_resp.status_code == 200
        assert del_resp.json()["deleted"] is True

        # Check Nequi balance was restored to 100,000 COP
        acc_restored = account_service.get_account(nequi.id)
        assert acc_restored.balance_cents == 10000000
        assert acc_restored.balance == 100000.0

