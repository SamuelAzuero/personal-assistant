"""Tier 4: Real-World Scenarios — Comprehensive Multi-Turn Lifecycles.

Tests 4 realistic end-to-end user application workflows:
- Scenario 4.1: The Busy Executive Morning Briefing (Voice fanout -> Calendar + Email + Finance -> Follow-up task + coffee).
- Scenario 4.2: Weekend Leisure Planning with Budget Guardrails (Search -> Calendar book -> Expense -> Budget exceedance alert).
- Scenario 4.3: Travel Disruption Crisis & Schedule Recovery (Proactive flight cancel -> Meeting rescheduling & cancellation -> Urgent task).
- Scenario 4.4: Monthly Financial Audit & Discrepancy Correction (Monthly audit -> Duplicate identification -> Voiding -> Balance reconciliation).
"""

from datetime import datetime, timezone
import sqlite3
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
from tests.conftest import MockTelegramBotClient, MockSTTService


@pytest.fixture
def workflow_env(mock_db: sqlite3.Connection):
    """Hermetic multi-service environment for end-to-end user journeys."""
    db_mgr = DatabaseManager(db_path=":memory:")
    db_mgr.init_db()

    for uid in ["usr_exec_01", "usr_weekend_02", "usr_disruption_03", "usr_audit_04", "default_user", "usr_test_default"]:
        mock_db.execute("INSERT OR IGNORE INTO users (user_id, telegram_chat_id, full_name) VALUES (?, ?, ?)", (uid, f"chat_{uid}", f"User {uid}"))
        with db_mgr.connection() as c:
            c.execute("INSERT OR IGNORE INTO users (user_id, telegram_chat_id, full_name) VALUES (?, ?, ?)", (uid, f"chat_{uid}", f"User {uid}"))
    mock_db.commit()

    fin_repo = FinanceRepository(db_mgr)
    cal_repo = CalendarRepository(conn=mock_db)
    task_repo = TaskRepository(conn=mock_db)

    cal_client = MockCalendarClient()
    gmail_client = MockGmailClient()
    search_client = MockWebSearchClient()
    stt_client = MockSTTService()
    tg_client = MockTelegramBotClient()

    return {
        "finance": FinanceService(repository=fin_repo),
        "calendar": CalendarService(client=cal_client, repository=cal_repo),
        "email": EmailService(client=gmail_client),
        "task": TaskService(repository=task_repo),
        "search": SearchService(search_client=search_client),
        "stt": stt_client,
        "telegram": tg_client,
        "session": SessionManager(),
        "parser": IntentParser(reference_time=datetime(2026, 11, 4, 12, 0, 0, tzinfo=timezone.utc)),
    }


