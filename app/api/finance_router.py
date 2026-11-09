"""FastAPI router for Personal Finance Ledger & Analytics REST endpoints (R2)."""

from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator

from app.database.connection import DatabaseManager, get_default_manager
from app.services.finance_service import FinanceService, validate_iso_date
from app.services.account_service import AccountService
from app.services.debt_service import DebtService
from app.services.subscription_service import SubscriptionService

router = APIRouter(tags=["finance"])
finance_router = router

# Service dependency injection
_service_instance: Optional[FinanceService] = None
_account_service_instance: Optional[AccountService] = None
_debt_service_instance: Optional[DebtService] = None
_subscription_service_instance: Optional[SubscriptionService] = None


def get_finance_service() -> FinanceService:
    """Dependency provider for FinanceService."""
    global _service_instance
    if _service_instance is None:
        _service_instance = FinanceService(db_manager=get_default_manager())
    return _service_instance


def set_finance_service(service: Optional[FinanceService]) -> None:
    """Set global FinanceService instance (primarily for testing with isolated in-memory DB)."""
    global _service_instance, _account_service_instance, _debt_service_instance, _subscription_service_instance
    _service_instance = service
    if service is None:
        _account_service_instance = None
        _debt_service_instance = None
        _subscription_service_instance = None
        return
    db_mgr = getattr(service.repo, "db_manager", None)
    if db_mgr:
        _account_service_instance = AccountService(db_manager=db_mgr)
        _debt_service_instance = DebtService(db_manager=db_mgr, account_service=_account_service_instance)
        _subscription_service_instance = SubscriptionService(db_manager=db_mgr)


def _get_active_db_manager() -> DatabaseManager:
    """Safely obtain active DatabaseManager instance."""
    if _service_instance and hasattr(_service_instance, "repo"):
        return (
            getattr(_service_instance.repo, "db", None)
            or getattr(_service_instance.repo, "db_manager", None)
            or get_default_manager()
        )
    return get_default_manager()


def get_effective_user_id(user_id: Optional[str] = None) -> str:
    """Resolve effective user_id: if 'default_user' has no data, fallback to active Telegram user."""
    eff_user = (user_id or "default_user").strip()
    if eff_user == "default_user":
        try:
            db_mgr = _get_active_db_manager()
            with db_mgr.connection() as conn:
                row = conn.execute(
                    "SELECT user_id FROM users WHERE telegram_chat_id IS NOT NULL ORDER BY created_at DESC LIMIT 1;"
                ).fetchone()
                if row and row["user_id"]:
                    return str(row["user_id"])
        except Exception:
            pass
    return eff_user


def get_account_service() -> AccountService:
    """Dependency provider for AccountService."""
    global _account_service_instance
    if _account_service_instance is None:
        db_mgr = _get_active_db_manager()
        _account_service_instance = AccountService(db_manager=db_mgr)
    return _account_service_instance


def set_account_service(service: AccountService) -> None:
    """Set global AccountService instance for testing."""
    global _account_service_instance
    _account_service_instance = service


def get_debt_service() -> DebtService:
    """Dependency provider for DebtService."""
    global _debt_service_instance
    if _debt_service_instance is None:
        db_mgr = _get_active_db_manager()
        _debt_service_instance = DebtService(db_manager=db_mgr, account_service=get_account_service())
    return _debt_service_instance


def set_debt_service(service: DebtService) -> None:
    """Set global DebtService instance for testing."""
    global _debt_service_instance
    _debt_service_instance = service


def get_subscription_service() -> SubscriptionService:
    """Dependency provider for SubscriptionService."""
    global _subscription_service_instance
    if _subscription_service_instance is None:
        db_mgr = _get_active_db_manager()
        _subscription_service_instance = SubscriptionService(db_manager=db_mgr)
    return _subscription_service_instance


def set_subscription_service(service: SubscriptionService) -> None:
    """Set global SubscriptionService instance for testing."""
    global _subscription_service_instance
    _subscription_service_instance = service


