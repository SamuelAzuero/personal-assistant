"""Debt repository: Typed data access layer for debts, loans/receivables, and payment settlements."""

import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Generator, List, Optional, Union

from app.database.connection import DatabaseManager, get_default_manager
from app.database.repositories.finance_repo import parse_datetime


class DebtType(str, Enum):
    DEBT = "debt"              # User owes money to counterparty (Por Pagar)
    RECEIVABLE = "receivable"  # Counterparty owes money to user (Por Cobrar / Préstamo)


class DebtStatus(str, Enum):
    ACTIVE = "active"
    PARTIALLY_PAID = "partially_paid"
    SETTLED = "settled"
    CANCELLED = "cancelled"


@dataclass
class DebtRecord:
    id: str
    user_id: str
    debt_type: DebtType
    counterparty: str
    amount_cents: int
    remaining_cents: int
    reason: str
    due_date: Optional[datetime] = None
    status: DebtStatus = DebtStatus.ACTIVE
    account_id: Optional[str] = None
    account_name: Optional[str] = None
    paid_amount_cents: int = 0
    created_at: Optional[datetime] = None
    settled_at: Optional[datetime] = None

    @property
    def debt_id(self) -> str:
        return self.id

    @property
    def remaining_amount_cents(self) -> int:
        return self.remaining_cents

    @property
    def amount(self) -> float:
        return round(self.amount_cents / 100.0, 2)

    @property
    def remaining(self) -> float:
        return round(self.remaining_cents / 100.0, 2)

    @property
    def remaining_amount(self) -> float:
        return self.remaining

    @property
    def paid_amount(self) -> float:
        return round(self.paid_amount_cents / 100.0, 2)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "debt_id": self.id,
            "user_id": self.user_id,
            "debt_type": self.debt_type.value,
            "type": self.debt_type.value,
            "counterparty": self.counterparty,
            "amount_cents": self.amount_cents,
            "amount": self.amount,
            "remaining_cents": self.remaining_cents,
            "remaining": self.remaining,
            "remaining_amount": self.remaining,
            "paid_amount_cents": self.paid_amount_cents,
            "paid_amount": self.paid_amount,
            "reason": self.reason,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "status": self.status.value,
            "account_id": self.account_id,
            "account_name": self.account_name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "settled_at": self.settled_at.isoformat() if self.settled_at else None,
        }


