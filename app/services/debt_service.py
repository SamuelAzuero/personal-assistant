"""DebtService: Domain service managing bilateral debts, loans/receivables, and account-linked settlements."""

import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from app.database.connection import DatabaseManager, get_default_manager
from app.database.repositories.debt_repo import (
    DebtRecord,
    DebtRepository,
    DebtStatus,
    DebtType,
)
from app.services.account_service import AccountService


class DebtService:
    """Service providing debt/receivable creation, querying, and account-linked settlement lifecycle."""

    def __init__(
        self,
        repository: Optional[DebtRepository] = None,
        account_service: Optional[AccountService] = None,
        db_manager: Optional[DatabaseManager] = None,
        conn: Optional[sqlite3.Connection] = None,
    ):
        if repository is not None:
            self.repo = repository
        elif conn is not None:
            self.repo = DebtRepository(conn=conn)
        else:
            self.repo = DebtRepository(db_manager=db_manager or get_default_manager())

        if account_service is not None:
            self.account_service = account_service
        elif conn is not None:
            self.account_service = AccountService(conn=conn)
        else:
            self.account_service = AccountService(db_manager=db_manager or get_default_manager())

    def _resolve_or_create_account(
        self,
        user_id: str,
        account_name: Optional[str] = None,
        account_id: Optional[str] = None,
    ) -> Any:
        """Resolve account by ID, name, or default to Efectivo."""
        self.account_service.ensure_default_accounts(user_id)

        if account_id:
            acc = self.account_service.get_account(account_id)
            if acc and acc.user_id == user_id:
                return acc

        target_name = account_name.strip() if account_name and account_name.strip() else "Efectivo"
        acc = self.account_service.get_account_by_name(user_id, target_name)
        if acc:
            return acc

        # Create custom account if it doesn't exist
        return self.account_service.create_account(user_id, target_name)

    def record_debt(
        self,
        user_id: str,
        counterparty: str,
        amount_cents: int,
        debt_type: Union[DebtType, str],
        reason: str,
        due_date: Optional[Union[datetime, str]] = None,
        account_name: Optional[str] = None,
        account_id: Optional[str] = None,
        adjust_account_balance: bool = True,
    ) -> DebtRecord:
        """Record a debt (owed to others) or receivable/loan (owed by others).

        Accounting links:
        - Receivable (lending money): Debits account balance (outflow).
        - Debt (borrowing money): Credits account balance (inflow).
        """
        if not user_id or not str(user_id).strip():
            raise ValueError("User ID cannot be empty.")
        if not counterparty or not str(counterparty).strip():
            raise ValueError("Counterparty name cannot be empty.")
        if not reason or not str(reason).strip():
            raise ValueError("Debt reason cannot be empty.")
        if amount_cents <= 0:
            raise ValueError("Debt amount must be greater than zero.")

        resolved_type = DebtType(debt_type.value if hasattr(debt_type, "value") else str(debt_type).lower())
        account = self._resolve_or_create_account(user_id, account_name, account_id)

        # Apply initial cash flow if requested
        if adjust_account_balance and account:
            if resolved_type == DebtType.RECEIVABLE:
                # Disbursing a loan to someone -> user's account is debited (outflow)
                self.account_service.adjust_balance(account.id, -amount_cents)
            elif resolved_type == DebtType.DEBT:
                # Borrowing funds from someone -> user's account is credited (inflow)
                self.account_service.adjust_balance(account.id, amount_cents)

        return self.repo.create_debt(
            user_id=user_id.strip(),
            debt_type=resolved_type,
            counterparty=counterparty.strip(),
            amount_cents=amount_cents,
            reason=reason.strip(),
            due_date=due_date,
            account_id=account.id if account else None,
            account_name=account.name if account else None,
        )

    def record_payment(
        self,
        user_id: str,
        debt_id: str,
        amount_cents: int,
        account_name: Optional[str] = None,
        account_id: Optional[str] = None,
        notes: Optional[str] = None,
        payment_date: Optional[Union[datetime, str]] = None,
        adjust_account_balance: bool = True,
    ) -> Dict[str, Any]:
        """Apply a settlement payment to a debt or receivable.

        Accounting links:
        - Receivable payment (counterparty pays user): Credits account balance (inflow).
        - Debt payment (user repays counterparty): Debits account balance (outflow).
        """
        if not user_id or not str(user_id).strip():
            raise ValueError("User ID cannot be empty.")
        if amount_cents <= 0:
            raise ValueError("Settlement payment amount must be greater than zero.")

        debt = self.repo.get_debt(debt_id)
        if not debt:
            raise ValueError(f"Debt with ID '{debt_id}' does not exist.")
        if debt.user_id != user_id:
            raise ValueError("Unauthorized: debt belongs to another user.")
        if debt.status in (DebtStatus.SETTLED, DebtStatus.CANCELLED):
            raise ValueError("Debt is already settled or cancelled.")
        if amount_cents > debt.remaining_cents:
            raise ValueError(
                f"Settlement amount (${amount_cents / 100:.2f}) exceeds remaining balance (${debt.remaining_cents / 100:.2f})."
            )

        # Resolve settlement account
        if account_name:
            account = self._resolve_or_create_account(user_id, account_name, account_id)
        else:
            account = self._resolve_or_create_account(user_id, debt.account_name, account_id or debt.account_id)

        # Apply settlement cash flow
        if adjust_account_balance and account:
            if debt.debt_type == DebtType.RECEIVABLE:
                # Counterparty repays user -> user's account is credited (inflow)
                self.account_service.adjust_balance(account.id, amount_cents)
            elif debt.debt_type == DebtType.DEBT:
                # User repays debt to counterparty -> user's account is debited (outflow)
                self.account_service.adjust_balance(account.id, -amount_cents)

        payment_record = self.repo.add_payment(
            debt_id=debt_id,
            user_id=user_id,
            amount_cents=amount_cents,
            account_id=account.id if account else None,
            account_name=account.name if account else None,
            notes=notes,
            payment_date=payment_date,
        )

        updated_debt = self.repo.get_debt(debt_id)

        return {
            "success": True,
            "payment": payment_record.to_dict(),
            "debt": updated_debt.to_dict() if updated_debt else None,
            "settled": updated_debt.status == DebtStatus.SETTLED if updated_debt else False,
            "account_id": account.id if account else None,
            "account_name": account.name if account else None,
        }

    def settle_debt(
        self,
        user_id: str,
        debt_id: str,
        account_name: Optional[str] = None,
        account_id: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Settle entire remaining amount of an outstanding debt or receivable."""
        debt = self.repo.get_debt(debt_id)
        if not debt:
            raise ValueError(f"Debt with ID '{debt_id}' does not exist.")
        if debt.status in (DebtStatus.SETTLED, DebtStatus.CANCELLED):
            raise ValueError("Debt is already settled or cancelled.")

        return self.record_payment(
            user_id=user_id,
            debt_id=debt_id,
            amount_cents=debt.remaining_cents,
            account_name=account_name,
            account_id=account_id,
            notes=notes or "Full settlement",
        )

    def get_debt(self, debt_id: str) -> Optional[DebtRecord]:
        """Retrieve a debt record by ID."""
        return self.repo.get_debt(debt_id)

    def list_debts(
        self,
        user_id: str,
        debt_type: Optional[Union[DebtType, str]] = None,
        status: Optional[Union[DebtStatus, str]] = None,
        counterparty: Optional[str] = None,
    ) -> List[DebtRecord]:
        """Query user's debts and receivables with optional filters."""
        if not user_id or not str(user_id).strip():
            raise ValueError("User ID cannot be empty.")
        return self.repo.list_debts(
            user_id=user_id.strip(),
            debt_type=debt_type,
            status=status,
            counterparty=counterparty,
        )

    def get_debt_summary(self, user_id: str) -> Dict[str, Any]:
        """Get aggregate metrics on outstanding debts and loans."""
        if not user_id or not str(user_id).strip():
            raise ValueError("User ID cannot be empty.")
        return self.repo.get_debt_summary(user_id.strip())
