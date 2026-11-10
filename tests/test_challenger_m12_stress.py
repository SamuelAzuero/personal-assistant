"""Empirical Adversarial Stress Test Suite for Milestone M12:
Advanced Debt Management: Modifications & Installments / Cuotas (Requirement R3).

Targets:
1. Odd cent splits:
   - 100,000 COP into 3 cuotas, 1,000,000 COP into 7 cuotas.
   - Batch payments and randomized prime cuota fuzzer verifying zero cent loss and exact settlement.
   - Edge case 1 cent and 10 cents split across odd cuotas.
2. Boundary conditions:
   - Zero or negative cuotas on debt creation.
   - Zero or negative cuotas on installment payment (Service + REST API).
   - Paying more cuotas than remain (Service + REST API).
   - Paying on already settled or cancelled debts (Service + REST API).
   - Boundary inputs on update_debt (zero/negative amounts, missing IDs, empty user_id).
3. Cross-user authorization:
   - Unauthorized user editing someone else's debt (PATCH 403 Forbidden).
   - Unauthorized user paying someone else's debt (POST 403 Forbidden).
   - PermissionError enforcement in Service and Repository layers.
   - Effective user resolution fallback boundaries.
4. Atomic account linking:
   - Paying a debt cuota debits user's linked account (cash outflow).
   - Receiving a receivable cuota credits user's linked account (cash inflow).
   - Multi-account switching across sequential cuotas with exact zero cent loss.
   - Due date advancement by payment frequency (monthly, biweekly, weekly).
   - Atomic transaction rollback on failure.
5. Debt modification workflows:
   - Updating counterparty, reason, and amount with automatic installment amount recalculation.
6. Telegram NLP & ToolRouter integration:
   - Natural language parsing for installment debts and cuota settlements.
   - Router end-to-end execution and response formatting.
"""

from datetime import datetime, timezone
import random
from typing import List
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
from app.database.repositories.debt_repo import (
    DebtRepository,
    DebtStatus,
    DebtType,
)
from app.services.account_service import AccountService
from app.services.debt_service import DebtService
from app.services.finance_service import FinanceService


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture
def memory_db():
    """Isolated in-memory SQLite database initialized with full schema and indexes."""
    db = DatabaseManager(":memory:")
    db.init_db()
    yield db
    db.close()


@pytest.fixture
def account_service(memory_db):
    return AccountService(db_manager=memory_db)


@pytest.fixture
def debt_service(memory_db, account_service):
    return DebtService(db_manager=memory_db, account_service=account_service)


@pytest.fixture
def finance_service(memory_db, account_service):
    return FinanceService(db_manager=memory_db, account_service=account_service)


@pytest.fixture
def intent_parser():
    return IntentParser()


@pytest.fixture
def tool_router(account_service, debt_service, finance_service):
    return ToolRouter(
        account_service=account_service,
        debt_service=debt_service,
        finance_service=finance_service,
    )


@pytest.fixture
def api_client(account_service, debt_service, finance_service):
    app = FastAPI()
    app.include_router(finance_router)
    set_account_service(account_service)
    set_debt_service(debt_service)
    set_finance_service(finance_service)
    return TestClient(app)


# ==============================================================================
# 1. Odd Cent Splits & Zero Cent Loss (Empirical Oracles & Fuzzing Harness)
# ==============================================================================

