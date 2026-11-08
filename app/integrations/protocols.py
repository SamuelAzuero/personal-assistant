"""Protocols and core data models for personal assistant integrations."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


class IntentType(str, Enum):
    """Supported user intent types."""
    FINANCE_ENTRY = "finance_entry"
    FINANCE_QUERY = "finance_query"
    EMAIL_CHECK = "email_check"
    CALENDAR_SCHEDULE = "calendar_schedule"
    CALENDAR_QUERY = "calendar_query"
    TASK_CREATE = "task_create"
    TASK_LIST = "task_list"
    TASK_COMPLETE = "task_complete"
    TASK_DELETE = "task_delete"
    DAILY_BRIEFING = "daily_briefing"
    FINANCIAL_ADVICE = "financial_advice"
    OUTING_RESEARCH = "outing_research"
    ACCOUNT_TRANSFER = "account_transfer"
    ACCOUNT_QUERY = "account_query"
    DEBT_RECORD = "debt_record"
    DEBT_SETTLE = "debt_settle"
    DEBT_QUERY = "debt_query"
    SUBSCRIPTION_RECORD = "subscription_record"
    UPCOMING_PAYMENTS_QUERY = "upcoming_payments_query"
    CANCEL = "cancel"
    UNKNOWN = "unknown"


@dataclass
class IntentResult:
    """Normalized output from natural language intent parsing."""
    intent: IntentType
    confidence: float
    slots: Dict[str, Any] = field(default_factory=dict)
    is_complete: bool = True
    missing_slots: List[str] = field(default_factory=list)
    raw_text: str = ""


@runtime_checkable
class IntentParserProtocol(Protocol):
    """Protocol for intent and slot extraction."""
    def parse(self, text: str, session_context: Optional[Dict[str, Any]] = None) -> IntentResult:
        ...


class TransactionType(str, Enum):
    """Personal finance transaction type."""
    EXPENSE = "expense"
    INCOME = "income"


@dataclass
class TransactionRecord:
    """Record of a financial transaction with exact integer cents."""
    id: str
    user_id: str
    amount_cents: int
    transaction_type: TransactionType
    category: str
    description: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


@runtime_checkable
class FinanceServiceProtocol(Protocol):
    """Protocol for personal finance ledger operations."""
    def record_transaction(
        self,
        user_id: str,
        amount_cents: int,
        t_type: TransactionType,
        category: str,
        description: str,
    ) -> TransactionRecord:
        ...

    def get_balance(self, user_id: str) -> Dict[str, Any]:
        """Returns balance_cents, income_cents, expense_cents."""
        ...

    def get_category_breakdown(
        self, user_id: str, month: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        ...

    def check_budget_alerts(self, user_id: str) -> List[str]:
        ...


@runtime_checkable
class EmailServiceProtocol(Protocol):
    """Protocol for email monitoring and digest generation."""
    def poll_unread(self, user_id: str) -> List[Dict[str, Any]]:
        ...

    def generate_digest(self, user_id: str) -> Dict[str, Any]:
        """Returns urgent_count, items: List[Dict], summary_text."""
        ...


@runtime_checkable
class CalendarServiceProtocol(Protocol):
    """Protocol for Google Calendar event management and conflict detection."""
    def list_events(
        self, user_id: str, start_time: datetime, end_time: datetime
    ) -> List[Dict[str, Any]]:
        ...

    def create_event(
        self,
        user_id: str,
        title: str,
        start_time: datetime,
        end_time: datetime,
        location: str = "",
    ) -> Dict[str, Any]:
        ...

    def check_conflicts(
        self, user_id: str, start_time: datetime, end_time: datetime
    ) -> List[Dict[str, Any]]:
        ...


@runtime_checkable
class TaskServiceProtocol(Protocol):
    """Protocol for daily task and reminder management."""
    def create_task(
        self,
        user_id: str,
        title: str,
        due_date: Optional[datetime] = None,
        priority: str = "medium",
    ) -> Dict[str, Any]:
        ...

    def list_tasks(
        self, user_id: str, status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        ...


@runtime_checkable
class SearchServiceProtocol(Protocol):
    """Protocol for outing, dining, and activity research."""
    def search_outings(
        self, user_id: str, query: str, location: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        ...


@runtime_checkable
class AudioTranscriptionProtocol(Protocol):
    """Protocol for audio note speech-to-text decoding."""
    def transcribe(self, audio_bytes: bytes, filename: str = "voice.ogg") -> str:
        ...


@runtime_checkable
class TelegramClientProtocol(Protocol):
    """Protocol for sending responses to Telegram."""
    def send_message(
        self,
        chat_id: str,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
        parse_mode: str = "Markdown",
    ) -> Dict[str, Any]:
        ...
