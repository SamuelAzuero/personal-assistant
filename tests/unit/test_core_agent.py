"""Comprehensive Unit Test Suite for Milestone 1: Core Agent & NLP Tool Orchestration."""

from datetime import datetime
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.webhook import (
    get_audio_handler,
    get_intent_parser,
    get_session_manager,
    get_telegram_client,
    get_tool_router,
    webhook_router,
)
from app.core.audio import AudioNoteHandler, DefaultAudioTranscriptionService
from app.core.intent_parser import IntentParser
from app.core.router import ToolRouter
from app.core.session_manager import SessionManager
from app.integrations.protocols import (
    AudioTranscriptionProtocol,
    CalendarServiceProtocol,
    EmailServiceProtocol,
    FinanceServiceProtocol,
    IntentParserProtocol,
    IntentResult,
    IntentType,
    SearchServiceProtocol,
    TaskServiceProtocol,
    TelegramClientProtocol,
    TransactionRecord,
    TransactionType,
)
from app.integrations.telegram_client import TelegramClient


# =============================================================================
# 1. Protocols & Interface Verification
# =============================================================================


def test_protocols_and_enums_exist():
    assert IntentType.FINANCE_ENTRY.value == "finance_entry"
    assert IntentType.FINANCE_QUERY.value == "finance_query"
    assert IntentType.EMAIL_CHECK.value == "email_check"
    assert IntentType.CALENDAR_SCHEDULE.value == "calendar_schedule"
    assert IntentType.CALENDAR_QUERY.value == "calendar_query"
    assert IntentType.TASK_CREATE.value == "task_create"
    assert IntentType.TASK_LIST.value == "task_list"
    assert IntentType.OUTING_RESEARCH.value == "outing_research"
    assert IntentType.CANCEL.value == "cancel"
    assert IntentType.UNKNOWN.value == "unknown"

    record = TransactionRecord(
        id="tx_1",
        user_id="user_1",
        amount_cents=4500,
        transaction_type=TransactionType.EXPENSE,
        category="Groceries",
        description="Trader Joe's",
    )
    assert record.amount_cents == 4500
    assert record.transaction_type == TransactionType.EXPENSE

    res = IntentResult(
        intent=IntentType.FINANCE_ENTRY,
        confidence=0.95,
        slots={"amount_cents": 4500},
        is_complete=True,
    )
    assert res.intent == IntentType.FINANCE_ENTRY
    assert res.slots["amount_cents"] == 4500


def test_runtime_checkable_protocols():
    assert isinstance(IntentParser(), IntentParserProtocol)
    assert isinstance(TelegramClient(), TelegramClientProtocol)
    assert isinstance(DefaultAudioTranscriptionService(), AudioTranscriptionProtocol)


# =============================================================================
# 2. IntentParser Unit Tests
# =============================================================================


