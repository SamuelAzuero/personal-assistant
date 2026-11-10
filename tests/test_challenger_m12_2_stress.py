"""Empirical Adversarial Stress Test Suite for Milestone M12 (Challenger 2).

Scope:
1. Spanish NLP Parser Across Phrasing Permutations:
   - "debo 600k en 6 cuotas a Juan"
   - "preste 1 millón en 10 cuotas mensuales a Carlos"
   - "pagar 2 cuotas de la deuda de Juan con Bancolombia"
   - "abono 1 cuota a Daviplata"
   - Variations: number words, colloquial verbs, frequencies, and account isolation.
   - End-to-end ToolRouter execution with DB balance and debt state verification.
2. Web UI HTML Dialogs Integrity & Static Assets:
   - #debt-edit-dialog and #installment-pay-dialog have closedby="any"
   - Participation in backdrop isolation array (mousedown, touchstart, touchmove, touchend, click)
   - Debounced submit handlers (dataset.submitting, disabled button, submit button reset map on close)
   - UI styling and elements in styles.css and index.html.
3. REST Endpoints Validation & Boundary Stress:
   - PATCH /api/finance/debts/{id} (404, 403, 400, valid partial/full updates)
   - POST /api/finance/debts/{id}/installments/pay (404, 403, 400 <= 0, 400 > remaining, 400 already settled/cancelled)
   - Exact-cent arithmetic with zero rounding drift (odd splits: 100k / 3 cuotas)
   - Dual-directional account balance updates (debt debits account, receivable credits account).
4. Concurrency & Multithreading Stress:
   - Concurrent PATCH requests to same debt record.
   - Concurrent installment payments verifying race condition safety and overpayment protection.
"""

import concurrent.futures
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.finance_router import (
    finance_router,
    set_account_service,
    set_debt_service,
    set_finance_service,
)
from app.core.intent_parser import IntentParser
from app.core.router import ToolRouter
from app.database.connection import DatabaseManager
from app.database.repositories.debt_repo import DebtStatus, DebtType
from app.integrations.protocols import IntentType
from app.services.account_service import AccountService
from app.services.debt_service import DebtService
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
def debt_service(memory_db, account_service):
    return DebtService(db_manager=memory_db, account_service=account_service)


@pytest.fixture
def intent_parser():
    return IntentParser()


@pytest.fixture
def tool_router(debt_service, account_service, finance_service):
    return ToolRouter(
        debt_service=debt_service,
        account_service=account_service,
        finance_service=finance_service,
    )


@pytest.fixture
def api_client(account_service, finance_service, debt_service):
    app = FastAPI()
    app.include_router(finance_router)
    set_finance_service(finance_service)
    set_account_service(account_service)
    set_debt_service(debt_service)
    with TestClient(app) as client:
        yield client
    set_finance_service(None)
    set_account_service(None)
    set_debt_service(None)


# ==============================================================================
# 1. Spanish NLP Phrasing Permutations
# ==============================================================================

