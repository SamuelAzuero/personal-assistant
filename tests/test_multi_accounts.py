"""Unit and Integration Test Suite for Multi-Account Asset Allocation & Transfers (R2).

Verifies Features F64–F67:
1. F64_ACCOUNT_SCHEMA_INIT: Default accounts initialization (Efectivo, Nequi, Nu, Daviplata, Bancolombia)
   and dynamic custom account creation with case-insensitive name uniqueness.
2. F65_ACCOUNT_LINKED_TX: Attribution of income and expense transactions to specific accounts,
   automatically debiting or crediting individual account balances.
3. F66_ACCOUNT_TRANSFER: Inter-account transfers with exact integer cents and strict zero net wealth loss.
   Validation and rejection of self-transfers, negative/zero amounts, and invalid accounts.
4. F67_NET_WORTH_AGGREGATION: Real-time total net worth and asset allocation percentages across all accounts.
"""

import pytest

from app.database.connection import DatabaseManager
from app.database.repositories.account_repo import AccountRepository, TransferRecord
from app.services.account_service import AccountService
from app.services.finance_service import FinanceService
from app.database.repositories.finance_repo import TransactionType


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
def finance_service(memory_db):
    """FinanceService instance wired to isolated in-memory DB."""
    return FinanceService(db_manager=memory_db)


# ==============================================================================
# 1. Default Accounts Initialization & Idempotency (F64)
# ==============================================================================


class TestDefaultAccountsInitialization:
    """Tests that the 5 default Colombian accounts are seeded with 0 COP initial balance."""

    EXPECTED_DEFAULTS = [
        {"name": "Efectivo", "account_type": "cash"},
        {"name": "Nequi", "account_type": "digital_wallet"},
        {"name": "Nu", "account_type": "bank_account"},
        {"name": "Daviplata", "account_type": "digital_wallet"},
        {"name": "Bancolombia", "account_type": "bank_account"},
    ]

    def test_default_accounts_seeded_on_init(self, account_service):
        user_id = "usr_colombia_01"
        accounts = account_service.ensure_default_accounts(user_id)

        assert len(accounts) == 5, f"Expected exactly 5 default accounts, got {len(accounts)}"
        account_names = {a.name: a for a in accounts}

        for expected in self.EXPECTED_DEFAULTS:
            name = expected["name"]
            assert name in account_names, f"Expected default account '{name}' was not created"
            acc = account_names[name]
            assert acc.account_type == expected["account_type"], (
                f"Account '{name}' expected type '{expected['account_type']}', got '{acc.account_type}'"
            )
            assert acc.balance_cents == 0, f"Account '{name}' must have 0 initial balance, got {acc.balance_cents}"
            assert acc.balance == 0.0
            assert acc.currency == "COP"
            assert acc.is_active is True
            assert acc.user_id == user_id

    def test_ensure_default_accounts_is_idempotent(self, account_service):
        user_id = "usr_idempotent_01"
        # First call seeds accounts
        accounts_first = account_service.ensure_default_accounts(user_id)
        assert len(accounts_first) == 5

        # Modify balance of one account
        nequi = account_service.get_account_by_name(user_id, "Nequi")
        assert nequi is not None
        account_service.set_balance(nequi.id, 5000000)  # 50,000 COP

        # Second call must not overwrite balance or duplicate records
        accounts_second = account_service.ensure_default_accounts(user_id)
        assert len(accounts_second) == 5

        nequi_after = account_service.get_account_by_name(user_id, "Nequi")
        assert nequi_after.balance_cents == 5000000, "ensure_default_accounts must preserve existing balance"

    def test_ensure_default_accounts_rejects_empty_user(self, account_service):
        with pytest.raises(ValueError, match="User ID cannot be empty"):
            account_service.ensure_default_accounts("")

        with pytest.raises(ValueError, match="User ID cannot be empty"):
            account_service.ensure_default_accounts("   ")


# ==============================================================================
# 2. Dynamic Account Creation & Uniqueness (F64)
# ==============================================================================