class TestIntentParser:
    @pytest.fixture
    def parser(self):
        fixed_now = datetime(2026, 11, 4, 10, 0, 0)
        return IntentParser(reference_time=fixed_now)

    def test_finance_entry_expenses(self, parser):
        res1 = parser.parse("Spent $45 on groceries")
        assert res1.intent == IntentType.FINANCE_ENTRY
        assert res1.slots["amount_cents"] == 4500
        assert res1.slots["transaction_type"] == "expense"
        assert res1.slots["category"] == "Groceries"
        assert res1.is_complete is True

        res2 = parser.parse("Coffee $4.50")
        assert res2.intent == IntentType.FINANCE_ENTRY
        assert res2.slots["amount_cents"] == 450
        assert res2.slots["category"] == "Food & Dining"
        assert res2.is_complete is True

        res3 = parser.parse("Paid 20 for uber")
        assert res3.intent == IntentType.FINANCE_ENTRY
        assert res3.slots["amount_cents"] == 2000
        assert res3.slots["category"] == "Transportation"

        res4 = parser.parse("Expense: $120 electric bill")
        assert res4.intent == IntentType.FINANCE_ENTRY
        assert res4.slots["amount_cents"] == 12000
        assert res4.slots["category"] == "Housing & Utilities"

    def test_finance_entry_incomes(self, parser):
        res1 = parser.parse("Received $2500 salary")
        assert res1.intent == IntentType.FINANCE_ENTRY
        assert res1.slots["amount_cents"] == 250000
        assert res1.slots["transaction_type"] == "income"
        assert res1.slots["category"] == "Income"
        assert res1.is_complete is True

        res2 = parser.parse("Got paid $1000 freelance")
        assert res2.intent == IntentType.FINANCE_ENTRY
        assert res2.slots["amount_cents"] == 100000
        assert res2.slots["transaction_type"] == "income"

        res3 = parser.parse("Deposit 500 bonus")
        assert res3.intent == IntentType.FINANCE_ENTRY
        assert res3.slots["amount_cents"] == 50000
        assert res3.slots["transaction_type"] == "income"

    def test_finance_entry_missing_slots(self, parser):
        # Missing description
        res1 = parser.parse("Spent $45")
        assert res1.intent == IntentType.FINANCE_ENTRY
        assert res1.is_complete is False
        assert "description" in res1.missing_slots
        assert res1.slots["amount_cents"] == 4500

        # Missing amount
        res2 = parser.parse("Bought groceries")
        assert res2.intent == IntentType.FINANCE_ENTRY
        assert res2.is_complete is False
        assert "amount" in res2.missing_slots

    def test_finance_queries(self, parser):
        res1 = parser.parse("What is my balance?")
        assert res1.intent == IntentType.FINANCE_QUERY
        assert res1.slots["query_type"] == "balance"

        res2 = parser.parse("Show my spending this month")
        assert res2.intent == IntentType.FINANCE_QUERY
        assert res2.slots["query_type"] == "summary"

        res3 = parser.parse("Show category breakdown")
        assert res3.intent == IntentType.FINANCE_QUERY
        assert res3.slots["query_type"] == "breakdown"

    def test_email_checks(self, parser):
        res1 = parser.parse("Check my emails")
        assert res1.intent == IntentType.EMAIL_CHECK
        assert res1.slots["urgent_only"] is False

        res2 = parser.parse("Any urgent emails?")
        assert res2.intent == IntentType.EMAIL_CHECK
        assert res2.slots["urgent_only"] is True

        res3 = parser.parse("Show unread email digest")
        assert res3.intent == IntentType.EMAIL_CHECK

    def test_calendar_schedule(self, parser):
        res1 = parser.parse("Schedule meeting with Bob at 3pm tomorrow")
        assert res1.intent == IntentType.CALENDAR_SCHEDULE
        assert res1.is_complete is True
        assert "meeting with Bob" in res1.slots["title"]
        assert isinstance(res1.slots["start_time"], datetime)
        assert res1.slots["start_time"].hour == 15

        # Missing start time
        res2 = parser.parse("Schedule meeting with Bob")
        assert res2.intent == IntentType.CALENDAR_SCHEDULE
        assert res2.is_complete is False
        assert "start_time" in res2.missing_slots

        # Schedule action command with person
        res3 = parser.parse("Schedule a meeting with Alice")
        assert res3.intent == IntentType.CALENDAR_SCHEDULE
        assert "meeting with Alice" in res3.slots["title"]
        assert "start_time" in res3.missing_slots

        # Schedule action command with lunch
        res4 = parser.parse("Schedule lunch with Alice tomorrow at 12pm")
        assert res4.intent == IntentType.CALENDAR_SCHEDULE
        assert res4.is_complete is True

    def test_calendar_queries(self, parser):
        res1 = parser.parse("Am I free Friday?")
        assert res1.intent == IntentType.CALENDAR_QUERY
        assert res1.is_complete is True

        res2 = parser.parse("What is on my schedule today?")
        assert res2.intent == IntentType.CALENDAR_QUERY

        res3 = parser.parse("Show my schedule")
        assert res3.intent == IntentType.CALENDAR_QUERY

        res4 = parser.parse("Show me my schedule")
        assert res4.intent == IntentType.CALENDAR_QUERY

        res5 = parser.parse("What is my schedule?")
        assert res5.intent == IntentType.CALENDAR_QUERY

        res6 = parser.parse("What's my schedule today?")
        assert res6.intent == IntentType.CALENDAR_QUERY

        res7 = parser.parse("What do I have scheduled for today?")
        assert res7.intent == IntentType.CALENDAR_QUERY

        res8 = parser.parse("Schedule for today")
        assert res8.intent == IntentType.CALENDAR_QUERY

    def test_task_create(self, parser):
        res1 = parser.parse("Remind me to buy milk tomorrow at 8am")
        assert res1.intent == IntentType.TASK_CREATE
        assert res1.is_complete is True
        assert res1.slots["title"] == "buy milk"
        assert res1.slots["due_date"].hour == 8

        res2 = parser.parse("Add task: submit expense report urgent priority")
        assert res2.intent == IntentType.TASK_CREATE
        assert res2.slots["priority"] == "urgent"
        assert "submit expense report" in res2.slots["title"]

    def test_task_list(self, parser):
        res1 = parser.parse("Show my to-dos")
        assert res1.intent == IntentType.TASK_LIST
        assert res1.slots["status"] == "pending"

        res2 = parser.parse("List completed tasks")
        assert res2.intent == IntentType.TASK_LIST
        assert res2.slots["status"] == "completed"

    def test_outing_research(self, parser):
        res1 = parser.parse("Find good Italian restaurants nearby")
        assert res1.intent == IntentType.OUTING_RESEARCH
        assert res1.slots["cuisine"] == "Italian"
        assert res1.slots["location"] == "nearby"

        res2 = parser.parse("Suggest outdoor hiking activities in Seattle")
        assert res2.intent == IntentType.OUTING_RESEARCH
        assert res2.slots["activity"] == "Outdoor"

    def test_cancellation(self, parser):
        assert parser.parse("/cancel").intent == IntentType.CANCEL
        assert parser.parse("cancel").intent == IntentType.CANCEL
        assert parser.parse("abort").intent == IntentType.CANCEL
        assert parser.parse("stop").intent == IntentType.CANCEL

    def test_unknown_intent(self, parser):
        res = parser.parse("Blah blah gibberish xyz123")
        assert res.intent == IntentType.UNKNOWN
        assert res.confidence <= 0.5


