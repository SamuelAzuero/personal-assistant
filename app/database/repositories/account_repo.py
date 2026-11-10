"""Account repository: Typed data access layer for multi-account banking and inter-account transfers."""

import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional, Tuple, Union

from app.database.connection import (
    DatabaseManager,
    get_default_manager,
    seed_default_accounts_for_user,
)
from app.database.repositories.finance_repo import parse_datetime


@dataclass
class AccountRecord:
    id: str
    user_id: str
    name: str
    account_type: str = "digital_wallet"
    balance_cents: int = 0
    currency: str = "COP"
    color: Optional[str] = None
    icon: Optional[str] = None
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @property
    def account_id(self) -> str:
        return self.id

    @property
    def balance(self) -> float:
        """Helper property providing amount in standard currency units."""
        return round(self.balance_cents / 100.0, 2)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "account_id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "account_type": self.account_type,
            "balance_cents": self.balance_cents,
            "balance": self.balance,
            "current_balance": self.balance,
            "currency": self.currency,
            "color": self.color,
            "icon": self.icon,
            "is_active": bool(self.is_active),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


@dataclass
class TransferRecord:
    id: str
    user_id: str
    from_account_id: str
    to_account_id: str
    amount_cents: int
    fee_cents: int = 0
    description: Optional[str] = None
    from_account_name: Optional[str] = None
    to_account_name: Optional[str] = None
    timestamp: Optional[datetime] = None
    created_at: Optional[datetime] = None

    @property
    def transfer_id(self) -> str:
        return self.id

    @property
    def amount(self) -> float:
        return round(self.amount_cents / 100.0, 2)

    @property
    def fee(self) -> float:
        return round(self.fee_cents / 100.0, 2)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "transfer_id": self.id,
            "user_id": self.user_id,
            "from_account_id": self.from_account_id,
            "to_account_id": self.to_account_id,
            "from_account_name": self.from_account_name,
            "to_account_name": self.to_account_name,
            "amount_cents": self.amount_cents,
            "amount": self.amount,
            "fee_cents": self.fee_cents,
            "fee": self.fee,
            "description": self.description,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AccountRepository:
    """Repository for user accounts and inter-account transfers."""

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        conn: Optional[sqlite3.Connection] = None,
    ):
        self._conn = conn
        self.db = db_manager or (get_default_manager() if conn is None else None)

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        if self._conn is not None:
            yield self._conn
        elif self.db is not None:
            with self.db.connection() as conn:
                yield conn
        else:
            with get_default_manager().connection() as conn:
                yield conn

    def _row_to_account(self, row: sqlite3.Row) -> AccountRecord:
        raw_created = row["created_at"]
        raw_updated = row["updated_at"]
        return AccountRecord(
            id=row["account_id"],
            user_id=row["user_id"],
            name=row["name"],
            account_type=row["account_type"],
            balance_cents=row["balance_cents"],
            currency=row["currency"],
            color=row["color"],
            icon=row["icon"],
            is_active=bool(row["is_active"]),
            created_at=parse_datetime(raw_created) if raw_created else None,
            updated_at=parse_datetime(raw_updated) if raw_updated else None,
        )

    def _row_to_transfer(self, row: sqlite3.Row) -> TransferRecord:
        raw_ts = row["timestamp"]
        raw_created = row["created_at"]
        keys = row.keys()
        return TransferRecord(
            id=row["transfer_id"],
            user_id=row["user_id"],
            from_account_id=row["from_account_id"],
            to_account_id=row["to_account_id"],
            amount_cents=row["amount_cents"],
            fee_cents=row["fee_cents"],
            description=row["description"],
            from_account_name=row["from_account_name"] if "from_account_name" in keys else None,
            to_account_name=row["to_account_name"] if "to_account_name" in keys else None,
            timestamp=parse_datetime(raw_ts) if raw_ts else None,
            created_at=parse_datetime(raw_created) if raw_created else None,
        )

    def ensure_default_accounts(self, user_id: str) -> List[AccountRecord]:
        """Ensure user exists and has all 5 default Colombian accounts."""
        with self._connection() as conn:
            seed_default_accounts_for_user(conn, user_id)
        return self.list_accounts(user_id)

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
        """Create a new custom account with case-insensitive name uniqueness check."""
        if not user_id or not str(user_id).strip():
            raise ValueError("User ID cannot be empty.")
        if not name or not str(name).strip():
            raise ValueError("Account name cannot be empty.")

        clean_name = str(name).strip()
        existing = self.get_account_by_name(user_id, clean_name)
        if existing:
            raise ValueError(f"Account '{clean_name}' already exists for user.")

        acc_id = f"acc_{uuid.uuid4().hex[:12]}"
        now_time = datetime.now(timezone.utc)
        iso_now = now_time.isoformat()

        with self._connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users (user_id, full_name) VALUES (?, ?);",
                (user_id, user_id),
            )
            conn.execute(
                """
                INSERT INTO accounts (
                    account_id, user_id, name, account_type, balance_cents,
                    currency, color, icon, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?);
                """,
                (
                    acc_id,
                    user_id,
                    clean_name,
                    account_type,
                    initial_balance_cents,
                    currency,
                    color,
                    icon,
                    iso_now,
                    iso_now,
                ),
            )

        return AccountRecord(
            id=acc_id,
            user_id=user_id,
            name=clean_name,
            account_type=account_type,
            balance_cents=initial_balance_cents,
            currency=currency,
            color=color,
            icon=icon,
            is_active=True,
            created_at=now_time,
            updated_at=now_time,
        )

    def get_account(self, account_id: str) -> Optional[AccountRecord]:
        """Retrieve account by ID."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM accounts WHERE account_id = ?;",
                (account_id,),
            ).fetchone()
            if not row:
                return None
            return self._row_to_account(row)

    def get_account_by_name(self, user_id: str, name: str) -> Optional[AccountRecord]:
        """Retrieve account by user ID and name (case-insensitive)."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM accounts WHERE user_id = ? AND LOWER(name) = LOWER(?);",
                (user_id, name.strip()),
            ).fetchone()
            if not row:
                return None
            return self._row_to_account(row)

    def list_accounts(self, user_id: str, active_only: bool = True) -> List[AccountRecord]:
        """List accounts for a user."""
        query = "SELECT * FROM accounts WHERE user_id = ?"
        params: List[Any] = [user_id]
        if active_only:
            query += " AND is_active = 1"
        query += " ORDER BY created_at ASC;"

        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_account(r) for r in rows]

    def update_balance(self, account_id: str, delta_cents: int) -> AccountRecord:
        """Atomically adjust account balance by delta_cents."""
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE accounts
                SET balance_cents = balance_cents + ?, updated_at = CURRENT_TIMESTAMP
                WHERE account_id = ?;
                """,
                (delta_cents, account_id),
            )
            row = conn.execute(
                "SELECT * FROM accounts WHERE account_id = ?;",
                (account_id,),
            ).fetchone()
            if not row:
                raise ValueError(f"Account '{account_id}' does not exist.")
            return self._row_to_account(row)

    def set_balance(self, account_id: str, new_balance_cents: int) -> AccountRecord:
        """Set account balance to an explicit value."""
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE accounts
                SET balance_cents = ?, updated_at = CURRENT_TIMESTAMP
                WHERE account_id = ?;
                """,
                (new_balance_cents, account_id),
            )
            row = conn.execute(
                "SELECT * FROM accounts WHERE account_id = ?;",
                (account_id,),
            ).fetchone()
            if not row:
                raise ValueError(f"Account '{account_id}' does not exist.")
            return self._row_to_account(row)

    def execute_balance_operation(
        self,
        user_id: str,
        account_id: str,
        delta_cents: int,
        transaction_type: str,
        category: str,
        description: str,
        timestamp: Optional[Union[datetime, str]] = None,
    ) -> Tuple[AccountRecord, Dict[str, Any]]:
        """Atomically adjust account balance and record ledger transaction in a single SQLite transaction."""
        tx_id = f"tx_{uuid.uuid4().hex[:12]}"
        ts = parse_datetime(timestamp) if timestamp else datetime.now(timezone.utc)
        now_time = datetime.now(timezone.utc)
        iso_ts = ts.isoformat()
        iso_created = now_time.isoformat()

        with self._connection() as conn:
            conn.execute(
                """
                UPDATE accounts
                SET balance_cents = balance_cents + ?, updated_at = CURRENT_TIMESTAMP
                WHERE account_id = ?;
                """,
                (delta_cents, account_id),
            )
            row = conn.execute(
                "SELECT * FROM accounts WHERE account_id = ?;",
                (account_id,),
            ).fetchone()
            if not row:
                raise ValueError(f"Account '{account_id}' does not exist.")
            acc = self._row_to_account(row)

            conn.execute(
                """
                INSERT INTO transactions (
                    transaction_id, user_id, amount_cents, transaction_type,
                    category, description, timestamp, created_at,
                    account_id, account_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    tx_id,
                    user_id,
                    abs(delta_cents),
                    transaction_type,
                    category.strip(),
                    description.strip(),
                    iso_ts,
                    iso_created,
                    acc.id,
                    acc.name,
                ),
            )

        tx_dict = {
            "id": tx_id,
            "transaction_id": tx_id,
            "user_id": user_id,
            "amount_cents": abs(delta_cents),
            "amount": round(abs(delta_cents) / 100.0, 2),
            "type": transaction_type,
            "transaction_type": transaction_type,
            "category": category.strip(),
            "description": description.strip(),
            "timestamp": iso_ts,
            "created_at": iso_created,
            "account_id": acc.id,
            "account_name": acc.name,
        }
        return acc, tx_dict

    def log_transfer(
        self,
        user_id: str,
        from_account_id: str,
        to_account_id: str,
        amount_cents: int,
        fee_cents: int = 0,
        description: Optional[str] = None,
        from_account_name: Optional[str] = None,
        to_account_name: Optional[str] = None,
        timestamp: Optional[Union[datetime, str]] = None,
    ) -> TransferRecord:
        """Record an inter-account transfer in the transfers ledger."""
        transfer_id = f"tr_{uuid.uuid4().hex[:12]}"
        ts = parse_datetime(timestamp)
        now_time = datetime.now(timezone.utc)
        iso_ts = ts.isoformat()
        iso_created = now_time.isoformat()

        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO transfers (
                    transfer_id, user_id, from_account_id, to_account_id,
                    from_account_name, to_account_name,
                    amount_cents, fee_cents, description, timestamp, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    transfer_id,
                    user_id,
                    from_account_id,
                    to_account_id,
                    from_account_name,
                    to_account_name,
                    amount_cents,
                    fee_cents,
                    description,
                    iso_ts,
                    iso_created,
                ),
            )

        return TransferRecord(
            id=transfer_id,
            user_id=user_id,
            from_account_id=from_account_id,
            to_account_id=to_account_id,
            amount_cents=amount_cents,
            fee_cents=fee_cents,
            description=description,
            from_account_name=from_account_name,
            to_account_name=to_account_name,
            timestamp=ts,
            created_at=now_time,
        )

    def list_transfers(self, user_id: str, limit: int = 50) -> List[TransferRecord]:
        """List recent transfers for user."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM transfers WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?;",
                (user_id, limit),
            ).fetchall()
            return [self._row_to_transfer(r) for r in rows]
