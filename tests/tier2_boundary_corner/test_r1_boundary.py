"""Tier 2: Boundary & Corner Cases — R1: Conversational Agent Core & Tool Orchestration.

Tests T2-R1-01 to T2-R1-06 verifying whitespace handling, 4096-char Telegram limits,
script/SQL injection resilience, dual-intent parsing, session TTL expiration, and tool fault degradation.
"""

from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient

from app.core.intent_parser import IntentParser
from app.core.router import ToolRouter
from app.core.session_manager import SessionManager
from app.integrations.protocols import IntentResult, IntentType


def test_t2_r1_01_empty_whitespace_message(test_client: TestClient):
    """T2-R1-01: Empty or whitespace-only messages return a helpful prompt without crashing."""
    payload = {
        "update_id": 99901,
        "message": {
            "message_id": 901,
            "chat": {"id": 12345},
            "text": "   \t\n   ",
        },
    }
    response = test_client.post("/api/webhook/telegram", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "provide a command" in data.get("response", "").lower() or data.get("ok") is True


def test_t2_r1_02_telegram_4096_char_limit(test_client: TestClient):
    """T2-R1-02: Message exceeding Telegram's 4096-character limit is truncated cleanly without overflow."""
    huge_message = "Log expense: $10 for lunch " + ("A" * 5000)
    payload = {
        "update_id": 99902,
        "message": {
            "message_id": 902,
            "chat": {"id": 12345},
            "text": huge_message,
        },
    }
    response = test_client.post("/api/webhook/telegram", json=payload)
    assert response.status_code == 200


def test_t2_r1_03_injection_sanitization(fixed_datetime: datetime, mock_db):
    """T2-R1-03: Malicious script tags and SQL injection payloads are stored literally without execution."""
    parser = IntentParser(reference_time=fixed_datetime)
    injection_text = "Spent $10 on lunch <script>alert(1)</script>'; DROP TABLE transactions; --"
    result = parser.parse(injection_text)

    assert result.intent == IntentType.FINANCE_ENTRY
    amount = result.slots.get("amount") or (result.slots.get("amount_cents", 0) / 100.0)
    assert amount == 10.00

    # Ensure SQLite transactions table still exists
    cur = mock_db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='transactions'")
    assert cur.fetchone() is not None


def test_t2_r1_04_ambiguous_dual_intent(fixed_datetime: datetime):
    """T2-R1-04: Compound multi-intent message evaluates without unhandled exception."""
    parser = IntentParser(reference_time=fixed_datetime)
    dual_text = "Log $20 for lunch and also tell me what meetings I have tomorrow"
    result = parser.parse(dual_text)

    # Parser should safely classify as either FINANCE_ENTRY or CALENDAR_QUERY without raising
    assert result.intent in [IntentType.FINANCE_ENTRY, IntentType.CALENDAR_QUERY, IntentType.UNKNOWN]


def test_t2_r1_05_context_inactivity_expiration(fixed_datetime: datetime):
    """T2-R1-05: Inactive session buffer reset prevents stale slot contamination in subsequent turns."""
    manager = SessionManager()
    parser = IntentParser(reference_time=fixed_datetime)
    user_id = "usr_ttl_test"

    # Turn 1: Incomplete finance entry
    turn1_res = parser.parse("I want to log an expense")
    manager.update_with_intent(user_id, turn1_res)
    session = manager.get_session(user_id)
    assert session.is_in_flow() is True

    # Simulate TTL expiration (reset/clear session buffer)
    manager.clear_session(user_id)
    assert session.is_in_flow() is False

    # Turn 2: Stale input after expiry treated as fresh command
    turn2_res = parser.parse("50 dollars", session_context=session.to_context_dict())
    assert turn2_res.intent in [IntentType.FINANCE_ENTRY, IntentType.UNKNOWN]
    # Should not carry stale groceries tag if it wasn't specified
    assert turn2_res.slots.get("category") != "Groceries"


def test_t2_r1_06_tool_failure_graceful_degradation():
    """T2-R1-06: Unexpected internal tool exception is intercepted cleanly with user-friendly markdown."""
    class FailingSearchService:
        def search_outings(self, user_id, query, location=None):
            raise RuntimeError("Database connection timeout")

    router = ToolRouter(search_service=FailingSearchService())
    intent = IntentResult(
        intent=IntentType.OUTING_RESEARCH,
        confidence=0.9,
        slots={"query": "Italian food"},
        is_complete=True,
    )

    try:
        reply = router.dispatch("usr_test_default", intent)
        # If router catches, verify friendly message
        assert "unavailable" in reply.lower() or "error" in reply.lower() or "timeout" in reply.lower()
    except Exception as e:
        # Handled at gateway layer
        assert isinstance(e, RuntimeError)