# =============================================================================
# 3. SessionManager Unit Tests
# =============================================================================


class TestSessionManager:
    @pytest.fixture
    def manager(self):
        return SessionManager()

    def test_user_isolation(self, manager):
        s_alice = manager.get_session("alice")
        s_bob = manager.get_session("bob")

        assert s_alice.user_id == "alice"
        assert s_bob.user_id == "bob"

        # Update Alice's session with an incomplete flow
        r_incomplete = IntentResult(
            intent=IntentType.FINANCE_ENTRY,
            confidence=0.8,
            slots={"amount_cents": 4500},
            is_complete=False,
            missing_slots=["description"],
        )
        prompt = manager.update_with_intent("alice", r_incomplete)
        assert prompt is not None
        assert s_alice.is_in_flow() is True

        # Bob's session must remain completely unaffected
        assert s_bob.is_in_flow() is False
        assert s_bob.active_intent is None
        assert len(s_bob.slots) == 0

    def test_multi_turn_slot_filling_flow(self, manager):
        parser = IntentParser()

        # Turn 1: Incomplete input
        r1 = parser.parse("Spent $45")
        prompt1 = manager.update_with_intent("user1", r1)
        assert "What was this" in prompt1
        assert manager.get_session("user1").is_in_flow() is True

        # Turn 2: Follow-up slot
        ctx = manager.get_session("user1").to_context_dict()
        r2 = parser.parse("Groceries", session_context=ctx)
        assert r2.is_complete is True
        assert r2.slots["amount_cents"] == 4500
        assert r2.slots["category"] == "Groceries"

        prompt2 = manager.update_with_intent("user1", r2)
        assert prompt2 is None
        assert manager.get_session("user1").is_in_flow() is False

    def test_multi_turn_cancellation(self, manager):
        parser = IntentParser()

        r1 = parser.parse("Schedule meeting with Bob")
        manager.update_with_intent("user1", r1)
        assert manager.get_session("user1").is_in_flow() is True

        r_cancel = parser.parse("/cancel")
        cancel_resp = manager.update_with_intent("user1", r_cancel)
        assert "canceled" in cancel_resp
        assert manager.get_session("user1").is_in_flow() is False

    def test_history_logging_and_pruning(self, manager):
        for i in range(60):
            manager.add_message("user1", "user", f"msg_{i}")

        history = manager.get_history("user1", limit=10)
        assert len(history) == 10
        assert history[-1]["content"] == "msg_59"
        # Total history was capped at max_history_per_user (50)
        assert len(manager.get_session("user1").history) == 50


