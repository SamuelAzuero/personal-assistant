"""Finance repository: Typed data access layer with exact integer cents to eliminate floating-point drift."""

import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from app.database.connection import DatabaseManager, get_default_manager


class TransactionType(str, Enum):
    EXPENSE = "expense"
    INCOME = "income"


def parse_datetime(dt_val: Union[datetime, str, None]) -> datetime:
    """Parse string or datetime object into UTC datetime."""
    if dt_val is None:
        return datetime.now(timezone.utc)
    if isinstance(dt_val, datetime):
        if dt_val.tzinfo is None:
            return dt_val.replace(tzinfo=timezone.utc)
        return dt_val.astimezone(timezone.utc)
    if isinstance(dt_val, str):
        cleaned = dt_val.strip()
        # Handle trailing Z
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(cleaned)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            weekdays_map = {
                "lunes": 0, "monday": 0,
                "martes": 1, "tuesday": 1,
                "miércoles": 2, "miercoles": 2, "wednesday": 2,
                "jueves": 3, "thursday": 3,
                "viernes": 4, "friday": 4,
                "sábado": 5, "sabado": 5, "saturday": 5,
                "domingo": 6, "sunday": 6,
            }
            lower = cleaned.lower()
            now = datetime.now(timezone.utc)
            base_date = now.date()
            if "mañana" in lower or "manana" in lower or "tomorrow" in lower:
                target_date = base_date + timedelta(days=1)
                return datetime.combine(target_date, time(hour=9, minute=0, tzinfo=timezone.utc))
            if "hoy" in lower or "today" in lower:
                return datetime.combine(base_date, time(hour=9, minute=0, tzinfo=timezone.utc))
            for day_name, day_num in weekdays_map.items():
                if re.search(rf"\b{day_name}\b", lower):
                    days_ahead = (day_num - base_date.weekday() + 7) % 7 or 7
                    target_date = base_date + timedelta(days=days_ahead)
                    return datetime.combine(target_date, time(hour=9, minute=0, tzinfo=timezone.utc))
            raise ValueError(f"Invalid isoformat string: {cleaned!r}")
    raise ValueError(f"Unsupported datetime type: {type(dt_val)}")


