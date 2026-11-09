"""FinanceService: Core domain engine for personal finance ledger and analytics (R2)."""

import math
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Union

from app.database.connection import DatabaseManager, get_default_manager
from app.database.repositories.finance_repo import (
    FinanceRepository,
    TransactionRecord,
    TransactionType,
)

# Standard taxonomy categories
STANDARD_CATEGORIES = [
    "Food & Dining",
    "Groceries",
    "Transportation",
    "Housing & Utilities",
    "Entertainment",
    "Health & Wellness",
    "Shopping",
    "Income",
    "Other",
]


def validate_iso_date(date_val: Union[str, datetime]) -> str:
    """Validate date and return ISO-8601 string. Rejects invalid dates like '2026-02-31' or 'not-a-date'."""
    if isinstance(date_val, datetime):
        if date_val.tzinfo is None:
            return date_val.replace(tzinfo=timezone.utc).isoformat()
        return date_val.astimezone(timezone.utc).isoformat()

    if not isinstance(date_val, str) or not date_val.strip():
        raise ValueError("Invalid date format. Expected ISO-8601 (YYYY-MM-DD).")

    cleaned = date_val.strip()
    # Handle YYYY-MM-DD without time
    if re.match(r"^\d{4}-\d{2}-\d{2}$", cleaned):
        try:
            # datetime.strptime or date.fromisoformat validates day bounds strictly
            dt = datetime.strptime(cleaned, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            raise ValueError("Invalid date format. Expected ISO-8601 (YYYY-MM-DD).")

    # Handle ISO-8601 with time
    iso_clean = cleaned
    if iso_clean.endswith("Z"):
        iso_clean = iso_clean[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(iso_clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except Exception:
        raise ValueError("Invalid date format. Expected ISO-8601 (YYYY-MM-DD).")


class FinanceService:
    """Service providing income/expense recording, validation, balance, category breakdowns,

    auto-categorization, budget alerts, and periodic summaries.
    """

    def __init__(
        self,
        repository: Optional[FinanceRepository] = None,
        db_manager: Optional[DatabaseManager] = None,
        high_value_threshold_cents: int = 50000,  # $500.00
        account_service: Optional[Any] = None,
    ):
        self.db_mgr = db_manager or get_default_manager()
        self.repo = repository or FinanceRepository(self.db_mgr)
        self.high_value_threshold_cents = high_value_threshold_cents
        if account_service is not None:
            self.account_service = account_service
        else:
            from app.services.account_service import AccountService
            self.account_service = AccountService(db_manager=self.db_mgr)

    def record_transaction(
        self,
        user_id: str,
        amount_cents: Optional[int] = None,
        t_type: Optional[Union[TransactionType, str]] = None,
        category: Optional[str] = None,
        description: Optional[str] = None,
        *,
        amount: Optional[Union[Decimal, float, str, int]] = None,
        transaction_type: Optional[Union[TransactionType, str]] = None,
        timestamp: Optional[Union[datetime, str]] = None,
        idempotency_key: Optional[str] = None,
        account_name: Optional[str] = None,
        account_id: Optional[str] = None,
    ) -> TransactionRecord:
        """Record an income or expense transaction with strict validation and zero floating-point drift.

        Validates positive amount, non-empty description, valid category, and valid timestamp.
        """
        if not user_id or not str(user_id).strip():
            raise ValueError("User ID cannot be empty.")

        # 1. Resolve & Validate Amount
        cents: int
        if amount_cents is not None:
            if not isinstance(amount_cents, int):
                raise ValueError("amount_cents must be an integer.")
            if amount_cents <= 0:
                raise ValueError("Transaction amount must be greater than zero.")
            cents = amount_cents
        elif amount is not None:
            if isinstance(amount, float) and (math.isnan(amount) or math.isinf(amount)):
                raise ValueError("Invalid numeric format for transaction amount: cannot be NaN or Infinity.")
            try:
                dec_str = str(amount).strip().lower()
                if "nan" in dec_str or "inf" in dec_str:
                    raise ValueError("Invalid numeric format for transaction amount: cannot be NaN or Infinity.")
                dec = Decimal(str(amount).strip())
                if dec.is_nan() or dec.is_infinite():
                    raise ValueError("Invalid numeric format for transaction amount: cannot be NaN or Infinity.")
            except (InvalidOperation, ValueError):
                raise ValueError("Invalid numeric format for transaction amount.")

            if dec <= Decimal("0"):
                if dec < Decimal("0"):
                    raise ValueError("Amount must be positive; specify type as expense or income.")
                raise ValueError("Transaction amount must be greater than zero.")

            # Validate max 2 decimal places
            # Decimal.as_tuple().exponent gives negative exponent for decimals
            exp = dec.as_tuple().exponent
            if isinstance(exp, int) and exp < -2:
                raise ValueError("Amount cannot have more than 2 decimal places.")

            cents = int(round(dec * 100))
            if cents <= 0:
                raise ValueError("Transaction amount must be greater than zero.")
        else:
            raise ValueError("Transaction amount must be specified.")

        # 2. Resolve & Validate Transaction Type
        type_input = t_type if t_type is not None else transaction_type
        if type_input is None:
            raise ValueError("Transaction type must be specified ('expense' or 'income').")

        if hasattr(type_input, "value"):
            type_str = str(type_input.value).strip().lower()
        else:
            type_str = str(type_input).strip().lower()
        if "." in type_str:
            type_str = type_str.split(".")[-1]
        if type_str not in ("income", "expense"):
            raise ValueError("Invalid transaction type: must be 'income' or 'expense'.")
        resolved_type = TransactionType(type_str)

        # 3. Resolve & Validate Description
        if description is None or not str(description).strip():
            raise ValueError("Transaction description cannot be empty.")
        clean_description = str(description).strip()

        # 4. Resolve & Validate Category
        clean_category: str
        if category is None or not str(category).strip() or str(category).strip().lower() == "auto":
            clean_category = self.auto_categorize(clean_description)
        else:
            clean_category = str(category).strip()
            if not clean_category:
                raise ValueError("Transaction category cannot be empty.")

        # 5. Validate Timestamp if provided
        iso_timestamp: Optional[str] = None
        if timestamp is not None:
            iso_timestamp = validate_iso_date(timestamp)

        # 6. Resolve target account and adjust balance if account is specified
        target_account = None
        if account_name or account_id:
            clean_uid = user_id.strip()
            self.account_service.ensure_default_accounts(clean_uid)
            if account_id:
                target_account = self.account_service.get_account(account_id)
            if not target_account and account_name:
                target_account = self.account_service.get_account_by_name(clean_uid, account_name.strip())
                if not target_account:
                    target_account = self.account_service.create_account(clean_uid, account_name.strip())

            if target_account:
                if resolved_type == TransactionType.INCOME:
                    self.account_service.adjust_balance(target_account.id, cents)
                elif resolved_type == TransactionType.EXPENSE:
                    self.account_service.adjust_balance(target_account.id, -cents)

        # 7. Persist through repository with integer cents
        return self.repo.add_transaction(
            user_id=user_id.strip(),
            amount_cents=cents,
            transaction_type=resolved_type,
            category=clean_category,
            description=clean_description,
            timestamp=iso_timestamp,
            idempotency_key=idempotency_key.strip() if idempotency_key else None,
            account_id=target_account.id if target_account else None,
            account_name=target_account.name if target_account else None,
        )

    def get_balance(self, user_id: str) -> Dict[str, Any]:
        """Calculate cumulative balance: sum(income) - sum(expense), total income, and total expenses."""
        if not user_id or not str(user_id).strip():
            raise ValueError("User ID cannot be empty.")
        return self.repo.get_balance(user_id.strip())

    def get_category_breakdown(
        self,
        user_id: str,
        month: Optional[str] = None,
        period: Optional[str] = None,
        start_date: Optional[Union[datetime, str]] = None,
        end_date: Optional[Union[datetime, str]] = None,
    ) -> List[Dict[str, Any]]:
        """Compute category totals and percentage breakdown across spending categories.

        Includes zero-division guard for empty ledgers.
        """
        if not user_id or not str(user_id).strip():
            raise ValueError("User ID cannot be empty.")

        p = month or period
        start_val = start_date
        end_val = end_date

        if p and not start_val and not end_val:
            clean_p = p.strip()
            # If period is 'YYYY-MM'
            if re.match(r"^\d{4}-\d{2}$", clean_p):
                start_val = f"{clean_p}-01T00:00:00Z"
                # Determine end of month or next month start
                year, m = map(int, clean_p.split("-"))
                next_year = year if m < 12 else year + 1
                next_m = m + 1 if m < 12 else 1
                end_val = f"{next_year:04d}-{next_m:02d}-01T00:00:00Z"

        totals_map = self.repo.get_category_totals(
            user_id=user_id.strip(),
            start_date=start_val,
            end_date=end_val,
            transaction_type=TransactionType.EXPENSE.value,
        )

        total_cents = sum(totals_map.values())
        if total_cents == 0:
            return []

        breakdown: List[Dict[str, Any]] = []
        for cat, cents in totals_map.items():
            pct = round((cents / total_cents) * 100.0, 2)
            breakdown.append({
                "category": cat,
                "total_cents": cents,
                "total": round(cents / 100.0, 2),
                "percentage": pct,
            })

        # Sort descending by total_cents
        breakdown.sort(key=lambda x: x["total_cents"], reverse=True)
        return breakdown

    def auto_categorize(self, text: str) -> str:
        """Infer budget category from transaction description using deterministic keyword and rule heuristics."""
        if not text or not str(text).strip():
            return "Other"

        lower = str(text).lower()

        # Income keywords
        income_kws = ["salary", "paycheck", "bonus", "dividend", "interest", "deposit", "payroll", "stipend", "reimbursement", "income"]
        if any(kw in lower for kw in income_kws):
            return "Income"

        # Groceries vs Food & Dining
        groceries_kws = ["groceries", "grocery", "supermarket", "safeway", "trader joe", "whole foods", "walmart", "costco", "aldi", "kroger", "market"]
        if any(kw in lower for kw in groceries_kws):
            return "Groceries"

        dining_kws = ["lunch", "dinner", "breakfast", "brunch", "coffee", "cafe", "starbucks", "chipotle", "mcdonald", "burger", "pizza", "sushi", "restaurant", "bistro", "taco", "dining", "bar", "pub", "bakery", "food"]
        if any(kw in lower for kw in dining_kws):
            return "Food & Dining"

        # Transportation
        transport_kws = ["uber", "lyft", "gas", "fuel", "subway", "metro", "bus", "train", "transit", "taxi", "cab", "parking", "flight", "airline", "toll", "transportation", "transport"]
        if any(kw in lower for kw in transport_kws):
            return "Transportation"

        # Housing & Utilities
        housing_kws = ["rent", "mortgage", "electric", "electricity", "water bill", "utilities", "utility", "internet", "wifi", "broadband", "heating", "gas bill", "trash", "hoa", "housing"]
        if any(kw in lower for kw in housing_kws):
            return "Housing & Utilities"

        # Entertainment
        entertainment_kws = ["cinema", "movie", "movies", "netflix", "spotify", "hulu", "disney", "concert", "theatre", "theater", "game", "gaming", "steam", "playstation", "xbox", "entertainment"]
        if any(kw in lower for kw in entertainment_kws):
            return "Entertainment"

        # Health & Wellness
        health_kws = ["doctor", "dentist", "pharmacy", "medicine", "prescription", "hospital", "clinic", "gym", "fitness", "yoga", "health", "wellness", "dental", "medical"]
        if any(kw in lower for kw in health_kws):
            return "Health & Wellness"

        # Shopping
        shopping_kws = ["amazon", "clothes", "clothing", "shoes", "apparel", "electronics", "mall", "shopping", "target", "best buy", "hardware"]
        if any(kw in lower for kw in shopping_kws):
            return "Shopping"

        return "Other"

    def set_budget(
        self,
        user_id: str,
        category: str,
        monthly_limit_cents: Optional[int] = None,
        monthly_limit: Optional[Union[float, Decimal, int]] = None,
        period: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Configure a monthly spending budget for a category."""
        if not user_id or not str(user_id).strip():
            raise ValueError("User ID cannot be empty.")
        if not category or not str(category).strip():
            raise ValueError("Budget category cannot be empty.")

        cents: int
        if monthly_limit_cents is not None:
            if monthly_limit_cents <= 0:
                raise ValueError("Monthly budget limit must be greater than zero.")
            cents = monthly_limit_cents
        elif monthly_limit is not None:
            if isinstance(monthly_limit, float) and (math.isnan(monthly_limit) or math.isinf(monthly_limit)):
                raise ValueError("Monthly budget limit must be a valid positive number.")
            try:
                dec_str = str(monthly_limit).strip().lower()
                if "nan" in dec_str or "inf" in dec_str:
                    raise ValueError("Monthly budget limit must be a valid positive number.")
                dec = Decimal(str(monthly_limit))
                if dec.is_nan() or dec.is_infinite():
                    raise ValueError("Monthly budget limit must be a valid positive number.")
            except (InvalidOperation, ValueError):
                raise ValueError("Monthly budget limit must be a valid positive number.")
            if dec <= 0:
                raise ValueError("Monthly budget limit must be greater than zero.")
            cents = int(round(dec * 100))
        else:
            raise ValueError("Monthly budget limit must be provided.")

        active_period = period.strip() if period else datetime.now(timezone.utc).strftime("%Y-%m")
        return self.repo.set_budget(user_id.strip(), category.strip(), cents, active_period)

    def check_budget_alerts(self, user_id: str, period: Optional[str] = None) -> List[str]:
        """Check for budget limit threshold exceedances (>=80% warning, >=100% exceeded)

        and single high-value transaction alerts.
        """
        if not user_id or not str(user_id).strip():
            raise ValueError("User ID cannot be empty.")

        active_period = period.strip() if period else datetime.now(timezone.utc).strftime("%Y-%m")
        budgets = self.repo.list_budgets(user_id.strip(), active_period)
        alerts: List[str] = []

        # 1. Check category budgets
        for b in budgets:
            cat = b["category"]
            limit_cents = b["monthly_limit_cents"]
            spent_cents = self.repo.get_category_spending_for_period(user_id.strip(), cat, active_period)

            if spent_cents >= limit_cents:
                spent_str = f"${spent_cents / 100.0:.2f}"
                limit_str = f"${limit_cents / 100.0:.2f}"
                alerts.append(f"Budget exceeded: {cat} spending is now {spent_str} of {limit_str} limit")
            elif spent_cents >= int(limit_cents * 0.8):
                pct = (spent_cents / limit_cents) * 100.0
                spent_str = f"${spent_cents / 100.0:.2f}"
                limit_str = f"${limit_cents / 100.0:.2f}"
                alerts.append(f"Budget warning: {cat} spending is at {pct:.1f}% ({spent_str} of {limit_str} limit)")

        # 2. Check for single high-value transactions in the active period
        recent_txs = self.repo.list_transactions(user_id=user_id.strip(), limit=50)
        for tx in recent_txs:
            if tx.transaction_type == TransactionType.EXPENSE and tx.amount_cents >= self.high_value_threshold_cents:
                # Only alert if within the active period
                tx_period = tx.timestamp.strftime("%Y-%m")
                if tx_period == active_period:
                    alerts.append(
                        f"High-value expense recorded: ${tx.amount:.2f} for {tx.description} [{tx.category}]"
                    )

        return alerts

    def get_summary(
        self,
        user_id: str,
        period: Optional[str] = None,
        month: Optional[str] = None,
        start_date: Optional[Union[datetime, str]] = None,
        end_date: Optional[Union[datetime, str]] = None,
    ) -> Dict[str, Any]:
        """Compute monthly, weekly, or date-bounded financial aggregations."""
        if not user_id or not str(user_id).strip():
            raise ValueError("User ID cannot be empty.")

        p = month or period
        if p and not start_date and not end_date:
            clean_p = p.strip()
            if re.match(r"^\d{4}-\d{2}$", clean_p):
                start_date = f"{clean_p}-01T00:00:00Z"
                year, m = map(int, clean_p.split("-"))
                next_year = year if m < 12 else year + 1
                next_m = m + 1 if m < 12 else 1
                end_date = f"{next_year:04d}-{next_m:02d}-01T00:00:00Z"

        if start_date or end_date:
            # Filtered aggregation
            filtered_txs = self.repo.list_transactions(
                user_id=user_id.strip(),
                start_date=start_date,
                end_date=end_date,
                limit=10000,
            )
            income_cents = sum(t.amount_cents for t in filtered_txs if t.transaction_type == TransactionType.INCOME)
            expense_cents = sum(t.amount_cents for t in filtered_txs if t.transaction_type == TransactionType.EXPENSE)
            balance_cents = income_cents - expense_cents
            tx_count = len(filtered_txs)
            balance_data = {
                "user_id": user_id,
                "balance_cents": balance_cents,
                "income_cents": income_cents,
                "expense_cents": expense_cents,
                "net_balance": round(balance_cents / 100.0, 2),
                "total_income": round(income_cents / 100.0, 2),
                "total_expenses": round(expense_cents / 100.0, 2),
                "transaction_count": tx_count,
            }
        else:
            balance_data = self.repo.get_balance(user_id.strip())

        category_breakdown = self.get_category_breakdown(
            user_id=user_id.strip(),
            period=p,
            start_date=start_date,
            end_date=end_date,
        )

        categories_dict = {item["category"]: item["total"] for item in category_breakdown}
        alerts = self.check_budget_alerts(user_id.strip(), period=p)

        return {
            "user_id": user_id,
            "net_balance": balance_data["net_balance"],
            "total_income": balance_data["total_income"],
            "total_expenses": balance_data["total_expenses"],
            "net_savings": balance_data["net_balance"],
            "balance_cents": balance_data["balance_cents"],
            "income_cents": balance_data["income_cents"],
            "expense_cents": balance_data["expense_cents"],
            "transaction_count": balance_data["transaction_count"],
            "category_breakdown": category_breakdown,
            "categories": categories_dict,
            "budget_alerts": alerts,
            "period": p,
        }

    def void_transaction(self, transaction_id: str, user_id: Optional[str] = None) -> bool:
        """Void / delete an errant transaction idempotently, reversing linked account balance if present."""
        if not transaction_id or not str(transaction_id).strip():
            raise ValueError("Transaction ID cannot be empty.")
        clean_tx_id = transaction_id.strip()
        clean_user_id = user_id.strip() if user_id else None

        # Look up transaction before deletion to retrieve linked account details
        existing_tx = self.repo.get_transaction(clean_tx_id)
        deleted = self.repo.delete_transaction(clean_tx_id, user_id=clean_user_id)
        if deleted and existing_tx and getattr(self, "account_service", None):
            if existing_tx.account_id:
                t_type = (
                    existing_tx.transaction_type.value
                    if hasattr(existing_tx.transaction_type, "value")
                    else str(existing_tx.transaction_type)
                ).lower()
                if t_type == "expense":
                    self.account_service.adjust_balance(existing_tx.account_id, existing_tx.amount_cents)
                elif t_type == "income":
                    self.account_service.adjust_balance(existing_tx.account_id, -existing_tx.amount_cents)
        return deleted

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
        """Query transactions by date range, category, or type."""
        if not user_id or not str(user_id).strip():
            raise ValueError("User ID cannot be empty.")

        # Validate date filters if supplied
        iso_start = validate_iso_date(start_date) if start_date else None
        iso_end = validate_iso_date(end_date) if end_date else None

        return self.repo.list_transactions(
            user_id=user_id.strip(),
            start_date=iso_start,
            end_date=iso_end,
            category=category.strip() if category else None,
            transaction_type=transaction_type,
            limit=limit,
            offset=offset,
        )