# Pydantic Request Models
class TransactionCreateRequest(BaseModel):
    amount: Optional[Decimal] = None
    amount_cents: Optional[int] = None
    type: Optional[str] = None
    transaction_type: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    date: Optional[str] = None
    timestamp: Optional[str] = None
    user_id: Optional[str] = "default_user"
    idempotency_key: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def validate_fields(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values

        # Resolve amount / amount_cents
        amt = values.get("amount")
        amt_cents = values.get("amount_cents")

        if amt is None and amt_cents is None:
            raise ValueError("Transaction amount must be specified.")

        if amt is not None:
            try:
                dec = Decimal(str(amt).strip())
            except Exception:
                raise ValueError("Invalid numeric format for transaction amount.")

            if dec <= Decimal("0"):
                if dec < Decimal("0"):
                    raise ValueError("Amount must be positive; specify type as expense or income.")
                raise ValueError("Transaction amount must be greater than zero.")

            exp = dec.as_tuple().exponent
            if isinstance(exp, int) and exp < -2:
                raise ValueError("Amount cannot have more than 2 decimal places.")

        if amt_cents is not None:
            if not isinstance(amt_cents, int) or amt_cents <= 0:
                raise ValueError("Transaction amount must be greater than zero.")

        # Resolve transaction type
        t_type = values.get("type") or values.get("transaction_type")
        if not t_type or str(t_type).strip().lower() not in ("income", "expense"):
            raise ValueError("Invalid transaction type: must be 'income' or 'expense'.")

        # Resolve description
        desc = values.get("description")
        if desc is None or not str(desc).strip():
            raise ValueError("Transaction description cannot be empty.")

        # Resolve category
        cat = values.get("category")
        if cat is not None and not str(cat).strip():
            raise ValueError("Transaction category cannot be empty.")

        # Validate date/timestamp if provided
        raw_date = values.get("date") or values.get("timestamp")
        if raw_date is not None:
            try:
                validate_iso_date(str(raw_date))
            except ValueError as e:
                raise ValueError(str(e))

        return values


class BudgetCreateRequest(BaseModel):
    category: str = Field(..., min_length=1)
    monthly_limit: Optional[Decimal] = None
    monthly_limit_cents: Optional[int] = None
    period: Optional[str] = None
    user_id: Optional[str] = "default_user"

    @model_validator(mode="before")
    @classmethod
    def validate_budget(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        cat = values.get("category")
        if not cat or not str(cat).strip():
            raise ValueError("Budget category cannot be empty.")

        limit = values.get("monthly_limit")
        limit_cents = values.get("monthly_limit_cents")
        if limit is None and limit_cents is None:
            raise ValueError("Monthly budget limit must be provided.")
        if limit is not None and Decimal(str(limit)) <= 0:
            raise ValueError("Monthly budget limit must be greater than zero.")
        if limit_cents is not None and limit_cents <= 0:
            raise ValueError("Monthly budget limit must be greater than zero.")
        return values


# Endpoints


def _handle_summary(
    user_id: str,
    month: Optional[str],
    period: Optional[str],
    start_date: Optional[str],
    end_date: Optional[str],
    service: FinanceService,
) -> Dict[str, Any]:
    if start_date:
        try:
            validate_iso_date(start_date)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid date format. Expected ISO-8601 (YYYY-MM-DD).",
            )
    if end_date:
        try:
            validate_iso_date(end_date)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="Invalid date format. Expected ISO-8601 (YYYY-MM-DD).",
            )

    return service.get_summary(
        user_id=user_id,
        period=period or month,
        month=month,
        start_date=start_date,
        end_date=end_date,
    )