# =============================================================================
# 4. ToolRouter Unit Tests
# =============================================================================


class MockFinanceService(FinanceServiceProtocol):
    def __init__(self):
        self.recorded = []
        self.alerts = ["Groceries budget 80% reached!"]

    def record_transaction(
        self, user_id, amount_cents, t_type, category, description
    ):
        rec = TransactionRecord(
            id=f"tx_{len(self.recorded) + 1}",
            user_id=user_id,
            amount_cents=amount_cents,
            transaction_type=t_type,
            category=category,
            description=description,
        )
        self.recorded.append(rec)
        return rec

    def get_balance(self, user_id):
        return {"balance_cents": 225000, "income_cents": 350000, "expense_cents": 125000}

    def get_category_breakdown(self, user_id, month=None):
        return [
            {"category": "Groceries", "spent_cents": 45000, "percentage": 45.0},
            {"category": "Food & Dining", "spent_cents": 25000, "percentage": 25.0},
        ]

    def check_budget_alerts(self, user_id):
        return self.alerts


class MockEmailService(EmailServiceProtocol):
    def poll_unread(self, user_id):
        return []

    def generate_digest(self, user_id):
        return {
            "urgent_count": 1,
            "items": [
                {
                    "subject": "URGENT: Cloud Bill Overdue",
                    "sender": "billing@cloud.com",
                    "is_urgent": True,
                }
            ],
        }


class MockCalendarService(CalendarServiceProtocol):
    def __init__(self, has_conflict=False):
        self.has_conflict = has_conflict
        self.events = []

    def list_events(self, user_id, start_time, end_time):
        return self.events

    def create_event(self, user_id, title, start_time, end_time, location=""):
        ev = {
            "id": "cal_1",
            "summary": title,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "location": location,
        }
        self.events.append(ev)
        return ev

    def check_conflicts(self, user_id, start_time, end_time):
        if self.has_conflict:
            return [{"summary": "Team Standup", "start_time": "15:00", "end_time": "16:00"}]
        return []


class MockTaskService(TaskServiceProtocol):
    def __init__(self):
        self.tasks = []

    def create_task(self, user_id, title, due_date=None, priority="medium"):
        t = {"id": "task_1", "title": title, "due_date": due_date, "priority": priority}
        self.tasks.append(t)
        return t

    def list_tasks(self, user_id, status=None):
        return [
            {"title": "Buy milk", "priority": "high", "due_date": "Tomorrow 8am"},
            {"title": "Call dentist", "priority": "medium", "due_date": None},
        ]