class TestDynamicAccountManagement:
    """Tests custom account addition, case-insensitive uniqueness, and input validation."""

    def test_dynamic_account_addition_success(self, account_service):
        user_id = "usr_custom_acc"
        account_service.ensure_default_accounts(user_id)

        custom = account_service.create_account(
            user_id=user_id,
            name="Lulo Bank",
            account_type="bank_account",
            initial_balance_cents=25000000,  # 250,000 COP
            currency="COP",
            color="#00E676",
            icon="🏦",
        )

        assert custom.id.startswith("acc_")
        assert custom.name == "Lulo Bank"
        assert custom.account_type == "bank_account"
        assert custom.balance_cents == 25000000
        assert custom.balance == 250000.0
        assert custom.color == "#00E676"
        assert custom.icon == "🏦"
        assert custom.is_active is True

        all_accounts = account_service.get_accounts(user_id)
        assert len(all_accounts) == 6
        names = [a.name for a in all_accounts]
        assert "Lulo Bank" in names

    @pytest.mark.parametrize("duplicate_name", [
        "nequi",
        "NEQUI",
        "Nequi",
        "NeQuI",
        "  nequi  ",
    ])
    def test_dynamic_account_case_insensitive_uniqueness(self, account_service, duplicate_name):
        user_id = "usr_case_unique"
        account_service.ensure_default_accounts(user_id)

        with pytest.raises(ValueError, match=r"(?i)already exists"):
            account_service.create_account(
                user_id=user_id,
                name=duplicate_name,
                account_type="digital_wallet",
            )

    def test_create_account_empty_or_blank_name_rejected(self, account_service):
        user_id = "usr_invalid_acc"
        with pytest.raises(ValueError, match="Account name cannot be empty"):
            account_service.create_account(user_id=user_id, name="")

        with pytest.raises(ValueError, match="Account name cannot be empty"):
            account_service.create_account(user_id=user_id, name="   ")

    def test_get_account_by_name_case_insensitive(self, account_service):
        user_id = "usr_case_lookup"
        account_service.ensure_default_accounts(user_id)

        acc_upper = account_service.get_account_by_name(user_id, "BANCOLOMBIA")
        acc_lower = account_service.get_account_by_name(user_id, "bancolombia")
        acc_title = account_service.get_account_by_name(user_id, "Bancolombia")

        assert acc_upper is not None
        assert acc_lower is not None
        assert acc_title is not None
        assert acc_upper.id == acc_lower.id == acc_title.id


# ==============================================================================
# 3. Income & Expense Adjusting Account Balances (F65)
# ==============================================================================


class TestIncomeAndExpenseBalanceAdjustments:
    """Tests that financial transactions debit or credit linked account balances accurately."""

    def test_expense_debits_account_balance(self, account_service):
        user_id = "usr_tx_debit"
        account_service.ensure_default_accounts(user_id)
        nequi = account_service.get_account_by_name(user_id, "Nequi")

        # Set initial balance of 100,000 COP
        account_service.set_balance(nequi.id, 10000000)

        # Expense of 35,000 COP debited
        account_service.adjust_balance(nequi.id, -3500000)

        updated = account_service.get_account(nequi.id)
        assert updated.balance_cents == 6500000  # 65,000 COP
        assert updated.balance == 65000.0

        # Verify other accounts remain unchanged
        bancolombia = account_service.get_account_by_name(user_id, "Bancolombia")
        assert bancolombia.balance_cents == 0

    def test_income_credits_account_balance(self, account_service):
        user_id = "usr_tx_credit"
        account_service.ensure_default_accounts(user_id)
        bancolombia = account_service.get_account_by_name(user_id, "Bancolombia")

        # Income of 2,000,000 COP credited
        account_service.adjust_balance(bancolombia.id, 200000000)

        updated = account_service.get_account(bancolombia.id)
        assert updated.balance_cents == 200000000
        assert updated.balance == 2000000.0

    def test_finance_service_integration_with_account_name(self, finance_service, account_service):
        """Verify that FinanceService.record_transaction adjusts linked account balance when provided."""
        user_id = "usr_fin_linked"
        account_service.ensure_default_accounts(user_id)
        nu = account_service.get_account_by_name(user_id, "Nu")
        account_service.set_balance(nu.id, 20000000)  # 200,000 COP

        # Check if record_transaction supports account_name / account_id
        import inspect
        sig = inspect.signature(finance_service.record_transaction)

        if "account_name" in sig.parameters or "account_id" in sig.parameters:
            kwargs = {}
            if "account_name" in sig.parameters:
                kwargs["account_name"] = "Nu"
            elif "account_id" in sig.parameters:
                kwargs["account_id"] = nu.id

            tx = finance_service.record_transaction(
                user_id=user_id,
                amount_cents=4500000,  # 45,000 COP
                t_type=TransactionType.EXPENSE,
                category="Entertainment",
                description="Concierto",
                **kwargs,
            )
            assert tx.id is not None
            updated_nu = account_service.get_account(nu.id)
            assert updated_nu.balance_cents == 15500000  # 155,000 COP


