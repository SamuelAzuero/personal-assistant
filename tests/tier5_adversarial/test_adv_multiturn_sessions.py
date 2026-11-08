"""Adversarial stress testing for natural language multi-turn session handling, slot filling, and session isolation."""

from datetime import datetime, timezone, timedelta
import concurrent.futures
import pytest

from app.core.intent_parser import IntentParser
from app.core.session_manager import SessionManager
from app.integrations.protocols import IntentResult, IntentType


@pytest.fixture
def parser():
    ref_time = datetime(2026, 11, 4, 12, 0, 0, tzinfo=timezone.utc)
    return IntentParser(reference_time=ref_time)


@pytest.fixture
def session_manager():
    return SessionManager()


def test_adv_nlp_01_compound_followup_slot_filling(parser: IntentParser, session_manager: SessionManager):
    """
    CRITICAL EMPIRICAL BUG CHECK:
    Turn 1: User says 'I want to log an expense'.
    The system asks for amount / description.
    Turn 2: User responds with compound message: '$45 for groceries'.
    Does IntentParser extract BOTH amount ($45.00) AND description ('groceries')?
    In app/core/intent_parser.py:194:
        if not self._extract_amount_cents(cleaned):
            pending_slots["description"] = cleaned
    Because cleaned contains '$45', self._extract_amount_cents returns 4500 (truthy),
    which causes description to be SKIPPED! The flow remains incomplete and asks again!
    """
    user = "usr_compound_followup"

    # Turn 1
    t1_res = parser.parse("I want to log an expense")
    assert t1_res.intent == IntentType.FINANCE_ENTRY
    assert not t1_res.is_complete
    prompt1 = session_manager.update_with_intent(user, t1_res)
    assert prompt1 is not None

    session = session_manager.get_session(user)
    context = session.to_context_dict()

    # Turn 2: User provides BOTH amount and description
    t2_res = parser.parse("$45 for groceries", session_context=context)
    print("Turn 2 slots:", t2_res.slots)
    print("Turn 2 missing_slots:", t2_res.missing_slots)
    print("Turn 2 is_complete:", t2_res.is_complete)

    assert t2_res.is_complete, f"BUG CONFIRMED: Multi-turn failed to extract compound response '$45 for groceries'. Missing: {t2_res.missing_slots}"
    assert t2_res.slots.get("amount_cents") == 4500
    assert "groceries" in str(t2_res.slots.get("description", "")).lower()


def test_adv_nlp_02_compound_calendar_followup_slot_filling(parser: IntentParser, session_manager: SessionManager):
    """
    CRITICAL EMPIRICAL BUG CHECK:
    Turn 1: User says 'Schedule a meeting'.
    The system asks for details (title, time).
    Turn 2: User responds 'Meeting with Bob tomorrow at 3pm'.
    In app/core/intent_parser.py:212:
        time_cand = self._extract_datetime(cleaned)
        if not time_cand:
            pending_slots["title"] = cleaned
    Because 'tomorrow at 3pm' matches a time, time_cand is NOT None!
    So 'title' is NOT extracted! The flow remains stuck asking for 'title'!
    """
    user = "usr_cal_followup"

    # Turn 1
    t1_res = parser.parse("Schedule a meeting")
    assert t1_res.intent == IntentType.CALENDAR_SCHEDULE
    assert not t1_res.is_complete
    prompt1 = session_manager.update_with_intent(user, t1_res)
    assert prompt1 is not None

    session = session_manager.get_session(user)
    context = session.to_context_dict()

    # Turn 2: User provides title and time
    t2_res = parser.parse("Meeting with Bob tomorrow at 3pm", session_context=context)
    print("Calendar Turn 2 slots:", t2_res.slots)
    print("Calendar Turn 2 missing_slots:", t2_res.missing_slots)
    print("Calendar Turn 2 is_complete:", t2_res.is_complete)

    assert t2_res.is_complete, f"BUG CONFIRMED: Calendar multi-turn dropped title in 'Meeting with Bob tomorrow at 3pm'. Missing: {t2_res.missing_slots}"
    assert "bob" in str(t2_res.slots.get("title", "")).lower()
    assert t2_res.slots.get("start_time") is not None


def test_adv_nlp_03_automatic_session_ttl_inactivity_expiration(parser: IntentParser, session_manager: SessionManager):
    """
    CRITICAL EMPIRICAL BUG CHECK:
    When a user leaves a conversation inactive for 2 hours, does SessionManager
    automatically expire/clear the pending flow, or does it stay permanently stuck in-flow?
    """
    user = "usr_ttl_empirical"

    # Turn 1: Incomplete finance entry
    t1_res = parser.parse("Spent 25 dollars")
    session_manager.update_with_intent(user, t1_res)
    session = session_manager.get_session(user)
    assert session.is_in_flow() is True

    # Simulate 2 hours of inactivity
    session.updated_at = datetime.utcnow() - timedelta(hours=2)

    # Now user returns and sends a completely new, unrelated query: "what is on my schedule today?"
    # If session expired, it should NOT treat this as a description for the $25 transaction!
    active_session = session_manager.get_session(user)

    # Check if session manager has any TTL check in get_session
    # If no TTL check, is_in_flow() is still True after 2 hours!
    assert not active_session.is_in_flow(), f"BUG CONFIRMED: Session state never expires after 2 hours of inactivity; still in active intent: {active_session.active_intent}"


def test_adv_nlp_04_user_isolation_under_concurrency(parser: IntentParser, session_manager: SessionManager):
    """Stress test: 20 concurrent users executing multi-turn flows simultaneously with zero cross-talk."""
    num_users = 20

    def user_flow(user_idx: int):
        user_id = f"usr_iso_{user_idx}"
        amount = (user_idx + 1) * 10  # e.g. $10, $20, etc.

        # Turn 1
        t1 = parser.parse(f"Spent {amount} dollars")
        session_manager.update_with_intent(user_id, t1)
        sess = session_manager.get_session(user_id)
        assert sess.user_id == user_id
        assert sess.slots.get("amount_cents") == amount * 100

        # Turn 2
        item_desc = f"Item for user {user_idx}"
        t2 = parser.parse(item_desc, session_context=sess.to_context_dict())
        session_manager.update_with_intent(user_id, t2)

        # Ensure no cross contamination
        assert sess.slots == {} or t2.slots.get("amount_cents") == amount * 100

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(user_flow, i) for i in range(num_users)]
        for f in concurrent.futures.as_completed(futures):
            f.result()


def test_adv_nlp_05_cancellation_flow(parser: IntentParser, session_manager: SessionManager):
    """Stress test: Active multi-turn flow is cleanly aborted via /cancel or 'nevermind'."""
    user = "usr_cancel_test"

    t1 = parser.parse("I want to log an expense")
    session_manager.update_with_intent(user, t1)
    session = session_manager.get_session(user)
    assert session.is_in_flow() is True

    # User cancels
    t2 = parser.parse("/cancel", session_context=session.to_context_dict())
    assert t2.intent == IntentType.CANCEL
    cancel_msg = session_manager.update_with_intent(user, t2)
    assert "canceled" in cancel_msg.lower() or "cancelled" in cancel_msg.lower()
    assert session.is_in_flow() is False
    assert len(session.slots) == 0