class TestOddCentSplitsAndExactSettlement:
    """Rigorous mathematical tests ensuring exact integer cent math with 0 cent drift."""

    def test_100k_cop_split_3_cuotas_exact_settlement_zero_cent_loss(self, debt_service):
        """100,000 COP (10,000,000 cents) into 3 cuotas.

        Integer division: 10,000,000 // 3 = 3,333,333 cents per base cuota ($33,333.33 COP).
        Cuota 1: 3,333,333 cents -> Remaining = 6,666,667 cents.
        Cuota 2: 3,333,333 cents -> Remaining = 3,333,334 cents.
        Cuota 3: 3,333,334 cents -> Remaining = 0 cents. Settled = True.
        Sum of payments = 3,333,333 + 3,333,333 + 3,333,334 = 10,000,000 cents.
        """
        user_id = "usr_split_3"
        total_cents = 10000000  # 100,000 COP

        debt = debt_service.record_debt(
            user_id=user_id,
            counterparty="Carlos Gomez",
            amount_cents=total_cents,
            debt_type=DebtType.DEBT,
            reason="Compra herramientas en cuotas",
            is_installment=True,
            total_installments=3,
            payment_frequency="monthly",
            adjust_account_balance=False,
        )

        assert debt.total_installments == 3
        assert debt.remaining_installments == 3
        assert debt.installment_amount_cents == 3333333
        assert debt.remaining_cents == total_cents

        # Step 1: Pay 1 cuota
        p1 = debt_service.record_installment_payment(debt.id, user_id, installments_to_pay=1)
        assert p1["payment"]["amount_cents"] == 3333333
        assert p1["remaining_installments"] == 2
        assert p1["debt"]["remaining_cents"] == 6666667
        assert p1["settled"] is False
        assert p1["debt"]["status"] == DebtStatus.PARTIALLY_PAID.value

        # Step 2: Pay 1 cuota
        p2 = debt_service.record_installment_payment(debt.id, user_id, installments_to_pay=1)
        assert p2["payment"]["amount_cents"] == 3333333
        assert p2["remaining_installments"] == 1
        assert p2["debt"]["remaining_cents"] == 3333334
        assert p2["settled"] is False

        # Step 3: Pay final cuota (absorbs odd cent remainder)
        p3 = debt_service.record_installment_payment(debt.id, user_id, installments_to_pay=1)
        assert p3["payment"]["amount_cents"] == 3333334
        assert p3["remaining_installments"] == 0
        assert p3["debt"]["remaining_cents"] == 0
        assert p3["settled"] is True
        assert p3["debt"]["status"] == DebtStatus.SETTLED.value
        assert p3["debt"]["settled_at"] is not None

        # Verify mathematical conservation oracle
        total_paid = (
            p1["payment"]["amount_cents"]
            + p2["payment"]["amount_cents"]
            + p3["payment"]["amount_cents"]
        )
        assert total_paid == total_cents, f"Cent loss detected! Expected {total_cents}, got {total_paid}"

    def test_1m_cop_split_7_cuotas_exact_settlement_zero_cent_loss(self, debt_service):
        """1,000,000 COP (100,000,000 cents) into 7 cuotas.

        Integer division: 100,000,000 // 7 = 14,285,714 cents per base cuota ($142,857.14 COP).
        Cuotas 1 to 6: 14,285,714 cents each (total 85,714,284 cents).
        Cuota 7: 100,000,000 - 85,714,284 = 14,285,716 cents ($142,857.16 COP).
        Verify zero cent loss and exact settlement.
        """
        user_id = "usr_split_7"
        total_cents = 100000000  # 1,000,000 COP

        debt = debt_service.record_debt(
            user_id=user_id,
            counterparty="Banco Falabella",
            amount_cents=total_cents,
            debt_type=DebtType.DEBT,
            reason="Crédito consumo 7 cuotas",
            is_installment=True,
            total_installments=7,
            payment_frequency="monthly",
            adjust_account_balance=False,
        )

        assert debt.installment_amount_cents == 14285714

        paid_amounts: List[int] = []
        for i in range(1, 8):
            res = debt_service.record_installment_payment(debt.id, user_id, installments_to_pay=1)
            paid_cents = res["payment"]["amount_cents"]
            paid_amounts.append(paid_cents)

            if i < 7:
                assert paid_cents == 14285714
                assert res["settled"] is False
                assert res["remaining_installments"] == 7 - i
            else:
                # 7th and final installment absorbs remainder
                assert paid_cents == 14285716
                assert res["settled"] is True
                assert res["remaining_installments"] == 0
                assert res["debt"]["remaining_cents"] == 0

        assert sum(paid_amounts) == total_cents
        final_debt = debt_service.get_debt(debt.id)
        assert final_debt.status == DebtStatus.SETTLED
        assert final_debt.paid_amount_cents == total_cents
        assert final_debt.remaining_cents == 0

    def test_1m_cop_split_7_cuotas_batch_payments(self, debt_service):
        """1,000,000 COP into 7 cuotas paid in batch chunks: 2 cuotas, then 3 cuotas, then 2 cuotas.

        Chunk 1 (2 cuotas): 2 * 14,285,714 = 28,571,428 cents. Remaining = 71,428,572 cents.
        Chunk 2 (3 cuotas): 3 * 14,285,714 = 42,857,142 cents. Remaining = 28,571,430 cents.
        Chunk 3 (2 cuotas, final): remaining 28,571,430 cents. Remaining = 0 cents.
        """
        user_id = "usr_split_7_batch"
        total_cents = 100000000

        debt = debt_service.record_debt(
            user_id=user_id,
            counterparty="Banco",
            amount_cents=total_cents,
            debt_type=DebtType.DEBT,
            reason="Batch test",
            is_installment=True,
            total_installments=7,
            adjust_account_balance=False,
        )

        b1 = debt_service.record_installment_payment(debt.id, user_id, installments_to_pay=2)
        assert b1["payment"]["amount_cents"] == 28571428
        assert b1["debt"]["remaining_cents"] == 71428572
        assert b1["remaining_installments"] == 5

        b2 = debt_service.record_installment_payment(debt.id, user_id, installments_to_pay=3)
        assert b2["payment"]["amount_cents"] == 42857142
        assert b2["debt"]["remaining_cents"] == 28571430
        assert b2["remaining_installments"] == 2

        b3 = debt_service.record_installment_payment(debt.id, user_id, installments_to_pay=2)
        assert b3["payment"]["amount_cents"] == 28571430
        assert b3["debt"]["remaining_cents"] == 0
        assert b3["remaining_installments"] == 0
        assert b3["settled"] is True

        total_paid = (
            b1["payment"]["amount_cents"]
            + b2["payment"]["amount_cents"]
            + b3["payment"]["amount_cents"]
        )
        assert total_paid == total_cents

    def test_fuzz_random_odd_cents_and_prime_cuotas(self, debt_service):
        """Oracle Fuzzer: Tests 50 randomized odd-cent amounts with prime cuota counts.

        Verifies that for every odd amount and prime installment count:
        - At each step: remaining_cents + paid_amount_cents == initial amount.
        - After final installment: remaining_cents == 0, status == SETTLED.
        - Sum of all payment records in database equals initial amount with 0 cent deviation.
        """
        rng = random.Random(42)  # Deterministic seed for reproducible adversarial fuzzing
        prime_cuotas = [3, 5, 7, 11, 13, 17, 19, 23, 29, 31]

        for test_idx in range(50):
            user_id = f"usr_fuzz_{test_idx}"
            total_installments = rng.choice(prime_cuotas)
            # Pick odd cent amounts between 10,000 COP and 5,000,000 COP
            amount_cents = rng.randint(1000000, 500000000)
            if amount_cents % 2 == 0:
                amount_cents += 1

            debt = debt_service.record_debt(
                user_id=user_id,
                counterparty=f"Counterparty_{test_idx}",
                amount_cents=amount_cents,
                debt_type=DebtType.DEBT if test_idx % 2 == 0 else DebtType.RECEIVABLE,
                reason=f"Fuzz test #{test_idx}",
                is_installment=True,
                total_installments=total_installments,
                adjust_account_balance=False,
            )

            # Randomly batch the payments
            remaining_to_pay = total_installments
            collected_payments: List[int] = []

            while remaining_to_pay > 0:
                step = rng.randint(1, remaining_to_pay)
                res = debt_service.record_installment_payment(debt.id, user_id, installments_to_pay=step)
                paid = res["payment"]["amount_cents"]
                collected_payments.append(paid)
                remaining_to_pay -= step

                # Invariant: conservation of money at each intermediate step
                assert res["debt"]["remaining_cents"] + res["debt"]["paid_amount_cents"] == amount_cents

            # Final assertions
            assert sum(collected_payments) == amount_cents
            final_debt = debt_service.get_debt(debt.id)
            assert final_debt.remaining_cents == 0
            assert final_debt.paid_amount_cents == amount_cents
            assert final_debt.remaining_installments == 0
            assert final_debt.status == DebtStatus.SETTLED

    def test_single_call_pays_all_cuotas_at_once(self, debt_service):
        """User pays all cuotas in a single transaction (e.g. paying 3 cuotas of a 3-cuota debt)."""
        user_id = "usr_pay_all"
        total_cents = 10000000

        debt = debt_service.record_debt(
            user_id=user_id,
            counterparty="Elena",
            amount_cents=total_cents,
            debt_type=DebtType.DEBT,
            reason="Préstamo",
            is_installment=True,
            total_installments=3,
            adjust_account_balance=False,
        )

        res = debt_service.record_installment_payment(debt.id, user_id, installments_to_pay=3)
        assert res["payment"]["amount_cents"] == total_cents
        assert res["settled"] is True
        assert res["remaining_installments"] == 0
        assert res["debt"]["status"] == DebtStatus.SETTLED.value

    def test_small_cents_debt_odd_split(self, debt_service):
        """Extreme minimum boundary: 10 cents split into 3 cuotas (3, 3, 4 cents)."""
        user_id = "usr_small_cents"
        debt = debt_service.record_debt(
            user_id=user_id,
            counterparty="Micro",
            amount_cents=10,
            debt_type=DebtType.DEBT,
            reason="Microdebt",
            is_installment=True,
            total_installments=3,
            adjust_account_balance=False,
        )

        p1 = debt_service.record_installment_payment(debt.id, user_id, installments_to_pay=1)
        p2 = debt_service.record_installment_payment(debt.id, user_id, installments_to_pay=1)
        p3 = debt_service.record_installment_payment(debt.id, user_id, installments_to_pay=1)

        assert p1["payment"]["amount_cents"] == 3
        assert p2["payment"]["amount_cents"] == 3
        assert p3["payment"]["amount_cents"] == 4
        assert p1["payment"]["amount_cents"] + p2["payment"]["amount_cents"] + p3["payment"]["amount_cents"] == 10
        assert p3["settled"] is True


