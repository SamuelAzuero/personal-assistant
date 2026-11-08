"""Subscription repository: Typed data access layer for recurring subscriptions with month-end clamping."""

import calendar
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Generator, List, Optional, Union

from app.database.connection import DatabaseManager, get_default_manager
from app.database.repositories.finance_repo import parse_datetime


def clamp_day_to_month(year: int, month: int, target_day: int) -> int:
    """Clamp target day to the maximum valid days for the given year and month (e.g. Feb 28/29, Apr 30)."""
    _, max_days = calendar.monthrange(year, month)
    return min(max(1, target_day), max_days)


def calculate_next_renewal_date(
    from_date: date,
    billing_day: int,
    billing_cycle: str = "monthly",
) -> date:
    """Compute the next subscription renewal date with strict month-end clamping.

    Guarantees valid dates across leap years (Feb 29) and short months (30 days).
    """
    cycle = billing_cycle.lower().strip()

    if cycle in ("weekly", "week"):
        return from_date + timedelta(days=7)

    target_day = max(1, min(31, billing_day))

    if cycle in ("monthly", "month"):
        # Check current month candidate
        curr_clamped = clamp_day_to_month(from_date.year, from_date.month, target_day)
        curr_candidate = date(from_date.year, from_date.month, curr_clamped)
        if curr_candidate > from_date:
            return curr_candidate

        # Advance to next month
        year = from_date.year
        month = from_date.month + 1
        if month > 12:
            month = 1
            year += 1
        next_clamped = clamp_day_to_month(year, month, target_day)
        return date(year, month, next_clamped)

    if cycle in ("quarterly", "quarter"):
        year = from_date.year
        month = from_date.month + 3
        while month > 12:
            month -= 12
            year += 1
        clamped = clamp_day_to_month(year, month, target_day)
        return date(year, month, clamped)

    if cycle in ("semiannual", "semiannually"):
        year = from_date.year
        month = from_date.month + 6
        while month > 12:
            month -= 12
            year += 1
        clamped = clamp_day_to_month(year, month, target_day)
        return date(year, month, clamped)

    if cycle in ("annual", "annually", "yearly", "year"):
        # Advance 1 year
        year = from_date.year + 1
        clamped = clamp_day_to_month(year, from_date.month, target_day)
        return date(year, from_date.month, clamped)

    # Default fallback: 1 month forward
    year = from_date.year
    month = from_date.month + 1
    if month > 12:
        month = 1
        year += 1
    clamped = clamp_day_to_month(year, month, target_day)
    return date(year, month, clamped)


