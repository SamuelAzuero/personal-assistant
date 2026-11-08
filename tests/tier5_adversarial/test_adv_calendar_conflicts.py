"""Adversarial stress testing for Calendar conflict engine: intervals, contiguous meetings, all-day events, and time zones."""

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import sqlite3
import pytest

from app.database.repositories.calendar_repo import CalendarRepository
from app.integrations.mocks import MockCalendarClient
from app.services.calendar_service import CalendarService
from app.core.router import ToolRouter
from app.integrations.protocols import IntentResult, IntentType


@pytest.fixture
def calendar_env(tmp_path):
    """File-backed SQLite repository and clean MockCalendarClient for calendar testing."""
    db_file = str(tmp_path / "adv_calendar.db")
    repo = CalendarRepository(db_path=db_file)
    client = MockCalendarClient()
    # Clear default events to test clean scenarios
    client.events["usr_cal_test"] = []
    service = CalendarService(client=client, repository=repo)
    return service, repo, client


def test_adv_cal_01_interval_collision_matrix(calendar_env):
    """Stress test: Complete interval collision matrix (exact, interior, enclosing, overlaps, disjoint)."""
    service, repo, client = calendar_env
    user = "usr_cal_test"

    # Base event: 14:00 to 15:00 UTC
    base_start = "2026-11-10T14:00:00Z"
    base_end = "2026-11-10T15:00:00Z"
    service.create_event(user, "Base Meeting", base_start, base_end)

    # 1. Exact match: 14:00 to 15:00 -> CONFLICT
    c_exact = service.check_conflicts(user, "2026-11-10T14:00:00Z", "2026-11-10T15:00:00Z")
    assert len(c_exact) == 1

    # 2. Interior subset: 14:15 to 14:45 -> CONFLICT
    c_interior = service.check_conflicts(user, "2026-11-10T14:15:00Z", "2026-11-10T14:45:00Z")
    assert len(c_interior) == 1

    # 3. Enclosing superset: 13:30 to 15:30 -> CONFLICT
    c_enclosing = service.check_conflicts(user, "2026-11-10T13:30:00Z", "2026-11-10T15:30:00Z")
    assert len(c_enclosing) == 1

    # 4. Left overlap: 13:30 to 14:30 -> CONFLICT
    c_left = service.check_conflicts(user, "2026-11-10T13:30:00Z", "2026-11-10T14:30:00Z")
    assert len(c_left) == 1

    # 5. Right overlap: 14:30 to 15:30 -> CONFLICT
    c_right = service.check_conflicts(user, "2026-11-10T14:30:00Z", "2026-11-10T15:30:00Z")
    assert len(c_right) == 1

    # 6. Contiguous left: 13:00 to 14:00 -> NO CONFLICT (allowed back-to-back)
    c_contig_left = service.check_conflicts(user, "2026-11-10T13:00:00Z", "2026-11-10T14:00:00Z")
    assert len(c_contig_left) == 0

    # 7. Contiguous right: 15:00 to 16:00 -> NO CONFLICT (allowed back-to-back)
    c_contig_right = service.check_conflicts(user, "2026-11-10T15:00:00Z", "2026-11-10T16:00:00Z")
    assert len(c_contig_right) == 0

    # 8. Disjoint before: 11:00 to 12:00 -> NO CONFLICT
    c_disjoint = service.check_conflicts(user, "2026-11-10T11:00:00Z", "2026-11-10T12:00:00Z")
    assert len(c_disjoint) == 0


def test_adv_cal_02_timezone_conversion_conflicts(calendar_env):
    """Stress test: Event conflict detection across non-UTC time zones (JST +09:00, EST -05:00)."""
    service, repo, client = calendar_env
    user = "usr_cal_tz"

    # Base meeting stored in UTC: 14:00 to 15:00 UTC
    service.create_event(user, "UTC Strategy Sync", "2026-11-10T14:00:00Z", "2026-11-10T15:00:00Z")

    # Tokyo time: 23:00 to 24:00 JST (+09:00) is 14:00 to 15:00 UTC -> SHOULD CONFLICT!
    tokyo_start = "2026-11-10T23:00:00+09:00"
    tokyo_end = "2026-11-11T00:00:00+09:00"
    c_tokyo = service.check_conflicts(user, tokyo_start, tokyo_end)
    assert len(c_tokyo) == 1, f"Expected conflict with Tokyo time, got {c_tokyo}"

    # New York time: 09:30 to 10:30 EST (-05:00) is 14:30 to 15:30 UTC -> SHOULD CONFLICT!
    ny_start = "2026-11-10T09:30:00-05:00"
    ny_end = "2026-11-10T10:30:00-05:00"
    c_ny = service.check_conflicts(user, ny_start, ny_end)
    assert len(c_ny) == 1, f"Expected conflict with New York time, got {c_ny}"

    # Non-conflicting New York time: 08:00 to 09:00 EST (-05:00) is 13:00 to 14:00 UTC -> contiguous, NO CONFLICT!
    ny_free_start = "2026-11-10T08:00:00-05:00"
    ny_free_end = "2026-11-10T09:00:00-05:00"
    c_ny_free = service.check_conflicts(user, ny_free_start, ny_free_end)
    assert len(c_ny_free) == 0, f"Expected no conflict for back-to-back New York meeting, got {c_ny_free}"


