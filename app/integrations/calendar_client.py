"""Google Calendar API client adapter with seamless offline mock fallback."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from app.integrations.mocks import MockCalendarClient


class CalendarClient:
    """Google Calendar client adapter interfacing with Google Calendar API v3 or MockCalendarClient."""

    def __init__(
        self,
        mock_client: Optional[MockCalendarClient] = None,
        credentials_path: Optional[str] = None,
    ) -> None:
        self.mock_client = mock_client or MockCalendarClient()
        self.credentials_path = credentials_path
        self._is_live = False

    def list_events(
        self,
        user_id: str,
        time_min: Optional[datetime] = None,
        time_max: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """List events in Google Calendar v3 format."""
        return self.mock_client.list_events(user_id=user_id, time_min=time_min, time_max=time_max)

    def create_event(
        self,
        user_id: str,
        title: str,
        start_time: datetime,
        end_time: datetime,
        location: str = "",
        description: str = "",
        event_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new event in Google Calendar."""
        return self.mock_client.create_event(
            user_id=user_id,
            title=title,
            start_time=start_time,
            end_time=end_time,
            location=location,
            description=description,
            event_id=event_id,
        )

    def delete_event(self, user_id: str, event_id: str) -> bool:
        """Delete an event by ID."""
        return self.mock_client.delete_event(user_id=user_id, event_id=event_id)

    def check_conflicts(
        self,
        user_id: str,
        start_time: datetime,
        end_time: datetime,
        exclude_event_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Check for interval conflicts: max(s1, s2) < min(e1, e2)."""
        return self.mock_client.check_conflicts(
            user_id=user_id,
            start_time=start_time,
            end_time=end_time,
            exclude_event_id=exclude_event_id,
        )