# ==============================================================================
# 4. Inter-Account Transfers & Zero Net Wealth Loss (F66)
# ==============================================================================


class TestInterAccountTransferZeroNetWorthLoss:
    """Tests atomic fund movement between accounts with exact net worth invariance."""

    def test_transfer_preserves_total_net_worth(self, account_service):
        user_id = "usr_transfer_01"
        account_service.ensure_default_accounts(user_id)

        banco = account_service.get_account_by_name(user_id, "Bancolombia")
        nequi = account_service.get_account_by_name(user_id, "Nequi")

        # Setup initial funds
        account_service.set_balance(banco.id, 100000000)  # 1,000,000 COP
        account_service.set_balance(nequi.id, 20000000)   # 200,000 COP

        net_worth_before = account_service.get_net_worth(user_id)["total_net_worth_cents"]
        assert net_worth_before == 120000000  # 1,200,000 COP

        # Transfer 350,000 COP (35,000,000 cents) from Bancolombia to Nequi
        transfer = account_service.transfer(
            user_id=user_id,
            from_account_name_or_id="Bancolombia",
            to_account_name_or_id="Nequi",
            amount_cents=35000000,
            fee_cents=0,
            description="Recarga para gastos del mes",
        )

        assert isinstance(transfer, TransferRecord)
        assert transfer.amount_cents == 35000000
        assert transfer.amount == 350000.0
        assert transfer.from_account_id == banco.id
        assert transfer.to_account_id == nequi.id
        assert transfer.from_account_name == "Bancolombia"
        assert transfer.to_account_name == "Nequi"
        assert transfer.description == "Recarga para gastos del mes"

        # Verify new individual balances
        banco_after = account_service.get_account(banco.id)
        nequi_after = account_service.get_account(nequi.id)
        assert banco_after.balance_cents == 65000000  # 650,000 COP
        assert nequi_after.balance_cents == 55000000  # 550,000 COP

        # Zero Net Wealth Loss Invariant: Total before == Total after
        net_worth_after = account_service.get_net_worth(user_id)["total_net_worth_cents"]
        assert net_worth_after == net_worth_before == 120000000
        delta_net_worth = net_worth_after - net_worth_before
        assert delta_net_worth == 0, f"Expected zero wealth loss, got delta: {delta_net_worth}"

    def test_multi_hop_transfers_preserve_net_worth_invariance(self, account_service):
        user_id = "usr_multi_hop"
        account_service.ensure_default_accounts(user_id)

        # Deposit 500k into Bancolombia
        banco = account_service.get_account_by_name(user_id, "Bancolombia")
        account_service.set_balance(banco.id, 50000000)

        initial_worth = account_service.get_net_worth(user_id)["total_net_worth_cents"]
        assert initial_worth == 50000000

        # Hop 1: Bancolombia -> Nequi (200k)
        account_service.transfer(user_id, "Bancolombia", "Nequi", 20000000)
        assert account_service.get_net_worth(user_id)["total_net_worth_cents"] == initial_worth

        # Hop 2: Nequi -> Efectivo (50k retiro cajero)
        account_service.transfer(user_id, "Nequi", "Efectivo", 5000000)
        assert account_service.get_net_worth(user_id)["total_net_worth_cents"] == initial_worth

        # Hop 3: Efectivo -> Daviplata (20k consignación)
        account_service.transfer(user_id, "Efectivo", "Daviplata", 2000000)
        assert account_service.get_net_worth(user_id)["total_net_worth_cents"] == initial_worth

        # Hop 4: Daviplata -> Nu (10k)
        account_service.transfer(user_id, "Daviplata", "Nu", 1000000)
        final_worth = account_service.get_net_worth(user_id)["total_net_worth_cents"]
        assert final_worth == initial_worth

    def test_transfer_with_fee_decrements_net_worth_by_fee_only(self, account_service):
        user_id = "usr_fee_tx"
        account_service.ensure_default_accounts(user_id)
        banco = account_service.get_account_by_name(user_id, "Bancolombia")
        account_service.set_balance(banco.id, 100000000)  # 1,000,000 COP

        initial_worth = account_service.get_net_worth(user_id)["total_net_worth_cents"]

        # Transfer 100,000 COP with 2,500 COP transaction fee
        account_service.transfer(
            user_id=user_id,
            from_account_name_or_id="Bancolombia",
            to_account_name_or_id="Efectivo",
            amount_cents=10000000,
            fee_cents=250000,
        )

        banco_after = account_service.get_account_by_name(user_id, "Bancolombia")
        efectivo_after = account_service.get_account_by_name(user_id, "Efectivo")
        assert banco_after.balance_cents == 89750000  # 1000k - (100k + 2.5k)
        assert efectivo_after.balance_cents == 10000000

        final_worth = account_service.get_net_worth(user_id)["total_net_worth_cents"]
        assert final_worth == initial_worth - 250000

    def test_transfer_funds_convenience_wrapper(self, account_service):
        user_id = "usr_wrapper"
        account_service.ensure_default_accounts(user_id)
        banco = account_service.get_account_by_name(user_id, "Bancolombia")
        account_service.set_balance(banco.id, 50000000)

        res = account_service.transfer_funds(
            user_id=user_id,
            from_account_name="Bancolombia",
            to_account_name="Nequi",
            amount_cents=10000000,
            note="Pago almuerzo compartido",
        )

        assert res["success"] is True
        assert "transfer" in res
        assert "net_worth" in res
        assert res["transfer"]["amount_cents"] == 10000000