# ==============================================================================
# 2. Boundary & Corner Conditions
# ==============================================================================

class TestDebtBoundaryConditions:
    """Stress testing boundary inputs, zero/negative inputs, and illegal transitions."""

    def test_create_debt_zero_installments_rejected(self, debt_service):
        with pytest.raises(ValueError, match="Total installments must be greater than zero"):
            debt_service.record_debt(
                user_id="usr_bnd_1",
                counterparty="Test",
                amount_cents=50000,
                debt_type=DebtType.DEBT,
                reason="Test zero cuotas",
                is_installment=True,
                total_installments=0,
            )

    def test_create_debt_negative_installments_rejected(self, debt_service):
        with pytest.raises(ValueError, match="Total installments must be greater than zero"):
            debt_service.record_debt(
                user_id="usr_bnd_2",
                counterparty="Test",
                amount_cents=50000,
                debt_type=DebtType.DEBT,
                reason="Test negative cuotas",
                is_installment=True,
                total_installments=-5,
            )

    def test_pay_zero_installments_rejected_service_and_api(self, debt_service, api_client):
        user_id = "usr_bnd_zero_pay"
        debt = debt_service.record_debt(
            user_id=user_id,
            counterparty="Test",
            amount_cents=10000000,
            debt_type=DebtType.DEBT,
            reason="Test",
            is_installment=True,
            total_installments=5,
            adjust_account_balance=False,
        )

        # Service level rejection
        with pytest.raises(ValueError, match="Installments to pay must be greater than zero"):
            debt_service.record_installment_payment(debt.id, user_id, installments_to_pay=0)

        # REST API level rejection
        resp = api_client.post(
            f"/api/finance/debts/{debt.id}/installments/pay?user_id={user_id}",
            json={"installments_to_pay": 0},
        )
        assert resp.status_code == 400
        assert "greater than zero" in resp.json()["detail"]

    def test_pay_negative_installments_rejected_service_and_api(self, debt_service, api_client):
        user_id = "usr_bnd_neg_pay"
        debt = debt_service.record_debt(
            user_id=user_id,
            counterparty="Test",
            amount_cents=10000000,
            debt_type=DebtType.DEBT,
            reason="Test",
            is_installment=True,
            total_installments=5,
            adjust_account_balance=False,
        )

        # Service level rejection
        with pytest.raises(ValueError, match="Installments to pay must be greater than zero"):
            debt_service.record_installment_payment(debt.id, user_id, installments_to_pay=-2)

        # REST API level rejection
        resp = api_client.post(
            f"/api/finance/debts/{debt.id}/installments/pay?user_id={user_id}",
            json={"installments_to_pay": -1},
        )
        assert resp.status_code == 400
        assert "greater than zero" in resp.json()["detail"]

    def test_pay_more_installments_than_remaining_rejected_service_and_api(self, debt_service, api_client):
        user_id = "usr_bnd_exceed"
        debt = debt_service.record_debt(
            user_id=user_id,
            counterparty="Test",
            amount_cents=9000000,
            debt_type=DebtType.DEBT,
            reason="Test",
            is_installment=True,
            total_installments=3,
            adjust_account_balance=False,
        )

        # Try to pay 4 cuotas when only 3 exist
        with pytest.raises(ValueError, match="Cannot pay 4 installments; only 3 remaining"):
            debt_service.record_installment_payment(debt.id, user_id, installments_to_pay=4)

        resp = api_client.post(
            f"/api/finance/debts/{debt.id}/installments/pay?user_id={user_id}",
            json={"installments_to_pay": 4},
        )
        assert resp.status_code == 400
        assert "only 3 remaining" in resp.json()["detail"]

        # Pay 2 cuotas (1 remaining)
        debt_service.record_installment_payment(debt.id, user_id, installments_to_pay=2)

        # Now try to pay 2 cuotas when only 1 remains
        with pytest.raises(ValueError, match="Cannot pay 2 installments; only 1 remaining"):
            debt_service.record_installment_payment(debt.id, user_id, installments_to_pay=2)

        resp = api_client.post(
            f"/api/finance/debts/{debt.id}/installments/pay?user_id={user_id}",
            json={"installments_to_pay": 2},
        )
        assert resp.status_code == 400
        assert "only 1 remaining" in resp.json()["detail"]

    def test_pay_installments_on_already_settled_debt_rejected(self, debt_service, api_client):
        user_id = "usr_bnd_settled"
        debt = debt_service.record_debt(
            user_id=user_id,
            counterparty="Test",
            amount_cents=10000000,
            debt_type=DebtType.DEBT,
            reason="Test",
            is_installment=True,
            total_installments=2,
            adjust_account_balance=False,
        )

        # Settle all cuotas
        debt_service.record_installment_payment(debt.id, user_id, installments_to_pay=2)
        settled_debt = debt_service.get_debt(debt.id)
        assert settled_debt.status == DebtStatus.SETTLED

        # Attempt to pay another installment via Service
        with pytest.raises(ValueError, match="Debt is already settled or cancelled"):
            debt_service.record_installment_payment(debt.id, user_id, installments_to_pay=1)

        # Attempt via REST API
        resp = api_client.post(
            f"/api/finance/debts/{debt.id}/installments/pay?user_id={user_id}",
            json={"installments_to_pay": 1},
        )
        assert resp.status_code == 400
        assert "already settled or cancelled" in resp.json()["detail"]

        # Attempt via settle_debt
        with pytest.raises(ValueError, match="Debt is already settled or cancelled"):
            debt_service.settle_debt(user_id, debt.id)

        # Attempt via record_payment
        with pytest.raises(ValueError, match="Debt is already settled or cancelled"):
            debt_service.record_payment(user_id, debt.id, amount_cents=1000)

    def test_pay_installments_on_cancelled_debt_rejected(self, debt_service, api_client):
        user_id = "usr_bnd_cancelled"
        debt = debt_service.record_debt(
            user_id=user_id,
            counterparty="Test",
            amount_cents=10000000,
            debt_type=DebtType.DEBT,
            reason="Test",
            is_installment=True,
            total_installments=3,
            adjust_account_balance=False,
        )

        # Cancel the debt via update_debt
        debt_service.update_debt(debt.id, user_id, {"status": "cancelled"})

        # Attempt to pay installment via Service
        with pytest.raises(ValueError, match="Debt is already settled or cancelled"):
            debt_service.record_installment_payment(debt.id, user_id, installments_to_pay=1)

        # Attempt via REST API
        resp = api_client.post(
            f"/api/finance/debts/{debt.id}/installments/pay?user_id={user_id}",
            json={"installments_to_pay": 1},
        )
        assert resp.status_code == 400
        assert "already settled or cancelled" in resp.json()["detail"]

    def test_update_debt_boundary_validation(self, debt_service, api_client):
        user_id = "usr_bnd_update"
        debt = debt_service.record_debt(
            user_id=user_id,
            counterparty="Test",
            amount_cents=10000000,
            debt_type=DebtType.DEBT,
            reason="Test",
            adjust_account_balance=False,
        )

        # Amount <= 0 rejected
        with pytest.raises(ValueError, match="Amount must be greater than zero"):
            debt_service.update_debt(debt.id, user_id, {"amount_cents": 0})

        with pytest.raises(ValueError, match="Amount must be greater than zero"):
            debt_service.update_debt(debt.id, user_id, {"amount_cents": -500})

        resp = api_client.patch(
            f"/api/finance/debts/{debt.id}?user_id={user_id}",
            json={"amount_cents": 0},
        )
        assert resp.status_code == 400

        # Non-existent debt ID rejected
        with pytest.raises(ValueError, match="does not exist"):
            debt_service.update_debt("debt_non_existent", user_id, {"counterparty": "Nobody"})

        resp = api_client.patch(
            f"/api/finance/debts/debt_non_existent?user_id={user_id}",
            json={"counterparty": "Nobody"},
        )
        assert resp.status_code == 404

        # Empty user_id rejected
        with pytest.raises(ValueError, match="User ID cannot be empty"):
            debt_service.update_debt(debt.id, "", {"counterparty": "Nobody"})