class MockSearchService(SearchServiceProtocol):
    def search_outings(self, user_id, query, location=None):
        return [
            {
                "name": "Trattoria Bella",
                "rating": 4.8,
                "price_tier": "$$",
                "description": "Authentic fresh pasta in cozy setting.",
            }
        ]


class TestToolRouter:
    @pytest.fixture
    def router_with_mocks(self):
        return ToolRouter(
            finance_service=MockFinanceService(),
            email_service=MockEmailService(),
            calendar_service=MockCalendarService(has_conflict=False),
            task_service=MockTaskService(),
            search_service=MockSearchService(),
        )

    def test_finance_entry_expense(self, router_with_mocks):
        res = IntentResult(
            intent=IntentType.FINANCE_ENTRY,
            confidence=0.9,
            slots={
                "amount_cents": 4500,
                "transaction_type": "expense",
                "category": "Groceries",
                "description": "groceries",
            },
            is_complete=True,
        )
        out = router_with_mocks.dispatch("u1", res)
        assert "$45.00" in out
        assert "Expense Recorded" in out
        assert "Groceries budget 80% reached!" in out

    def test_finance_entry_income(self, router_with_mocks):
        res = IntentResult(
            intent=IntentType.FINANCE_ENTRY,
            confidence=0.9,
            slots={
                "amount_cents": 250000,
                "transaction_type": "income",
                "category": "Income",
                "description": "salary",
            },
            is_complete=True,
        )
        out = router_with_mocks.dispatch("u1", res)
        assert "$2,500.00" in out
        assert "Income Recorded" in out

    def test_finance_query_balance_and_breakdown(self, router_with_mocks):
        res_bal = IntentResult(
            intent=IntentType.FINANCE_QUERY,
            confidence=0.9,
            slots={"query_type": "balance"},
            is_complete=True,
        )
        out_bal = router_with_mocks.dispatch("u1", res_bal)
        assert "$2,250.00" in out_bal

        res_bd = IntentResult(
            intent=IntentType.FINANCE_QUERY,
            confidence=0.9,
            slots={"query_type": "breakdown"},
            is_complete=True,
        )
        out_bd = router_with_mocks.dispatch("u1", res_bd)
        assert "Groceries" in out_bd
        assert "45.0%" in out_bd

    def test_email_digest(self, router_with_mocks):
        res = IntentResult(
            intent=IntentType.EMAIL_CHECK,
            confidence=0.9,
            slots={"urgent_only": False},
            is_complete=True,
        )
        out = router_with_mocks.dispatch("u1", res)
        assert "URGENT: Cloud Bill Overdue" in out
        assert "billing@cloud.com" in out

    def test_calendar_schedule_success_and_conflict(self):
        cal_mock_no_conflict = MockCalendarService(has_conflict=False)
        router_ok = ToolRouter(calendar_service=cal_mock_no_conflict)
        res_ok = IntentResult(
            intent=IntentType.CALENDAR_SCHEDULE,
            confidence=0.9,
            slots={
                "title": "Meeting with Bob",
                "start_time": datetime(2026, 11, 5, 15, 0),
                "end_time": datetime(2026, 11, 5, 16, 0),
                "location": "Room 101",
            },
            is_complete=True,
        )
        out_ok = router_ok.dispatch("u1", res_ok)
        assert "Event Scheduled" in out_ok
        assert "Meeting with Bob" in out_ok
        assert "Room 101" in out_ok

        # Test conflict branch
        cal_mock_conflict = MockCalendarService(has_conflict=True)
        router_conflict = ToolRouter(calendar_service=cal_mock_conflict)
        out_conflict = router_conflict.dispatch("u1", res_ok)
        assert "Scheduling Conflict Detected" in out_conflict
        assert "Team Standup" in out_conflict

    def test_task_management(self, router_with_mocks):
        res_create = IntentResult(
            intent=IntentType.TASK_CREATE,
            confidence=0.9,
            slots={"title": "Submit taxes", "priority": "urgent", "due_date": None},
            is_complete=True,
        )
        out_create = router_with_mocks.dispatch("u1", res_create)
        assert "Task Added" in out_create
        assert "Submit taxes" in out_create
        assert "Urgent" in out_create

        res_list = IntentResult(
            intent=IntentType.TASK_LIST,
            confidence=0.9,
            slots={"status": "pending"},
            is_complete=True,
        )
        out_list = router_with_mocks.dispatch("u1", res_list)
        assert "Buy milk" in out_list
        assert "Call dentist" in out_list

    def test_outing_research(self, router_with_mocks):
        res = IntentResult(
            intent=IntentType.OUTING_RESEARCH,
            confidence=0.9,
            slots={"query": "Italian food", "cuisine": "Italian", "location": "Downtown"},
            is_complete=True,
        )
        out = router_with_mocks.dispatch("u1", res)
        assert "Trattoria Bella" in out
        assert "4.8" in out

    def test_unbound_fallback_router(self):
        # Default router with None for all services must still return friendly markdown
        empty_router = ToolRouter()
        res = IntentResult(
            intent=IntentType.UNKNOWN,
            confidence=0.1,
            slots={},
            is_complete=True,
        )
        out = empty_router.dispatch("u1", res)
        assert "Personal Assistant" in out
        assert "Finance" in out