@dataclass
class TransactionRecord:
    id: str
    user_id: str
    amount_cents: int
    transaction_type: TransactionType
    category: str
    description: str
    timestamp: datetime
    created_at: Optional[datetime] = None
    idempotency_key: Optional[str] = None
    account_id: Optional[str] = None
    account_name: Optional[str] = None

    @property
    def amount(self) -> float:
        """Helper property providing amount in standard currency units (dollars)."""
        return round(self.amount_cents / 100.0, 2)

    def to_dict(self) -> Dict[str, Any]:
        """Convert record to dictionary format."""
        return {
            "id": self.id,
            "transaction_id": self.id,
            "user_id": self.user_id,
            "amount_cents": self.amount_cents,
            "amount": self.amount,
            "type": self.transaction_type.value,
            "transaction_type": self.transaction_type.value,
            "category": self.category,
            "description": self.description,
            "timestamp": self.timestamp.isoformat(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "idempotency_key": self.idempotency_key,
            "account_id": self.account_id,
            "account_name": self.account_name,
        }


class FinanceRepository:
    """Typed repository for transactions and budgets backed by SQLite."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or get_default_manager()

    def ensure_user(self, user_id: str, full_name: Optional[str] = None) -> None:
        """Ensure a user record exists to satisfy foreign key constraints."""
        with self.db.connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users (user_id, full_name) VALUES (?, ?);",
                (user_id, full_name or user_id),
            )

    def add_transaction(
        self,
        user_id: str,
        amount_cents: int,
        transaction_type: Union[TransactionType, str],
        category: str,
        description: str,
        timestamp: Optional[Union[datetime, str]] = None,
        transaction_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        account_id: Optional[str] = None,
        account_name: Optional[str] = None,
    ) -> TransactionRecord:
        """Record a transaction with integer cents. Supports idempotency deduplication."""
        if isinstance(transaction_type, str):
            transaction_type = TransactionType(transaction_type.lower())

        # Check existing idempotency key to prevent double charging / duplicate insertion
        if idempotency_key:
            existing = self.get_by_idempotency_key(user_id, idempotency_key)
            if existing:
                return existing

        self.ensure_user(user_id)

        tx_id = transaction_id or f"tx_{uuid.uuid4().hex[:12]}"
        tx_time = parse_datetime(timestamp)
        now_time = datetime.now(timezone.utc)
        iso_timestamp = tx_time.isoformat()
        iso_created_at = now_time.isoformat()

        try:
            with self.db.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO transactions (
                        transaction_id, user_id, amount_cents, transaction_type,
                        category, description, timestamp, created_at, idempotency_key,
                        account_id, account_name
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        tx_id,
                        user_id,
                        amount_cents,
                        transaction_type.value,
                        category.strip(),
                        description.strip(),
                        iso_timestamp,
                        iso_created_at,
                        idempotency_key,
                        account_id,
                        account_name,
                    ),
                )
        except sqlite3.IntegrityError:
            if idempotency_key:
                existing = self.get_by_idempotency_key(user_id, idempotency_key)
                if existing:
                    return existing
            raise

        return TransactionRecord(
            id=tx_id,
            user_id=user_id,
            amount_cents=amount_cents,
            transaction_type=transaction_type,
            category=category.strip(),
            description=description.strip(),
            timestamp=tx_time,
            created_at=now_time,
            idempotency_key=idempotency_key,
            account_id=account_id,
            account_name=account_name,
        )

    def get_transaction(self, transaction_id: str) -> Optional[TransactionRecord]:
        """Retrieve transaction by ID."""
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM transactions WHERE transaction_id = ?;",
                (transaction_id,),
            ).fetchone()
            if not row:
                return None
            return self._row_to_record(row)

    def get_by_idempotency_key(self, user_id: str, idempotency_key: str) -> Optional[TransactionRecord]:
        """Retrieve existing transaction by user ID and idempotency key."""
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM transactions WHERE user_id = ? AND idempotency_key = ?;",
                (user_id, idempotency_key),
            ).fetchone()
            if not row:
                return None
            return self._row_to_record(row)

    def delete_transaction(self, transaction_id: str, user_id: Optional[str] = None) -> bool:
        """Delete (void) a transaction. Returns True if row was deleted."""
        with self.db.connection() as conn:
            if user_id:
                cursor = conn.execute(
                    "DELETE FROM transactions WHERE transaction_id = ? AND user_id = ?;",
                    (transaction_id, user_id),
                )
            else:
                cursor = conn.execute(
                    "DELETE FROM transactions WHERE transaction_id = ?;",
                    (transaction_id,),
                )
            return cursor.rowcount > 0

    def list_transactions(
        self,
        user_id: str,
        start_date: Optional[Union[datetime, str]] = None,
        end_date: Optional[Union[datetime, str]] = None,
        category: Optional[str] = None,
        transaction_type: Optional[Union[TransactionType, str]] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[TransactionRecord]:
        """List transactions with optional filtering and pagination."""
        query = "SELECT * FROM transactions WHERE user_id = ?"
        params: List[Any] = [user_id]

        if start_date is not None:
            iso_start = parse_datetime(start_date).isoformat()
            query += " AND timestamp >= ?"
            params.append(iso_start)

        if end_date is not None:
            iso_end = parse_datetime(end_date).isoformat()
            query += " AND timestamp <= ?"
            params.append(iso_end)

        if category is not None:
            query += " AND LOWER(category) = LOWER(?)"
            params.append(category.strip())

        if transaction_type is not None:
            t_val = transaction_type.value if isinstance(transaction_type, TransactionType) else str(transaction_type).lower()
            query += " AND transaction_type = ?"
            params.append(t_val)

        query += " ORDER BY timestamp DESC, created_at DESC LIMIT ? OFFSET ?;"
        params.extend([limit, offset])

        with self.db.connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_record(row) for row in rows]

    def get_balance(self, user_id: str) -> Dict[str, Any]:
        """Calculate cumulative net balance, total income, and total expenses in exact integer cents."""
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT transaction_type, SUM(amount_cents) as total_cents, COUNT(*) as tx_count
                FROM transactions
                WHERE user_id = ?
                GROUP BY transaction_type;
                """,
                (user_id,),
            ).fetchall()

            income_cents = 0
            expense_cents = 0
            tx_count = 0

            for row in rows:
                t_type = row["transaction_type"]
                amount = row["total_cents"] or 0
                count = row["tx_count"] or 0
                tx_count += count
                if t_type == TransactionType.INCOME.value:
                    income_cents += amount
                elif t_type == TransactionType.EXPENSE.value:
                    expense_cents += amount

            balance_cents = income_cents - expense_cents

            return {
                "user_id": user_id,
                "balance_cents": balance_cents,
                "income_cents": income_cents,
                "expense_cents": expense_cents,
                "net_balance": round(balance_cents / 100.0, 2),
                "total_income": round(income_cents / 100.0, 2),
                "total_expenses": round(expense_cents / 100.0, 2),
                "transaction_count": tx_count,
            }

    def get_category_totals(
        self,
        user_id: str,
        start_date: Optional[Union[datetime, str]] = None,
        end_date: Optional[Union[datetime, str]] = None,
        transaction_type: str = "expense",
    ) -> Dict[str, int]:
        """Aggregate total spending (in cents) grouped by category."""
        query = "SELECT category, SUM(amount_cents) as total_cents FROM transactions WHERE user_id = ? AND transaction_type = ?"
        params: List[Any] = [user_id, transaction_type]

        if start_date is not None:
            iso_start = parse_datetime(start_date).isoformat()
            query += " AND timestamp >= ?"
            params.append(iso_start)

        if end_date is not None:
            iso_end = parse_datetime(end_date).isoformat()
            query += " AND timestamp <= ?"
            params.append(iso_end)

        query += " GROUP BY category ORDER BY total_cents DESC;"

        with self.db.connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return {row["category"]: row["total_cents"] for row in rows}

    # Budgets management
    def set_budget(
        self,
        user_id: str,
        category: str,
        monthly_limit_cents: int,
        period: str,
        budget_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create or update a category budget for a period (e.g. '2026-11')."""
        self.ensure_user(user_id)
        b_id = budget_id or f"bg_{uuid.uuid4().hex[:12]}"
        clean_cat = category.strip()
        clean_period = period.strip()

        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO budgets (budget_id, user_id, category, monthly_limit_cents, period)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, category, period)
                DO UPDATE SET monthly_limit_cents = excluded.monthly_limit_cents;
                """,
                (b_id, user_id, clean_cat, monthly_limit_cents, clean_period),
            )

        return {
            "budget_id": b_id,
            "user_id": user_id,
            "category": clean_cat,
            "monthly_limit_cents": monthly_limit_cents,
            "monthly_limit": round(monthly_limit_cents / 100.0, 2),
            "period": clean_period,
        }

    def get_budget(self, user_id: str, category: str, period: str) -> Optional[Dict[str, Any]]:
        """Retrieve specific category budget for a period."""
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM budgets WHERE user_id = ? AND LOWER(category) = LOWER(?) AND period = ?;",
                (user_id, category.strip(), period.strip()),
            ).fetchone()
            if not row:
                return None
            return {
                "budget_id": row["budget_id"],
                "user_id": row["user_id"],
                "category": row["category"],
                "monthly_limit_cents": row["monthly_limit_cents"],
                "monthly_limit": round(row["monthly_limit_cents"] / 100.0, 2),
                "period": row["period"],
            }

    def list_budgets(self, user_id: str, period: Optional[str] = None) -> List[Dict[str, Any]]:
        """List budgets for a user, optionally filtered by period."""
        query = "SELECT * FROM budgets WHERE user_id = ?"
        params: List[Any] = [user_id]
        if period is not None:
            query += " AND period = ?"
            params.append(period.strip())
        query += " ORDER BY category ASC;"

        with self.db.connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [
                {
                    "budget_id": r["budget_id"],
                    "user_id": r["user_id"],
                    "category": r["category"],
                    "monthly_limit_cents": r["monthly_limit_cents"],
                    "monthly_limit": round(r["monthly_limit_cents"] / 100.0, 2),
                    "period": r["period"],
                }
                for r in rows
            ]

    def delete_budget(self, budget_id: str, user_id: Optional[str] = None) -> bool:
        """Delete a budget entry."""
        with self.db.connection() as conn:
            if user_id:
                c = conn.execute(
                    "DELETE FROM budgets WHERE budget_id = ? AND user_id = ?;",
                    (budget_id, user_id),
                )
            else:
                c = conn.execute("DELETE FROM budgets WHERE budget_id = ?;", (budget_id,))
            return c.rowcount > 0

    def get_category_spending_for_period(self, user_id: str, category: str, period: str) -> int:
        """Calculate total expense amount in cents for category in the specified period (YYYY-MM)."""
        pattern = f"{period.strip()}%"
        with self.db.connection() as conn:
            row = conn.execute(
                """
                SELECT SUM(amount_cents) as total_cents
                FROM transactions
                WHERE user_id = ?
                  AND LOWER(category) = LOWER(?)
                  AND transaction_type = 'expense'
                  AND timestamp LIKE ?;
                """,
                (user_id, category.strip(), pattern),
            ).fetchone()
            return row["total_cents"] or 0

    def _row_to_record(self, row: sqlite3.Row) -> TransactionRecord:
        """Helper to convert sqlite3.Row into TransactionRecord."""
        raw_ts = row["timestamp"]
        parsed_ts = parse_datetime(raw_ts)
        raw_created = row["created_at"]
        parsed_created = parse_datetime(raw_created) if raw_created else None
        key = row["idempotency_key"] if "idempotency_key" in row.keys() else None
        acc_id = row["account_id"] if "account_id" in row.keys() else None
        acc_name = row["account_name"] if "account_name" in row.keys() else None

        return TransactionRecord(
            id=row["transaction_id"],
            user_id=row["user_id"],
            amount_cents=row["amount_cents"],
            transaction_type=TransactionType(row["transaction_type"]),
            category=row["category"],
            description=row["description"],
            timestamp=parsed_ts,
            created_at=parsed_created,
            idempotency_key=key,
            account_id=acc_id,
            account_name=acc_name,
        )
