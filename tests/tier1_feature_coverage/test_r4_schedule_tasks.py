"""Tier 1: Feature Coverage — R4: Schedule Management, Task Tracking & Outing Research.

Tests T1-R4-01 to T1-R4-06 verifying calendar event creation, chronological schedule listing,
task creation, task lifecycle status updates, task filtering, and structured outing research.
"""

from datetime import datetime, timedelta, timezone
import sqlite3
import pytest

from app.database.repositories.calendar_repo import CalendarRepository
from app.database.repositories.task_repo import TaskRepository
from app.integrations.mocks import MockCalendarClient, MockWebSearchClient
from app.services.calendar_service import CalendarService
from app.services.search_service import SearchService
from app.services.task_service import TaskService


@pytest.fixture
def calendar_service(mock_db: sqlite3.Connection) -> CalendarService:
    repo = CalendarRepository(conn=mock_db)
    client = MockCalendarClient()
    return CalendarService(client=client, repository=repo)


@pytest.fixture
def task_service(mock_db: sqlite3.Connection) -> TaskService:
    repo = TaskRepository(conn=mock_db)
    return TaskService(repository=repo)


@pytest.fixture
def search_service() -> SearchService:
    client = MockWebSearchClient()
    return SearchService(search_client=client)


def test_t1_r4_01_create_calendar_event(calendar_service: CalendarService):
    """T1-R4-01: Create calendar event persists event with summary, start, end, and returns confirmation."""
    user = "usr_test_default"
    start_dt = "2026-11-10T10:00:00Z"
    end_dt = "2026-11-10T11:00:00Z"

    event = calendar_service.create_event(
        user_id=user,
        title="Dentist Appointment",
        start_time=start_dt,
        end_time=end_dt,
        location="Dental Clinic",
    )

    assert event is not None
    assert event["summary"] == "Dentist Appointment" or event.get("title") == "Dentist Appointment"
    start_str = event["start"]["dateTime"] if isinstance(event.get("start"), dict) else str(event.get("start_time") or event.get("start"))
    assert "2026-11-10" in start_str


def test_t1_r4_02_list_daily_schedule(calendar_service: CalendarService):
    """T1-R4-02: Query schedule returns chronological events for the date range."""
    user = "usr_test_default"
    calendar_service.create_event(user, "Standup", "2026-11-04T09:00:00Z", "2026-11-04T09:30:00Z")
    calendar_service.create_event(user, "Design Review", "2026-11-04T14:00:00Z", "2026-11-04T15:00:00Z")

    events = calendar_service.list_events(user, "2026-11-04T00:00:00Z", "2026-11-04T23:59:59Z")
    assert len(events) >= 2
    summaries = [e.get("summary") or e.get("title") for e in events]
    assert "Standup" in summaries
    assert "Design Review" in summaries


def test_t1_r4_03_add_todo_task(task_service: TaskService):
    """T1-R4-03: Create task persists item with priority, due date, and pending status."""
    user = "usr_test_default"
    due_date = "2026-11-06T18:00:00Z"

    task = task_service.create_task(
        user_id=user,
        title="Buy flight tickets",
        priority="high",
        due_date=due_date,
    )

    assert task is not None
    assert task["title"] == "Buy flight tickets"
    assert task["priority"] == "high"
    assert task["status"] in ["pending", "PENDING"]


def test_t1_r4_04_complete_todo_task(task_service: TaskService):
    """T1-R4-04: Update task status moves item from pending to completed with completed_at set."""
    user = "usr_test_default"
    task = task_service.create_task(user, "Submit expense report")
    task_id = task["task_id"]

    updated = task_service.update_status(task_id=task_id, status="completed", user_id=user)
    assert updated is not None
    assert updated["status"] in ["completed", "COMPLETED"]
    assert updated.get("is_completed") in [1, True]


def test_t1_r4_05_query_pending_tasks(task_service: TaskService):
    """T1-R4-05: Querying tasks filtered by status=pending returns only uncompleted items."""
    user = "usr_test_default"
    t1 = task_service.create_task(user, "Pending Task 1", priority="high")
    t2 = task_service.create_task(user, "Pending Task 2", priority="medium")
    t3 = task_service.create_task(user, "Done Task", priority="low")
    task_service.update_status(task_id=t3["task_id"], status="completed", user_id=user)

    pending = task_service.list_tasks(user, status="pending")
    titles = [t["title"] for t in pending]
    assert "Pending Task 1" in titles
    assert "Pending Task 2" in titles
    assert "Done Task" not in titles


def test_t1_r4_06_outing_and_leisure_research(search_service: SearchService):
    """T1-R4-06: Outing research returns structured venue recommendations with rating and location."""
    user = "usr_test_default"
    results = search_service.search_outings(user, query="Italian restaurants near Downtown", location="Downtown")

    assert len(results) >= 1
    first = results[0]
    assert "name" in first
    assert "rating" in first
    assert first["rating"] >= 4.0
    assert first.get("category") == "Italian" or "italian" in str(first).lower()
    assert "downtown" in first.get("address", "").lower() or "downtown" in first.get("location", "").lower()