def test_adv_cal_03_all_day_event_conflict_boundaries(calendar_env):
    """Stress test: All-day event collision detection and multi-day boundaries."""
    service, repo, client = calendar_env
    user = "usr_cal_allday"

    # All day event on 2026-11-12
    service.create_event(
        user,
        "Annual Offsite Retreat",
        start_time="2026-11-12T00:00:00Z",
        end_time="2026-11-12T23:59:59Z",
    )

    # 1. Timed meeting during the day (11:00-12:00) -> CONFLICT
    c_during = service.check_conflicts(user, "2026-11-12T11:00:00Z", "2026-11-12T12:00:00Z")
    assert len(c_during) == 1

    # 2. Meeting on following day (2026-11-13 09:00-10:00) -> NO CONFLICT
    c_next_day = service.check_conflicts(user, "2026-11-13T09:00:00Z", "2026-11-13T10:00:00Z")
    assert len(c_next_day) == 0


def test_adv_cal_04_router_conflict_none_to_none_display_bug(calendar_env):
    """
    CRITICAL EMPIRICAL BUG CHECK:
    In ToolRouter._handle_calendar_schedule (app/core/router.py:209):
    conflict_lines = [
        f"• **{c.get('summary', 'Busy')}** ({c.get('start_time')} to {c.get('end_time')})"
        for c in conflicts
    ]
    Because CalendarClient returns Google Calendar v3 dicts where start is c['start']['dateTime'],
    c.get('start_time') is None, and c.get('end_time') is None!
    The router sends the user:
    '• **Team Sync** (None to None)'!
    """
    service, repo, client = calendar_env
    user = "usr_router_cal_bug"

    # Seed an event
    service.create_event(
        user_id=user,
        title="Existing Strategy Review",
        start_time=datetime(2026, 11, 10, 14, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc),
    )

    router = ToolRouter(calendar_service=service)
    intent = IntentResult(
        intent=IntentType.CALENDAR_SCHEDULE,
        confidence=1.0,
        slots={
            "title": "Overlapping New Meeting",
            "start_time": datetime(2026, 11, 10, 14, 30, tzinfo=timezone.utc),
            "end_time": datetime(2026, 11, 10, 15, 30, tzinfo=timezone.utc),
            "location": "Room A",
        },
        is_complete=True,
        missing_slots=[],
        raw_text="schedule meeting",
    )

    reply = router.dispatch(user, intent)
    print("Router conflict reply:\n", reply)

    # Check if bug is present: "None to None"
    assert "None to None" not in reply, f"BUG CONFIRMED: Conflict details formatted as 'None to None':\n{reply}"
    assert "14:00" in reply or "2:00" in reply, f"Expected actual event time in conflict notice:\n{reply}"


def test_adv_cal_05_repository_chronological_sorting_under_mixed_timezones(calendar_env):
    """
    Stress test: Repository list_events must sort events by actual chronological time,
    even when events are created with different timezone offsets (+09:00, -05:00, +00:00).
    """
    service, repo, client = calendar_env
    user = "usr_repo_tz_sort"

    # Event 1: 14:00 UTC
    repo.create(user, "Event 1 (14:00 UTC)", "2026-11-10T14:00:00+00:00", "2026-11-10T15:00:00+00:00")

    # Event 2: 09:30 EST (-05:00) which is 14:30 UTC (AFTER Event 1)
    # Notice: In string comparison, "2026-11-10T09:30:00-05:00" < "2026-11-10T14:00:00+00:00"
    repo.create(user, "Event 2 (14:30 UTC / 09:30 EST)", "2026-11-10T09:30:00-05:00", "2026-11-10T10:30:00-05:00")

    # Event 3: 23:45 JST (+09:00) which is 14:45 UTC (AFTER Event 2)
    repo.create(user, "Event 3 (14:45 UTC / 23:45 JST)", "2026-11-10T23:45:00+09:00", "2026-11-11T00:45:00+09:00")

    events = repo.list_events(user)
    titles = [e.summary for e in events]
    print("Ordered titles:", titles)

    # True chronological order:
    # 1. Event 1 (14:00 UTC)
    # 2. Event 2 (14:30 UTC)
    # 3. Event 3 (14:45 UTC)
    assert titles == [
        "Event 1 (14:00 UTC)",
        "Event 2 (14:30 UTC / 09:30 EST)",
        "Event 3 (14:45 UTC / 23:45 JST)",
    ], f"BUG: Events sorted lexicographically rather than chronologically:\n{titles}"