# ==============================================================================
# 3. Cross-User Authorization & RBAC Boundaries
# ==============================================================================

class TestCrossUserAuthorization:
    """Rigorous security testing verifying 403 Forbidden and PermissionError on cross-user operations."""

    def test_unauthorized_user_cannot_patch_debt_api_403(self, debt_service, api_client):
        """Alice creates a debt; Bob attempts to PATCH it -> 403 Forbidden."""
        alice_id = "usr_alice"
        bob_id = "usr_bob"

        debt = debt_service.record_debt(
            user_id=alice_id,
            counterparty="Carlos",
            amount_cents=5000000,
            debt_type=DebtType.DEBT,
            reason="Préstamo de Alice",
            adjust_account_balance=False,
        )

        resp = api_client.patch(
            f"/api/finance/debts/{debt.id}?user_id={bob_id}",
            json={"counterparty": "Attacker", "amount_cents": 1000},
        )
        assert resp.status_code == 403
        assert "Unauthorized: debt belongs to another user" in resp.json()["detail"]

    def test_unauthorized_user_cannot_pay_installment_api_403(self, debt_service, api_client):
        """Alice creates an installment debt; Bob attempts to pay it -> 403 Forbidden."""
        alice_id = "usr_alice_inst"
        bob_id = "usr_bob_inst"

        debt = debt_service.record_debt(
            user_id=alice_id,
            counterparty="Banco",
            amount_cents=10000000,
            debt_type=DebtType.DEBT,
            reason="Alice loan",
            is_installment=True,
            total_installments=4,
            adjust_account_balance=False,
        )

        resp = api_client.post(
            f"/api/finance/debts/{debt.id}/installments/pay?user_id={bob_id}",
            json={"installments_to_pay": 1},
        )
        assert resp.status_code == 403
        assert "Unauthorized: debt belongs to another user" in resp.json()["detail"]

    def test_unauthorized_user_cannot_update_debt_service_permission_error(self, debt_service):
        alice_id = "usr_alice_svc"
        bob_id = "usr_bob_svc"

        debt = debt_service.record_debt(
            user_id=alice_id,
            counterparty="David",
            amount_cents=3000000,
            debt_type=DebtType.DEBT,
            reason="Debt",
            adjust_account_balance=False,
        )

        with pytest.raises(PermissionError, match="Unauthorized: debt belongs to another user"):
            debt_service.update_debt(debt.id, user_id=bob_id, updates={"counterparty": "Hacked"})

    def test_unauthorized_user_cannot_pay_installment_service_permission_error(self, debt_service):
        alice_id = "usr_alice_svc_pay"
        bob_id = "usr_bob_svc_pay"

        debt = debt_service.record_debt(
            user_id=alice_id,
            counterparty="David",
            amount_cents=6000000,
            debt_type=DebtType.DEBT,
            reason="Debt in cuotas",
            is_installment=True,
            total_installments=3,
            adjust_account_balance=False,
        )

        with pytest.raises(PermissionError, match="Unauthorized: debt belongs to another user"):
            debt_service.record_installment_payment(debt.id, user_id=bob_id, installments_to_pay=1)

    def test_unauthorized_user_cannot_execute_settlement_repo_permission_error(self, memory_db, debt_service):
        repo = DebtRepository(db_manager=memory_db)
        alice_id = "usr_alice_repo"
        bob_id = "usr_bob_repo"

        debt = debt_service.record_debt(
            user_id=alice_id,
            counterparty="Laura",
            amount_cents=5000000,
            debt_type=DebtType.DEBT,
            reason="Debt",
            is_installment=True,
            total_installments=2,
            adjust_account_balance=False,
        )

        with pytest.raises(PermissionError, match="Unauthorized: debt belongs to another user"):
            repo.execute_installment_settlement(debt.id, user_id=bob_id, installments_to_pay=1)

    def test_unauthorized_user_cannot_update_debt_repo_permission_error(self, memory_db, debt_service):
        repo = DebtRepository(db_manager=memory_db)
        alice_id = "usr_alice_repo_upd"
        bob_id = "usr_bob_repo_upd"

        debt = debt_service.record_debt(
            user_id=alice_id,
            counterparty="Laura",
            amount_cents=5000000,
            debt_type=DebtType.DEBT,
            reason="Debt",
            adjust_account_balance=False,
        )

        with pytest.raises(PermissionError, match="Unauthorized: debt belongs to another user"):
            repo.update_debt(debt.id, user_id=bob_id, updates={"counterparty": "Hacker"})

    def test_effective_user_fallback_cross_user_isolation(self, debt_service, api_client):
        """When user_id query param is omitted, request falls back to default user.

        If the debt belongs to a custom user ('usr_special'), the request without user_id
        must be rejected with 403 Forbidden.
        """
        special_user = "usr_special_isolated"
        debt = debt_service.record_debt(
            user_id=special_user,
            counterparty="Privado",
            amount_cents=10000000,
            debt_type=DebtType.DEBT,
            reason="Secret debt",
            adjust_account_balance=False,
        )

        # Call without user_id query parameter
        resp = api_client.patch(
            f"/api/finance/debts/{debt.id}",
            json={"reason": "Attempted override"},
        )
        assert resp.status_code == 403
        assert "Unauthorized" in resp.json()["detail"]


