"""Global hermetic test fixtures and test doubles for E2E opaque-box test suite."""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

import pytest
from fastapi.testclient import TestClient

from app.integrations.protocols import (
    AudioTranscriptionProtocol,
    CalendarServiceProtocol,
    EmailServiceProtocol,
    FinanceServiceProtocol,
    IntentParserProtocol,
    IntentResult,
    IntentType,
    SearchServiceProtocol,
    TelegramClientProtocol,
    TransactionRecord,
    TransactionType,
)


FIXTURES_DIR = Path(__file__).parent / "fixtures"
SCHEMA_PATH = Path(__file__).parent.parent / "app" / "database" / "schema.sql"
FIXED_TIMESTAMP_STR = "2026-11-04T12:00:00Z"
FIXED_DATETIME = datetime(2026, 11, 4, 12, 0, 0, tzinfo=timezone.utc)


# ============================================================================
# Deterministic Clock Fixtures
# ============================================================================

@pytest.fixture(scope="session")
def fixed_clock() -> str:
    """Fixed ISO-8601 UTC timestamp string pinned to 2026-11-04T12:00:00Z."""
    return FIXED_TIMESTAMP_STR


@pytest.fixture(scope="session")
def fixed_datetime() -> datetime:
    """Fixed datetime object pinned to 2026-11-04T12:00:00Z."""
    return FIXED_DATETIME


# ============================================================================
# Static JSON Fixture Loaders
# ============================================================================

