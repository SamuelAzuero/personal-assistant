"""Comprehensive unit test suite for Milestone 3 components:

Google Integrations, Email Monitoring & Digest, Calendar Schedule Conflict Engine,
Task Management, and Outing Research (F23-F44).
"""

from __future__ import annotations

import base64
import sqlite3
from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

# Integration Mocks
from app.integrations.mocks import (
    AudioProcessingError,
    CalendarAPIError,
    GmailAPIError,
    MockCalendarClient,
    MockGmailClient,
    MockSTTService,
    MockWebSearchClient,
    SilentAudioException,
)
from app.integrations.gmail_client import GmailClient
from app.integrations.calendar_client import CalendarClient

# Repositories & Entities
from app.database.repositories.task_repo import Task, TaskRepository
from app.database.repositories.calendar_repo import CalendarRepository, CalendarEventRecord

# Services
from app.services.email_service import EmailService
from app.services.calendar_service import CalendarService
from app.services.task_service import TaskService
from app.services.search_service import SearchService

# API Router
from app.api.task_router import router as task_router, set_task_service


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def memory_db_conn():
    """In-memory SQLite connection for isolated repository tests."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    yield conn
    conn.close()


@pytest.fixture
def task_repo(memory_db_conn):
    """TaskRepository backed by memory database."""
    return TaskRepository(conn=memory_db_conn)


@pytest.fixture
def calendar_repo(memory_db_conn):
    """CalendarRepository backed by memory database."""
    return CalendarRepository(conn=memory_db_conn)


@pytest.fixture
def mock_stt():
    """Fresh MockSTTService instance."""
    return MockSTTService()


@pytest.fixture
def mock_gmail():
    """Fresh MockGmailClient instance with default fixtures."""
    client = MockGmailClient()
    client.reset_fixtures()
    return client


@pytest.fixture
def mock_calendar():
    """Fresh MockCalendarClient instance."""
    return MockCalendarClient()


@pytest.fixture
def mock_search():
    """Fresh MockWebSearchClient instance."""
    return MockWebSearchClient()


@pytest.fixture
def email_service(mock_gmail):
    """EmailService wired with mock Gmail client."""
    client = GmailClient(mock_client=mock_gmail)
    return EmailService(client=client)


@pytest.fixture
def calendar_service(mock_calendar, calendar_repo):
    """CalendarService wired with mock calendar client and calendar repository."""
    client = CalendarClient(mock_client=mock_calendar)
    return CalendarService(client=client, repository=calendar_repo)


@pytest.fixture
def task_service(task_repo):
    """TaskService backed by in-memory repository."""
    return TaskService(repository=task_repo)


@pytest.fixture
def search_service(mock_search):
    """SearchService backed by mock search client."""
    return SearchService(search_client=mock_search)


@pytest.fixture
def api_client(task_service):
    """FastAPI TestClient with task_router and injected task_service."""
    app = FastAPI()
    app.include_router(task_router)
    set_task_service(task_service)
    return TestClient(app)


# ============================================================================
# 1. MockSTTService Tests
# ============================================================================

def test_mock_stt_transcribes_pre_registered_fixtures(mock_stt):
    """MockSTTService should match pre-registered byte payloads to exact transcripts."""
    transcript = mock_stt.transcribe(b"MOCK_OGG_EXPENSE_45")
    assert "Spent 45 dollars on groceries" in transcript

    transcript_lunch = mock_stt.transcribe(b"MOCK_OGG_LUNCH_18")
    assert "lunch at Chipotle" in transcript_lunch


def test_mock_stt_transcribes_custom_registered_fixture(mock_stt):
    """Registering a new fixture should allow deterministic lookup by hash."""
    custom_bytes = b"MY_CUSTOM_TEST_AUDIO_BYTES_12345"
    mock_stt.register_fixture(custom_bytes, "Schedule meeting with Dave on Monday")

    result = mock_stt.transcribe(custom_bytes)
    assert result == "Schedule meeting with Dave on Monday"


def test_mock_stt_handles_mock_voice_prefix(mock_stt):
    """Payloads formatted with MOCK_VOICE: prefix should extract the embedded transcript."""
    audio = b"MOCK_VOICE:Add milk and eggs to my grocery list"
    assert mock_stt.transcribe(audio) == "Add milk and eggs to my grocery list"


def test_mock_stt_fault_injection_corrupt_raises_error(mock_stt):
    """Corrupt audio simulation must raise AudioProcessingError."""
    # Prefix trigger
    with pytest.raises(AudioProcessingError) as exc_info:
        mock_stt.transcribe(b"CORRUPT_RANDOM_BYTES_000")
    assert "Could not transcribe voice note" in str(exc_info.value)

    # Mode switch trigger
    mock_stt.set_mode("corrupt")
    with pytest.raises(AudioProcessingError):
        mock_stt.transcribe(b"ANY_AUDIO")


def test_mock_stt_fault_injection_silent_audio(mock_stt):
    """Zero-amplitude or empty audio must raise SilentAudioException."""
    with pytest.raises(SilentAudioException):
        mock_stt.transcribe(b"")

    with pytest.raises(SilentAudioException):
        mock_stt.transcribe(b"SILENCE")

    mock_stt.set_mode("silent")
    with pytest.raises(SilentAudioException):
        mock_stt.transcribe(b"SOME_SOUND")


# ============================================================================
# 2. MockGmailClient Tests
# ============================================================================

def test_mock_gmail_lists_and_retrieves_unread_messages(mock_gmail):
    """MockGmailClient lists unread messages and retrieves RFC 2822 detail."""
    unread = mock_gmail.list_unread(user_id="default_user", max_results=10)
    assert len(unread) >= 4

    first_id = unread[0]["id"]
    msg = mock_gmail.get_message(user_id="default_user", message_id=first_id)
    assert msg["id"] == first_id
    assert "payload" in msg
    assert "headers" in msg["payload"]
    assert "body" in msg["payload"]


def test_mock_gmail_modifies_labels(mock_gmail):
    """MockGmailClient modifies labels (e.g. marking message as read)."""
    msg_id = "msg_urgent_bill_001"
    msg = mock_gmail.get_message("default_user", msg_id)
    assert "UNREAD" in msg["labelIds"]

    mock_gmail.modify_labels("default_user", msg_id, remove_labels=["UNREAD"], add_labels=["PROCESSED"])
    updated = mock_gmail.get_message("default_user", msg_id)
    assert "UNREAD" not in updated["labelIds"]
    assert "PROCESSED" in updated["labelIds"]


def test_mock_gmail_simulates_rate_limit_and_unauthorized(mock_gmail):
    """MockGmailClient simulates HTTP 429 and 401 exceptions."""
    mock_gmail.set_simulate_rate_limit(True)
    with pytest.raises(GmailAPIError) as exc_429:
        mock_gmail.list_unread("default_user")
    assert exc_429.value.status_code == 429

    mock_gmail.set_simulate_rate_limit(False)
    mock_gmail.set_simulate_unauthorized(True)
    with pytest.raises(GmailAPIError) as exc_401:
        mock_gmail.list_unread("default_user")
    assert exc_401.value.status_code == 401


# ============================================================================
# 3. MockCalendarClient Tests
# ============================================================================

def test_mock_calendar_creates_and_lists_events(mock_calendar):
    """MockCalendarClient creates events and lists them within time window."""
    user = "test_user_cal"
    now = datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc)
    ev = mock_calendar.create_event(
        user_id=user,
        title="Dentist Appointment",
        start_time=now,
        end_time=now + timedelta(hours=1),
        location="Dental Clinic",
    )
    assert ev["summary"] == "Dentist Appointment"

    events = mock_calendar.list_events(
        user_id=user,
        time_min=now - timedelta(hours=1),
        time_max=now + timedelta(hours=2),
    )
    assert len(events) == 1
    assert events[0]["id"] == ev["id"]


def test_mock_calendar_conflict_detection_strict_interval(mock_calendar):
    """Strict interval overlap: max(s1, s2) < min(e1, e2)."""
    user = "conflict_user"
    # Event 1: 14:00 - 15:00
    s1 = datetime(2026, 11, 4, 14, 0, tzinfo=timezone.utc)
    e1 = datetime(2026, 11, 4, 15, 0, tzinfo=timezone.utc)
    mock_calendar.create_event(user_id=user, title="Existing Meeting", start_time=s1, end_time=e1)

    # Case A: Partial Overlap (14:30 - 15:30) -> Conflict
    conflicts_a = mock_calendar.check_conflicts(
        user_id=user,
        start_time=datetime(2026, 11, 4, 14, 30, tzinfo=timezone.utc),
        end_time=datetime(2026, 11, 4, 15, 30, tzinfo=timezone.utc),
    )
    assert len(conflicts_a) == 1

    # Case B: Adjacent / Back-to-Back (15:00 - 16:00) -> NO Conflict
    conflicts_b = mock_calendar.check_conflicts(
        user_id=user,
        start_time=datetime(2026, 11, 4, 15, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 11, 4, 16, 0, tzinfo=timezone.utc),
    )
    assert len(conflicts_b) == 0

    # Case C: Prior Adjacent (13:00 - 14:00) -> NO Conflict
    conflicts_c = mock_calendar.check_conflicts(
        user_id=user,
        start_time=datetime(2026, 11, 4, 13, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 11, 4, 14, 0, tzinfo=timezone.utc),
    )
    assert len(conflicts_c) == 0


def test_mock_calendar_rejects_inverted_times(mock_calendar):
    """Event creation with end <= start must raise ValueError."""
    s = datetime(2026, 11, 4, 15, 0, tzinfo=timezone.utc)
    e = datetime(2026, 11, 4, 14, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError) as exc:
        mock_calendar.create_event(user_id="user_inv", title="Impossible", start_time=s, end_time=e)
    assert "cannot be before or equal" in str(exc.value)


def test_mock_calendar_deletes_event(mock_calendar):
    """Deleting an event returns True, and event is no longer listed."""
    user = "user_del"
    s = datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc)
    e = datetime(2026, 11, 4, 11, 0, tzinfo=timezone.utc)
    ev = mock_calendar.create_event(user_id=user, title="Temporary", start_time=s, end_time=e)

    assert mock_calendar.delete_event(user_id=user, event_id=ev["id"]) is True
    assert len(mock_calendar.list_events(user_id=user)) == 0


# ============================================================================
# 4. MockWebSearchClient Tests
# ============================================================================

def test_mock_web_search_returns_structured_recommendations(mock_search):
    """MockWebSearchClient returns places with rating, price tier, and address."""
    results = mock_search.search(query="Italian restaurants near downtown", location="Downtown")
    assert len(results) >= 2
    assert any("Luigi's" in r["name"] or "Pasta Fresca" in r["name"] for r in results)
    first = results[0]
    assert "rating" in first
    assert "price_tier" in first
    assert "address" in first


def test_mock_web_search_zero_result_query(mock_search):
    """Specific impossible queries should return 0 results to test boundary handling."""
    results = mock_search.search(query="Antarctic Penguin Fine Dining in Sahara Desert")
    assert results == []


# ============================================================================
# 5. EmailService Tests
# ============================================================================

def test_email_service_decodes_and_scores_urgency(email_service):
    """EmailService parses unread messages, extracts headers, and computes urgency score."""
    items = email_service.poll_unread(user_id="default_user")
    assert len(items) >= 4

    urgent_bill = next((it for it in items if "AWS bill" in it["subject"]), None)
    assert urgent_bill is not None
    assert urgent_bill["is_urgent"] is True
    assert urgent_bill["urgency_score"] >= 70
    assert urgent_bill["category"] in {"BILL", "ALERT"}
    assert any("pay" in act.lower() or "review" in act.lower() for act in urgent_bill["actions"])


def test_email_service_deescalates_promotional_noise(email_service):
    """Marketing and promo newsletters must be de-escalated to LOW priority."""
    items = email_service.poll_unread(user_id="default_user")

    # Promo with fake urgent subject: "URGENT FLASH SALE: 90% OFF SHOES!"
    fake_urgent = next((it for it in items if "FLASH SALE" in it["subject"]), None)
    assert fake_urgent is not None
    assert fake_urgent["is_urgent"] is False
    assert fake_urgent["category"] == "NEWSLETTER"
    assert fake_urgent["urgency_score"] < 70


def test_email_service_generates_executive_digest(email_service):
    """EmailService generates executive bulleted digest with urgent highlights."""
    digest = email_service.generate_digest(user_id="default_user")
    assert digest["urgent_count"] >= 1
    assert digest["total_unread"] >= 4
    summary = digest["summary_text"]
    assert "🚨 **High Priority / Urgent**:" in summary
    assert "URGENT: Your AWS bill" in summary or "Critical security alert" in summary


def test_email_service_handles_empty_inbox(mock_gmail):
    """Empty inbox should return friendly zero-divide message."""
    mock_gmail.messages.clear()
    svc = EmailService(client=GmailClient(mock_client=mock_gmail))
    digest = svc.generate_digest("default_user")
    assert digest["urgent_count"] == 0
    assert digest["total_unread"] == 0
    assert "You're all caught up! No unread emails" in digest["summary_text"]


def test_email_service_handles_large_body_truncation(mock_gmail):
    """Email with >50KB body should truncate cleanly without memory issues."""
    huge_body = "Important memo content line. " * 3000  # ~90KB
    mock_gmail.add_message(
        msg_id="msg_huge_001",
        sender="boss@corp.com",
        to="me@corp.com",
        subject="Very Long Strategic Plan",
        date="Wed, 04 Nov 2026 12:00:00 +0000",
        body=huge_body,
    )
    svc = EmailService(client=GmailClient(mock_client=mock_gmail))
    items = svc.poll_unread("default_user")
    huge_item = next(it for it in items if it["id"] == "msg_huge_001")
    assert len(huge_item["body"]) <= 50_500
    assert "[Body truncated" in huge_item["body"]


def test_email_service_formats_proactive_alert(email_service):
    """Proactive alert format should produce clean markdown alert for Telegram."""
    items = email_service.poll_unread("default_user")
    urgent_item = next(it for it in items if it["is_urgent"])
    alert_text = email_service.format_proactive_alert(urgent_item)
    assert "🚨 **URGENT EMAIL ALERT**" in alert_text
    assert f"**Subject**: {urgent_item['subject']}" in alert_text


# ============================================================================
# 6. CalendarService Tests
# ============================================================================

def test_calendar_service_creates_and_lists_events(calendar_service):
    """CalendarService creates events and lists them chronologically."""
    user = "user_cal_svc"
    s = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)
    e = datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc)

    created = calendar_service.create_event(
        user_id=user,
        title="Project Kickoff",
        start_time=s,
        end_time=e,
        location="Boardroom A",
    )
    assert created["summary"] == "Project Kickoff"
    assert created["has_conflict"] is False

    events = calendar_service.list_events(user_id=user, start_time=s - timedelta(hours=1), end_time=e + timedelta(hours=1))
    assert len(events) == 1
    assert events[0]["summary"] == "Project Kickoff"


def test_calendar_service_conflict_reporting_on_create(calendar_service):
    """Creating an overlapping event flags conflicts accurately."""
    user = "user_cal_conflict"
    s1 = datetime(2026, 11, 5, 14, 0, tzinfo=timezone.utc)
    e1 = datetime(2026, 11, 5, 15, 0, tzinfo=timezone.utc)
    calendar_service.create_event(user_id=user, title="First Meeting", start_time=s1, end_time=e1)

    # Create overlapping meeting 14:30 - 15:30
    s2 = datetime(2026, 11, 5, 14, 30, tzinfo=timezone.utc)
    e2 = datetime(2026, 11, 5, 15, 30, tzinfo=timezone.utc)
    overlapping = calendar_service.create_event(user_id=user, title="Second Meeting", start_time=s2, end_time=e2)

    assert overlapping["has_conflict"] is True
    assert len(overlapping["conflicts"]) == 1
    assert overlapping["conflicts"][0]["summary"] == "First Meeting"


def test_calendar_service_back_to_back_is_non_conflicting(calendar_service):
    """Back-to-back events (e1 == s2) must NOT trigger conflict."""
    user = "user_b2b"
    s1 = datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc)
    e1 = datetime(2026, 11, 5, 11, 0, tzinfo=timezone.utc)
    calendar_service.create_event(user_id=user, title="Session 1", start_time=s1, end_time=e1)

    s2 = datetime(2026, 11, 5, 11, 0, tzinfo=timezone.utc)
    e2 = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
    conflicts = calendar_service.check_conflicts(user_id=user, start_time=s2, end_time=e2)
    assert len(conflicts) == 0


def test_calendar_service_rejects_inverted_times(calendar_service):
    """CalendarService must reject end <= start with ValueError."""
    s = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
    e = datetime(2026, 11, 5, 11, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError) as exc:
        calendar_service.create_event(user_id="u", title="Invalid", start_time=s, end_time=e)
    assert "cannot be before or equal" in str(exc.value)


def test_calendar_service_deletes_event(calendar_service):
    """CalendarService deletes event from both client and repo."""
    user = "user_del_svc"
    s = datetime(2026, 11, 5, 13, 0, tzinfo=timezone.utc)
    e = datetime(2026, 11, 5, 14, 0, tzinfo=timezone.utc)
    created = calendar_service.create_event(user_id=user, title="Delete Me", start_time=s, end_time=e)

    assert calendar_service.delete_event(user_id=user, event_id=created["id"]) is True


# ============================================================================
# 7. TaskService & TaskRepository Tests
# ============================================================================

def test_task_service_creates_and_retrieves_task(task_service):
    """TaskService creates task with priority and due date."""
    user = "task_user_01"
    due = datetime(2026, 11, 6, 17, 0, tzinfo=timezone.utc)
    task = task_service.create_task(
        user_id=user,
        title="Submit Expense Report",
        due_date=due,
        priority="high",
        description="Attach receipts from lunch and travel",
        category="finance",
    )
    assert task["title"] == "Submit Expense Report"
    assert task["priority"] == "high"
    assert task["status"] == "pending"
    assert task["is_completed"] is False

    retrieved = task_service.get_task(task_id=task["task_id"], user_id=user)
    assert retrieved is not None
    assert retrieved["title"] == "Submit Expense Report"


def test_task_service_rejects_empty_title(task_service):
    """Task creation with empty title must raise ValueError."""
    with pytest.raises(ValueError) as exc:
        task_service.create_task(user_id="u", title="   ")
    assert "cannot be empty" in str(exc.value)


def test_task_service_truncates_oversized_title(task_service):
    """Oversized task titles (>255 chars) are cleanly truncated with ellipsis (T2-R4-05)."""
    long_title = "Important task: " + ("x" * 300)
    task = task_service.create_task(user_id="u", title=long_title)
    assert len(task["title"]) == 255
    assert task["title"].endswith("...")


def test_task_service_status_lifecycle_and_completed_at(task_service):
    """Status lifecycle transitions (pending -> in_progress -> completed -> cancelled)."""
    task = task_service.create_task(user_id="user_life", title="Lifecycle Task")
    tid = task["task_id"]

    # Transition to in_progress
    in_prog = task_service.update_status(task_id=tid, status="in_progress")
    assert in_prog["status"] == "in_progress"
    assert in_prog["is_completed"] is False
    assert in_prog["completed_at"] is None

    # Transition to completed
    done = task_service.update_status(task_id=tid, status="completed")
    assert done["status"] == "completed"
    assert done["is_completed"] is True
    assert done["completed_at"] is not None

    # Transition to cancelled
    cancelled = task_service.update_status(task_id=tid, status="cancelled")
    assert cancelled["status"] == "cancelled"
    assert cancelled["is_completed"] is False


def test_task_service_filters_by_status_and_priority(task_service):
    """Tasks are filtered by status and sorted by priority (urgent > high > medium > low)."""
    user = "filter_user"
    task_service.create_task(user_id=user, title="Low Task", priority="low")
    task_service.create_task(user_id=user, title="Urgent Task", priority="urgent")
    task_service.create_task(user_id=user, title="High Task", priority="high")
    t4 = task_service.create_task(user_id=user, title="Done Task", priority="medium")
    task_service.update_status(task_id=t4["task_id"], status="completed")

    # List pending tasks
    pending = task_service.list_tasks(user_id=user, status="pending")
    assert len(pending) == 3
    assert pending[0]["priority"] == "urgent"
    assert pending[1]["priority"] == "high"
    assert pending[2]["priority"] == "low"

    # List completed tasks
    completed = task_service.list_tasks(user_id=user, status="completed")
    assert len(completed) == 1
    assert completed[0]["title"] == "Done Task"


def test_task_service_reminders_and_overdue(task_service):
    """Upcoming reminder window and overdue calculations."""
    user = "remind_user"
    fixed_now = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)

    # Task due in 30 minutes (within 60m window)
    task_service.create_task(user_id=user, title="Due Soon", due_date=fixed_now + timedelta(minutes=30))
    # Task due in 3 hours (outside 60m window)
    task_service.create_task(user_id=user, title="Due Later", due_date=fixed_now + timedelta(hours=3))
    # Task overdue by 1 hour
    task_service.create_task(user_id=user, title="Overdue Task", due_date=fixed_now - timedelta(hours=1))

    reminders = task_service.get_upcoming_reminders(user_id=user, window_minutes=60, current_time=fixed_now)
    assert len(reminders) == 1
    assert reminders[0]["title"] == "Due Soon"

    overdue = task_service.get_overdue_tasks(user_id=user, current_time=fixed_now)
    assert len(overdue) == 1
    assert overdue[0]["title"] == "Overdue Task"


def test_task_service_delete(task_service):
    """Deleting a task removes it permanently."""
    task = task_service.create_task(user_id="u", title="To Be Deleted")
    tid = task["task_id"]
    assert task_service.delete_task(task_id=tid) is True
    assert task_service.get_task(task_id=tid) is None


# ============================================================================
# 8. SearchService Tests
# ============================================================================

def test_search_service_parameter_extraction(search_service):
    """SearchService extracts cuisine, activity, location, and budget constraints."""
    params = search_service.extract_parameters("Find top-rated Italian restaurants near Downtown with outdoor seating")
    assert params["cuisine"] == "Italian"
    assert params["activity"] == "dining"
    assert params["location"] == "Downtown"
    assert "outdoor seating" in params["amenities"]

    sushi_params = search_service.extract_parameters("Recommend cheap sushi in Seattle with wifi")
    assert sushi_params["cuisine"] == "Sushi"
    assert sushi_params["location"] == "Seattle"
    assert sushi_params["budget"] == "$"
    assert "wifi" in sushi_params["amenities"]


def test_search_service_outings_and_formatting(search_service):
    """SearchService executes search and formats structured conversational Markdown."""
    recommendations = search_service.search_outings(
        user_id="user_search",
        query="Recommend an Italian dinner near Downtown",
    )
    assert len(recommendations) >= 1
    assert any("Luigi's" in r["name"] or "Pasta Fresca" in r["name"] for r in recommendations)

    md = search_service.format_recommendations_markdown(recommendations)
    assert "Here are top curated recommendations" in md
    assert "⭐" in md


def test_search_service_zero_result_fallback(search_service):
    """SearchService returns friendly message when no results match."""
    empty = search_service.search_outings(
        user_id="u",
        query="Antarctic Penguin Fine Dining in Sahara Desert",
    )
    assert empty == []
    md = search_service.format_recommendations_markdown(empty)
    assert "No places found matching your criteria" in md


# ============================================================================
# 9. Task API Router Tests
# ============================================================================

def test_task_api_get_empty_list(api_client):
    """GET /api/tasks returns HTTP 200 with empty list when no tasks exist."""
    response = api_client.get("/api/tasks?user_id=new_user")
    assert response.status_code == 200
    assert response.json() == []


def test_task_api_post_creates_task(api_client):
    """POST /api/tasks creates a task and returns HTTP 201 Created."""
    payload = {
        "title": "Buy flight tickets",
        "priority": "HIGH",
        "due_date": "2026-11-06T18:00:00Z",
        "description": "Round trip to SFO",
        "category": "travel",
        "user_id": "test_user_api",
    }
    response = api_client.post("/api/tasks", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Buy flight tickets"
    assert data["priority"] == "high"
    assert data["status"] == "pending"
    assert "task_id" in data


def test_task_api_post_empty_title_returns_422(api_client):
    """POST /api/tasks with empty title returns HTTP 422 Unprocessable Entity."""
    response = api_client.post("/api/tasks", json={"title": "   ", "user_id": "u"})
    assert response.status_code == 422
    assert "cannot be empty" in response.text


def test_task_api_patch_updates_status(api_client):
    """PATCH /api/tasks/{id} updates task status to COMPLETED."""
    create_resp = api_client.post("/api/tasks", json={"title": "Complete me", "user_id": "u"})
    task_id = create_resp.json()["task_id"]

    patch_resp = api_client.patch(f"/api/tasks/{task_id}", json={"status": "COMPLETED"})
    assert patch_resp.status_code == 200
    updated = patch_resp.json()
    assert updated["status"] == "completed"
    assert updated["is_completed"] is True


def test_task_api_patch_nonexistent_returns_404(api_client):
    """PATCH /api/tasks/{nonexistent} returns HTTP 404 Not Found."""
    resp = api_client.patch("/api/tasks/nonexistent_12345", json={"status": "COMPLETED"})
    assert resp.status_code == 404


def test_task_api_delete_task(api_client):
    """DELETE /api/tasks/{id} removes task and returns HTTP 200."""
    create_resp = api_client.post("/api/tasks", json={"title": "Delete me", "user_id": "u"})
    task_id = create_resp.json()["task_id"]

    del_resp = api_client.delete(f"/api/tasks/{task_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["success"] is True

    # Subsequent delete of same ID returns 404
    del_again = api_client.delete(f"/api/tasks/{task_id}")
    assert del_again.status_code == 404