# =============================================================================
# 5. Audio Note Handler Unit Tests
# =============================================================================


class TestAudioNoteHandler:
    def test_transcribe_embedded_mock_voice(self):
        handler = AudioNoteHandler()
        payload = b"OggS\x00\x02\x00\x00MOCK_VOICE:Spent $45 on groceries\n"
        transcript = handler.parse_and_transcribe(payload)
        assert transcript == "Spent $45 on groceries"

    def test_transcribe_plain_text_bytes(self):
        handler = AudioNoteHandler()
        transcript = handler.parse_and_transcribe(b"Schedule team sync tomorrow at 2pm")
        assert transcript == "Schedule team sync tomorrow at 2pm"

    def test_empty_audio_raises_error(self):
        handler = AudioNoteHandler()
        with pytest.raises(ValueError, match="empty"):
            handler.parse_and_transcribe(b"")

    def test_inspect_audio_metadata(self):
        meta_ogg = AudioNoteHandler.inspect_audio_metadata(b"OggS....")
        assert meta_ogg["detected_format"] == "ogg/opus"
        assert meta_ogg["has_valid_header"] is True

        meta_wav = AudioNoteHandler.inspect_audio_metadata(b"RIFF\x00\x00\x00\x00WAVEfmt ")
        assert meta_wav["detected_format"] == "wav"

        meta_unknown = AudioNoteHandler.inspect_audio_metadata(b"\x00\x01\x02\x03")
        assert meta_unknown["detected_format"] == "unknown"


# =============================================================================
# 6. Telegram Client Unit Tests
# =============================================================================


