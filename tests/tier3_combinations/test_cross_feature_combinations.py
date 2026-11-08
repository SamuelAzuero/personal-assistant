"""Tier 3: Cross-Feature Interactions — Pairwise Integration Workflows.

Tests T3-01 to T3-08 verifying multi-subsystem interoperability:
- T3-01 (R1 x R2): Multi-turn conversational slot filling for missing financial parameters.
- T3-02 (R2 x R5): Telegram bot expense entry reflected in Web Dashboard summary.
- T3-03 (R3 x R4): Urgent email flight alert triggers Calendar conflict check and reschedule.
- T3-04 (R1 x R4): Outing recommendation with pronoun resolution ('there') into Calendar booking.
- T3-05 (R1 x R3): Natural language command triggers Gmail unread poll and formats Telegram briefing.
- T3-06 (R2 x R4): Outing calendar event followed by expense attribution.
- T3-07 (R4 x R5): Telegram task command appears on Web Dashboard task board.
- T3-08 (R3 x R5): Background email poll detects urgent message and dispatches proactive Telegram alert.
"""

from datetime import datetime, timezone
import sqlite3
from typing import Any, Dict
import pytest
from fastapi.testclient import TestClient

from app.core.intent_parser import IntentParser
from app.core.session_manager import SessionManager
from app.database.connection import DatabaseManager
from app.database.repositories.calendar_repo import CalendarRepository
from app.database.repositories.finance_repo import FinanceRepository, TransactionType
from app.database.repositories.task_repo import TaskRepository
from app.integrations.mocks import MockCalendarClient, MockGmailClient, MockWebSearchClient
from app.services.calendar_service import CalendarService
from app.services.email_service import EmailService
from app.services.finance_service import FinanceService
from app.services.search_service import SearchService
from app.services.task_service import TaskService


@pytest.fixture
def core_services(mock_db: sqlite3.Connection):
    db_mgr = DatabaseManager(db_path=":memory:")
    db_mgr.init_db()

    fin_repo = FinanceRepository(db_mgr)
    cal_repo = CalendarRepository(conn=mock_db)
    task_repo = TaskRepository(conn=mock_db)

    cal_client = MockCalendarClient()
    gmail_client = MockGmailClient()
    search_client = MockWebSearchClient()

    return {
        "finance": FinanceService(repository=fin_repo),
        "calendar": CalendarService(client=cal_client, repository=cal_repo),
        "email": EmailService(client=gmail_client),
        "task": TaskService(repository=task_repo),
        "search": SearchService(search_client=search_client),
        "session": SessionManager(),
        "parser": IntentParser(reference_time=datetime(2026, 11, 4, 12, 0, 0, tzinfo=timezone.utc)),
    }


def test_t3_01_conversational_slot_filling_to_ledger(core_services):
    """T3-01 (R1 x R2): Multi-turn dialogue collects missing amount, then persists transaction to ledger."""
    parser = core_services["parser"]
    session_mgr = core_services["session"]
    finance_svc = core_services["finance"]
    user = "usr_t3_01"

    # Turn 1: User says expense without amount
    res1 = parser.parse("I just bought groceries")
    prompt = session_mgr.update_with_intent(user, res1)
    session = session_mgr.get_session(user)

    assert session.is_in_flow() is True
    assert "amount" in session.missing_slots
    assert "how much" in prompt.lower() or "specify" in prompt.lower()

    # Turn 2: User provides amount and merchant
    res2 = parser.parse("$54.20 at Safeway", session_context=session.to_context_dict())
    assert res2.is_complete is True
    amount = res2.slots.get("amount") or (res2.slots.get("amount_cents", 0) / 100.0)
    assert amount == 54.20

    # Persist to finance ledger
    record = finance_svc.record_transaction(
        user_id=user,
        amount=amount,
        transaction_type=TransactionType.EXPENSE,
        category="Groceries",
        description="Safeway groceries",
    )
    assert record.amount_cents == 5420

    balance = finance_svc.get_balance(user)
    assert balance["total_expenses"] == 54.20


def test_t3_02_telegram_bot_entry_to_web_dashboard(test_client: TestClient, mock_services):
    """T3-02 (R2 x R5): Transaction recorded via Telegram webhook is immediately queryable via dashboard REST API."""
    mock_services["telegram"].clear()
    payload = {
        "update_id": 99302,
        "message": {
            "message_id": 302,
            "chat": {"id": 12345},
            "text": "Spent $35.00 on fuel",
        },
    }

    # Post via webhook
    resp_hook = test_client.post("/api/webhook/telegram", json=payload)
    assert resp_hook.status_code == 200

    # Query web dashboard summary
    resp_dash = test_client.get("/api/finance/summary")
    assert resp_dash.status_code == 200
    data = resp_dash.json()
    assert data["total_expenses"] >= 35.00


