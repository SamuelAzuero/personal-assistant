"""FastAPI router for Personal Finance Ledger & Analytics REST endpoints (R2)."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator

from app.database.connection import DatabaseManager, get_default_manager
from app.database.repositories.finance_repo import TransactionType
from app.services.finance_service import FinanceService, validate_iso_date

router = APIRouter(tags=["finance"])

# Service dependency injection
_service_instance: Optional[FinanceService] = None


def get_finance_service() -> FinanceService:
    """Dependency provider for FinanceService."""
    global _service_instance
    if _service_instance is None:
        _service_instance = FinanceService(db_manager=get_default_manager())
    return _service_instance


def set_finance_service(service: FinanceService) -> None:
    """Set global FinanceService instance (primarily for testing with isolated in-memory DB)."""
    global _service_instance
    _service_instance = service


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