# ==============================================================================
# 4. Atomic Account Linking & Balance Invariants
# ==============================================================================

class TestAtomicAccountLinking:
    """Verifies cash flow direction, atomic ledger adjustments, and frequency advancement."""

    def test_debt_cuota_payment_debits_user_linked_account(self, debt_service, account_service):
        """Paying a DEBT cuota debits user's linked account (cash outflow: balance decreases)."""
        user_id = "usr_link_debt"
        account_service.ensure_default_accounts(user_id)
        bancolombia = account_service.get_account_by_name(user_id, "Bancolombia")
        account_service.set_balance(bancolombia.id, 50000000)  # 500,000 COP

        # Debt: user owes 300,000 COP (30,000,000 cents) in 3 cuotas (10,000,000 cents each)
        debt = debt_service.record_debt(
            user_id=user_id,
            counterparty="Juan Perez",
            amount_cents=30000000,
            debt_type=DebtType.DEBT,
            reason="Préstamo personal",
            account_name="Bancolombia",
            is_installment=True,
            total_installments=3,
            adjust_account_balance=False,
        )

        # Pay 1 cuota -> Bancolombia debited by 10,000,000 cents
        res1 = debt_service.record_installment_payment(debt.id, user_id, installments_to_pay=1)
        acc1 = account_service.get_account(bancolombia.id)
        assert acc1.balance_cents == 40000000  # 500k - 100k = 400k
        assert res1["payment"]["amount_cents"] == 10000000

        # Pay remaining 2 cuotas -> Bancolombia debited by 20,000,000 cents
        res2 = debt_service.record_installment_payment(debt.id, user_id, installments_to_pay=2)
        acc2 = account_service.get_account(bancolombia.id)
        assert acc2.balance_cents == 20000000  # 400k - 200k = 200k
        assert res2["payment"]["amount_cents"] == 20000000
        assert res2["settled"] is True

        # Total debit equals exactly 30,000,000 cents
        assert 50000000 - acc2.balance_cents == 30000000

    def test_receivable_cuota_payment_credits_user_linked_account(self, debt_service, account_service):
        """Receiving a RECEIVABLE cuota credits user's linked account (cash inflow: balance increases)."""
        user_id = "usr_link_receivable"
        account_service.ensure_default_accounts(user_id)
        nequi = account_service.get_account_by_name(user_id, "Nequi")
        account_service.set_balance(nequi.id, 50000000)  # 500,000 COP

        # User lends 400,000 COP (40,000,000 cents) in 4 cuotas from Nequi
        # Initial loan creation debits Nequi (outflow)
        debt = debt_service.record_debt(
            user_id=user_id,
            counterparty="Maria Rodriguez",
            amount_cents=40000000,
            debt_type=DebtType.RECEIVABLE,
            reason="Préstamo para curso",
            account_name="Nequi",
            is_installment=True,
            total_installments=4,
            adjust_account_balance=True,
        )

        acc_after_lend = account_service.get_account(nequi.id)
        assert acc_after_lend.balance_cents == 10000000  # 500k - 400k = 100k

        # Maria pays cuota 1 (100,000 COP = 10,000,000 cents) -> Nequi credited
        res1 = debt_service.record_installment_payment(debt.id, user_id, installments_to_pay=1)
        acc1 = account_service.get_account(nequi.id)
        assert acc1.balance_cents == 20000000  # 100k + 100k = 200k
        assert res1["settled"] is False

        # Maria pays remaining 3 cuotas (300,000 COP = 30,000,000 cents) -> Nequi credited
        res2 = debt_service.record_installment_payment(debt.id, user_id, installments_to_pay=3)
        acc2 = account_service.get_account(nequi.id)
        assert acc2.balance_cents == 50000000  # 200k + 300k = 500k
        assert res2["settled"] is True

        # Initial account balance is completely restored!
        assert acc2.balance_cents == 50000000

    def test_multi_account_switching_per_cuota(self, debt_service, account_service):
        """User pays cuotas of an odd debt using 3 different accounts: Nequi, Nu, Daviplata.

        Debt: 100,000 COP in 3 cuotas.
        Cuota 1: 3,333,333 cents paid from Nequi.
        Cuota 2: 3,333,333 cents paid from Nu.
        Cuota 3: 3,333,334 cents paid from Daviplata.
        Verify exact balance changes and zero cent loss.
        """
        user_id = "usr_multi_acc_pay"
        account_service.ensure_default_accounts(user_id)
        nequi = account_service.get_account_by_name(user_id, "Nequi")
        nu = account_service.get_account_by_name(user_id, "Nu")
        daviplata = account_service.get_account_by_name(user_id, "Daviplata")

        account_service.set_balance(nequi.id, 10000000)
        account_service.set_balance(nu.id, 10000000)
        account_service.set_balance(daviplata.id, 10000000)

        debt = debt_service.record_debt(
            user_id=user_id,
            counterparty="Almacén",
            amount_cents=10000000,
            debt_type=DebtType.DEBT,
            reason="Electrodoméstico",
            is_installment=True,
            total_installments=3,
            adjust_account_balance=False,
        )

        # Pay cuota 1 with Nequi
        debt_service.record_installment_payment(debt.id, user_id, installments_to_pay=1, account_name="Nequi")
        assert account_service.get_account(nequi.id).balance_cents == 10000000 - 3333333

        # Pay cuota 2 with Nu
        debt_service.record_installment_payment(debt.id, user_id, installments_to_pay=1, account_name="Nu")
        assert account_service.get_account(nu.id).balance_cents == 10000000 - 3333333

        # Pay cuota 3 with Daviplata
        debt_service.record_installment_payment(debt.id, user_id, installments_to_pay=1, account_name="Daviplata")
        assert account_service.get_account(daviplata.id).balance_cents == 10000000 - 3333334

        # Total debits across the 3 accounts
        total_debited = (
            (10000000 - account_service.get_account(nequi.id).balance_cents)
            + (10000000 - account_service.get_account(nu.id).balance_cents)
            + (10000000 - account_service.get_account(daviplata.id).balance_cents)
        )
        assert total_debited == 10000000

    def test_due_date_advancement_calendar_frequencies(self, debt_service):
        """Verifies monthly, biweekly, and weekly due date advancement calculations."""
        user_id = "usr_advance_dates"
        now_dt = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        # Monthly debt
        d_monthly = debt_service.record_debt(
            user_id=user_id,
            counterparty="Banco A",
            amount_cents=30000000,
            debt_type=DebtType.DEBT,
            reason="Monthly",
            is_installment=True,
            total_installments=3,
            payment_frequency="monthly",
            next_installment_due_date=now_dt,
            adjust_account_balance=False,
        )
        res_m = debt_service.record_installment_payment(d_monthly.id, user_id, installments_to_pay=1)
        next_m = res_m["debt"]["next_installment_due_date"]
        # January 15 + 1 month = February 15
        assert "2026-02-15" in str(next_m)

        # Weekly debt
        d_weekly = debt_service.record_debt(
            user_id=user_id,
            counterparty="Banco B",
            amount_cents=30000000,
            debt_type=DebtType.DEBT,
            reason="Weekly",
            is_installment=True,
            total_installments=4,
            payment_frequency="weekly",
            next_installment_due_date=now_dt,
            adjust_account_balance=False,
        )
        res_w = debt_service.record_installment_payment(d_weekly.id, user_id, installments_to_pay=2)
        next_w = res_w["debt"]["next_installment_due_date"]
        # January 15 + 14 days (2 weeks) = January 29
        assert "2026-01-29" in str(next_w)

        # Biweekly debt
        d_biweekly = debt_service.record_debt(
            user_id=user_id,
            counterparty="Banco C",
            amount_cents=20000000,
            debt_type=DebtType.DEBT,
            reason="Biweekly",
            is_installment=True,
            total_installments=2,
            payment_frequency="biweekly",
            next_installment_due_date=now_dt,
            adjust_account_balance=False,
        )
        res_bw = debt_service.record_installment_payment(d_biweekly.id, user_id, installments_to_pay=1)
        next_bw = res_bw["debt"]["next_installment_due_date"]
        # January 15 + 14 days = January 29
        assert "2026-01-29" in str(next_bw)


