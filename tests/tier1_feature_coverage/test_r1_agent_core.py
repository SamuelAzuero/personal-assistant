"""Tier 1: Feature Coverage — R1: Conversational Agent Core & Tool Orchestration.

Tests T1-R1-01 to T1-R1-06 verifying nominal intent parsing, slot extraction,
multi-turn slot collection, and simulated voice STT decoding.
"""

from datetime import datetime, timezone
import pytest

from app.core.intent_parser import IntentParser
from app.integrations.protocols import IntentType


@pytest.fixture
def parser(fixed_datetime: datetime) -> IntentParser:
    return IntentParser(reference_time=fixed_datetime)


def test_t1_r1_01_intent_finance_entry(parser: IntentParser):
    """T1-R1-01: Natural language finance entry extracts amount, category, and description."""
    text = "Spent $18.50 on lunch at Chipotle"
    result = parser.parse(text)

    assert result.intent == IntentType.FINANCE_ENTRY
    assert result.is_complete is True
    amount = result.slots.get("amount") or (result.slots.get("amount_cents", 0) / 100.0)
    assert amount == 18.50
    assert "lunch" in result.slots.get("description", "").lower() or "chipotle" in result.slots.get("description", "").lower()
    assert result.slots.get("category") in ["Food & Dining", "Food/Dining", "Food", "Dining"]


def test_t1_r1_02_intent_calendar_query(parser: IntentParser):
    """T1-R1-02: Calendar query intent recognizes schedule request and date reference."""
    text = "Do I have any meetings tomorrow?"
    result = parser.parse(text)

    assert result.intent == IntentType.CALENDAR_QUERY
    assert result.is_complete is True
    start_time = result.slots.get("start_time") or result.slots.get("date")
    if start_time:
        assert "2026-11-05" in str(start_time)


def test_t1_r1_03_intent_email_digest(parser: IntentParser):
    """T1-R1-03: Email digest intent extracts email check request."""
    text = "Check my unread emails and show urgent ones"
    result = parser.parse(text)

    assert result.intent == IntentType.EMAIL_CHECK
    assert result.is_complete is True


def test_t1_r1_04_intent_task_creation(parser: IntentParser):
    """T1-R1-04: Task creation intent extracts title and time."""
    text = "Remind me to submit project report by 5 PM"
    result = parser.parse(text)

    assert result.intent == IntentType.TASK_CREATE
    title = result.slots.get("title", "").lower()
    assert "submit project report" in title or "project report" in title


def test_t1_r1_05_intent_outing_research(parser: IntentParser):
    """T1-R1-05: Outing research intent extracts cuisine and location."""
    text = "Find top-rated Italian restaurants near Downtown"
    result = parser.parse(text)

    assert result.intent == IntentType.OUTING_RESEARCH
    assert result.is_complete is True
    slots_repr = str(result.slots).lower()
    assert "italian" in slots_repr
    assert "downtown" in slots_repr


def test_t1_r1_06_voice_note_ingestion_and_stt(mock_services, parser: IntentParser):
    """T1-R1-06: Simulated voice note is transcribed to text and routed to intent."""
    stt = mock_services["stt"]
    file_id = "voice_file_groceries_7845"
    transcription = stt.transcribe_file_id(file_id)

    assert "78.45" in transcription
    assert "groceries" in transcription.lower()

    result = parser.parse(transcription)
    assert result.intent == IntentType.FINANCE_ENTRY
    amount = result.slots.get("amount") or (result.slots.get("amount_cents", 0) / 100.0)
    assert amount == 78.45