@router.get("/api/finance/summary")
@router.get("/summary")
def get_summary(
    user_id: str = Query("default_user", description="User ID"),
    month: Optional[str] = Query(None, description="Month in YYYY-MM format"),
    period: Optional[str] = Query(None, description="Period in YYYY-MM format"),
    start_date: Optional[str] = Query(None, description="Start date ISO-8601"),
    end_date: Optional[str] = Query(None, description="End date ISO-8601"),
    service: FinanceService = Depends(get_finance_service),
) -> Dict[str, Any]:
    summary = _handle_summary(user_id, month, period, start_date, end_date, service)
    if user_id == "default_user" and summary.get("transaction_count", 0) == 0:
        try:
            with service.repo.db.connection() as conn:
                row = conn.execute("SELECT user_id FROM transactions ORDER BY created_at DESC LIMIT 1;").fetchone()
                if row and row["user_id"] != user_id:
                    alt_summary = _handle_summary(row["user_id"], month, period, start_date, end_date, service)
                    if alt_summary.get("transaction_count", 0) > 0:
                        return alt_summary
        except Exception:
            pass
    return summary


def _handle_list_transactions(
    user_id: str,
    start_date: Optional[str],
    end_date: Optional[str],
    category: Optional[str],
    t_type: Optional[str],
    limit: int,
    offset: int,
    service: FinanceService,
) -> List[Dict[str, Any]]:
    if start_date:
        try:
            validate_iso_date(start_date)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="Invalid date format. Expected ISO-8601 (YYYY-MM-DD).",
            )
    if end_date:
        try:
            validate_iso_date(end_date)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="Invalid date format. Expected ISO-8601 (YYYY-MM-DD).",
            )

    txs = service.list_transactions(
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
        category=category,
        transaction_type=t_type,
        limit=limit,
        offset=offset,
    )
    return [tx.to_dict() for tx in txs]


@router.get("/api/finance/transactions")
@router.get("/transactions")
def list_transactions(
    user_id: str = Query("default_user"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    service: FinanceService = Depends(get_finance_service),
) -> List[Dict[str, Any]]:
    return _handle_list_transactions(user_id, start_date, end_date, category, type, limit, offset, service)


@router.get("/api/finance/categories")
@router.get("/categories")
def get_categories(
    user_id: str = Query("default_user"),
    month: Optional[str] = Query(None),
    period: Optional[str] = Query(None),
    service: FinanceService = Depends(get_finance_service),
) -> List[Dict[str, Any]]:
    return service.get_category_breakdown(user_id=user_id, month=month, period=period)


def _handle_create_transaction(
    payload: TransactionCreateRequest,
    service: FinanceService,
) -> Dict[str, Any]:
    resolved_type = payload.type or payload.transaction_type
    raw_date = payload.date or payload.timestamp

    try:
        record = service.record_transaction(
            user_id=payload.user_id or "default_user",
            amount=payload.amount,
            amount_cents=payload.amount_cents,
            transaction_type=resolved_type,
            category=payload.category,
            description=payload.description,
            timestamp=raw_date,
            idempotency_key=payload.idempotency_key,
        )
        return record.to_dict()
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail=str(e),
        )


@router.post("/api/finance/transactions", status_code=status.HTTP_201_CREATED)
@router.post("/api/finance/transaction", status_code=status.HTTP_201_CREATED)
@router.post("/transactions", status_code=status.HTTP_201_CREATED)
@router.post("/transaction", status_code=status.HTTP_201_CREATED)
def create_transaction(
    payload: TransactionCreateRequest,
    service: FinanceService = Depends(get_finance_service),
) -> Dict[str, Any]:
    return _handle_create_transaction(payload, service)


@router.delete("/api/finance/transactions/{id}")
@router.delete("/transactions/{id}")
def delete_transaction(
    id: str,
    user_id: Optional[str] = Query(None),
    service: FinanceService = Depends(get_finance_service),
) -> Dict[str, Any]:
    deleted = service.void_transaction(transaction_id=id, user_id=user_id)
    return {
        "success": True,
        "message": "Transaction voided",
        "id": id,
        "deleted": deleted,
    }