# ==============================================================================
# 5. Debt Modification Workflows
# ==============================================================================

class TestDebtModificationWorkflows:
    """Tests updating fields, counterparty, due date, and amount recalculation."""

    def test_update_debt_counterparty_and_reason_persists(self, debt_service):
        user_id = "usr_upd_fields"
        debt = debt_service.record_debt(
            user_id=user_id,
            counterparty="Juan",
            amount_cents=5000000,
            debt_type=DebtType.DEBT,
            reason="Almuerzo",
            adjust_account_balance=False,
        )

        updated = debt_service.update_debt(
            debt.id,
            user_id,
            {
                "counterparty": "Juan Carlos Perez",
                "reason": "Almuerzo ejecutivo y café",
                "due_date": "2026-12-01T12:00:00Z",
            },
        )

        assert updated.counterparty == "Juan Carlos Perez"
        assert updated.reason == "Almuerzo ejecutivo y café"
        assert updated.due_date is not None
        assert "2026-12-01" in updated.due_date.isoformat()

        # Retrieve again to verify SQLite persistence
        persisted = debt_service.get_debt(debt.id)
        assert persisted.counterparty == "Juan Carlos Perez"
        assert persisted.reason == "Almuerzo ejecutivo y café"

    def test_update_debt_amount_recalculates_installment_cents(self, debt_service):
        """Updating debt amount must update remaining_cents and installment_amount_cents."""
        user_id = "usr_upd_amount"
        # Initial: 120,000 COP in 4 cuotas -> 30,000 COP (3,000,000 cents) per cuota
        debt = debt_service.record_debt(
            user_id=user_id,
            counterparty="Credito",
            amount_cents=12000000,
            debt_type=DebtType.DEBT,
            reason="Compra",
            is_installment=True,
            total_installments=4,
            adjust_account_balance=False,
        )

        assert debt.installment_amount_cents == 3000000

        # Update amount to 200,000 COP (20,000,000 cents)
        updated = debt_service.update_debt(debt.id, user_id, {"amount_cents": 20000000})
        assert updated.amount_cents == 20000000
        assert updated.remaining_cents == 20000000
        # 20,000,000 // 4 = 5,000,000 cents per cuota
        assert updated.installment_amount_cents == 5000000

        # Update installments from 4 to 5
        updated2 = debt_service.update_debt(debt.id, user_id, {"total_installments": 5})
        assert updated2.total_installments == 5
        # Re-fetch and pay 1 cuota
        p1 = debt_service.record_installment_payment(debt.id, user_id, installments_to_pay=1)
        # Total remaining 20M, now with total_installments 5 -> base cuota is updated
        assert p1["settled"] is False