def test_scenario_4_1_executive_morning_briefing(workflow_env):
    """Scenario 4.1: The Busy Executive Morning Briefing.

    Executive sends morning voice query, receives aggregated briefing (calendar + emails + balance),
    and creates follow-up task and coffee expense.
    """
    user = "usr_exec_01"
    env = workflow_env

    # 1. Seed initial state: Salary ($4,250.00)
    env["finance"].record_transaction(
        user_id=user,
        amount=4250.00,
        transaction_type=TransactionType.INCOME,
        category="Income",
        description="Monthly Salary",
    )
    initial_bal = env["finance"].get_balance(user)["net_balance"]
    assert initial_bal == 4250.00

    # 2. Voice note ingestion & STT transcription
    voice_transcript = env["stt"].transcribe_file_id("voice_file_morning_briefing")
    assert "schedule" in voice_transcript.lower()
    assert "balance" in voice_transcript.lower()

    # 3. Aggregated Morning Briefing queries
    events = env["calendar"].list_events(user, "2026-11-04T00:00:00Z", "2026-11-04T23:59:59Z")
    email_digest = env["email"].generate_digest(user)
    fin_balance = env["finance"].get_balance(user)

    # Format unified briefing
    briefing = (
        f"🌅 **Good Morning Briefing**\n"
        f"• **Meetings Today:** {len(events)}\n"
        f"• **Urgent Emails:** {email_digest['urgent_count']}\n"
        f"• **Available Balance:** ${fin_balance['net_balance']:,.2f}"
    )
    env["telegram"].send_message(chat_id="998877", text=briefing)
    assert len(env["telegram"].sent_messages) == 1
    assert "4,250.00" in env["telegram"].sent_messages[0]["text"]

    # 4. Actionable Follow-up: Add high-priority task & coffee expense
    task = env["task"].create_task(
        user_id=user,
        title="Finish board deck revisions",
        priority="high",
        due_date="2026-11-04T11:30:00Z",
    )
    assert task["priority"] == "high"
    assert task["status"] in ["pending", "PENDING"]

    coffee = env["finance"].record_transaction(
        user_id=user,
        amount=5.20,
        transaction_type=TransactionType.EXPENSE,
        category="Food & Dining",
        description="Morning coffee",
    )
    assert coffee.amount_cents == 520

    # 5. Verify final reconciled balance ($4,250.00 - $5.20 = $4,244.80)
    updated_bal = env["finance"].get_balance(user)["net_balance"]
    assert updated_bal == 4244.80


def test_scenario_4_2_weekend_leisure_planning_with_budget(workflow_env):
    """Scenario 4.2: Weekend Leisure Planning with Budget Guardrails.

    User searches French bistro, checks calendar availability, books table, logs dinner expense,
    and system triggers budget limit warning alert.
    """
    user = "usr_weekend_02"
    env = workflow_env

    # 1. Set Dining budget limit = $200.00, seed existing spend = $180.00
    current_period = datetime.now(timezone.utc).strftime("%Y-%m")
    env["finance"].repo.set_budget(user, "Food & Dining", 20000, current_period)
    env["finance"].record_transaction(
        user_id=user,
        amount=180.00,
        transaction_type=TransactionType.EXPENSE,
        category="Food & Dining",
        description="Early month dining",
    )

    # 2. Outing search for French bistro near Midtown
    places = env["search"].search_outings(user, query="French bistro near Midtown", location="Midtown")
    assert len(places) >= 1
    bistro = next((p for p in places if "bistro" in p["name"].lower() or "french" in p.get("category", "").lower()), places[0])
    venue_name = bistro["name"]

    # 3. Calendar availability check for Saturday night 19:00 - 21:00 UTC
    sat_start = "2026-11-07T19:00:00Z"
    sat_end = "2026-11-07T21:00:00Z"
    conflicts = env["calendar"].check_conflicts(user, sat_start, sat_end)
    assert len(conflicts) == 0

    # 4. Calendar reservation
    booking = env["calendar"].create_event(
        user_id=user,
        title=f"Dinner at {venue_name}",
        start_time=sat_start,
        end_time=sat_end,
        location=bistro.get("address", "Midtown"),
    )
    assert booking is not None

    # 5. Log $88 dinner expense
    dinner_tx = env["finance"].record_transaction(
        user_id=user,
        amount=88.00,
        transaction_type=TransactionType.EXPENSE,
        category="Food & Dining",
        description=f"Dinner at {venue_name}",
    )
    assert dinner_tx.amount_cents == 8800

    # 6. Budget guardrail alert check ($180 + $88 = $268 > $200)
    alerts = env["finance"].check_budget_alerts(user)
    assert len(alerts) >= 1
    alert_str = " ".join(alerts).lower()
    assert "exceeded" in alert_str
    assert "food & dining" in alert_str