@router.post("/api/finance/budgets", status_code=status.HTTP_201_CREATED)
@router.post("/budgets", status_code=status.HTTP_201_CREATED)
def create_budget(
    payload: BudgetCreateRequest,
    service: FinanceService = Depends(get_finance_service),
) -> Dict[str, Any]:
    try:
        return service.set_budget(
            user_id=payload.user_id or "default_user",
            category=payload.category,
            monthly_limit=payload.monthly_limit,
            monthly_limit_cents=payload.monthly_limit_cents,
            period=payload.period,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail=str(e),
        )


@router.get("/api/finance/budgets")
@router.get("/budgets")
def list_budgets(
    user_id: str = Query("default_user"),
    period: Optional[str] = Query(None),
    service: FinanceService = Depends(get_finance_service),
) -> List[Dict[str, Any]]:
    return service.repo.list_budgets(user_id=user_id, period=period)


# =============================================================================
# Colombian Banking, Debts & Subscriptions REST Models & Endpoints (M7 / R1-R4)
# =============================================================================

class AccountCreateRequest(BaseModel):
    name: str = Field(..., min_length=1)
    account_type: str = "digital_wallet"
    initial_balance: Optional[Decimal] = None
    initial_balance_cents: Optional[int] = 0
    currency: str = "COP"
    color: Optional[str] = None
    icon: Optional[str] = None
    user_id: Optional[str] = "default_user"


class TransferRequest(BaseModel):
    from_account: Optional[str] = None
    from_account_name: Optional[str] = None
    from_account_id: Optional[str] = None
    to_account: Optional[str] = None
    to_account_name: Optional[str] = None
    to_account_id: Optional[str] = None
    amount: Optional[Decimal] = None
    amount_cents: Optional[int] = None
    fee_cents: Optional[int] = 0
    note: Optional[str] = None
    description: Optional[str] = None
    user_id: Optional[str] = "default_user"


class DebtCreateRequest(BaseModel):
    counterparty: str = Field(..., min_length=1)
    amount: Optional[Decimal] = None
    amount_cents: Optional[int] = None
    debt_type: Optional[str] = None
    type: Optional[str] = None
    reason: Optional[str] = None
    notes: Optional[str] = None
    due_date: Optional[str] = None
    account: Optional[str] = None
    account_name: Optional[str] = None
    account_id: Optional[str] = None
    user_id: Optional[str] = "default_user"
    adjust_account_balance: Optional[bool] = True


class DebtSettleRequest(BaseModel):
    amount: Optional[Decimal] = None
    amount_cents: Optional[int] = None
    account: Optional[str] = None
    account_name: Optional[str] = None
    account_id: Optional[str] = None
    notes: Optional[str] = None
    user_id: Optional[str] = "default_user"


class SubscriptionCreateRequest(BaseModel):
    name: Optional[str] = None
    service_name: Optional[str] = None
    amount: Optional[Decimal] = None
    amount_cents: Optional[int] = None
    billing_cycle: Optional[str] = "monthly"
    billing_day: Optional[int] = None
    renewal_day: Optional[int] = None
    next_payment_date: Optional[str] = None
    account: Optional[str] = None
    account_name: Optional[str] = None
    account_id: Optional[str] = None
    category: Optional[str] = "Entertainment"
    reminder_days_before: Optional[int] = 3
    notes: Optional[str] = None
    user_id: Optional[str] = "default_user"


# --- Accounts Endpoints ---

@router.get("/api/finance/accounts")
@router.get("/api/accounts")
@router.get("/accounts")
def list_accounts(
    user_id: str = Query("default_user"),
    active_only: bool = Query(True),
    as_list: bool = Query(False),
    service: AccountService = Depends(get_account_service),
) -> Any:
    """Retrieve all accounts and net worth breakdown."""
    eff_user = get_effective_user_id(user_id)
    service.ensure_default_accounts(eff_user)
    net_worth = service.get_net_worth(eff_user)
    if as_list:
        return net_worth["accounts"]
    return net_worth