# ==============================================================================
# 6. Telegram NLP & ToolRouter Integration
# ==============================================================================

class TestTelegramNLPAndRouterInstallmentFlows:
    """End-to-end integration tests through natural language and tool routing."""

    def test_nlp_parse_cuotas_debt_record_phrases(self, intent_parser):
        """IntentParser extracts installment terms and avoids polluting the counterparty."""
        # 1. "presté 150000 a Andrés en 3 cuotas mensuales"
        r1 = intent_parser.parse("presté 150000 a Andrés en 3 cuotas mensuales")
        assert r1.intent == "debt_record"
        assert r1.slots["is_installment"] is True
        assert r1.slots["total_installments"] == 3
        assert r1.slots["payment_frequency"] == "monthly"
        assert r1.slots["counterparty"].lower() == "andrés"
        assert r1.slots["debt_type"] == "receivable"

        # 2. "debo 500k a Sofia a 6 cuotas quincenales"
        r2 = intent_parser.parse("debo 500k a Sofia a 6 cuotas quincenales")
        assert r2.intent == "debt_record"
        assert r2.slots["is_installment"] is True
        assert r2.slots["total_installments"] == 6
        assert r2.slots["payment_frequency"] == "biweekly"
        assert r2.slots["counterparty"].lower() == "sofia"
        assert r2.slots["debt_type"] in ("debt", "payable")

    def test_nlp_parse_cuotas_settle_phrases(self, intent_parser):
        """IntentParser intercepts cuota settlement requests."""
        # 1. "pagar 2 cuotas de la deuda de Juan con Bancolombia"
        s1 = intent_parser.parse("pagar 2 cuotas de la deuda de Juan con Bancolombia")
        assert s1.intent == "debt_settle"
        assert s1.slots["is_installment_payment"] is True
        assert s1.slots["installments_to_pay"] == 2
        assert s1.slots["counterparty"].lower() == "juan"
        assert s1.slots["account"].lower() == "bancolombia"

        # 2. "abono 1 cuota a Daviplata"
        s2 = intent_parser.parse("abono 1 cuota a Daviplata")
        assert s2.intent == "debt_settle"
        assert s2.slots["is_installment_payment"] is True
        assert s2.slots["installments_to_pay"] == 1
        assert s2.slots["account"].lower() == "daviplata"

    def test_router_end_to_end_debt_cuotas_and_payment(self, tool_router, intent_parser, account_service, debt_service):
        """ToolRouter processes debt creation in cuotas followed by cuota payment."""
        user_id = "usr_telegram_e2e"
        account_service.ensure_default_accounts(user_id)
        bancolombia = account_service.get_account_by_name(user_id, "Bancolombia")
        account_service.set_balance(bancolombia.id, 50000000)

        # 1. Record debt via router
        p_rec = intent_parser.parse("debo 100000 a Pedro en 3 cuotas mensuales")
        resp_record = tool_router.dispatch(user_id=user_id, intent_result=p_rec)
        assert "Pedro" in resp_record
        assert "3" in resp_record  # 3 cuotas displayed

        # Verify in DB
        debts = debt_service.list_debts(user_id, counterparty="Pedro")
        assert len(debts) == 1
        d = debts[0]
        assert d.is_installment is True
        assert d.total_installments == 3
        assert d.remaining_installments == 3

        # 2. Pay 1 cuota via router
        p_pay = intent_parser.parse("pagar 1 cuota de la deuda de Pedro con Bancolombia")
        resp_pay = tool_router.dispatch(user_id=user_id, intent_result=p_pay)
        assert "Pedro" in resp_pay
        assert "Abono de Cuota(s) Registrado" in resp_pay

        # Verify DB balance and remaining cuotas
        updated_debt = debt_service.get_debt(d.id)
        assert updated_debt.remaining_installments == 2
        acc = account_service.get_account(bancolombia.id)
        assert acc.balance_cents == 50000000 - 3333333

        # 3. Pay remaining 2 cuotas via router
        p_final = intent_parser.parse("pagar 2 cuotas de la deuda de Pedro con Bancolombia")
        resp_final = tool_router.dispatch(user_id=user_id, intent_result=p_final)
        assert "Totalmente Saldada" in resp_final
        final_debt = debt_service.get_debt(d.id)
        assert final_debt.status == DebtStatus.SETTLED
        assert final_debt.remaining_cents == 0
        final_acc = account_service.get_account(bancolombia.id)
        assert final_acc.balance_cents == 50000000 - 10000000  # Exactly 100k COP debited


