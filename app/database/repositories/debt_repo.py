"""Debt repository: Typed data access layer for debts, loans/receivables, and payment settlements."""

import calendar
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
    # Installment fields (M12 / R3)
    is_installment: bool = False
    total_installments: int = 1
    remaining_installments: int = 1
    installment_amount_cents: int = 0
    payment_frequency: str = "monthly"
    next_installment_due_date: Optional[datetime] = None
    updated_at: Optional[datetime] = None

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

    @property
    def installment_amount(self) -> float:
        return round(self.installment_amount_cents / 100.0, 2)

    @property
    def installments_paid(self) -> int:
        if not self.is_installment:
            return 0
        return max(0, self.total_installments - self.remaining_installments)

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
            # Installment additions (M12 / R3)
            "is_installment": bool(self.is_installment),
            "total_installments": self.total_installments,
            "remaining_installments": self.remaining_installments,
            "installment_amount_cents": self.installment_amount_cents,
            "installment_amount": self.installment_amount,
            "payment_frequency": self.payment_frequency,
            "next_installment_due_date": (
                self.next_installment_due_date.isoformat() if self.next_installment_due_date else None
            ),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "installments_paid": self.installments_paid,
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
    installments_paid: int = 1

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
            "installments_paid": self.installments_paid,
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
        keys = row.keys()
        raw_due = row["due_date"]
        raw_created = row["created_at"]
        raw_settled = row["settled_at"]
        raw_next_due = row["next_installment_due_date"] if "next_installment_due_date" in keys else None
        raw_updated = row["updated_at"] if "updated_at" in keys else None

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
            is_installment=(
                bool(row["is_installment"])
                if "is_installment" in keys and row["is_installment"] is not None
                else False
            ),
            total_installments=(
                row["total_installments"]
                if "total_installments" in keys and row["total_installments"] is not None
                else 1
            ),
            remaining_installments=(
                row["remaining_installments"]
                if "remaining_installments" in keys and row["remaining_installments"] is not None
                else 1
            ),
            installment_amount_cents=(
                row["installment_amount_cents"]
                if "installment_amount_cents" in keys and row["installment_amount_cents"] is not None
                else 0
            ),
            payment_frequency=(
                row["payment_frequency"]
                if "payment_frequency" in keys and row["payment_frequency"] is not None
                else "monthly"
            ),
            next_installment_due_date=parse_datetime(raw_next_due) if raw_next_due else None,
            updated_at=parse_datetime(raw_updated) if raw_updated else None,
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
            installments_paid=(
                row["installments_paid"]
                if "installments_paid" in keys and row["installments_paid"] is not None
                else 1
            ),
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
        is_installment: bool = False,
        total_installments: int = 1,
        remaining_installments: Optional[int] = None,
        installment_amount_cents: Optional[int] = None,
        payment_frequency: str = "monthly",
        next_installment_due_date: Optional[Union[datetime, str]] = None,
    ) -> DebtRecord:
        """Create a new debt or receivable record with optional installment terms."""
        if not user_id or not str(user_id).strip():
            raise ValueError("User ID cannot be empty.")
        if not counterparty or not str(counterparty).strip():
            raise ValueError("Counterparty name cannot be empty.")
        if not reason or not str(reason).strip():
            raise ValueError("Debt reason cannot be empty.")
        if amount_cents <= 0:
            raise ValueError("Debt amount must be greater than zero.")

        if is_installment:
            if total_installments <= 0:
                raise ValueError("Total installments must be greater than zero.")
            rem_inst = total_installments if remaining_installments is None else remaining_installments
            inst_amt = (
                (amount_cents // total_installments)
                if installment_amount_cents is None
                else installment_amount_cents
            )
        else:
            total_installments = 1
            rem_inst = 1
            inst_amt = 0

        resolved_type = DebtType(debt_type.value if hasattr(debt_type, "value") else str(debt_type).lower())
        debt_id = f"debt_{uuid.uuid4().hex[:12]}"
        due_dt = parse_datetime(due_date) if due_date else None
        iso_due = due_dt.isoformat() if due_dt else None
        next_due_dt = parse_datetime(next_installment_due_date) if next_installment_due_date else due_dt
        iso_next_due = next_due_dt.isoformat() if next_due_dt else None
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
                    account_name, paid_amount_cents, created_at, updated_at,
                    is_installment, total_installments, remaining_installments,
                    installment_amount_cents, payment_frequency, next_installment_due_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?);
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
                    iso_created,
                    1 if is_installment else 0,
                    total_installments,
                    rem_inst,
                    inst_amt,
                    payment_frequency,
                    iso_next_due,
                ),
            )

        updated_record = self.get_debt(debt_id)
        if not updated_record:
            raise ValueError(f"Failed to retrieve created debt '{debt_id}'.")
        return updated_record

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

    def update_debt(self, debt_id: str, user_id: str, updates: Dict[str, Any]) -> DebtRecord:
        """Update debt fields (counterparty, reason, due date, status, amounts, installments)."""
        if not user_id or not str(user_id).strip():
            raise ValueError("User ID cannot be empty.")
        if not debt_id or not str(debt_id).strip():
            raise ValueError("Debt ID cannot be empty.")

        debt = self.get_debt(debt_id)
        if not debt:
            raise ValueError(f"Debt with ID '{debt_id}' does not exist.")
        if debt.user_id != user_id:
            raise PermissionError("Unauthorized: debt belongs to another user.")

        allowed_fields = {
            "counterparty", "reason", "due_date", "status", "amount_cents",
            "remaining_cents", "account_id", "account_name", "is_installment",
            "total_installments", "remaining_installments", "installment_amount_cents",
            "payment_frequency", "next_installment_due_date", "settled_at"
        }

        set_clauses: List[str] = []
        params: List[Any] = []

        for key, val in updates.items():
            if key not in allowed_fields:
                continue
            if key in ("counterparty", "reason") and (val is None or not str(val).strip()):
                raise ValueError(f"Field '{key}' cannot be empty.")
            if key == "amount_cents" and int(val) <= 0:
                raise ValueError("Amount must be greater than zero.")
            if key in ("remaining_cents", "remaining_installments") and int(val) < 0:
                raise ValueError(f"Field '{key}' cannot be negative.")
            if key == "total_installments" and int(val) <= 0:
                raise ValueError("Total installments must be greater than zero.")

            if isinstance(val, datetime):
                val_formatted = val.isoformat()
            elif hasattr(val, "value"):  # Enum support
                val_formatted = val.value
            else:
                val_formatted = val

            set_clauses.append(f"{key} = ?")
            params.append(val_formatted)

        if not set_clauses:
            return debt

        set_clauses.append("updated_at = CURRENT_TIMESTAMP")
        params.extend([debt_id, user_id])

        with self._connection() as conn:
            conn.execute(
                f"UPDATE debts SET {', '.join(set_clauses)} WHERE debt_id = ? AND user_id = ?;",
                tuple(params),
            )

        updated_debt = self.get_debt(debt_id)
        if not updated_debt:
            raise ValueError(f"Failed to retrieve updated debt '{debt_id}'.")
        return updated_debt

    @staticmethod
    def _advance_due_date(current_dt: Optional[datetime], frequency: str, count: int) -> Optional[datetime]:
        """Advance due date by given payment frequency and installment count using standard library."""
        if not current_dt:
            return None
        freq = (frequency or "monthly").lower().strip()
        if freq in ("weekly", "semanal"):
            return current_dt + timedelta(days=7 * count)
        elif freq in ("biweekly", "quincenal"):
            return current_dt + timedelta(days=14 * count)
        elif freq in ("yearly", "anual"):
            year = current_dt.year + count
            return current_dt.replace(year=year, day=min(current_dt.day, 28))
        else:
            # Monthly
            year = current_dt.year + (current_dt.month + count - 1) // 12
            month = (current_dt.month + count - 1) % 12 + 1
            day = min(current_dt.day, calendar.monthrange(year, month)[1])
            return current_dt.replace(year=year, month=month, day=day)

    def execute_installment_settlement(
        self,
        debt_id: str,
        user_id: str,
        installments_to_pay: int,
        account_id: Optional[str] = None,
        account_name: Optional[str] = None,
        notes: Optional[str] = None,
        payment_date: Optional[Union[datetime, str]] = None,
        adjust_account: bool = True,
    ) -> Dict[str, Any]:
        """Atomically record installment payment, update debt balance/cuotas, and adjust account balance."""
        if installments_to_pay <= 0:
            raise ValueError("Installments to pay must be greater than zero.")

        with self._connection() as conn:
            # 1. Fetch debt record within the transaction
            cur = conn.execute("SELECT * FROM debts WHERE debt_id = ?;", (debt_id,))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Debt with ID '{debt_id}' does not exist.")
            if row["user_id"] != user_id:
                raise PermissionError("Unauthorized: debt belongs to another user.")
            if row["status"] in (DebtStatus.SETTLED.value, DebtStatus.CANCELLED.value):
                raise ValueError("Debt is already settled or cancelled.")

            rem_cents = row["remaining_cents"]
            paid_cents = row["paid_amount_cents"]
            rem_inst = row["remaining_installments"] if row["remaining_installments"] is not None else 1
            inst_amt = row["installment_amount_cents"] if row["installment_amount_cents"] is not None else rem_cents
            debt_type = row["debt_type"]

            if installments_to_pay > rem_inst:
                raise ValueError(f"Cannot pay {installments_to_pay} installments; only {rem_inst} remaining.")

            # 2. Exact-cent calculation eliminating rounding loss (Odd cent split invariant)
            if installments_to_pay == rem_inst:
                payment_cents = rem_cents
            else:
                payment_cents = min(installments_to_pay * inst_amt, rem_cents)

            new_rem_cents = rem_cents - payment_cents
            new_paid_cents = paid_cents + payment_cents
            new_rem_inst = rem_inst - installments_to_pay
            is_settled = (new_rem_cents == 0 or new_rem_inst == 0)
            new_status = DebtStatus.SETTLED.value if is_settled else DebtStatus.PARTIALLY_PAID.value

            now_time = datetime.now(timezone.utc)
            iso_now = now_time.isoformat()
            pay_dt = parse_datetime(payment_date) if payment_date else now_time
            iso_pay = pay_dt.isoformat()
            settled_iso = iso_now if is_settled else None

            # 3. Advance next installment due date
            next_due_iso = None
            if not is_settled and row["next_installment_due_date"]:
                curr_due = parse_datetime(row["next_installment_due_date"])
                if curr_due:
                    advanced_dt = self._advance_due_date(
                        curr_due, row["payment_frequency"] or "monthly", installments_to_pay
                    )
                    if advanced_dt:
                        next_due_iso = advanced_dt.isoformat()

            # 4. Atomically adjust linked account if requested
            target_account_id = account_id or row["account_id"]
            if adjust_account and target_account_id:
                # Receivable repayment: money flows into user's account (+balance)
                # Debt repayment: money flows out of user's account (-balance)
                acc_delta = payment_cents if debt_type == DebtType.RECEIVABLE.value else -payment_cents
                conn.execute(
                    """
                    UPDATE accounts
                    SET balance_cents = balance_cents + ?, updated_at = CURRENT_TIMESTAMP
                    WHERE account_id = ?;
                    """,
                    (acc_delta, target_account_id),
                )

            # 5. Insert debt payment record
            payment_id = f"pay_{uuid.uuid4().hex[:12]}"
            conn.execute(
                """
                INSERT INTO debt_payments (
                    payment_id, debt_id, user_id, amount_cents, account_id,
                    account_name, notes, payment_date, created_at, installments_paid
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    payment_id,
                    debt_id,
                    user_id,
                    payment_cents,
                    target_account_id,
                    account_name or row["account_name"],
                    notes or f"Pago de {installments_to_pay} cuota(s)",
                    iso_pay,
                    iso_now,
                    installments_to_pay,
                ),
            )

            # 6. Update debt record
            conn.execute(
                """
                UPDATE debts SET
                    remaining_cents = ?,
                    paid_amount_cents = ?,
                    remaining_installments = ?,
                    next_installment_due_date = COALESCE(?, next_installment_due_date),
                    status = ?,
                    settled_at = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE debt_id = ?;
                """,
                (
                    new_rem_cents,
                    new_paid_cents,
                    new_rem_inst,
                    next_due_iso,
                    new_status,
                    settled_iso,
                    debt_id,
                ),
            )

        # 7. Construct clean response
        updated_debt = self.get_debt(debt_id)
        payment_record = DebtPaymentRecord(
            id=payment_id,
            debt_id=debt_id,
            user_id=user_id,
            amount_cents=payment_cents,
            account_id=target_account_id,
            account_name=account_name or (row["account_name"] if row else None),
            notes=notes or f"Pago de {installments_to_pay} cuota(s)",
            payment_date=pay_dt,
            created_at=now_time,
            installments_paid=installments_to_pay,
        )

        return {
            "success": True,
            "payment": payment_record.to_dict(),
            "debt": updated_debt.to_dict() if updated_debt else None,
            "installments_paid": installments_to_pay,
            "remaining_installments": new_rem_inst,
            "settled": is_settled,
            "amount_cents": payment_cents,
        }

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
            msg = (
                f"Settlement amount (${amount_cents / 100:.2f}) "
                f"exceeds remaining balance (${debt.remaining_cents / 100:.2f})."
            )
            raise ValueError(msg)

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
