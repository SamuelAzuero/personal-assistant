"""Calendar scheduling, event management, and interval conflict detection engine."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
from app.database.repositories.calendar_repo import CalendarRepository
from app.integrations.calendar_client import CalendarClient


class CalendarService:
    """Service managing calendar events and interval scheduling conflicts."""

    def __init__(
        self,
        client: Optional[CalendarClient] = None,
        repository: Optional[CalendarRepository] = None,
    ) -> None:
        self.client = client or CalendarClient()
        self.repository = repository or CalendarRepository()

    def _normalize_dt(self, val: Any) -> datetime:
        """Convert input to UTC datetime."""
        if isinstance(val, datetime):
            return val if val.tzinfo is not None else val.replace(tzinfo=timezone.utc)
        if isinstance(val, (int, float)):
            return datetime.fromtimestamp(val, tz=timezone.utc)
        if isinstance(val, str):
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
        raise ValueError(f"Cannot parse datetime from: {val}")

    def list_events(
        self,
        user_id: str,
        start_time: Union[str, datetime],
        end_time: Union[str, datetime],
    ) -> List[Dict[str, Any]]:
        """List events in chronological order within a time window."""
        s = self._normalize_dt(start_time)
        e = self._normalize_dt(end_time)

        # Retrieve from client and/or repository
        client_events = self.client.list_events(user_id=user_id, time_min=s, time_max=e)
        return client_events

    def check_conflicts(
        self,
        user_id: str,
        start_time: Union[str, datetime],
        end_time: Union[str, datetime],
        exclude_event_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Strict interval conflict detection: max(start1, start2) < min(end1, end2)."""
        s = self._normalize_dt(start_time)
        e = self._normalize_dt(end_time)

        if e <= s:
            raise ValueError("Event end time cannot be before or equal to start time.")

        return self.client.check_conflicts(
            user_id=user_id,
            start_time=s,
            end_time=e,
            exclude_event_id=exclude_event_id,
        )

    def create_event(
        self,
        user_id: str,
        title: str,
        start_time: Union[str, datetime],
        end_time: Union[str, datetime],
        location: str = "",
        description: str = "",
        ignore_conflicts: bool = False,
    ) -> Dict[str, Any]:
        """Create a new event, checking for interval conflicts first."""
        s = self._normalize_dt(start_time)
        e = self._normalize_dt(end_time)

        if e <= s:
            raise ValueError("Event end time cannot be before or equal to start time.")

        conflicts = self.check_conflicts(user_id=user_id, start_time=s, end_time=e)

        # Create on client
        created = self.client.create_event(
            user_id=user_id,
            title=title,
            start_time=s,
            end_time=e,
            location=location,
            description=description,
        )

        # Mirror in local repository
        try:
            self.repository.create(
                user_id=user_id,
                summary=title,
                start_time=s,
                end_time=e,
                location=location,
                description=description,
                external_calendar_id=created.get("id"),
            )
        except Exception:
            pass

        # Return event with conflict status if any
        created["conflicts"] = conflicts
        created["has_conflict"] = len(conflicts) > 0
        return created

    def delete_event(self, user_id: str, event_id: str) -> bool:
        """Delete an event by ID."""
        client_deleted = self.client.delete_event(user_id=user_id, event_id=event_id)
        repo_deleted = self.repository.delete(event_id=event_id, user_id=user_id)
        return client_deleted or repo_deleted