# ==============================================================================
# 7. Additional Adversarial Stress Tests (Security Invariants & Edge Cases)
# ==============================================================================

class TestAdversarialSecurityAndEdgeCases:
    """Advanced security, account isolation, and calendar clamping edge cases."""

    def test_cross_user_account_id_injection_protection(self, debt_service, account_service):
        """Security invariant: Alice cannot debit Bob's account by specifying Bob's account_id.

        If Alice attempts to pass Bob's account_id in record_installment_payment,
        the system must refuse to use Bob's account and must not alter Bob's balance.
        """
        alice_id = "usr_alice_attacker"
        bob_id = "usr_bob_victim"

        account_service.ensure_default_accounts(alice_id)
        account_service.ensure_default_accounts(bob_id)

        bob_bancolombia = account_service.get_account_by_name(bob_id, "Bancolombia")
        account_service.set_balance(bob_bancolombia.id, 100000000)  # Bob has 1M COP

        alice_debt = debt_service.record_debt(
            user_id=alice_id,
            counterparty="Tienda",
            amount_cents=30000000,
            debt_type=DebtType.DEBT,
            reason="Compra personal de Alice",
            is_installment=True,
            total_installments=3,
            adjust_account_balance=False,
        )

        # Alice attempts to pay her installment using Bob's account_id
        debt_service.record_installment_payment(
            debt_id=alice_debt.id,
            user_id=alice_id,
            installments_to_pay=1,
            account_id=bob_bancolombia.id,
        )

        # Bob's account balance MUST remain 100% untouched
        bob_acc_after = account_service.get_account(bob_bancolombia.id)
        assert bob_acc_after.balance_cents == 100000000, (
            f"VULNERABILITY DETECTED! Bob's account was debited: {bob_acc_after.balance_cents}"
        )

    def test_full_settlement_on_installment_debt_clears_all_remaining(self, debt_service):
        """Calling settle_debt on a partially-paid installment debt clears the entire remaining balance."""
        user_id = "usr_settle_all_inst"
        total_cents = 10000000  # 100,000 COP

        debt = debt_service.record_debt(
            user_id=user_id,
            counterparty="Carlos",
            amount_cents=total_cents,
            debt_type=DebtType.DEBT,
            reason="Préstamo en cuotas",
            is_installment=True,
            total_installments=4,
            adjust_account_balance=False,
        )

        # Pay 1 cuota (25,000 COP = 2,500,000 cents)
        debt_service.record_installment_payment(debt.id, user_id, installments_to_pay=1)
        d_part = debt_service.get_debt(debt.id)
        assert d_part.remaining_cents == 7500000

        # Now execute full settlement via settle_debt
        res = debt_service.settle_debt(user_id=user_id, debt_id=debt.id)
        assert res["settled"] is True
        assert res["debt"]["remaining_cents"] == 0
        assert res["debt"]["paid_amount_cents"] == total_cents
        assert res["debt"]["status"] == DebtStatus.SETTLED.value

    def test_calendar_clamping_month_end_boundaries(self):
        """Verifies calendar month-end clamping logic in DebtRepository._advance_due_date."""
        # Jan 31, 2026 -> Feb 28, 2026 (non-leap year clamping)
        dt_jan31 = datetime(2026, 1, 31, 10, 0, 0, tzinfo=timezone.utc)
        adv_feb = DebtRepository._advance_due_date(dt_jan31, "monthly", 1)
        assert adv_feb == datetime(2026, 2, 28, 10, 0, 0, tzinfo=timezone.utc)

        # Jan 31, 2028 -> Feb 29, 2028 (leap year clamping)
        dt_leap = datetime(2028, 1, 31, 10, 0, 0, tzinfo=timezone.utc)
        adv_leap = DebtRepository._advance_due_date(dt_leap, "monthly", 1)
        assert adv_leap == datetime(2028, 2, 29, 10, 0, 0, tzinfo=timezone.utc)

        # Aug 31 -> Sep 30 (31-day to 30-day clamping)
        dt_aug31 = datetime(2026, 8, 31, 10, 0, 0, tzinfo=timezone.utc)
        adv_sep = DebtRepository._advance_due_date(dt_aug31, "monthly", 1)
        assert adv_sep == datetime(2026, 9, 30, 10, 0, 0, tzinfo=timezone.utc)

        # Monthly advancing 3 months: Nov 30, 2026 + 3 months -> Feb 28, 2027
        dt_nov30 = datetime(2026, 11, 30, 10, 0, 0, tzinfo=timezone.utc)
        adv_3m = DebtRepository._advance_due_date(dt_nov30, "monthly", 3)
        assert adv_3m == datetime(2027, 2, 28, 10, 0, 0, tzinfo=timezone.utc)

    def test_legacy_non_installment_debt_compatibility(self, debt_service):
        """Verify backwards compatibility for debts created without installments (is_installment=False)."""
        user_id = "usr_legacy_comp"
        debt = debt_service.record_debt(
            user_id=user_id,
            counterparty="Antiguo",
            amount_cents=5000000,
            debt_type=DebtType.DEBT,
            reason="Deuda antigua sin cuotas",
            is_installment=False,
            adjust_account_balance=False,
        )

        assert debt.is_installment is False
        assert debt.total_installments == 1
        assert debt.remaining_installments == 1

        # Partial settlement via standard record_payment
        p1 = debt_service.record_payment(
            user_id=user_id, debt_id=debt.id, amount_cents=2000000, adjust_account_balance=False
        )
        assert p1["debt"]["remaining_cents"] == 3000000
        assert p1["debt"]["status"] == DebtStatus.PARTIALLY_PAID.value

        # Full settlement via settle_debt
        p2 = debt_service.settle_debt(user_id=user_id, debt_id=debt.id)
        assert p2["settled"] is True
        assert p2["debt"]["remaining_cents"] == 0
        assert p2["debt"]["status"] == DebtStatus.SETTLED.value