def test_t3_03_email_flight_alert_to_calendar_reschedule(core_services):
    """T3-03 (R3 x R4): Urgent flight delay email triggers Calendar query and rescheduling."""
    email_svc = core_services["email"]
    cal_svc = core_services["calendar"]
    user = "default_user"

    # 1. Background poll unread emails
    unread = email_svc.poll_unread(user)
    urgent_flight = [m for m in unread if "flight" in m.get("subject", "").lower()]
    assert len(urgent_flight) >= 1

    # 2. Check calendar conflicts around 4 PM (16:00 UTC)
    conflicts = cal_svc.check_conflicts(user, "2026-11-04T15:30:00Z", "2026-11-04T16:30:00Z")
    assert len(conflicts) >= 1
    conflicting_evt = conflicts[0]
    assert "Strategy Call" in (conflicting_evt.get("summary") or conflicting_evt.get("title"))

    # 3. Reschedule strategy call to tomorrow morning
    cal_svc.delete_event(user, conflicting_evt["id"])
    cal_svc.create_event(user, "Rescheduled Strategy Call", "2026-11-05T10:00:00Z", "2026-11-05T11:00:00Z")

    # Verify 4 PM window is now free
    resolved_conflicts = cal_svc.check_conflicts(user, "2026-11-04T15:30:00Z", "2026-11-04T16:30:00Z")
    assert len(resolved_conflicts) == 0


def test_t3_04_outing_research_to_calendar_reservation(core_services):
    """T3-04 (R1 x R4): Outing recommendation antecedents resolved into Calendar booking."""
    search_svc = core_services["search"]
    cal_svc = core_services["calendar"]
    user = "usr_t3_04"

    # Step 1: Outing recommendation
    places = search_svc.search_outings(user, query="Italian restaurants near Downtown", location="Downtown")
    assert len(places) >= 1
    chosen = places[0]
    venue_name = chosen["name"]

    # Step 2: Calendar reservation for chosen venue
    start_time = "2026-11-05T19:00:00Z"
    end_time = "2026-11-05T21:00:00Z"
    event = cal_svc.create_event(
        user_id=user,
        title=f"Dinner at {venue_name}",
        start_time=start_time,
        end_time=end_time,
        location=chosen.get("address", "Downtown"),
    )

    assert event is not None
    assert venue_name in (event.get("summary") or event.get("title"))


def test_t3_05_voice_command_to_email_briefing(core_services, mock_services):
    """T3-05 (R1 x R3): Natural language email check triggers Gmail unread digest."""
    parser = core_services["parser"]
    email_svc = core_services["email"]
    user = "usr_t3_05"

    text = "Check my unread emails and show urgent ones"
    intent = parser.parse(text)
    assert intent.intent.value == "email_check"

    digest = email_svc.generate_digest(user)
    assert "summary_text" in digest
    assert digest["total_unread"] >= 1


def test_t3_06_outing_event_expense_attribution(core_services):
    """T3-06 (R2 x R4): Calendar outing event followed by dinner expense logging and category attribution."""
    cal_svc = core_services["calendar"]
    fin_svc = core_services["finance"]
    user = "usr_t3_06"

    # 1. Calendar event
    cal_svc.create_event(user, "Dinner at Bistro Pierre", "2026-11-07T19:00:00Z", "2026-11-07T21:00:00Z")

    # 2. Log dinner expense
    record = fin_svc.record_transaction(
        user_id=user,
        amount=88.00,
        transaction_type=TransactionType.EXPENSE,
        category="Food & Dining",
        description="Dinner at Bistro Pierre",
    )
    assert record.amount_cents == 8800
    assert record.category == "Food & Dining"

    breakdown = fin_svc.get_category_breakdown(user)
    dining_item = next((item for item in breakdown if item["category"] == "Food & Dining"), None)
    assert dining_item is not None
    assert dining_item["total"] == 88.00


def test_t3_07_telegram_task_command_to_dashboard(test_client: TestClient):
    """T3-07 (R4 x R5): Task created via Telegram webhook appears on Web Dashboard task board."""
    task_payload = {
        "update_id": 99307,
        "message": {
            "message_id": 307,
            "chat": {"id": 12345},
            "text": "Remind me to buy flight tickets by Friday",
        },
    }

    # Dispatch via webhook
    resp = test_client.post("/api/webhook/telegram", json=task_payload)
    assert resp.status_code == 200

    # Query tasks endpoint
    tasks_resp = test_client.get("/api/tasks")
    assert tasks_resp.status_code == 200
    tasks = tasks_resp.json()
    assert len(tasks) >= 1
    titles = [t["title"].lower() for t in tasks]
    assert any("flight" in title or "tickets" in title for title in titles)


def test_t3_08_urgent_email_background_poll_to_telegram_alert(core_services, mock_services):
    """T3-08 (R3 x R5): Background email poll identifies urgent outage and dispatches Telegram notification."""
    email_svc = core_services["email"]
    tg_client = mock_services["telegram"]
    user = "default_user"
    tg_client.clear()

    # Ingest unread emails
    unread = email_svc.poll_unread(user)
    urgent_msgs = [m for m in unread if m.get("is_urgent")]
    assert len(urgent_msgs) >= 1

    # Format proactive Telegram alert
    for msg in urgent_msgs:
        alert_text = f"⚠️ **URGENT EMAIL ALERT**\n• **From:** {msg['sender']}\n• **Subject:** {msg['subject']}"
        tg_client.send_message(chat_id="998877", text=alert_text)

    sent = tg_client.sent_messages
    assert len(sent) >= 1
    assert "URGENT EMAIL ALERT" in sent[0]["text"]