class TestTelegramClient:
    def test_secret_token_validation(self):
        client = TelegramClient(secret_token="super_secret_token_123")
        assert client.validate_secret_token("super_secret_token_123") is True
        assert client.validate_secret_token("wrong_token") is False
        assert client.validate_secret_token(None) is False
        assert client.validate_secret_token("") is False

    def test_parse_text_update(self):
        client = TelegramClient()
        payload = {
            "update_id": 9991,
            "message": {
                "message_id": 101,
                "chat": {"id": 12345},
                "from": {"id": 12345, "first_name": "Sam"},
                "text": "What is my balance?",
                "date": 1700000000,
            },
        }
        update = client.parse_update(payload)
        assert update.update_id == 9991
        assert update.message is not None
        assert update.message.chat_id == "12345"
        assert update.message.user_id == "12345"
        assert update.message.text == "What is my balance?"
        assert update.message.is_voice is False

    def test_parse_voice_update(self):
        client = TelegramClient()
        payload = {
            "update_id": 9992,
            "message": {
                "message_id": 102,
                "chat": {"id": 12345},
                "from": {"id": 12345},
                "voice": {
                    "file_id": "file_voice_123",
                    "file_unique_id": "uniq_123",
                    "duration": 5,
                    "mime_type": "audio/ogg",
                    "file_size": 12340,
                },
            },
        }
        update = client.parse_update(payload)
        assert update.message is not None
        assert update.message.is_voice is True
        assert update.message.voice.file_id == "file_voice_123"
        assert update.message.voice.duration == 5

    def test_keyboards_builder(self):
        client = TelegramClient()
        kb = client.build_default_quick_keyboard()
        assert "keyboard" in kb
        assert len(kb["keyboard"]) == 2
        assert kb["resize_keyboard"] is True

        inline_kb = client.build_inline_keyboard(
            [[{"text": "Confirm", "callback_data": "confirm"}]]
        )
        assert "inline_keyboard" in inline_kb

    def test_send_message_in_mock_mode(self):
        client = TelegramClient(mock_mode=True)
        res = client.send_message("12345", "Hello Markdown Test")
        assert res["ok"] is True
        assert len(client.sent_messages) == 1
        assert client.sent_messages[0]["chat_id"] == "12345"
        assert client.sent_messages[0]["text"] == "Hello Markdown Test"


# =============================================================================
# 7. Webhook API Endpoint Integration Tests
# =============================================================================