@router.get("/api/finance/net-worth")
@router.get("/api/net-worth")
def get_net_worth_endpoint(
    user_id: str = Query("default_user"),
    service: AccountService = Depends(get_account_service),
) -> Dict[str, Any]:
    """Retrieve total net worth and asset allocation percentages."""
    eff_user = get_effective_user_id(user_id)
    service.ensure_default_accounts(eff_user)
    return service.get_net_worth(eff_user)


@router.post("/api/finance/accounts", status_code=status.HTTP_201_CREATED)
@router.post("/api/accounts", status_code=status.HTTP_201_CREATED)
@router.post("/accounts", status_code=status.HTTP_201_CREATED)
def create_account(
    payload: AccountCreateRequest,
    user_id: Optional[str] = Query(None),
    service: AccountService = Depends(get_account_service),
) -> Dict[str, Any]:
    """Create a new custom user account."""
    eff_user = user_id or payload.user_id or "default_user"
    try:
        init_cents = payload.initial_balance_cents
        if payload.initial_balance is not None:
            init_cents = int(round(payload.initial_balance * 100))
        rec = service.create_account(
            user_id=eff_user,
            name=payload.name,
            account_type=payload.account_type,
            initial_balance_cents=init_cents or 0,
            currency=payload.currency,
            color=payload.color,
            icon=payload.icon,
        )
        acc_dict = rec.to_dict()
        acc_dict["account"] = rec.to_dict()
        return acc_dict
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/api/finance/transfers", status_code=status.HTTP_201_CREATED)
@router.post("/api/finance/accounts/transfers", status_code=status.HTTP_201_CREATED)
@router.post("/api/accounts/transfers", status_code=status.HTTP_201_CREATED)
@router.post("/api/transfers", status_code=status.HTTP_201_CREATED)
@router.post("/transfers", status_code=status.HTTP_201_CREATED)
def execute_transfer(
    payload: TransferRequest,
    user_id: Optional[str] = Query(None),
    service: AccountService = Depends(get_account_service),
) -> Dict[str, Any]:
    """Execute an invariant-preserving inter-account transfer."""
    eff_user = user_id or payload.user_id or "default_user"
    from_acc = payload.from_account or payload.from_account_name or payload.from_account_id
    to_acc = payload.to_account or payload.to_account_name or payload.to_account_id
    if not from_acc:
        raise HTTPException(status_code=400, detail="Source account must be specified.")
    if not to_acc:
        raise HTTPException(status_code=400, detail="Destination account must be specified.")

    amt_cents = payload.amount_cents
    if payload.amount is not None:
        try:
            amt_cents = int(round(payload.amount * 100))
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid transfer amount.")

    if amt_cents is None or amt_cents <= 0:
        raise HTTPException(status_code=400, detail="Transfer amount must be greater than zero.")

    try:
        record = service.transfer(
            user_id=eff_user,
            from_account_name_or_id=from_acc,
            to_account_name_or_id=to_acc,
            amount_cents=amt_cents,
            fee_cents=payload.fee_cents or 0,
            description=payload.note or payload.description or "",
        )
        return {
            "success": True,
            "transfer": record.to_dict(),
            "net_worth": service.get_net_worth(eff_user),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Debts & Receivables Endpoints ---

@router.get("/api/finance/debts")
@router.get("/api/debts")
@router.get("/debts")
def list_debts(
    user_id: str = Query("default_user"),
    status: Optional[str] = Query(None),
    debt_type: Optional[str] = Query(None),
    counterparty: Optional[str] = Query(None),
    as_list: bool = Query(False),
    service: DebtService = Depends(get_debt_service),
) -> Any:
    """List debts and receivables with optional filters."""
    eff_user = get_effective_user_id(user_id)
    records = service.list_debts(
        user_id=eff_user,
        debt_type=debt_type,
        status=status,
        counterparty=counterparty,
    )
    raw_list = [r.to_dict() for r in records]
    if as_list:
        return raw_list
    recs = [d for d in raw_list if (d.get("debt_type") or d.get("type")) == "receivable"]
    pays = [d for d in raw_list if (d.get("debt_type") or d.get("type")) in ("debt", "payable")]
    total_rec = sum(d.get("remaining_cents", 0) for d in recs) / 100.0
    total_pay = sum(d.get("remaining_cents", 0) for d in pays) / 100.0
    return {
        "debts": raw_list,
        "receivables": recs,
        "payables": pays,
        "total_receivable": total_rec,
        "total_payable": total_pay,
    }


@router.post("/api/finance/debts", status_code=status.HTTP_201_CREATED)
@router.post("/api/debts", status_code=status.HTTP_201_CREATED)
@router.post("/debts", status_code=status.HTTP_201_CREATED)
def create_debt(
    payload: DebtCreateRequest,
    user_id: Optional[str] = Query(None),
    service: DebtService = Depends(get_debt_service),
) -> Dict[str, Any]:
    """Record a debt (owed by user) or loan (owed to user)."""
    eff_user = user_id or payload.user_id or "default_user"
    resolved_type = payload.debt_type or payload.type or "receivable"
    if resolved_type == "debt":
        resolved_type = "payable"
    amt_cents = payload.amount_cents
    if payload.amount is not None:
        try:
            amt_cents = int(round(payload.amount * 100))
        except Exception:
            raise HTTPException(status_code=422, detail="Invalid debt amount.")

    if amt_cents is None or amt_cents <= 0:
        raise HTTPException(status_code=422, detail="Debt amount must be greater than zero.")

    reason = payload.reason or payload.notes or "préstamo"

    try:
        record = service.record_debt(
            user_id=eff_user,
            counterparty=payload.counterparty,
            amount_cents=amt_cents,
            debt_type=resolved_type,
            reason=reason,
            due_date=payload.due_date,
            account_name=payload.account or payload.account_name,
            account_id=payload.account_id,
            adjust_account_balance=payload.adjust_account_balance if payload.adjust_account_balance is not None else True,
        )
        debt_dict = record.to_dict()
        debt_dict["debt"] = record.to_dict()
        return debt_dict
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/api/finance/debts/{debt_id}/settle")
@router.post("/api/debts/{debt_id}/settle")
@router.post("/debts/{debt_id}/settle")
def settle_debt_endpoint(
    debt_id: str,
    payload: Optional[DebtSettleRequest] = None,
    user_id: Optional[str] = Query(None),
    service: DebtService = Depends(get_debt_service),
) -> Dict[str, Any]:
    """Execute a full or partial debt settlement payment."""
    eff_user = user_id or (payload.user_id if payload else None) or "default_user"
    amt_cents = None
    account = None
    account_id = None
    notes = None

    if payload is not None:
        account = payload.account or payload.account_name
        account_id = payload.account_id
        notes = payload.notes
        if payload.amount_cents is not None:
            amt_cents = payload.amount_cents
        elif payload.amount is not None:
            amt_cents = int(round(payload.amount * 100))

    try:
        debt = service.get_debt(debt_id)
        if not debt:
            raise HTTPException(status_code=404, detail=f"Debt '{debt_id}' not found.")

        if amt_cents is not None and amt_cents > 0:
            res = service.record_payment(
                user_id=eff_user,
                debt_id=debt_id,
                amount_cents=amt_cents,
                account_name=account,
                account_id=account_id,
                notes=notes,
            )
        else:
            res = service.settle_debt(
                user_id=eff_user,
                debt_id=debt_id,
                account_name=account,
                account_id=account_id,
                notes=notes,
            )
        if isinstance(res, dict) and "status" not in res:
            res["status"] = "settled" if res.get("settled") else "partially_paid"
        return res
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


# --- Subscriptions Endpoints ---

@router.get("/api/finance/subscriptions")
@router.get("/api/subscriptions")
@router.get("/subscriptions")
def list_subscriptions(
    user_id: str = Query("default_user"),
    status: Optional[str] = Query("active"),
    as_list: bool = Query(False),
    service: SubscriptionService = Depends(get_subscription_service),
) -> Any:
    """List all recurring subscriptions."""
    eff_user = get_effective_user_id(user_id)
    records = service.list_subscriptions(user_id=eff_user, status=status)
    raw_list = [r.to_dict() for r in records]
    if as_list:
        return raw_list
    total_monthly = sum(r.amount for r in records if r.billing_cycle == "monthly")
    return {
        "subscriptions": raw_list,
        "active_count": len([r for r in records if r.is_active]),
        "total_monthly": total_monthly,
    }


@router.post("/api/finance/subscriptions", status_code=status.HTTP_201_CREATED)
@router.post("/api/subscriptions", status_code=status.HTTP_201_CREATED)
@router.post("/subscriptions", status_code=status.HTTP_201_CREATED)
def create_subscription(
    payload: SubscriptionCreateRequest,
    user_id: Optional[str] = Query(None),
    service: SubscriptionService = Depends(get_subscription_service),
) -> Dict[str, Any]:
    """Add a new recurring subscription."""
    eff_user = user_id or payload.user_id or "default_user"
    name = payload.name or payload.service_name
    if not name or not name.strip():
        raise HTTPException(status_code=422, detail="Subscription name cannot be empty.")

    amt_cents = payload.amount_cents
    if payload.amount is not None:
        try:
            amt_cents = int(round(payload.amount * 100))
        except Exception:
            raise HTTPException(status_code=422, detail="Invalid subscription amount.")

    if amt_cents is None or amt_cents <= 0:
        raise HTTPException(status_code=422, detail="Subscription amount must be greater than zero.")

    b_day = payload.billing_day or payload.renewal_day

    try:
        record = service.create_subscription(
            user_id=eff_user,
            name=name.strip(),
            amount_cents=amt_cents,
            billing_cycle=payload.billing_cycle or "monthly",
            billing_day=b_day,
            next_payment_date=payload.next_payment_date,
            account_name=payload.account or payload.account_name,
            account_id=payload.account_id,
            category=payload.category or "Entertainment",
            reminder_days_before=payload.reminder_days_before or 3,
            notes=payload.notes,
        )
        sub_dict = record.to_dict()
        sub_dict["subscription"] = record.to_dict()
        return sub_dict
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


# --- Payment Calendar Timeline ---

@router.get("/api/finance/calendar/payments")
@router.get("/api/calendar/payments")
@router.get("/calendar/payments")
def get_upcoming_payments_calendar(
    user_id: str = Query("default_user"),
    days_ahead: int = Query(30, ge=1, le=365),
    reference_date: Optional[str] = Query(None),
    as_list: bool = Query(False),
    service: SubscriptionService = Depends(get_subscription_service),
) -> Any:
    """Retrieve chronological timeline merging subscriptions, debts, and loan receivables."""
    eff_user = get_effective_user_id(user_id)
    items = service.get_upcoming_payments(
        user_id=eff_user,
        days_ahead=days_ahead,
        reference_date=reference_date,
    )
    if as_list:
        return items

    sub_items = [p for p in items if p.get("item_type") == "subscription"]
    debt_items = [p for p in items if p.get("item_type") in ("debt", "receivable")]
    total_outflow = sum(p["amount"] for p in items if p.get("direction") == "outflow")
    total_inflow = sum(p["amount"] for p in items if p.get("direction") == "inflow")

    return {
        "upcoming_payments": items,
        "total_count": len(items),
        "days_ahead": days_ahead,
        "summary": {
            "active_subscriptions_count": len(sub_items),
            "debts_count": len(debt_items),
            "total_outflow": round(total_outflow, 2),
            "total_inflow": round(total_inflow, 2),
        },
    }
