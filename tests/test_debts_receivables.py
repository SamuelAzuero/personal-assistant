"""Unit and Integration Test Suite for Debts & Receivables Ledger (R1).

Verifies Features F60–F63:
1. F60_DEBT_RECORD: Recording bilateral credit agreements:
   - Receivables (loans to others): debits linked account (cash outflow).
   - Debts (money borrowed): credits linked account (cash inflow).
   - Validates positive amounts, non-empty counterparty and reason.
2. F61_DEBT_QUERY: Querying debts and receivables by status (active, partially_paid, settled),
   debt_type (debt, receivable), or counterparty name, with aggregate summaries.
3. F62_DEBT_SETTLEMENT: Partial settlements transitioning to 'partially_paid' and full settlements
   transitioning to 'settled', adjusting linked account balances and rejecting overpayments or settled debts.
4. F63_DEBT_DUE_ALERT: Computing impending due dates, remaining days countdown, and overdue flags.
"""

from datetime import datetime, timedelta, timezone
import pytest

from app.database.connection import DatabaseManager
from app.database.repositories.debt_repo import DebtStatus, DebtType
from app.services.account_service import AccountService
from app.services.debt_service import DebtService


@pytest.fixture
def memory_db():
    """Isolated in-memory SQLite database initialized with full schema."""
    db = DatabaseManager(":memory:")
    db.init_db()
    yield db
    db.close()


@pytest.fixture
def account_service(memory_db):
    """AccountService instance wired to isolated in-memory DB."""
    return AccountService(db_manager=memory_db)


@pytest.fixture
def debt_service(memory_db, account_service):
    """DebtService instance wired to isolated in-memory DB and AccountService."""
    return DebtService(db_manager=memory_db, account_service=account_service)


# ==============================================================================
# 1. Debt & Receivable Recording & Accounting Invariants (F60)
# ==============================================================================


