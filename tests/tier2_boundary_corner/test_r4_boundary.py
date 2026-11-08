"""Tier 2: Boundary & Corner Cases — R4: Schedule Management, Task Tracking & Outing Research.

Tests T2-R4-01 to T2-R4-06 verifying calendar temporal collision detection,
inverted time boundaries, overdue tasks, empty search fallbacks, title length bounds, and all-day collisions.
"""

from datetime import datetime, timezone
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


def test_t2_r4_01_calendar_temporal_overlap_collision(calendar_service: CalendarService):
    """T2-R4-01: Candidate booking overlapping existing event (14:30-15:30 overlaps 14:00-15:00) is detected."""
    user = "default_user"
    conflicts = calendar_service.check_conflicts(
        user_id=user,
        start_time="2026-11-04T14:30:00Z",
        end_time="2026-11-04T15:30:00Z",
    )

    assert len(conflicts) >= 1
    conflicting_titles = [c.get("summary") or c.get("title") for c in conflicts]
    assert "Team Sync" in conflicting_titles


def test_t2_r4_02_inverted_event_times_rejected(calendar_service: CalendarService):
    """T2-R4-02: Calendar event with end_time before start_time is rejected with ValueError."""
    user = "default_user"
    with pytest.raises(ValueError) as excinfo:
        calendar_service.create_event(
            user_id=user,
            title="Inverted Time Meeting",
            start_time="2026-11-04T16:00:00Z",
            end_time="2026-11-04T15:00:00Z",
        )
    assert "cannot be before" in str(excinfo.value).lower() or "end time" in str(excinfo.value).lower()


def test_t2_r4_03_task_due_date_in_past(task_service: TaskService):
    """T2-R4-03: Task created with past due date is recorded and immediately classified as overdue."""
    user = "usr_test_default"
    past_due = "2020-01-01T12:00:00Z"

    task = task_service.create_task(
        user_id=user,
        title="File historical tax return",
        due_date=past_due,
    )

    assert task is not None
    overdue_tasks = task_service.get_overdue_tasks(user)
    assert len(overdue_tasks) >= 1
    overdue_ids = [t["task_id"] for t in overdue_tasks]
    assert task["task_id"] in overdue_ids


def test_t2_r4_04_outing_research_zero_results_fallback(search_service: SearchService):
    """T2-R4-04: Outing search for impossible query returns empty list without unhandled exception."""
    user = "usr_test_default"
    results = search_service.search_outings(
        user_id=user,
        query="Antarctic Penguin Fine Dining in Sahara Desert",
        location="Sahara",
    )

    assert isinstance(results, list)
    assert len(results) == 0


def test_t2_r4_05_massive_task_title_length_truncated(task_service: TaskService):
    """T2-R4-05: Task title exceeding 255 characters is cleanly truncated without database error."""
    user = "usr_test_default"
    huge_title = "Important Task: " + ("Z" * 1000)

    task = task_service.create_task(user_id=user, title=huge_title)
    assert task is not None
    assert len(task["title"]) <= 255
    assert task["title"].startswith("Important Task:")


def test_t2_r4_06_all_day_vs_timed_event_conflict(calendar_service: CalendarService):
    """T2-R4-06: Existing all-day event triggers collision notice when booking timed event on same date."""
    user = "usr_test_default"
    # Create all-day event
    calendar_service.create_event(
        user_id=user,
        title="Annual Company Retreat",
        start_time="2026-11-15T00:00:00Z",
        end_time="2026-11-15T23:59:59Z",
    )

    # Candidate 2-hour meeting on that day
    conflicts = calendar_service.check_conflicts(
        user_id=user,
        start_time="2026-11-15T14:00:00Z",
        end_time="2026-11-15T16:00:00Z",
    )

    assert len(conflicts) >= 1
    conflict_titles = [c.get("summary") or c.get("title") for c in conflicts]
    assert "Annual Company Retreat" in conflict_titles