@pytest.fixture(scope="session")
def financial_fixtures() -> Dict[str, Any]:
    with open(FIXTURES_DIR / "financial_transactions.json", "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def gmail_fixtures() -> Dict[str, Any]:
    with open(FIXTURES_DIR / "gmail_payloads.json", "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def calendar_fixtures() -> Dict[str, Any]:
    with open(FIXTURES_DIR / "calendar_events.json", "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def telegram_fixtures() -> Dict[str, Any]:
    with open(FIXTURES_DIR / "telegram_updates.json", "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def multi_turn_fixtures() -> Dict[str, Any]:
    with open(FIXTURES_DIR / "multi_turn_conversations.json", "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================================
# Hermetic In-Memory SQLite Database Fixture
# ============================================================================

@pytest.fixture
def mock_db() -> Generator[sqlite3.Connection, None, None]:
    """Yields a freshly migrated isolated in-memory SQLite connection."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")

    if SCHEMA_PATH.exists():
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
    else:
        # Fallback DDL if schema.sql is not found
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                telegram_chat_id TEXT UNIQUE,
                full_name TEXT,
                timezone TEXT DEFAULT 'UTC',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS conversation_sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                active_intent TEXT,
                context_json TEXT DEFAULT '{}',
                turn_count INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS transactions (
                transaction_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                amount_cents INTEGER NOT NULL,
                transaction_type TEXT NOT NULL CHECK(transaction_type IN ('income', 'expense')),
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                idempotency_key TEXT UNIQUE,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS budgets (
                budget_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                category TEXT NOT NULL,
                monthly_limit_cents INTEGER NOT NULL,
                period TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, category, period),
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                priority TEXT NOT NULL DEFAULT 'medium' CHECK(priority IN ('low', 'medium', 'high', 'urgent')),
                due_date TIMESTAMP,
                is_completed BOOLEAN NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS calendar_events (
                event_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                external_calendar_id TEXT,
                summary TEXT NOT NULL,
                description TEXT,
                location TEXT,
                start_time TIMESTAMP NOT NULL,
                end_time TIMESTAMP NOT NULL,
                is_all_day BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS email_messages (
                message_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                sender TEXT NOT NULL,
                subject TEXT NOT NULL,
                snippet TEXT,
                is_urgent BOOLEAN DEFAULT 0,
                category TEXT DEFAULT 'general',
                received_at TIMESTAMP NOT NULL,
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            );
        """)

    # Seed default test user
    conn.execute(
        "INSERT OR IGNORE INTO users (user_id, telegram_chat_id, full_name) VALUES (?, ?, ?)",
        ("usr_test_default", "998877", "Test User"),
    )
    conn.commit()

    try:
        yield conn
    finally:
        conn.close()


# ============================================================================
# High-Fidelity Test Doubles (Integration Mocks)
# ============================================================================

class MockTelegramBotClient(TelegramClientProtocol):
    """In-memory Telegram Bot API mock recording all sent messages."""

    def __init__(self) -> None:
        self.sent_messages: List[Dict[str, Any]] = []

    def send_message(
        self,
        chat_id: str,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
        parse_mode: str = "Markdown",
    ) -> Dict[str, Any]:
        msg = {
            "message_id": len(self.sent_messages) + 1,
            "chat_id": str(chat_id),
            "text": text,
            "reply_markup": reply_markup,
            "parse_mode": parse_mode,
            "sent_at": datetime.now(timezone.utc).isoformat(),
        }
        self.sent_messages.append(msg)
        return {"ok": True, "result": msg}

    def get_last_message(self) -> Optional[Dict[str, Any]]:
        return self.sent_messages[-1] if self.sent_messages else None

    def clear(self) -> None:
        self.sent_messages.clear()


class MockGmailClient(EmailServiceProtocol):
    """Hermetic Gmail API mock reading from synthetic email payloads."""

    def __init__(self, raw_fixtures: Optional[Dict[str, Any]] = None) -> None:
        self.messages: List[Dict[str, Any]] = []
        self.rate_limit_enabled: bool = False
        self.unauthorized_enabled: bool = False

        if raw_fixtures and "messages" in raw_fixtures:
            for m in raw_fixtures["messages"]:
                self.messages.append(dict(m))
        else:
            # Fallback default fixture
            self.messages = [
                {
                    "id": "msg_urgent_001",
                    "threadId": "th_001",
                    "labelIds": ["UNREAD", "INBOX", "IMPORTANT"],
                    "snippet": "URGENT: Production outage reported in us-central1 cluster...",
                    "payload": {
                        "headers": [
                            {"name": "From", "value": "cto@company.com"},
                            {"name": "Subject", "value": "URGENT: Production outage reported in us-central1"},
                            {"name": "Date", "value": "Wed, 04 Nov 2026 11:30:00 +0000"},
                            {"name": "X-Priority", "value": "1"},
                        ],
                        "mimeType": "text/plain",
                    },
                    "decoded_body": "Please log on immediately. The authentication gateway is down.",
                    "expected_classification": {
                        "urgency_score": 95,
                        "category": "URGENT",
                        "is_actionable": true if "true" == "true" else True,
                        "should_proactively_alert": True,
                    },
                }
            ]

    def poll_unread(self, user_id: str) -> List[Dict[str, Any]]:
        if self.unauthorized_enabled:
            raise ConnectionRefusedError("401 Unauthorized: Invalid or expired OAuth2 token")
        if self.rate_limit_enabled:
            raise RuntimeError("429 Too Many Requests: Rate limit exceeded")

        unread = []
        for msg in self.messages:
            labels = msg.get("labelIds", [])
            if "UNREAD" in labels:
                headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
                unread.append({
                    "id": msg["id"],
                    "thread_id": msg.get("threadId"),
                    "sender": headers.get("From", "Unknown"),
                    "subject": headers.get("Subject", "(No Subject)"),
                    "snippet": msg.get("snippet", ""),
                    "received_at": headers.get("Date", FIXED_TIMESTAMP_STR),
                    "is_urgent": msg.get("expected_classification", {}).get("category") == "URGENT",
                    "category": msg.get("expected_classification", {}).get("category", "GENERAL"),
                    "body": msg.get("decoded_body", ""),
                })
        return unread

    def generate_digest(self, user_id: str) -> Dict[str, Any]:
        unread = self.poll_unread(user_id)
        urgent_items = [m for m in unread if m.get("is_urgent")]
        action_items = [
            m for m in unread
            if "review" in m.get("body", "").lower() or "immediately" in m.get("body", "").lower()
        ]

        if not unread:
            summary = "You're all caught up! No unread emails in your inbox."
        else:
            summary = f"You have {len(unread)} unread email(s), with {len(urgent_items)} urgent communication(s)."

        return {
            "total_unread": len(unread),
            "urgent_count": len(urgent_items),
            "items": unread,
            "urgent_items": urgent_items,
            "action_items": action_items,
            "summary_text": summary,
        }

    def modify_labels(
        self, msg_id: str, remove: Optional[List[str]] = None, add: Optional[List[str]] = None
    ) -> bool:
        for m in self.messages:
            if m["id"] == msg_id:
                labels = set(m.get("labelIds", []))
                if remove:
                    labels.difference_update(remove)
                if add:
                    labels.update(add)
                m["labelIds"] = list(labels)
                return True
        return False


class MockCalendarClient(CalendarServiceProtocol):
    """Hermetic Google Calendar API v3 mock with interval collision engine."""

    def __init__(self, raw_fixtures: Optional[Dict[str, Any]] = None) -> None:
        self.events: List[Dict[str, Any]] = []

        if raw_fixtures and "existing_events" in raw_fixtures:
            for evt in raw_fixtures["existing_events"]:
                self.events.append(dict(evt))
        else:
            self.events = [
                {
                    "id": "cal_evt_101",
                    "user_id": "usr_test_default",
                    "summary": "Engineering Standup",
                    "start": "2026-11-04T14:00:00Z",
                    "end": "2026-11-04T15:00:00Z",
                    "location": "Google Meet",
                    "status": "confirmed",
                },
                {
                    "id": "cal_evt_102",
                    "user_id": "usr_test_default",
                    "summary": "Quarterly Strategy Call",
                    "start": "2026-11-04T15:30:00Z",
                    "end": "2026-11-04T16:30:00Z",
                    "location": "Boardroom A",
                    "status": "confirmed",
                },
            ]

    def _parse_iso(self, val: Any) -> datetime:
        if isinstance(val, datetime):
            return val
        clean = str(val).replace("Z", "+00:00")
        return datetime.fromisoformat(clean)

    def list_events(
        self, user_id: str, start_time: datetime, end_time: datetime
    ) -> List[Dict[str, Any]]:
        matched = []
        for e in self.events:
            e_start = self._parse_iso(e["start"])
            e_end = self._parse_iso(e["end"])
            # Within interval or overlapping
            if e_start < end_time and e_end > start_time:
                matched.append(e)
        matched.sort(key=lambda x: self._parse_iso(x["start"]))
        return matched

    def check_conflicts(
        self, user_id: str, start_time: datetime, end_time: datetime
    ) -> List[Dict[str, Any]]:
        """Detects interval overlap: [start_time, end_time) overlaps [e_start, e_end)."""
        conflicts = []
        for e in self.events:
            e_start = self._parse_iso(e["start"])
            e_end = self._parse_iso(e["end"])
            if start_time < e_end and end_time > e_start:
                conflicts.append(e)
        return conflicts

    def create_event(
        self,
        user_id: str,
        title: str,
        start_time: datetime,
        end_time: datetime,
        location: str = "",
        is_all_day: bool = False,
    ) -> Dict[str, Any]:
        if end_time <= start_time:
            raise ValueError("Event end time cannot be before or equal to start time.")

        new_id = f"cal_evt_{len(self.events) + 101}"
        new_event = {
            "id": new_id,
            "user_id": user_id,
            "summary": title,
            "start": start_time.isoformat(),
            "end": end_time.isoformat(),
            "location": location,
            "is_all_day": is_all_day,
            "status": "confirmed",
        }
        self.events.append(new_event)
        return new_event

    def delete_event(self, user_id: str, event_id: str) -> bool:
        initial_len = len(self.events)
        self.events = [e for e in self.events if e.get("id") != event_id]
        return len(self.events) < initial_len


class MockSTTService(AudioTranscriptionProtocol):
    """Deterministic Speech-to-Text mock using pre-mapped voice files."""

    def __init__(self, transcripts_map: Optional[Dict[str, str]] = None) -> None:
        self.transcripts_map = transcripts_map or {
            "voice_file_groceries_7845": "Spent $78.45 on groceries at Trader Joe's",
            "voice_file_schedule_tomorrow": "What meetings do I have tomorrow?",
            "voice_file_morning_briefing": "Good morning! What's my schedule today, do I have any urgent emails, and what is my bank balance?",
            "voice_file_bistro_expense": "Spent $88 at Bistro Pierre on dinner",
            "voice_file_coffee_expense": "Log $4.50 for coffee",
        }

    def transcribe(self, audio_bytes: bytes, filename: str = "voice.ogg") -> str:
        if not audio_bytes or audio_bytes.startswith(b"CORRUPTED") or b"__CORRUPTED" in audio_bytes:
            raise ValueError("Could not transcribe voice note. Please re-record or type your request.")

        # Hash-based or string-based lookup
        text_repr = audio_bytes.decode("utf-8", errors="ignore")
        for key, val in self.transcripts_map.items():
            if key in text_repr:
                return val

        # Fallback default
        return "Record $45 for groceries at Trader Joe's"

    def transcribe_file_id(self, file_id: str) -> str:
        if file_id == "voice_file_corrupted" or "corrupted" in file_id:
            raise ValueError("Could not transcribe voice note. Please re-record or type your request.")
        if file_id in self.transcripts_map:
            return self.transcripts_map[file_id]
        return "Record $45 for groceries at Trader Joe's"


class MockWebSearchClient(SearchServiceProtocol):
    """Deterministic leisure and outing recommendation mock."""

    def __init__(self) -> None:
        self.places_db = [
            {
                "name": "Trattoria Stella",
                "category": "Italian",
                "rating": 4.8,
                "price_level": "$$",
                "address": "401 Pine St, Downtown",
                "summary": "Authentic handmade pasta and cozy romantic ambiance in Downtown.",
                "tags": ["italian", "pasta", "downtown", "romantic"],
            },
            {
                "name": "Sushi Kashiba",
                "category": "Japanese",
                "rating": 4.9,
                "price_level": "$$$$",
                "address": "86 Pike St, Downtown",
                "summary": "Legendary omakase dining with premium seafood in Downtown.",
                "tags": ["sushi", "japanese", "downtown", "omakase"],
            },
            {
                "name": "Bistro Pierre",
                "category": "French",
                "rating": 4.7,
                "price_level": "$$",
                "address": "1200 5th Ave, Midtown",
                "summary": "Classic Parisian fare, steak frites, and extensive wine list in Midtown.",
                "tags": ["french", "bistro", "midtown", "wine"],
            },
            {
                "name": "Monorail Espresso",
                "category": "Coffee",
                "rating": 4.8,
                "price_level": "$",
                "address": "510 Pike St, Downtown",
                "summary": "Historic espresso bar with artisanal coffee and free fast wifi.",
                "tags": ["coffee", "wifi", "espresso", "downtown"],
            },
        ]

    def search_outings(
        self, user_id: str, query: str, location: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        clean_q = query.lower()
        results = []
        for p in self.places_db:
            matches_q = any(t in clean_q for t in p["tags"]) or clean_q in p["name"].lower() or p["category"].lower() in clean_q
            matches_loc = True
            if location:
                matches_loc = location.lower() in p["address"].lower() or location.lower() in p["tags"]
            if matches_q and matches_loc:
                results.append(p)
        return results if results else []


# ============================================================================
# Service Container Fixture
# ============================================================================

@pytest.fixture
def mock_services(
    gmail_fixtures: Dict[str, Any],
    calendar_fixtures: Dict[str, Any],
    telegram_fixtures: Dict[str, Any],
) -> Dict[str, Any]:
    """Provides a unified container of hermetic test doubles."""
    return {
        "telegram": MockTelegramBotClient(),
        "gmail": MockGmailClient(gmail_fixtures),
        "calendar": MockCalendarClient(calendar_fixtures),
        "stt": MockSTTService(telegram_fixtures.get("mock_stt_transcripts")),
        "search": MockWebSearchClient(),
    }


# ============================================================================
# FastAPI Test Client Fixture
# ============================================================================

@pytest.fixture
def test_client(mock_db: sqlite3.Connection, mock_services: Dict[str, Any]) -> Generator[TestClient, None, None]:
    """Yields FastAPI TestClient configured with isolated in-memory DB and mocks directly against real app."""
    from app.main import app
    from app.database.connection import DatabaseManager, set_default_manager
    from app.api.finance_router import set_finance_service
    from app.api.task_router import set_task_service
    from app.services.finance_service import FinanceService
    from app.services.task_service import TaskService
    from app.database.repositories.task_repo import TaskRepository
    from app.api.webhook import set_tool_router, create_default_tool_router

    db_mgr = DatabaseManager(conn=mock_db)
    set_default_manager(db_mgr)

    app.state.db = mock_db
    app.state.telegram = mock_services["telegram"]
    app.state.gmail = mock_services["gmail"]
    app.state.calendar = mock_services["calendar"]
    app.state.stt = mock_services["stt"]
    app.state.search = mock_services["search"]

    fin_svc = FinanceService(db_manager=db_mgr)
    set_finance_service(fin_svc)
    app.state.finance_service = fin_svc

    task_svc = TaskService(repository=TaskRepository(conn=mock_db))
    set_task_service(task_svc)
    app.state.task_service = task_svc

    tool_router = create_default_tool_router(app.state)
    app.state.tool_router = tool_router
    set_tool_router(tool_router)

    try:
        with TestClient(app) as client:
            yield client
    finally:
        set_default_manager(None)
        set_finance_service(None)
        set_task_service(None)
        app.state.db = None
        app.state.telegram = None
        app.state.gmail = None
        app.state.calendar = None
        app.state.stt = None
        app.state.search = None
        app.state.finance_service = None
        app.state.task_service = None
        app.state.tool_router = None
        set_tool_router(create_default_tool_router())

def re_match_date(date_str: str) -> bool:
    """Helper to validate YYYY-MM-DD format."""
    import re
    if not re.match(r"^\d{4}-\d{2}-\d{2}", date_str):
        return False
    # Check valid date
    parts = date_str[:10].split("-")
    try:
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        datetime(y, m, d)
        return True
    except (ValueError, IndexError):
        return False