class TestDebtRecording:
    """Tests creation of receivables and debts with account balance adjustments."""

    def test_record_receivable_loan_to_other_debits_account(self, debt_service, account_service):
        """When user lends money to Juan from Nequi, Nequi balance is debited (cash outflow)."""
        user_id = "usr_debt_01"
        account_service.ensure_default_accounts(user_id)
        nequi = account_service.get_account_by_name(user_id, "Nequi")
        account_service.set_balance(nequi.id, 10000000)  # 100,000 COP

        due_date = datetime.now(timezone.utc) + timedelta(days=7)

        # Lent 50,000 COP to Juan for lunch from Nequi
        record = debt_service.record_debt(
            user_id=user_id,
            counterparty="Juan Perez",
            amount_cents=5000000,  # 50,000 COP
            debt_type=DebtType.RECEIVABLE,
            reason="Almuerzo de trabajo",
            due_date=due_date,
            account_name="Nequi",
            adjust_account_balance=True,
        )

        assert record.id.startswith("debt_")
        assert record.user_id == user_id
        assert record.debt_type == DebtType.RECEIVABLE
        assert record.counterparty == "Juan Perez"
        assert record.amount_cents == 5000000
        assert record.amount == 50000.0
        assert record.remaining_cents == 5000000
        assert record.remaining == 50000.0
        assert record.paid_amount_cents == 0
        assert record.reason == "Almuerzo de trabajo"
        assert record.status == DebtStatus.ACTIVE
        assert record.account_name == "Nequi"
        assert record.settled_at is None

        # Nequi balance should be debited by 50,000 COP (100k -> 50k)
        updated_nequi = account_service.get_account(nequi.id)
        assert updated_nequi.balance_cents == 5000000  # 50,000 COP

    def test_record_debt_borrowed_from_other_credits_account(self, debt_service, account_service):
        """When user borrows money from Carlos into Bancolombia, Bancolombia balance is credited (inflow)."""
        user_id = "usr_debt_02"
        account_service.ensure_default_accounts(user_id)
        banco = account_service.get_account_by_name(user_id, "Bancolombia")
        account_service.set_balance(banco.id, 20000000)  # 200,000 COP

        due_date = datetime.now(timezone.utc) + timedelta(days=15)

        # Borrowed 100,000 COP from Carlos into Bancolombia
        record = debt_service.record_debt(
            user_id=user_id,
            counterparty="Carlos Gomez",
            amount_cents=10000000,  # 100,000 COP
            debt_type=DebtType.DEBT,
            reason="Préstamo para servicios",
            due_date=due_date,
            account_name="Bancolombia",
            adjust_account_balance=True,
        )

        assert record.debt_type == DebtType.DEBT
        assert record.counterparty == "Carlos Gomez"
        assert record.amount_cents == 10000000
        assert record.remaining_cents == 10000000
        assert record.status == DebtStatus.ACTIVE
        assert record.account_name == "Bancolombia"

        # Bancolombia balance should be credited by 100,000 COP (200k -> 300k)
        updated_banco = account_service.get_account(banco.id)
        assert updated_banco.balance_cents == 30000000  # 300,000 COP

    def test_record_debt_without_balance_adjustment(self, debt_service, account_service):
        """When adjust_account_balance=False, linked account balance remains untouched."""
        user_id = "usr_debt_no_adj"
        account_service.ensure_default_accounts(user_id)
        efectivo = account_service.get_account_by_name(user_id, "Efectivo")
        account_service.set_balance(efectivo.id, 40000000)

        record = debt_service.record_debt(
            user_id=user_id,
            counterparty="Maria",
            amount_cents=10000000,
            debt_type=DebtType.RECEIVABLE,
            reason="Pasajes",
            account_name="Efectivo",
            adjust_account_balance=False,
        )

        assert record.status == DebtStatus.ACTIVE
        updated_efectivo = account_service.get_account(efectivo.id)
        assert updated_efectivo.balance_cents == 40000000  # Untouched

    @pytest.mark.parametrize("invalid_amount", [0, -1, -5000000])
    def test_record_debt_rejects_non_positive_amount(self, debt_service, invalid_amount):
        user_id = "usr_debt_invalid"
        with pytest.raises(ValueError, match="amount must be greater than zero"):
            debt_service.record_debt(
                user_id=user_id,
                counterparty="Pedro",
                amount_cents=invalid_amount,
                debt_type=DebtType.RECEIVABLE,
                reason="Almuerzo",
            )

    @pytest.mark.parametrize("invalid_counterparty", ["", "   "])
    def test_record_debt_rejects_empty_counterparty(self, debt_service, invalid_counterparty):
        user_id = "usr_debt_invalid"
        with pytest.raises(ValueError, match="Counterparty name cannot be empty"):
            debt_service.record_debt(
                user_id=user_id,
                counterparty=invalid_counterparty,
                amount_cents=5000000,
                debt_type=DebtType.DEBT,
                reason="Taxi",
            )

    @pytest.mark.parametrize("invalid_reason", ["", "   "])
    def test_record_debt_rejects_empty_reason(self, debt_service, invalid_reason):
        user_id = "usr_debt_invalid"
        with pytest.raises(ValueError, match="Debt reason cannot be empty"):
            debt_service.record_debt(
                user_id=user_id,
                counterparty="Laura",
                amount_cents=5000000,
                debt_type=DebtType.RECEIVABLE,
                reason=invalid_reason,
            )


# ==============================================================================
# 2. Partial Settlements & Balance Updates (F62)
# ==============================================================================