@dataclass
class DebtPaymentRecord:
    id: str
    debt_id: str
    user_id: str
    amount_cents: int
    account_id: Optional[str] = None
    account_name: Optional[str] = None
    notes: Optional[str] = None
    payment_date: Optional[datetime] = None
    created_at: Optional[datetime] = None

    @property
    def payment_id(self) -> str:
        return self.id

    @property
    def amount(self) -> float:
        return round(self.amount_cents / 100.0, 2)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "payment_id": self.id,
            "debt_id": self.debt_id,
            "user_id": self.user_id,
            "amount_cents": self.amount_cents,
            "amount": self.amount,
            "account_id": self.account_id,
            "account_name": self.account_name,
            "notes": self.notes,
            "payment_date": self.payment_date.isoformat() if self.payment_date else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class DebtRepository:
    """Repository for debts, receivables, and payment transactions."""

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

    def _row_to_debt(self, row: sqlite3.Row) -> DebtRecord:
        raw_due = row["due_date"]
        raw_created = row["created_at"]
        raw_settled = row["settled_at"]
        keys = row.keys()

        return DebtRecord(
            id=row["debt_id"],
            user_id=row["user_id"],
            debt_type=DebtType(row["debt_type"]),
            counterparty=row["counterparty"],
            amount_cents=row["amount_cents"],
            remaining_cents=row["remaining_cents"],
            reason=row["reason"],
            due_date=parse_datetime(raw_due) if raw_due else None,
            status=DebtStatus(row["status"]),
            account_id=row["account_id"] if "account_id" in keys else None,
            account_name=row["account_name"] if "account_name" in keys else None,
            paid_amount_cents=row["paid_amount_cents"] if "paid_amount_cents" in keys else 0,
            created_at=parse_datetime(raw_created) if raw_created else None,
            settled_at=parse_datetime(raw_settled) if raw_settled else None,
        )

    def _row_to_payment(self, row: sqlite3.Row) -> DebtPaymentRecord:
        raw_date = row["payment_date"]
        raw_created = row["created_at"]
        keys = row.keys()
        return DebtPaymentRecord(
            id=row["payment_id"],
            debt_id=row["debt_id"],
            user_id=row["user_id"],
            amount_cents=row["amount_cents"],
            account_id=row["account_id"] if "account_id" in keys else None,
            account_name=row["account_name"] if "account_name" in keys else None,
            notes=row["notes"] if "notes" in keys else None,
            payment_date=parse_datetime(raw_date) if raw_date else None,
            created_at=parse_datetime(raw_created) if raw_created else None,
        )

    def create_debt(
        self,
        user_id: str,
        debt_type: Union[DebtType, str],
        counterparty: str,
        amount_cents: int,
        reason: str,
        due_date: Optional[Union[datetime, str]] = None,
        account_id: Optional[str] = None,
        account_name: Optional[str] = None,
    ) -> DebtRecord:
        """Create a new debt or receivable record."""
        if not user_id or not str(user_id).strip():
            raise ValueError("User ID cannot be empty.")
        if not counterparty or not str(counterparty).strip():
            raise ValueError("Counterparty name cannot be empty.")
        if not reason or not str(reason).strip():
            raise ValueError("Debt reason cannot be empty.")
        if amount_cents <= 0:
            raise ValueError("Debt amount must be greater than zero.")

        resolved_type = DebtType(debt_type.value if hasattr(debt_type, "value") else str(debt_type).lower())
        debt_id = f"debt_{uuid.uuid4().hex[:12]}"
        due_dt = parse_datetime(due_date) if due_date else None
        iso_due = due_dt.isoformat() if due_dt else None
        now_time = datetime.now(timezone.utc)
        iso_created = now_time.isoformat()

        with self._connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users (user_id, full_name) VALUES (?, ?);",
                (user_id, user_id),
            )
            conn.execute(
                """
                INSERT INTO debts (
                    debt_id, user_id, debt_type, counterparty, amount_cents,
                    remaining_cents, reason, due_date, status, account_id,
                    account_name, paid_amount_cents, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, 0, ?);
                """,
                (
                    debt_id,
                    user_id,
                    resolved_type.value,
                    counterparty.strip(),
                    amount_cents,
                    amount_cents,
                    reason.strip(),
                    iso_due,
                    account_id,
                    account_name,
                    iso_created,
                ),
            )

        return DebtRecord(
            id=debt_id,
            user_id=user_id,
            debt_type=resolved_type,
            counterparty=counterparty.strip(),
            amount_cents=amount_cents,
            remaining_cents=amount_cents,
            reason=reason.strip(),
            due_date=due_dt,
            status=DebtStatus.ACTIVE,
            account_id=account_id,
            account_name=account_name,
            paid_amount_cents=0,
            created_at=now_time,
            settled_at=None,
        )

    def get_debt(self, debt_id: str) -> Optional[DebtRecord]:
        """Retrieve a debt record by ID."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM debts WHERE debt_id = ?;",
                (debt_id,),
            ).fetchone()
            if not row:
                return None
            return self._row_to_debt(row)

    def list_debts(
        self,
        user_id: str,
        debt_type: Optional[Union[DebtType, str]] = None,
        status: Optional[Union[DebtStatus, str]] = None,
        counterparty: Optional[str] = None,
    ) -> List[DebtRecord]:
        """Query debts/receivables with optional filtering."""
        query = "SELECT * FROM debts WHERE user_id = ?"
        params: List[Any] = [user_id]

        if debt_type is not None:
            dt_str = debt_type.value if hasattr(debt_type, "value") else str(debt_type).lower()
            query += " AND debt_type = ?"
            params.append(dt_str)

        if status is not None:
            st_str = status.value if hasattr(status, "value") else str(status).lower()
            query += " AND status = ?"
            params.append(st_str)

        if counterparty is not None and counterparty.strip():
            query += " AND LOWER(counterparty) LIKE LOWER(?)"
            params.append(f"%{counterparty.strip()}%")

        query += " ORDER BY due_date ASC NULLS LAST, created_at DESC;"

        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_debt(r) for r in rows]

    def add_payment(
        self,
        debt_id: str,
        user_id: str,
        amount_cents: int,
        account_id: Optional[str] = None,
        account_name: Optional[str] = None,
        notes: Optional[str] = None,
        payment_date: Optional[Union[datetime, str]] = None,
    ) -> DebtPaymentRecord:
        """Apply a partial or full payment to a debt record, transitioning status."""
        debt = self.get_debt(debt_id)
        if not debt:
            raise ValueError(f"Debt with ID '{debt_id}' does not exist.")
        if debt.user_id != user_id:
            raise ValueError("Unauthorized: debt belongs to another user.")
        if debt.status in (DebtStatus.SETTLED, DebtStatus.CANCELLED):
            raise ValueError("Debt is already settled or cancelled.")
        if amount_cents <= 0:
            raise ValueError("Payment amount must be greater than zero.")
        if amount_cents > debt.remaining_cents:
            raise ValueError(
                f"Settlement amount (${amount_cents / 100:.2f}) exceeds remaining balance (${debt.remaining_cents / 100:.2f})."
            )

        new_remaining = debt.remaining_cents - amount_cents
        new_paid = debt.paid_amount_cents + amount_cents
        is_fully_settled = new_remaining == 0
        new_status = DebtStatus.SETTLED if is_fully_settled else DebtStatus.PARTIALLY_PAID

        payment_id = f"pay_{uuid.uuid4().hex[:12]}"
        pay_dt = parse_datetime(payment_date) if payment_date else datetime.now(timezone.utc)
        iso_pay = pay_dt.isoformat()
        now_time = datetime.now(timezone.utc)
        iso_now = now_time.isoformat()
        settled_iso = iso_now if is_fully_settled else None

        with self._connection() as conn:
            # 1. Insert payment row
            conn.execute(
                """
                INSERT INTO debt_payments (
                    payment_id, debt_id, user_id, amount_cents, account_id,
                    account_name, notes, payment_date, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    payment_id,
                    debt_id,
                    user_id,
                    amount_cents,
                    account_id,
                    account_name,
                    notes,
                    iso_pay,
                    iso_now,
                ),
            )
            # 2. Update debt record
            conn.execute(
                """
                UPDATE debts
                SET remaining_cents = ?,
                    paid_amount_cents = ?,
                    status = ?,
                    settled_at = ?
                WHERE debt_id = ?;
                """,
                (
                    new_remaining,
                    new_paid,
                    new_status.value,
                    settled_iso,
                    debt_id,
                ),
            )

        return DebtPaymentRecord(
            id=payment_id,
            debt_id=debt_id,
            user_id=user_id,
            amount_cents=amount_cents,
            account_id=account_id,
            account_name=account_name,
            notes=notes,
            payment_date=pay_dt,
            created_at=now_time,
        )

    def list_payments(self, debt_id: str) -> List[DebtPaymentRecord]:
        """List all payments for a given debt."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM debt_payments WHERE debt_id = ? ORDER BY payment_date ASC;",
                (debt_id,),
            ).fetchall()
            return [self._row_to_payment(r) for r in rows]

    def get_debt_summary(self, user_id: str) -> Dict[str, Any]:
        """Aggregate total debts owed and receivables outstanding."""
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT debt_type, status, SUM(remaining_cents) as total_remaining, COUNT(*) as count
                FROM debts
                WHERE user_id = ? AND status IN ('active', 'partially_paid')
                GROUP BY debt_type, status;
                """,
                (user_id,),
            ).fetchall()

            total_debt_cents = 0
            total_receivable_cents = 0
            active_debts_count = 0
            active_receivables_count = 0

            for r in rows:
                dtype = r["debt_type"]
                rem = r["total_remaining"] or 0
                cnt = r["count"] or 0
                if dtype == DebtType.DEBT.value:
                    total_debt_cents += rem
                    active_debts_count += cnt
                elif dtype == DebtType.RECEIVABLE.value:
                    total_receivable_cents += rem
                    active_receivables_count += cnt

            net_pos_cents = total_receivable_cents - total_debt_cents

            return {
                "user_id": user_id,
                "total_debt_cents": total_debt_cents,
                "total_debt": round(total_debt_cents / 100.0, 2),
                "total_receivable_cents": total_receivable_cents,
                "total_receivable": round(total_receivable_cents / 100.0, 2),
                "net_position_cents": net_pos_cents,
                "net_position": round(net_pos_cents / 100.0, 2),
                "net_debt_position_cents": net_pos_cents,
                "net_debt_position": round(net_pos_cents / 100.0, 2),
                "active_debts_count": active_debts_count,
                "active_receivables_count": active_receivables_count,
            }