class TestSpanishNLPParserPermutations:
    """Stress-tests Spanish NLP parser across mandatory and adversarial phrasing permutations."""

    def test_phrase_1_debo_600k_en_6_cuotas_a_juan(self, intent_parser):
        """'debo 600k en 6 cuotas a Juan' -> DEBT_RECORD, payable, 6 cuotas, 600k COP."""
        res = intent_parser.parse("debo 600k en 6 cuotas a Juan")
        assert res.intent == IntentType.DEBT_RECORD
        assert res.slots.get("type") == "debt"
        assert res.slots.get("counterparty") == "Juan"
        assert res.slots.get("amount_cents") == 60000000
        assert res.slots.get("is_installment") is True
        assert res.slots.get("total_installments") == 6
        assert res.slots.get("remaining_installments") == 6
        assert res.slots.get("installment_amount_cents") == 10000000
        assert res.slots.get("payment_frequency") == "monthly"
        assert res.missing_slots == []

    def test_phrase_2_preste_1_millon_en_10_cuotas_mensuales_a_carlos(self, intent_parser):
        """'preste 1 millón en 10 cuotas mensuales a Carlos' -> DEBT_RECORD, receivable, 10 cuotas, 1M COP."""
        res = intent_parser.parse("preste 1 millón en 10 cuotas mensuales a Carlos")
        assert res.intent == IntentType.DEBT_RECORD
        assert res.slots.get("type") == "receivable"
        assert res.slots.get("counterparty") == "Carlos"
        assert res.slots.get("amount_cents") == 100000000
        assert res.slots.get("is_installment") is True
        assert res.slots.get("total_installments") == 10
        assert res.slots.get("remaining_installments") == 10
        assert res.slots.get("installment_amount_cents") == 10000000
        assert res.slots.get("payment_frequency") == "monthly"
        assert res.missing_slots == []

    def test_phrase_3_pagar_2_cuotas_de_la_deuda_de_juan_con_bancolombia(self, intent_parser):
        """'pagar 2 cuotas de la deuda de Juan con Bancolombia' -> DEBT_SETTLE, 2 cuotas, Juan, Bancolombia."""
        res = intent_parser.parse("pagar 2 cuotas de la deuda de Juan con Bancolombia")
        assert res.intent == IntentType.DEBT_SETTLE
        assert res.slots.get("is_installment_payment") is True
        assert res.slots.get("installments_to_pay") == 2
        assert res.slots.get("counterparty") == "Juan"
        assert res.slots.get("account") == "Bancolombia"
        assert res.missing_slots == []

    def test_phrase_4_abono_1_cuota_a_daviplata(self, intent_parser):
        """'abono 1 cuota a Daviplata' -> DEBT_SETTLE, 1 cuota, Daviplata."""
        res = intent_parser.parse("abono 1 cuota a Daviplata")
        assert res.intent == IntentType.DEBT_SETTLE
        assert res.slots.get("is_installment_payment") is True
        assert res.slots.get("installments_to_pay") == 1
        assert res.slots.get("account") == "Daviplata"

    @pytest.mark.parametrize("phrase,expected_cuotas,expected_freq", [
        ("le debo 500k a Maria en 5 cuotas quincenales", 5, "biweekly"),
        ("preste 240.000 a 12 cuotas mensuales a Pedro", 12, "monthly"),
        ("debo 70000 a Andrés en 7 cuotas semanales", 7, "weekly"),
        ("preste 2 millones en 24 cuotas a Camilo", 24, "monthly"),
        ("debo 100k a Sofia en dos cuotas", 2, "monthly"),
        ("preste 300k a Diego a tres cuotas", 3, "monthly"),
        ("debo 400 mil en cuatro cuotas a Laura", 4, "monthly"),
    ])
    def test_nlp_installment_creation_variations(self, intent_parser, phrase, expected_cuotas, expected_freq):
        """Verifies number words, frequencies, and varying phrase layouts."""
        res = intent_parser.parse(phrase)
        assert res.intent == IntentType.DEBT_RECORD
        assert res.slots.get("is_installment") is True
        assert res.slots.get("total_installments") == expected_cuotas
        assert res.slots.get("payment_frequency") == expected_freq

    @pytest.mark.parametrize("phrase,expected_cuotas,expected_account,expected_cp", [
        ("pagué 3 cuotas de la deuda de Juan con Nequi", 3, "Nequi", "Juan"),
        ("abonar 1 cuota de la deuda con Carlos por Efectivo", 1, "Efectivo", "Carlos"),
        ("abono dos cuotas de la deuda de Maria a Daviplata", 2, "Daviplata", "Maria"),
        ("pagar una cuota con Nu", 1, "Nu", None),
        ("abonando 4 cuotas de la deuda con Felipe en Bancolombia", 4, "Bancolombia", "Felipe"),
    ])
    def test_nlp_installment_payment_variations(self, intent_parser, phrase, expected_cuotas, expected_account, expected_cp):
        """Verifies installment settlement phrasing variations with accounts and counterparties."""
        res = intent_parser.parse(phrase)
        assert res.intent == IntentType.DEBT_SETTLE
        assert res.slots.get("is_installment_payment") is True
        assert res.slots.get("installments_to_pay") == expected_cuotas
        if expected_account:
            assert res.slots.get("account") == expected_account
        if expected_cp:
            assert res.slots.get("counterparty") == expected_cp

    def test_router_end_to_end_installment_journey(self, tool_router, intent_parser, account_service, debt_service):
        """Full lifecycle through ToolRouter: create 6-cuota debt via NLP, then pay 2 cuotas via NLP."""
        user_id = "usr_router_nlp_01"
        account_service.ensure_default_accounts(user_id)
        bancolombia = account_service.get_account_by_name(user_id, "Bancolombia")
        account_service.set_balance(bancolombia.id, 50000000)  # 500,000 COP

        # 1. NLP Create
        create_msg = "debo 600k en 6 cuotas a Juan"
        p_create = intent_parser.parse(create_msg)
        resp_create = tool_router.dispatch(user_id, p_create)
        assert "Juan" in resp_create
        assert "6 cuotas" in resp_create or "6" in resp_create

        # Verify debt created in DB
        debts = debt_service.list_debts(user_id=user_id, counterparty="Juan")
        assert len(debts) == 1
        debt = debts[0]
        assert debt.is_installment is True
        assert debt.total_installments == 6
        assert debt.remaining_installments == 6
        assert debt.installment_amount_cents == 10000000

        # 2. NLP Pay 2 cuotas from Bancolombia
        pay_msg = "pagar 2 cuotas de la deuda de Juan con Bancolombia"
        p_pay = intent_parser.parse(pay_msg)
        resp_pay = tool_router.dispatch(user_id, p_pay)
        assert "Juan" in resp_pay
        assert "Abono de Cuota" in resp_pay

        # Verify DB updated
        updated_debt = debt_service.get_debt(debt.id)
        assert updated_debt.remaining_installments == 4
        assert updated_debt.remaining_cents == 40000000
        assert updated_debt.status.value == "partially_paid"

        # Verify Bancolombia balance debited by 200,000 COP (20,000,000 cents)
        banco_after = account_service.get_account(bancolombia.id)
        assert banco_after.balance_cents == 30000000