class TestPartialSettlements:
    """Tests partial repayments transitioning debts to 'partially_paid' status."""

    def test_partial_settlement_on_receivable_credits_account(self, debt_service, account_service):
        """Juan repays 20k of 50k loan -> status becomes 'partially_paid', Nequi credited 20k."""
        user_id = "usr_part_recv"
        account_service.ensure_default_accounts(user_id)
        nequi = account_service.get_account_by_name(user_id, "Nequi")
        account_service.set_balance(nequi.id, 5000000)  # 50,000 COP

        # Create loan of 50,000 COP
        debt = debt_service.record_debt(
            user_id=user_id,
            counterparty="Juan",
            amount_cents=5000000,  # 50,000 COP
            debt_type=DebtType.RECEIVABLE,
            reason="Almuerzo",
            account_name="Nequi",
            adjust_account_balance=False,  # Keep baseline simple
        )

        # Juan pays back 20,000 COP to Nequi
        result = debt_service.record_payment(
            user_id=user_id,
            debt_id=debt.id,
            amount_cents=2000000,  # 20,000 COP
            account_name="Nequi",
            notes="Primer abono",
            adjust_account_balance=True,
        )

        assert result["success"] is True
        assert result["settled"] is False
        payment = result["payment"]
        assert payment["amount_cents"] == 2000000
        assert payment["notes"] == "Primer abono"

        # Check debt status transitioned to partially_paid
        updated_debt = debt_service.get_debt(debt.id)
        assert updated_debt.status == DebtStatus.PARTIALLY_PAID
        assert updated_debt.paid_amount_cents == 2000000  # 20,000 COP
        assert updated_debt.remaining_cents == 3000000     # 30,000 COP
        assert updated_debt.remaining == 30000.0
        assert updated_debt.settled_at is None

        # Nequi should be credited by 20,000 COP (50,000 COP + 20,000 COP = 70,000 COP / 7,000,000 cents)
        updated_nequi = account_service.get_account(nequi.id)
        assert updated_nequi.balance_cents == 7000000  # 70,000 COP

    def test_partial_settlement_on_debt_debits_account(self, debt_service, account_service):
        """User repays 30k of 100k debt to Carlos -> status 'partially_paid', Bancolombia debited 30k."""
        user_id = "usr_part_debt"
        account_service.ensure_default_accounts(user_id)
        banco = account_service.get_account_by_name(user_id, "Bancolombia")
        account_service.set_balance(banco.id, 100000000)  # 1,000,000 COP

        debt = debt_service.record_debt(
            user_id=user_id,
            counterparty="Carlos",
            amount_cents=10000000,  # 100,000 COP
            debt_type=DebtType.DEBT,
            reason="Préstamo",
            account_name="Bancolombia",
            adjust_account_balance=False,
        )

        # Repay 30,000 COP from Bancolombia
        result = debt_service.record_payment(
            user_id=user_id,
            debt_id=debt.id,
            amount_cents=3000000,  # 30,000 COP
            account_name="Bancolombia",
            notes="Abono 1",
            adjust_account_balance=True,
        )

        assert result["success"] is True
        assert result["settled"] is False

        updated_debt = debt_service.get_debt(debt.id)
        assert updated_debt.status == DebtStatus.PARTIALLY_PAID
        assert updated_debt.remaining_cents == 7000000  # 70,000 COP

        # Bancolombia debited by 30,000 COP (1,000k -> 970k)
        updated_banco = account_service.get_account(banco.id)
        assert updated_banco.balance_cents == 97000000


# ==============================================================================
# 3. Full Settlements & Settled Invariants (F62)
# ==============================================================================


class TestFullSettlements:
    """Tests complete debt payoff transitioning debts to 'settled' status."""

    def test_full_settlement_via_two_payments(self, debt_service):
        user_id = "usr_full_settle"
        debt = debt_service.record_debt(
            user_id=user_id,
            counterparty="Andres",
            amount_cents=8000000,  # 80,000 COP
            debt_type=DebtType.RECEIVABLE,
            reason="Cena",
            adjust_account_balance=False,
        )

        # Payment 1: 50,000 COP
        debt_service.record_payment(
            user_id=user_id,
            debt_id=debt.id,
            amount_cents=5000000,
            adjust_account_balance=False,
        )
        mid_debt = debt_service.get_debt(debt.id)
        assert mid_debt.status == DebtStatus.PARTIALLY_PAID
        assert mid_debt.remaining_cents == 3000000

        # Payment 2: Remaining 30,000 COP
        result = debt_service.record_payment(
            user_id=user_id,
            debt_id=debt.id,
            amount_cents=3000000,
            adjust_account_balance=False,
        )
        assert result["settled"] is True

        final_debt = debt_service.get_debt(debt.id)
        assert final_debt.status == DebtStatus.SETTLED
        assert final_debt.remaining_cents == 0
        assert final_debt.remaining == 0.0
        assert final_debt.paid_amount_cents == 8000000
        assert final_debt.settled_at is not None

    def test_settle_debt_convenience_method(self, debt_service):
        """settle_debt pays off the exact remaining balance in a single operation."""
        user_id = "usr_convenience_settle"
        debt = debt_service.record_debt(
            user_id=user_id,
            counterparty="Felipe",
            amount_cents=4500000,  # 45,000 COP
            debt_type=DebtType.DEBT,
            reason="Boleta de cine",
            adjust_account_balance=False,
        )

        res = debt_service.settle_debt(user_id=user_id, debt_id=debt.id)
        assert res["success"] is True
        assert res["settled"] is True

        settled_record = debt_service.get_debt(debt.id)
        assert settled_record.status == DebtStatus.SETTLED
        assert settled_record.remaining_cents == 0