@dataclass
class SubscriptionRecord:
    id: str
    user_id: str
    name: str
    amount_cents: int
    billing_cycle: str = "monthly"
    billing_day: Optional[int] = None
    next_payment_date: str = ""  # ISO Date 'YYYY-MM-DD'
    account_id: Optional[str] = None
    account_name: Optional[str] = None
    category: str = "Entertainment"
    status: str = "active"
    reminder_days_before: int = 3
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @property
    def subscription_id(self) -> str:
        return self.id

    @property
    def amount(self) -> float:
        return round(self.amount_cents / 100.0, 2)

    @property
    def renewal_day(self) -> Optional[int]:
        return self.billing_day

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "subscription_id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "service_name": self.name,
            "amount_cents": self.amount_cents,
            "amount": self.amount,
            "billing_cycle": self.billing_cycle,
            "billing_day": self.billing_day,
            "renewal_day": self.billing_day,
            "next_payment_date": self.next_payment_date,
            "account_id": self.account_id,
            "account_name": self.account_name,
            "category": self.category,
            "status": self.status,
            "is_active": self.is_active,
            "reminder_days_before": self.reminder_days_before,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class SubscriptionRepository:
    """Repository for recurring subscriptions with month-end date clamping."""

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

    def _row_to_subscription(self, row: sqlite3.Row) -> SubscriptionRecord:
        raw_created = row["created_at"]
        raw_updated = row["updated_at"]
        keys = row.keys()

        return SubscriptionRecord(
            id=row["subscription_id"],
            user_id=row["user_id"],
            name=row["name"],
            amount_cents=row["amount_cents"],
            billing_cycle=row["billing_cycle"],
            billing_day=row["billing_day"] if "billing_day" in keys else None,
            next_payment_date=str(row["next_payment_date"])[:10],
            account_id=row["account_id"] if "account_id" in keys else None,
            account_name=row["account_name"] if "account_name" in keys else None,
            category=row["category"] if "category" in keys else "Entertainment",
            status=row["status"] if "status" in keys else "active",
            reminder_days_before=row["reminder_days_before"] if "reminder_days_before" in keys else 3,
            notes=row["notes"] if "notes" in keys else None,
            created_at=parse_datetime(raw_created) if raw_created else None,
            updated_at=parse_datetime(raw_updated) if raw_updated else None,
        )

    def create_subscription(
        self,
        user_id: str,
        name: str,
        amount_cents: int,
        billing_cycle: str = "monthly",
        billing_day: Optional[int] = None,
        next_payment_date: Optional[Union[date, str]] = None,
        account_id: Optional[str] = None,
        account_name: Optional[str] = None,
        category: str = "Entertainment",
        reminder_days_before: int = 3,
        notes: Optional[str] = None,
    ) -> SubscriptionRecord:
        """Create a new recurring subscription with automatic clamped renewal calculation."""
        if not user_id or not str(user_id).strip():
            raise ValueError("User ID cannot be empty.")
        if not name or not str(name).strip():
            raise ValueError("Subscription name cannot be empty.")
        if amount_cents <= 0:
            raise ValueError("Subscription amount must be greater than zero.")

        # Determine billing day and next payment date
        today = datetime.now(timezone.utc).date()
        resolved_bday: Optional[int] = billing_day
        if resolved_bday is not None and (resolved_bday < 1 or resolved_bday > 31):
            raise ValueError("Billing day must be between 1 and 31.")

        if next_payment_date is not None:
            if isinstance(next_payment_date, str):
                resolved_next = next_payment_date[:10]
            else:
                resolved_next = next_payment_date.isoformat()
            if resolved_bday is None:
                resolved_bday = int(resolved_next.split("-")[2])
        else:
            effective_day = resolved_bday if resolved_bday is not None else today.day
            resolved_bday = effective_day
            calculated_date = calculate_next_renewal_date(today, effective_day, billing_cycle)
            resolved_next = calculated_date.isoformat()

        sub_id = f"sub_{uuid.uuid4().hex[:12]}"
        now_time = datetime.now(timezone.utc)
        iso_now = now_time.isoformat()

        with self._connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users (user_id, full_name) VALUES (?, ?);",
                (user_id, user_id),
            )
            conn.execute(
                """
                INSERT INTO subscriptions (
                    subscription_id, user_id, name, amount_cents, billing_cycle,
                    billing_day, next_payment_date, account_id, account_name,
                    category, status, reminder_days_before, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?);
                """,
                (
                    sub_id,
                    user_id,
                    name.strip(),
                    amount_cents,
                    billing_cycle.lower().strip(),
                    resolved_bday,
                    resolved_next,
                    account_id,
                    account_name,
                    category.strip(),
                    reminder_days_before,
                    notes,
                    iso_now,
                    iso_now,
                ),
            )

        return SubscriptionRecord(
            id=sub_id,
            user_id=user_id,
            name=name.strip(),
            amount_cents=amount_cents,
            billing_cycle=billing_cycle.lower().strip(),
            billing_day=resolved_bday,
            next_payment_date=resolved_next,
            account_id=account_id,
            account_name=account_name,
            category=category.strip(),
            status="active",
            reminder_days_before=reminder_days_before,
            notes=notes,
            created_at=now_time,
            updated_at=now_time,
        )

    def get_subscription(self, subscription_id: str) -> Optional[SubscriptionRecord]:
        """Retrieve a subscription by ID."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM subscriptions WHERE subscription_id = ?;",
                (subscription_id,),
            ).fetchone()
            if not row:
                return None
            return self._row_to_subscription(row)

    def list_subscriptions(
        self,
        user_id: str,
        status: Optional[str] = "active",
    ) -> List[SubscriptionRecord]:
        """List subscriptions for user, ordered by next payment date."""
        query = "SELECT * FROM subscriptions WHERE user_id = ?"
        params: List[Any] = [user_id]
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY next_payment_date ASC;"

        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_subscription(r) for r in rows]

    def update_subscription(
        self,
        subscription_id: str,
        **kwargs: Any,
    ) -> Optional[SubscriptionRecord]:
        """Update subscription fields."""
        allowed_fields = {
            "name", "amount_cents", "billing_cycle", "billing_day",
            "next_payment_date", "account_id", "account_name",
            "category", "status", "reminder_days_before", "notes"
        }
        updates = []
        params = []
        for key, val in kwargs.items():
            if key in allowed_fields:
                updates.append(f"{key} = ?")
                params.append(val)

        if not updates:
            return self.get_subscription(subscription_id)

        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(subscription_id)

        query = f"UPDATE subscriptions SET {', '.join(updates)} WHERE subscription_id = ?;"
        with self._connection() as conn:
            conn.execute(query, params)

        return self.get_subscription(subscription_id)

    def advance_renewal(self, subscription_id: str) -> Optional[SubscriptionRecord]:
        """Advance next_payment_date to the next cycle using clamped calculation."""
        sub = self.get_subscription(subscription_id)
        if not sub:
            return None

        current_dt = date.fromisoformat(sub.next_payment_date)
        billing_day = sub.billing_day or current_dt.day

        # Advance by billing cycle
        next_dt = calculate_next_renewal_date(current_dt, billing_day, sub.billing_cycle)
        return self.update_subscription(
            subscription_id,
            next_payment_date=next_dt.isoformat(),
        )

    def delete_subscription(self, subscription_id: str) -> bool:
        """Delete subscription record."""
        with self._connection() as conn:
            cursor = conn.execute(
                "DELETE FROM subscriptions WHERE subscription_id = ?;",
                (subscription_id,),
            )
            return cursor.rowcount > 0