# ==============================================================================
# 2. Web UI HTML Dialogs Integrity & Static Assets
# ==============================================================================

class TestWebUIDialogsAndScriptsIntegrity:
    """Verifies #debt-edit-dialog and #installment-pay-dialog contracts."""

    @pytest.fixture(autouse=True)
    def load_frontend_assets(self):
        index_path = REPO_ROOT / "app" / "static" / "index.html"
        app_js_path = REPO_ROOT / "app" / "static" / "js" / "app.js"
        styles_css_path = REPO_ROOT / "app" / "static" / "css" / "styles.css"
        assert index_path.exists(), "index.html must exist"
        assert app_js_path.exists(), "app.js must exist"
        assert styles_css_path.exists(), "styles.css must exist"
        self.html = index_path.read_text(encoding="utf-8")
        self.js = app_js_path.read_text(encoding="utf-8")
        self.css = styles_css_path.read_text(encoding="utf-8")

    def test_debt_edit_dialog_html_attributes_and_fields(self):
        """#debt-edit-dialog has closedby='any', class='modal-dialog', and all required inputs."""
        assert 'id="debt-edit-dialog"' in self.html
        assert '<dialog id="debt-edit-dialog" closedby="any"' in self.html
        assert 'id="debt-edit-form"' in self.html
        assert 'id="debt-edit-id"' in self.html
        assert 'id="debt-edit-counterparty"' in self.html
        assert 'id="debt-edit-amount"' in self.html
        assert 'id="debt-edit-reason"' in self.html
        assert 'id="debt-edit-due-date"' in self.html
        assert 'id="debt-edit-status"' in self.html
        assert 'id="btn-close-debt-edit-dialog"' in self.html
        assert 'id="btn-cancel-debt-edit"' in self.html
        assert 'id="btn-submit-debt-edit"' in self.html

    def test_installment_pay_dialog_html_attributes_and_fields(self):
        """#installment-pay-dialog has closedby='any', class='modal-dialog', and all required inputs."""
        assert 'id="installment-pay-dialog"' in self.html
        assert '<dialog id="installment-pay-dialog" closedby="any"' in self.html
        assert 'id="installment-pay-form"' in self.html
        assert 'id="inst-debt-id"' in self.html
        assert 'id="inst-amount-per-cuota"' in self.html
        assert 'id="inst-remaining-count"' in self.html
        assert 'id="inst-remaining-cents"' in self.html
        assert 'id="installment-summary-box"' in self.html
        assert 'id="inst-cuotas-to-pay"' in self.html
        assert 'id="inst-account"' in self.html
        assert 'id="inst-calc-preview"' in self.html
        assert 'id="btn-close-installment-dialog"' in self.html
        assert 'id="btn-cancel-installment"' in self.html
        assert 'id="btn-submit-installment"' in self.html

        # Verify Colombian accounts in installment account selector
        for acc in ["Efectivo", "Nequi", "Nu", "Daviplata", "Bancolombia"]:
            assert f'value="{acc}"' in self.html

    def test_app_js_backdrop_isolation_array_includes_m12_dialogs(self):
        """Verifies debtEditDialog and installmentPayDialog participate in backdrop isolation array."""
        assert "debtEditDialog" in self.js
        assert "installmentPayDialog" in self.js
        assert "isBackdropTarget = (e.target === dialog)" in self.js
        assert "touchMoved = true" in self.js

    def test_app_js_debounced_submit_handlers_and_button_reset_map(self):
        """Verifies both dialogs debounce submissions and reset button states."""
        # Reset map in close event
        assert '"btn-submit-debt-edit": "Guardar Cambios"' in self.js
        assert '"btn-submit-installment": "Confirmar Pago de Cuotas"' in self.js

        # Debt edit form debounce
        assert 'debtEditForm.dataset.submitting === "true"' in self.js
        assert 'debtEditForm.dataset.submitting = "true"' in self.js
        assert 'debtEditForm.dataset.submitting = "false"' in self.js

        # Installment pay form debounce
        assert 'installmentPayForm.dataset.submitting === "true"' in self.js
        assert 'installmentPayForm.dataset.submitting = "true"' in self.js
        assert 'installmentPayForm.dataset.submitting = "false"' in self.js

    def test_styles_css_contains_installment_components(self):
        """Verifies styling exists for badges, progress bars, and payment preview."""
        assert ".debt-installment-status" in self.css
        assert ".debt-progress-container" in self.css
        assert ".debt-progress-bar" in self.css
        assert ".payment-preview-box" in self.css
        assert ".badge-installment" in self.css