def test_scenario_4_3_travel_disruption_crisis_recovery(workflow_env):
    """Scenario 4.3: Travel Disruption Crisis & Schedule Recovery.

    Proactive flight cancellation email triggers push notification, user reschedules overlapping
    afternoon meetings, and creates an urgent task.
    """
    user = "default_user"
    env = workflow_env
    env["telegram"].clear()

    # 1. Background poll detects urgent cancellation email
    unread = env["email"].poll_unread(user)
    flight_emails = [m for m in unread if "flight" in m["subject"].lower()]
    assert len(flight_emails) >= 1
    flight_msg = flight_emails[0]

    # 2. Push proactive Telegram alert
    alert_msg = f"🚨 **TRAVEL ALERT**: {flight_msg['subject']}\n{flight_msg['snippet']}"
    env["telegram"].send_message(chat_id="998877", text=alert_msg)
    assert len(env["telegram"].sent_messages) == 1

    # 3. Inspect afternoon meetings on calendar
    afternoon_events = env["calendar"].list_events(user, "2026-11-04T13:00:00Z", "2026-11-04T18:00:00Z")
    assert len(afternoon_events) >= 1
    target_event = afternoon_events[0]
    target_id = target_event["id"]

    # 4. Restructure schedule: Cancel/delete event and create rescheduled event
    deleted = env["calendar"].delete_event(user, target_id)
    assert deleted is True

    rescheduled = env["calendar"].create_event(
        user_id=user,
        title="Rescheduled Strategic Call",
        start_time="2026-11-06T10:00:00Z",
        end_time="2026-11-06T11:00:00Z",
    )
    assert rescheduled is not None

    # 5. Create urgent recovery task
    task = env["task"].create_task(
        user_id=user,
        title="Call airline customer service to confirm rebooking",
        priority="urgent",
    )
    assert task["priority"] == "urgent"


def test_scenario_4_4_monthly_financial_audit_and_voiding(workflow_env):
    """Scenario 4.4: Monthly Financial Audit & Discrepancy Correction.

    User conducts monthly audit, discovers accidental duplicate charge, voids it,
    and reconciles balances across ledger and categories.
    """
    user = "usr_audit_04"
    env = workflow_env

    # 1. Initial baseline: Monthly salary $3,000, Rent $1,000, Groceries $200
    env["finance"].record_transaction(user, amount=3000.00, transaction_type=TransactionType.INCOME, category="Income", description="Salary")
    env["finance"].record_transaction(user, amount=1000.00, transaction_type=TransactionType.EXPENSE, category="Housing & Utilities", description="Rent")
    env["finance"].record_transaction(user, amount=200.00, transaction_type=TransactionType.EXPENSE, category="Groceries", description="Groceries")

    # 2. User accidentally enters $170.00 headphones twice in Shopping
    tx1 = env["finance"].record_transaction(user, amount=170.00, transaction_type=TransactionType.EXPENSE, category="Shopping", description="Noise Cancelling Headphones")
    tx2 = env["finance"].record_transaction(user, amount=170.00, transaction_type=TransactionType.EXPENSE, category="Shopping", description="Noise Cancelling Headphones (Duplicate)")

    # 3. Pre-void balance check: Expenses = 1000 + 200 + 170 + 170 = $1,540. Net = $1,460.
    pre_bal = env["finance"].get_balance(user)
    assert pre_bal["total_expenses"] == 1540.00
    assert pre_bal["net_balance"] == 1460.00

    # 4. Void / delete duplicate transaction
    voided = env["finance"].void_transaction(transaction_id=tx2.id, user_id=user)
    assert voided is True

    # 5. Post-void balance check: Expenses = $1,370. Net = $1,630.00
    post_bal = env["finance"].get_balance(user)
    assert post_bal["total_expenses"] == 1370.00
    assert post_bal["net_balance"] == 1630.00

    # 6. Verify category breakdown for Shopping is exactly $170.00
    breakdown = env["finance"].get_category_breakdown(user)
    shop_item = next((item for item in breakdown if item["category"] == "Shopping"), None)
    assert shop_item is not None
    assert shop_item["total"] == 170.00