# ==============================================================================
# 4. Overpayment & Error Handling (F62)
# ==============================================================================


class TestSettlementRejections:
    """Tests strict rejection of overpayments, negative payments, and settling settled debts."""

    def test_reject_overpayment_exceeding_remaining_balance(self, debt_service):
        user_id = "usr_overpay"
        debt = debt_service.record_debt(
            user_id=user_id,
            counterparty="Sara",
            amount_cents=5000000,  # 50,000 COP
            debt_type=DebtType.RECEIVABLE,
            reason="Libro",
            adjust_account_balance=False,
        )

        # Attempting to pay 60,000 COP on a 50,000 COP loan
        with pytest.raises(ValueError, match="exceeds remaining balance"):
            debt_service.record_payment(
                user_id=user_id,
                debt_id=debt.id,
                amount_cents=6000000,
                adjust_account_balance=False,
            )

        # Verify state was untouched
        untouched = debt_service.get_debt(debt.id)
        assert untouched.status == DebtStatus.ACTIVE
        assert untouched.remaining_cents == 5000000

    def test_reject_payment_on_already_settled_debt(self, debt_service):
        user_id = "usr_settled_repay"
        debt = debt_service.record_debt(
            user_id=user_id,
            counterparty="Mario",
            amount_cents=3000000,
            debt_type=DebtType.DEBT,
            reason="Gasolina",
            adjust_account_balance=False,
        )
        debt_service.settle_debt(user_id=user_id, debt_id=debt.id)

        # Attempting to pay again on settled debt
        with pytest.raises(ValueError, match="already settled or cancelled"):
            debt_service.record_payment(
                user_id=user_id,
                debt_id=debt.id,
                amount_cents=1000000,
                adjust_account_balance=False,
            )

    @pytest.mark.parametrize("invalid_amount", [0, -100, -5000000])
    def test_reject_zero_or_negative_payment_amount(self, debt_service, invalid_amount):
        user_id = "usr_bad_pay_amt"
        debt = debt_service.record_debt(
            user_id=user_id,
            counterparty="Daniel",
            amount_cents=2000000,
            debt_type=DebtType.DEBT,
            reason="Café",
            adjust_account_balance=False,
        )

        with pytest.raises(ValueError, match="greater than zero"):
            debt_service.record_payment(
                user_id=user_id,
                debt_id=debt.id,
                amount_cents=invalid_amount,
                adjust_account_balance=False,
            )

    def test_reject_payment_on_non_existent_debt(self, debt_service):
        with pytest.raises(ValueError, match="does not exist"):
            debt_service.record_payment(
                user_id="usr_ghost",
                debt_id="debt_nonexistent_999",
                amount_cents=5000000,
            )

    def test_reject_payment_by_unauthorized_user(self, debt_service):
        debt = debt_service.record_debt(
            user_id="usr_owner",
            counterparty="Clara",
            amount_cents=5000000,
            debt_type=DebtType.RECEIVABLE,
            reason="Regalo",
            adjust_account_balance=False,
        )

        with pytest.raises(ValueError, match="Unauthorized"):
            debt_service.record_payment(
                user_id="usr_stranger",
                debt_id=debt.id,
                amount_cents=2000000,
            )


# ==============================================================================
# 5. Debt Queries & Summary Analytics (F61)
# ==============================================================================