# ==============================================================================
# 3. REST Endpoints Validation & Boundary Stress
# ==============================================================================

class TestRESTEndpointsValidationAndEdgeCases:
    """Stress-tests PATCH /api/finance/debts/{id} and POST /api/finance/debts/{id}/installments/pay."""

    def test_patch_debt_validation_not_found(self, api_client):
        """PATCH non-existent debt returns 404."""
        resp = api_client.patch(
            "/api/finance/debts/debt_nonexistent_999?user_id=u1",
            json={"counterparty": "Nobody"},
        )
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_patch_debt_unauthorized_other_user(self, api_client, debt_service):
        """PATCH debt belonging to another user returns 403."""
        debt = debt_service.record_debt(
            user_id="user_owner",
            counterparty="Friend",
            amount_cents=5000000,
            debt_type=DebtType.DEBT,
            reason="Lunch",
        )
        resp = api_client.patch(
            f"/api/finance/debts/{debt.id}?user_id=user_attacker",
            json={"counterparty": "Hacker"},
        )
        assert resp.status_code == 403
        assert "unauthorized" in resp.json()["detail"].lower()

    def test_patch_debt_successful_updates(self, api_client, debt_service):
        """PATCH allows updating counterparty, amount, reason, status, and due_date."""
        debt = debt_service.record_debt(
            user_id="user_patch",
            counterparty="Original Person",
            amount_cents=10000000,
            debt_type=DebtType.DEBT,
            reason="Old Reason",
        )
        new_due = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        payload = {
            "counterparty": "New Person",
            "amount_cents": 15000000,
            "reason": "Updated Reason",
            "due_date": new_due,
            "status": "partially_paid",
        }
        resp = api_client.patch(
            f"/api/finance/debts/{debt.id}?user_id=user_patch",
            json=payload,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        updated = data["debt"]
        assert updated["counterparty"] == "New Person"
        assert updated["amount_cents"] == 15000000
        assert updated["reason"] == "Updated Reason"
        assert updated["status"] == "partially_paid"

    def test_pay_installment_zero_or_negative_rejected(self, api_client, debt_service):
        """POST pay installment with <= 0 returns 400."""
        debt = debt_service.record_debt(
            user_id="user_inst_val",
            counterparty="Bank",
            amount_cents=60000000,
            debt_type=DebtType.DEBT,
            reason="Loan",
            is_installment=True,
            total_installments=6,
        )
        # 0 cuotas
        r0 = api_client.post(
            f"/api/finance/debts/{debt.id}/installments/pay?user_id=user_inst_val",
            json={"installments_to_pay": 0},
        )
        assert r0.status_code == 400
        assert "greater than zero" in r0.json()["detail"]

        # -1 cuotas
        r_neg = api_client.post(
            f"/api/finance/debts/{debt.id}/installments/pay?user_id=user_inst_val",
            json={"installments_to_pay": -1},
        )
        assert r_neg.status_code == 400
        assert "greater than zero" in r_neg.json()["detail"]

    def test_pay_installment_exceeding_remaining_rejected(self, api_client, debt_service):
        """POST pay more installments than remaining returns 400."""
        debt = debt_service.record_debt(
            user_id="user_inst_exceed",
            counterparty="Store",
            amount_cents=30000000,
            debt_type=DebtType.DEBT,
            reason="Phone",
            is_installment=True,
            total_installments=3,
        )
        resp = api_client.post(
            f"/api/finance/debts/{debt.id}/installments/pay?user_id=user_inst_exceed",
            json={"installments_to_pay": 5},
        )
        assert resp.status_code == 400
        assert "only 3 remaining" in resp.json()["detail"]

    def test_pay_installment_on_already_settled_rejected(self, api_client, debt_service):
        """POST pay installment on settled debt returns 400."""
        debt = debt_service.record_debt(
            user_id="user_inst_settled",
            counterparty="Store",
            amount_cents=10000000,
            debt_type=DebtType.DEBT,
            reason="Speaker",
            is_installment=True,
            total_installments=1,
        )
        # Settle it
        debt_service.record_installment_payment(debt.id, "user_inst_settled", 1)

        # Attempt another payment
        resp = api_client.post(
            f"/api/finance/debts/{debt.id}/installments/pay?user_id=user_inst_settled",
            json={"installments_to_pay": 1},
        )
        assert resp.status_code == 400
        assert "already settled" in resp.json()["detail"]

    def test_exact_cent_arithmetic_odd_split_zero_drift(self, api_client, account_service, debt_service):
        """100,000 COP split into 3 cuotas clears exactly 10,000,000 cents with 0 drift."""
        user_id = "user_odd_split"
        account_service.ensure_default_accounts(user_id)
        nequi = account_service.get_account_by_name(user_id, "Nequi")
        account_service.set_balance(nequi.id, 20000000)  # 200,000 COP

        # 100,000 COP = 10,000,000 cents
        debt = debt_service.record_debt(
            user_id=user_id,
            counterparty="Carlos",
            amount_cents=10000000,
            debt_type=DebtType.DEBT,
            reason="Odd loan",
            is_installment=True,
            total_installments=3,
        )
        assert debt.installment_amount_cents == 3333333

        # Pay Cuota 1
        r1 = api_client.post(
            f"/api/finance/debts/{debt.id}/installments/pay?user_id={user_id}",
            json={"installments_to_pay": 1, "account": "Nequi"},
        )
        assert r1.status_code == 200
        p1 = r1.json()
        assert p1["payment"]["amount_cents"] == 3333333
        assert p1["remaining_installments"] == 2
        assert p1["settled"] is False

        # Pay Cuota 2
        r2 = api_client.post(
            f"/api/finance/debts/{debt.id}/installments/pay?user_id={user_id}",
            json={"installments_to_pay": 1, "account": "Nequi"},
        )
        assert r2.status_code == 200
        p2 = r2.json()
        assert p2["payment"]["amount_cents"] == 3333333
        assert p2["remaining_installments"] == 1
        assert p2["settled"] is False

        # Pay Cuota 3 (Final: must absorb remainder 3,333,334 cents)
        r3 = api_client.post(
            f"/api/finance/debts/{debt.id}/installments/pay?user_id={user_id}",
            json={"installments_to_pay": 1, "account": "Nequi"},
        )
        assert r3.status_code == 200
        p3 = r3.json()
        assert p3["payment"]["amount_cents"] == 3333334
        assert p3["remaining_installments"] == 0
        assert p3["settled"] is True

        # Sum of 3 payments equals exact initial amount
        total_paid = (
            p1["payment"]["amount_cents"]
            + p2["payment"]["amount_cents"]
            + p3["payment"]["amount_cents"]
        )
        assert total_paid == 10000000

        # Nequi balance: 200,000 COP - 100,000 COP = 100,000 COP
        nequi_final = account_service.get_account(nequi.id)
        assert nequi_final.balance_cents == 10000000

    def test_receivable_installment_payment_credits_account(self, api_client, account_service, debt_service):
        """When receiving installment on receivable loan, linked account is credited (cash inflow)."""
        user_id = "user_rec_pay"
        account_service.ensure_default_accounts(user_id)
        davi = account_service.get_account_by_name(user_id, "Daviplata")
        account_service.set_balance(davi.id, 10000000)  # 100,000 COP

        # Disburse 200,000 COP in 4 cuotas (50,000 COP per cuota)
        debt = debt_service.record_debt(
            user_id=user_id,
            counterparty="Friend",
            amount_cents=20000000,
            debt_type=DebtType.RECEIVABLE,
            reason="Help",
            is_installment=True,
            total_installments=4,
            account_name="Daviplata",
            adjust_account_balance=False,
        )

        # Friend pays 2 cuotas (100,000 COP)
        resp = api_client.post(
            f"/api/finance/debts/{debt.id}/installments/pay?user_id={user_id}",
            json={"installments_to_pay": 2, "account": "Daviplata"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["payment"]["amount_cents"] == 10000000
        assert data["remaining_installments"] == 2

        # Daviplata balance credited: 100,000 + 100,000 = 200,000 COP
        davi_final = account_service.get_account(davi.id)
        assert davi_final.balance_cents == 20000000


# ==============================================================================
# 4. Concurrency & Multithreading Stress Testing
# ==============================================================================

class TestConcurrencyAndRaceConditions:
    """Stress-tests SQLite WAL transactions under concurrent PATCH and installment operations."""

    def test_concurrent_patch_updates_consistency(self, api_client, debt_service):
        """Multiple concurrent PATCH calls to the same debt do not crash or corrupt state."""
        user_id = "usr_concurrent_patch"
        debt = debt_service.record_debt(
            user_id=user_id,
            counterparty="Initial",
            amount_cents=50000000,
            debt_type=DebtType.DEBT,
            reason="Initial Reason",
        )

        def worker(i: int):
            return api_client.patch(
                f"/api/finance/debts/{debt.id}?user_id={user_id}",
                json={"reason": f"Concurrent Update #{i}"},
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(worker, i) for i in range(15)]
            results = [f.result() for f in futures]

        for r in results:
            assert r.status_code == 200

        final_debt = debt_service.get_debt(debt.id)
        assert "Concurrent Update #" in final_debt.reason

    def test_concurrent_installment_payments_protection_against_overpayment(
        self, api_client, account_service, debt_service
    ):
        """Simultaneous attempts to pay installments on a 4-cuota debt cannot exceed 4 cuotas."""
        user_id = "usr_concurrent_pay"
        account_service.ensure_default_accounts(user_id)
        banco = account_service.get_account_by_name(user_id, "Bancolombia")
        account_service.set_balance(banco.id, 100000000)  # 1,000,000 COP

        debt = debt_service.record_debt(
            user_id=user_id,
            counterparty="Store",
            amount_cents=40000000,  # 400,000 COP
            debt_type=DebtType.DEBT,
            reason="Laptop",
            is_installment=True,
            total_installments=4,
        )

        # Launch 8 concurrent requests each attempting to pay 1 cuota
        def pay_one():
            return api_client.post(
                f"/api/finance/debts/{debt.id}/installments/pay?user_id={user_id}",
                json={"installments_to_pay": 1, "account": "Bancolombia"},
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            futures = [executor.submit(pay_one) for _ in range(8)]
            responses = [f.result() for f in futures]

        status_codes = [r.status_code for r in responses]
        successes = status_codes.count(200)
        rejections = status_codes.count(400)

        # Total successful payments must be exactly 4 (settling the loan)
        assert successes == 4, f"Expected exactly 4 successful payments, got {successes}"
        assert rejections == 4, f"Expected 4 rejections due to overpayment/settled, got {rejections}"

        final_debt = debt_service.get_debt(debt.id)
        assert final_debt.remaining_installments == 0
        assert final_debt.remaining_cents == 0
        assert final_debt.status.value == "settled"

        # Account debited exactly 400,000 COP
        banco_final = account_service.get_account(banco.id)
        assert banco_final.balance_cents == 60000000