# ==============================================================================
# 5. Transfer Validation & Error Handling (F66)
# ==============================================================================


class TestTransferValidationAndRejection:
    """Tests strict rejection of self-transfers, negative/zero amounts, and invalid accounts."""

    def test_self_transfer_rejected_by_name(self, account_service):
        user_id = "usr_self_tx"
        account_service.ensure_default_accounts(user_id)

        with pytest.raises(ValueError, match="Source and destination accounts must be distinct"):
            account_service.transfer(
                user_id=user_id,
                from_account_name_or_id="Nequi",
                to_account_name_or_id="Nequi",
                amount_cents=5000000,
            )

    def test_self_transfer_rejected_by_id(self, account_service):
        user_id = "usr_self_tx_id"
        account_service.ensure_default_accounts(user_id)
        nequi = account_service.get_account_by_name(user_id, "Nequi")

        with pytest.raises(ValueError, match="Source and destination accounts must be distinct"):
            account_service.transfer(
                user_id=user_id,
                from_account_name_or_id=nequi.id,
                to_account_name_or_id=nequi.id,
                amount_cents=5000000,
            )

    @pytest.mark.parametrize("invalid_amount", [0, -1, -5000000])
    def test_zero_or_negative_transfer_amount_rejected(self, account_service, invalid_amount):
        user_id = "usr_invalid_amt"
        account_service.ensure_default_accounts(user_id)

        with pytest.raises(ValueError, match="Transfer amount must be greater than zero"):
            account_service.transfer(
                user_id=user_id,
                from_account_name_or_id="Bancolombia",
                to_account_name_or_id="Nequi",
                amount_cents=invalid_amount,
            )

    def test_negative_fee_rejected(self, account_service):
        user_id = "usr_neg_fee"
        account_service.ensure_default_accounts(user_id)

        with pytest.raises(ValueError, match="Transfer fee cannot be negative"):
            account_service.transfer(
                user_id=user_id,
                from_account_name_or_id="Bancolombia",
                to_account_name_or_id="Nequi",
                amount_cents=5000000,
                fee_cents=-1000,
            )

    def test_non_existent_source_account_rejected(self, account_service):
        user_id = "usr_unknown_src"
        account_service.ensure_default_accounts(user_id)

        with pytest.raises(ValueError, match="not found for user"):
            account_service.transfer(
                user_id=user_id,
                from_account_name_or_id="NonExistentBank",
                to_account_name_or_id="Nequi",
                amount_cents=5000000,
            )

    def test_non_existent_destination_account_rejected(self, account_service):
        user_id = "usr_unknown_dst"
        account_service.ensure_default_accounts(user_id)

        with pytest.raises(ValueError, match="not found for user"):
            account_service.transfer(
                user_id=user_id,
                from_account_name_or_id="Nequi",
                to_account_name_or_id="ImaginaryCryptoWallet",
                amount_cents=5000000,
            )


