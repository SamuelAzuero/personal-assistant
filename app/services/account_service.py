"""AccountService: Domain service managing multi-account balances, net worth, and invariant-preserving transfers."""

import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from app.database.connection import DatabaseManager, get_default_manager
from app.database.repositories.account_repo import (
    AccountRecord,
    AccountRepository,
    TransferRecord,
)


class AccountService:
    """Service providing multi-account balance queries, creation, and zero-loss transfers."""

    def __init__(
        self,
        repository: Optional[AccountRepository] = None,
        db_manager: Optional[DatabaseManager] = None,
        conn: Optional[sqlite3.Connection] = None,
    ):
        if repository is not None:
            self.repo = repository
        elif conn is not None:
            self.repo = AccountRepository(conn=conn)
        else:
            self.repo = AccountRepository(db_manager=db_manager or get_default_manager())

    def ensure_default_accounts(self, user_id: str) -> List[AccountRecord]:
        """Ensure all 5 default Colombian accounts (Efectivo, Nequi, Nu, Daviplata, Bancolombia) exist."""
        if not user_id or not str(user_id).strip():
            raise ValueError("User ID cannot be empty.")
        return self.repo.ensure_default_accounts(user_id.strip())

    # Alias for API compatibility
    initialize_default_accounts = ensure_default_accounts

    def create_account(
        self,
        user_id: str,
        name: str,
        account_type: str = "digital_wallet",
        initial_balance_cents: int = 0,
        currency: str = "COP",
        color: Optional[str] = None,
        icon: Optional[str] = None,
    ) -> AccountRecord:
        """Create a new custom account with unique case-insensitive name."""
        return self.repo.create_account(
            user_id=user_id.strip(),
            name=name.strip(),
            account_type=account_type.strip(),
            initial_balance_cents=initial_balance_cents,
            currency=currency.strip(),
            color=color,
            icon=icon,
        )

    def get_accounts(self, user_id: str, active_only: bool = True) -> List[AccountRecord]:
        """Retrieve all accounts for a user."""
        if not user_id or not str(user_id).strip():
            raise ValueError("User ID cannot be empty.")
        return self.repo.list_accounts(user_id.strip(), active_only=active_only)

    def list_accounts(self, user_id: str, active_only: bool = True) -> List[AccountRecord]:
        """Alias for get_accounts."""
        return self.get_accounts(user_id, active_only=active_only)

    def get_account(self, account_id: str) -> Optional[AccountRecord]:
        """Retrieve account by ID."""
        return self.repo.get_account(account_id)

    def get_account_by_name(self, user_id: str, name: str) -> Optional[AccountRecord]:
        """Retrieve account by name (case-insensitive)."""
        return self.repo.get_account_by_name(user_id, name)

    def adjust_balance(self, account_id: str, delta_cents: int) -> AccountRecord:
        """Atomically adjust account balance by integer cents."""
        return self.repo.update_balance(account_id, delta_cents)

    def set_balance(self, account_id: str, new_balance_cents: int) -> AccountRecord:
        """Set explicit balance for an account."""
        return self.repo.set_balance(account_id, new_balance_cents)

    update_balance = set_balance

    def _resolve_account(self, user_id: str, identifier: str) -> AccountRecord:
        """Resolve account by ID or Name."""
        clean_id = identifier.strip()
        acc = self.repo.get_account(clean_id)
        if acc and acc.user_id == user_id:
            return acc
        acc_by_name = self.repo.get_account_by_name(user_id, clean_id)
        if acc_by_name:
            return acc_by_name
        raise ValueError(f"Account '{clean_id}' not found for user '{user_id}'.")

    def transfer(
        self,
        user_id: str,
        from_account_name_or_id: str,
        to_account_name_or_id: str,
        amount_cents: int,
        fee_cents: int = 0,
        description: str = "",
        timestamp: Optional[Union[datetime, str]] = None,
    ) -> TransferRecord:
        """Execute an inter-account transfer guaranteeing exact zero net wealth loss (Delta Net Worth = 0 when fee=0)."""
        if not user_id or not str(user_id).strip():
            raise ValueError("User ID cannot be empty.")
        if amount_cents <= 0:
            raise ValueError("Transfer amount must be greater than zero.")
        if fee_cents < 0:
            raise ValueError("Transfer fee cannot be negative.")

        # Ensure default accounts are seeded if user has no accounts yet
        self.ensure_default_accounts(user_id)

        from_acc = self._resolve_account(user_id, from_account_name_or_id)
        to_acc = self._resolve_account(user_id, to_account_name_or_id)

        if from_acc.id == to_acc.id:
            raise ValueError("Source and destination accounts must be distinct.")

        # Record pre-transfer net worth for invariance verification
        pre_net_worth = self.get_net_worth(user_id)["total_net_worth_cents"]

        # Perform atomic balance updates
        total_outflow = amount_cents + fee_cents
        self.adjust_balance(from_acc.id, -total_outflow)
        self.adjust_balance(to_acc.id, amount_cents)

        # Log transfer event
        record = self.repo.log_transfer(
            user_id=user_id,
            from_account_id=from_acc.id,
            to_account_id=to_acc.id,
            amount_cents=amount_cents,
            fee_cents=fee_cents,
            description=description.strip() if description else None,
            from_account_name=from_acc.name,
            to_account_name=to_acc.name,
            timestamp=timestamp,
        )

        # Invariant check: Net Worth Preservation
        post_net_worth = self.get_net_worth(user_id)["total_net_worth_cents"]
        expected_post = pre_net_worth - fee_cents
        if post_net_worth != expected_post:
            raise RuntimeError(
                f"Net worth invariance check failed: pre={pre_net_worth}, post={post_net_worth}, expected={expected_post}"
            )

        return record

    def transfer_funds(
        self,
        user_id: str,
        from_account_name: str,
        to_account_name: str,
        amount_cents: int,
        fee_cents: int = 0,
        note: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Convenience wrapper for transfer returning dictionary response."""
        record = self.transfer(
            user_id=user_id,
            from_account_name_or_id=from_account_name,
            to_account_name_or_id=to_account_name,
            amount_cents=amount_cents,
            fee_cents=fee_cents,
            description=note or kwargs.get("description", ""),
        )
        return {
            "success": True,
            "transfer": record.to_dict(),
            "net_worth": self.get_net_worth(user_id),
        }

    def get_net_worth(self, user_id: str) -> Dict[str, Any]:
        """Calculate total net worth and asset allocation percentages across all active accounts."""
        if not user_id or not str(user_id).strip():
            raise ValueError("User ID cannot be empty.")

        accounts = self.get_accounts(user_id, active_only=True)
        total_cents = sum(a.balance_cents for a in accounts)

        accounts_data = []
        for a in accounts:
            a_dict = a.to_dict()
            if total_cents > 0:
                share = round((max(0, a.balance_cents) / total_cents) * 100.0, 2)
            else:
                share = 0.0
            a_dict["percentage_share"] = share
            accounts_data.append(a_dict)

        return {
            "user_id": user_id,
            "total_net_worth_cents": total_cents,
            "total_net_worth": round(total_cents / 100.0, 2),
            "currency": "COP",
            "accounts": accounts_data,
            "account_count": len(accounts),
        }

    def get_net_worth_summary(self, user_id: str) -> Any:
        """Alias returning net worth summary object supporting attribute and dict access."""
        nw = self.get_net_worth(user_id)

        class _Summary:
            def __init__(self, data):
                self.__dict__.update(data)

            def __getitem__(self, key):
                return self.__dict__[key]

        return _Summary(nw)

    def list_transfers(self, user_id: str, limit: int = 50) -> List[TransferRecord]:
        """List past inter-account transfers."""
        return self.repo.list_transfers(user_id, limit=limit)