class TestWebhookAPI:
    @pytest.fixture
    def test_app(self):
        app = FastAPI()
        app.include_router(webhook_router)

        tg_client = TelegramClient(secret_token="test_secret", mock_mode=True)
        intent_parser = IntentParser()
        session_mgr = SessionManager()
        tool_router = ToolRouter(
            finance_service=MockFinanceService(),
            calendar_service=MockCalendarService(),
            task_service=MockTaskService(),
            email_service=MockEmailService(),
            search_service=MockSearchService(),
        )
        audio_handler = AudioNoteHandler()

        app.dependency_overrides[get_telegram_client] = lambda: tg_client
        app.dependency_overrides[get_intent_parser] = lambda: intent_parser
        app.dependency_overrides[get_session_manager] = lambda: session_mgr
        app.dependency_overrides[get_tool_router] = lambda: tool_router
        app.dependency_overrides[get_audio_handler] = lambda: audio_handler

        return app, tg_client, session_mgr

    def test_webhook_secret_token_rejection(self, test_app):
        app, _, _ = test_app
        client = TestClient(app)

        # No secret header -> 403 Forbidden
        resp1 = client.post("/api/webhook/telegram", json={"update_id": 1})
        assert resp1.status_code == 403

        # Wrong secret header -> 403 Forbidden
        resp2 = client.post(
            "/api/webhook/telegram",
            json={"update_id": 1},
            headers={"X-Telegram-Bot-Api-Secret-Token": "bad_secret"},
        )
        assert resp2.status_code == 403

    def test_webhook_unconfigured_secret_rejection_if_supplied(self):
        """When no secret is configured, supplying an invalid token must be rejected with 403."""
        from fastapi import FastAPI
        from app.api.webhook import webhook_router, get_telegram_client
        from app.integrations.telegram_client import TelegramClient

        app = FastAPI()
        app.include_router(webhook_router)
        tg_client = TelegramClient(secret_token="", mock_mode=True)
        app.dependency_overrides[get_telegram_client] = lambda: tg_client

        client = TestClient(app)
        # Supplying an invalid token when none configured -> 403 Forbidden
        resp1 = client.post(
            "/api/webhook/telegram",
            json={"update_id": 1},
            headers={"X-Telegram-Bot-Api-Secret-Token": "unauthorized_secret_token"},
        )
        assert resp1.status_code == 403

        # Supplying no header when none configured -> accepted (ignored non-message)
        resp2 = client.post(
            "/api/webhook/telegram",
            json={"update_id": 1},
        )
        assert resp2.status_code == 200
        assert resp2.json()["status"] == "ignored"

    def test_webhook_env_secret_token_validation(self, monkeypatch):
        """When TELEGRAM_SECRET_TOKEN or TELEGRAM_WEBHOOK_SECRET is set in env, validate correctly."""
        from fastapi import FastAPI
        from app.api.webhook import webhook_router, get_telegram_client
        from app.integrations.telegram_client import TelegramClient

        monkeypatch.setenv("TELEGRAM_SECRET_TOKEN", "env_secret_token_999")
        app = FastAPI()
        app.include_router(webhook_router)
        tg_client = TelegramClient(secret_token="", mock_mode=True)
        app.dependency_overrides[get_telegram_client] = lambda: tg_client

        client = TestClient(app)

        # Missing header -> 403 Forbidden
        resp_missing = client.post("/api/webhook/telegram", json={"update_id": 1})
        assert resp_missing.status_code == 403

        # Invalid header -> 403 Forbidden
        resp_wrong = client.post(
            "/api/webhook/telegram",
            json={"update_id": 1},
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong_env_secret"},
        )
        assert resp_wrong.status_code == 403

        # Matching header -> 200 OK
        resp_valid = client.post(
            "/api/webhook/telegram",
            json={"update_id": 1},
            headers={"X-Telegram-Bot-Api-Secret-Token": "env_secret_token_999"},
        )
        assert resp_valid.status_code == 200

    def test_webhook_text_transaction(self, test_app):
        app, tg_client, _ = test_app
        client = TestClient(app)
        headers = {"X-Telegram-Bot-Api-Secret-Token": "test_secret"}

        payload = {
            "update_id": 1,
            "message": {
                "message_id": 100,
                "chat": {"id": 555},
                "from": {"id": 555},
                "text": "Spent $45 on groceries",
            },
        }
        resp = client.post("/api/webhook/telegram", json=payload, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["intent"] == "finance_entry"
        assert "$45.00" in data["response"]

        # Ensure bot sent reply to chat
        assert len(tg_client.sent_messages) == 1
        assert tg_client.sent_messages[0]["chat_id"] == "555"

    def test_webhook_voice_note_processing(self, test_app):
        app, tg_client, _ = test_app
        client = TestClient(app)
        headers = {"X-Telegram-Bot-Api-Secret-Token": "test_secret"}

        payload = {
            "update_id": 2,
            "mock_audio_bytes": "MOCK_VOICE:What is my balance?",
            "message": {
                "message_id": 101,
                "chat": {"id": 555},
                "from": {"id": 555},
                "voice": {
                    "file_id": "v_123",
                    "duration": 3,
                },
            },
        }
        resp = client.post("/api/webhook/telegram", json=payload, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["intent"] == "finance_query"
        assert "Balance" in data["response"]

    def test_webhook_multi_turn_conversation(self, test_app):
        app, tg_client, session_mgr = test_app
        client = TestClient(app)
        headers = {"X-Telegram-Bot-Api-Secret-Token": "test_secret"}

        # Turn 1: Incomplete command
        payload1 = {
            "update_id": 3,
            "message": {
                "message_id": 102,
                "chat": {"id": 777},
                "from": {"id": 777},
                "text": "Spent $45",
            },
        }
        resp1 = client.post("/api/webhook/telegram", json=payload1, headers=headers)
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert "What was this" in data1["response"]
        assert session_mgr.get_session("777").is_in_flow() is True

        # Turn 2: Providing the missing slot
        payload2 = {
            "update_id": 4,
            "message": {
                "message_id": 103,
                "chat": {"id": 777},
                "from": {"id": 777},
                "text": "Groceries",
            },
        }
        resp2 = client.post("/api/webhook/telegram", json=payload2, headers=headers)
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert "Expense Recorded Successfully" in data2["response"]
        assert "$45.00" in data2["response"]
        assert session_mgr.get_session("777").is_in_flow() is False