class TestDebtQueriesAndSummary:
    """Tests querying debts by status, type, counterparty, and aggregate summary totals."""

    def test_list_debts_filtering_by_status(self, debt_service):
        user_id = "usr_filter_status"

        # 1. Active receivable
        d1 = debt_service.record_debt(user_id, "Ana", 5000000, DebtType.RECEIVABLE, "Renta", adjust_account_balance=False)
        # 2. Partially paid debt
        d2 = debt_service.record_debt(user_id, "Beto", 8000000, DebtType.DEBT, "Compras", adjust_account_balance=False)
        debt_service.record_payment(user_id, d2.id, 3000000, adjust_account_balance=False)
        # 3. Settled debt
        d3 = debt_service.record_debt(user_id, "Camilo", 2000000, DebtType.DEBT, "Cena", adjust_account_balance=False)
        debt_service.settle_debt(user_id, d3.id)

        # Query only active
        active_list = debt_service.list_debts(user_id, status=DebtStatus.ACTIVE)
        assert len(active_list) == 1
        assert active_list[0].id == d1.id

        # Query only partially_paid
        part_list = debt_service.list_debts(user_id, status=DebtStatus.PARTIALLY_PAID)
        assert len(part_list) == 1
        assert part_list[0].id == d2.id

        # Query only settled
        settled_list = debt_service.list_debts(user_id, status=DebtStatus.SETTLED)
        assert len(settled_list) == 1
        assert settled_list[0].id == d3.id

    def test_list_debts_filtering_by_debt_type(self, debt_service):
        user_id = "usr_filter_type"
        debt_service.record_debt(user_id, "Persona A", 1000000, DebtType.RECEIVABLE, "1", adjust_account_balance=False)
        debt_service.record_debt(user_id, "Persona B", 2000000, DebtType.RECEIVABLE, "2", adjust_account_balance=False)
        debt_service.record_debt(user_id, "Persona C", 3000000, DebtType.DEBT, "3", adjust_account_balance=False)

        receivables = debt_service.list_debts(user_id, debt_type=DebtType.RECEIVABLE)
        assert len(receivables) == 2

        debts = debt_service.list_debts(user_id, debt_type=DebtType.DEBT)
        assert len(debts) == 1

    def test_list_debts_filtering_by_counterparty_substring(self, debt_service):
        user_id = "usr_filter_name"
        debt_service.record_debt(user_id, "Juan Manuel", 5000000, DebtType.RECEIVABLE, "A", adjust_account_balance=False)
        debt_service.record_debt(user_id, "Manuel Antonio", 5000000, DebtType.DEBT, "B", adjust_account_balance=False)
        debt_service.record_debt(user_id, "Santiago", 5000000, DebtType.DEBT, "C", adjust_account_balance=False)

        results = debt_service.list_debts(user_id, counterparty="manuel")
        assert len(results) == 2
        names = {d.counterparty for d in results}
        assert "Juan Manuel" in names
        assert "Manuel Antonio" in names

    def test_get_debt_summary_calculations(self, debt_service):
        """Summary computes total receivables, total debts owed, and net debt position."""
        user_id = "usr_summary_01"

        # Lent 150,000 COP to Juan (Receivable)
        debt_service.record_debt(user_id, "Juan", 15000000, DebtType.RECEIVABLE, "Prestamo", adjust_account_balance=False)

        # Lent 50,000 COP to Pedro, Pedro repaid 20,000 COP -> remaining 30,000 COP
        p_debt = debt_service.record_debt(user_id, "Pedro", 5000000, DebtType.RECEIVABLE, "Almuerzo", adjust_account_balance=False)
        debt_service.record_payment(user_id, p_debt.id, 2000000, adjust_account_balance=False)

        # Borrowed 80,000 COP from Carlos (Debt)
        debt_service.record_debt(user_id, "Carlos", 8000000, DebtType.DEBT, "Servicios", adjust_account_balance=False)

        # Borrowed 40,000 COP from Andres, fully settled -> remaining 0 COP (should be excluded from active totals)
        a_debt = debt_service.record_debt(user_id, "Andres", 4000000, DebtType.DEBT, "Transporte", adjust_account_balance=False)
        debt_service.settle_debt(user_id, a_debt.id)

        summary = debt_service.get_debt_summary(user_id)

        # Expected:
        # Total Receivable = 150,000 + 30,000 = 180,000 COP (18,000,000 cents)
        # Total Debt       = 80,000 COP (8,000,000 cents)
        # Net Position     = 180,000 - 80,000 = +100,000 COP (+10,000,000 cents)
        assert summary["total_receivable_cents"] == 18000000
        assert summary["total_receivable"] == 180000.0
        assert summary["total_debt_cents"] == 8000000
        assert summary["total_debt"] == 80000.0
        assert summary["net_position_cents"] == 10000000
        assert summary["net_position"] == 100000.0
        assert summary["active_receivables_count"] == 2
        assert summary["active_debts_count"] == 1