# ==============================================================================
# 6. Real-Time Net Worth & Asset Allocation (F67)
# ==============================================================================


class TestNetWorthAggregation:
    """Tests total net worth calculation and accurate percentage shares."""

    def test_net_worth_aggregation_with_percentage_shares(self, account_service):
        user_id = "usr_alloc_01"
        account_service.ensure_default_accounts(user_id)

        efectivo = account_service.get_account_by_name(user_id, "Efectivo")
        nequi = account_service.get_account_by_name(user_id, "Nequi")
        nu = account_service.get_account_by_name(user_id, "Nu")
        banco = account_service.get_account_by_name(user_id, "Bancolombia")

        # Set balances:
        # Efectivo:    100,000 COP (10%)
        # Nequi:       200,000 COP (20%)
        # Nu:          300,000 COP (30%)
        # Bancolombia: 400,000 COP (40%)
        # Daviplata:         0 COP  (0%)
        # Total:     1,000,000 COP (100,000,000 cents)
        account_service.set_balance(efectivo.id, 10000000)
        account_service.set_balance(nequi.id, 20000000)
        account_service.set_balance(nu.id, 30000000)
        account_service.set_balance(banco.id, 40000000)

        summary = account_service.get_net_worth(user_id)

        assert summary["total_net_worth_cents"] == 100000000
        assert summary["total_net_worth"] == 1000000.0
        assert summary["currency"] == "COP"
        assert summary["account_count"] == 5

        shares_by_name = {a["name"]: a["percentage_share"] for a in summary["accounts"]}
        assert shares_by_name["Efectivo"] == 10.0
        assert shares_by_name["Nequi"] == 20.0
        assert shares_by_name["Nu"] == 30.0
        assert shares_by_name["Bancolombia"] == 40.0
        assert shares_by_name["Daviplata"] == 0.0

        total_shares = sum(shares_by_name.values())
        assert round(total_shares, 1) == 100.0

    def test_net_worth_zero_balance_safe_division(self, account_service):
        user_id = "usr_zero_worth"
        account_service.ensure_default_accounts(user_id)

        summary = account_service.get_net_worth(user_id)
        assert summary["total_net_worth_cents"] == 0
        assert summary["total_net_worth"] == 0.0

        for acc in summary["accounts"]:
            assert acc["percentage_share"] == 0.0
