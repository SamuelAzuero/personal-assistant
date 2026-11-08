"""SubscriptionService: Domain service managing recurring subscriptions and the unified payment calendar."""

import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Union

from app.database.connection import DatabaseManager, get_default_manager
from app.database.repositories.account_repo import AccountRepository
from app.database.repositories.debt_repo import DebtRepository, DebtStatus, DebtType
from app.database.repositories.subscription_repo import (
    SubscriptionRecord,
    SubscriptionRepository,
)


class SubscriptionService:
    """Service providing subscription management, month-end clamping renewals, and unified payment schedule."""

    def __init__(
        self,
        repository: Optional[SubscriptionRepository] = None,
        debt_repository: Optional[DebtRepository] = None,
        account_repository: Optional[AccountRepository] = None,
        db_manager: Optional[DatabaseManager] = None,
        conn: Optional[sqlite3.Connection] = None,
    ):
        if repository is not None:
            self.repo = repository
        elif conn is not None:
            self.repo = SubscriptionRepository(conn=conn)
        else:
            self.repo = SubscriptionRepository(db_manager=db_manager or get_default_manager())

        if debt_repository is not None:
            self.debt_repo = debt_repository
        elif conn is not None:
            self.debt_repo = DebtRepository(conn=conn)
        else:
            self.debt_repo = DebtRepository(db_manager=db_manager or get_default_manager())

        if account_repository is not None:
            self.account_repo = account_repository
        elif conn is not None:
            self.account_repo = AccountRepository(conn=conn)
        else:
            self.account_repo = AccountRepository(db_manager=db_manager or get_default_manager())

    def _resolve_account_info(
        self,
        user_id: str,
        account_name: Optional[str] = None,
        account_id: Optional[str] = None,
    ) -> tuple[Optional[str], Optional[str]]:
        """Resolve account ID and name for a subscription."""
        if account_id:
            acc = self.account_repo.get_account(account_id)
            if acc:
                return acc.id, acc.name

        if account_name:
            acc = self.account_repo.get_account_by_name(user_id, account_name)
            if acc:
                return acc.id, acc.name
            return None, account_name.strip()

        # Default fallback to Nu or Efectivo
        default_acc = self.account_repo.get_account_by_name(user_id, "Nu")
        if not default_acc:
            default_acc = self.account_repo.get_account_by_name(user_id, "Efectivo")
        if default_acc:
            return default_acc.id, default_acc.name

        return None, "Nu"

    def create_subscription(
        self,
        user_id: str,
        name: str,
        amount_cents: int,
        billing_cycle: str = "monthly",
        billing_day: Optional[int] = None,
        next_payment_date: Optional[Union[date, str]] = None,
        account_name: Optional[str] = None,
        account_id: Optional[str] = None,
        category: str = "Entertainment",
        reminder_days_before: int = 3,
        notes: Optional[str] = None,
    ) -> SubscriptionRecord:
        """Create a new subscription with clamped next renewal date."""
        acc_id, acc_name = self._resolve_account_info(user_id, account_name, account_id)
        return self.repo.create_subscription(
            user_id=user_id,
            name=name,
            amount_cents=amount_cents,
            billing_cycle=billing_cycle,
            billing_day=billing_day,
            next_payment_date=next_payment_date,
            account_id=acc_id,
            account_name=acc_name,
            category=category,
            reminder_days_before=reminder_days_before,
            notes=notes,
        )

    def get_subscription(self, subscription_id: str) -> Optional[SubscriptionRecord]:
        """Retrieve subscription by ID."""
        return self.repo.get_subscription(subscription_id)

    def list_subscriptions(
        self,
        user_id: str,
        status: Optional[str] = "active",
    ) -> List[SubscriptionRecord]:
        """List user's subscriptions."""
        if not user_id or not str(user_id).strip():
            raise ValueError("User ID cannot be empty.")
        return self.repo.list_subscriptions(user_id.strip(), status=status)

    def update_subscription(
        self,
        subscription_id: str,
        **kwargs: Any,
    ) -> Optional[SubscriptionRecord]:
        """Update subscription parameters."""
        return self.repo.update_subscription(subscription_id, **kwargs)

    def advance_subscription_renewal(self, subscription_id: str) -> Optional[SubscriptionRecord]:
        """Advance next payment date to the following cycle with clamped dates."""
        return self.repo.advance_renewal(subscription_id)

    def delete_subscription(self, subscription_id: str) -> bool:
        """Delete subscription."""
        return self.repo.delete_subscription(subscription_id)

    def _parse_ref_date(self, ref_val: Optional[Union[date, datetime, str]]) -> date:
        if ref_val is None:
            return datetime.now(timezone.utc).date()
        if isinstance(ref_val, datetime):
            return ref_val.date()
        if isinstance(ref_val, date):
            return ref_val
        clean = str(ref_val).strip()[:10]
        return date.fromisoformat(clean)

    def get_upcoming_payments(
        self,
        user_id: str,
        days_ahead: int = 30,
        reference_date: Optional[Union[date, datetime, str]] = None,
    ) -> List[Dict[str, Any]]:
        """Compute chronological payment schedule merging subscriptions, debts, and receivables.

        Sorted chronologically by due date.
        """
        if not user_id or not str(user_id).strip():
            raise ValueError("User ID cannot be empty.")

        ref_date = self._parse_ref_date(reference_date)
        cutoff_date = ref_date + timedelta(days=days_ahead)

        schedule: List[Dict[str, Any]] = []

        # 1. Subscriptions
        subscriptions = self.repo.list_subscriptions(user_id, status="active")
        for sub in subscriptions:
            try:
                sub_due = date.fromisoformat(sub.next_payment_date)
            except Exception:
                continue

            if sub_due <= cutoff_date:
                days_diff = (sub_due - ref_date).days
                urgency: str
                if days_diff < 0:
                    urgency = "overdue"
                elif days_diff == 0:
                    urgency = "today"
                elif days_diff <= 3:
                    urgency = "soon"
                else:
                    urgency = "upcoming"

                schedule.append({
                    "item_type": "subscription",
                    "type": "subscription",
                    "id": sub.id,
                    "title": sub.name,
                    "name": sub.name,
                    "amount_cents": sub.amount_cents,
                    "amount": sub.amount,
                    "direction": "outflow",
                    "due_date": sub_due.isoformat(),
                    "days_remaining": days_diff,
                    "is_overdue": days_diff < 0,
                    "urgency": urgency,
                    "account_id": sub.account_id,
                    "account_name": sub.account_name,
                    "category": sub.category,
                    "status": sub.status,
                })

        # 2. Debts and Receivables
        debts = self.debt_repo.list_debts(user_id)
        for d in debts:
            if d.status not in (DebtStatus.ACTIVE, DebtStatus.PARTIALLY_PAID) or not d.due_date:
                continue

            debt_due = d.due_date.date() if isinstance(d.due_date, datetime) else date.fromisoformat(str(d.due_date)[:10])
            if debt_due <= cutoff_date:
                days_diff = (debt_due - ref_date).days
                urgency = "overdue" if days_diff < 0 else ("today" if days_diff == 0 else ("soon" if days_diff <= 3 else "upcoming"))
                direction = "outflow" if d.debt_type == DebtType.DEBT else "inflow"

                schedule.append({
                    "item_type": d.debt_type.value,
                    "type": d.debt_type.value,
                    "id": d.id,
                    "title": d.counterparty,
                    "counterparty": d.counterparty,
                    "reason": d.reason,
                    "amount_cents": d.remaining_cents,
                    "amount": d.remaining,
                    "direction": direction,
                    "due_date": debt_due.isoformat(),
                    "days_remaining": days_diff,
                    "is_overdue": days_diff < 0,
                    "urgency": urgency,
                    "account_id": d.account_id,
                    "account_name": d.account_name,
                    "status": d.status.value,
                })

        # Chronological sort: by due_date ASC
        schedule.sort(key=lambda item: (item["due_date"], item["item_type"]))
        return schedule

    def get_subscription_reminders(
        self,
        user_id: str,
        alert_horizon_days: int = 3,
        reference_date: Optional[Union[date, datetime, str]] = None,
    ) -> List[Dict[str, Any]]:
        """Identify subscriptions renewing within the alert horizon."""
        ref_date = self._parse_ref_date(reference_date)
        subscriptions = self.repo.list_subscriptions(user_id, status="active")
        reminders = []

        for sub in subscriptions:
            try:
                sub_due = date.fromisoformat(sub.next_payment_date)
            except Exception:
                continue

            days_diff = (sub_due - ref_date).days
            horizon = max(alert_horizon_days, sub.reminder_days_before)
            if 0 <= days_diff <= horizon:
                reminders.append({
                    "subscription_id": sub.id,
                    "name": sub.name,
                    "amount_cents": sub.amount_cents,
                    "amount": sub.amount,
                    "due_date": sub.next_payment_date,
                    "days_remaining": days_diff,
                    "account_name": sub.account_name,
                    "message": f"Reminder: {sub.name} renewal of ${sub.amount:,.2f} COP is due in {days_diff} day(s) on {sub.next_payment_date} ({sub.account_name or 'unassigned'}).",
                })

        reminders.sort(key=lambda r: r["days_remaining"])
        return reminders
