"""Calendar repository providing local event persistence and interval conflict queries."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union


@dataclass
class CalendarEventRecord:
    """Typed domain entity for calendar events."""

    event_id: str
    user_id: str
    summary: str
    start_time: datetime
    end_time: datetime
    location: str = ""
    description: str = ""
    external_calendar_id: Optional[str] = None
    is_all_day: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def title(self) -> str:
        """Alias for summary."""
        return self.summary

    def to_dict(self) -> Dict[str, Any]:
        """Convert event record to dictionary representation."""
        return {
            "event_id": self.event_id,
            "id": self.event_id,
            "user_id": self.user_id,
            "summary": self.summary,
            "title": self.summary,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "location": self.location,
            "description": self.description,
            "external_calendar_id": self.external_calendar_id,
            "is_all_day": self.is_all_day,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else str(self.created_at),
        }


class CalendarRepository:
    """Repository managing calendar event storage in SQLite."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        conn: Optional[sqlite3.Connection] = None,
    ) -> None:
        self._custom_db_path = db_path
        self._injected_conn = conn
        self._ensure_table()

    def _get_connection(self) -> sqlite3.Connection:
        """Resolve database connection."""
        if self._injected_conn is not None:
            return self._injected_conn

        try:
            from app.database.connection import create_connection, get_db_path
            resolved = get_db_path(self._custom_db_path)
            return create_connection(resolved)
        except ImportError:
            c = sqlite3.connect(
                self._custom_db_path or ":memory:",
                timeout=30.0,
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
                check_same_thread=False,
            )
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA foreign_keys = ON;")
            return c

    def _ensure_table(self) -> None:
        """Ensure calendar_events table exists."""
        conn = self._get_connection()
        should_close = self._injected_conn is None
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS calendar_events (
                    event_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    external_calendar_id TEXT,
                    summary TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    location TEXT DEFAULT '',
                    start_time TIMESTAMP NOT NULL,
                    end_time TIMESTAMP NOT NULL,
                    is_all_day BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_calendar_user_times ON calendar_events(user_id, start_time, end_time);"
            )
            conn.commit()
        finally:
            if should_close:
                conn.close()

    def _normalize_dt(self, val: Any) -> datetime:
        """Normalize input to UTC datetime."""
        if isinstance(val, datetime):
            return val.astimezone(timezone.utc) if val.tzinfo is not None else val.replace(tzinfo=timezone.utc)
        if isinstance(val, (int, float)):
            return datetime.fromtimestamp(val, tz=timezone.utc)
        if isinstance(val, str):
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            return dt.astimezone(timezone.utc) if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
        raise ValueError(f"Cannot parse datetime from: {val}")

    def _row_to_record(self, row: sqlite3.Row) -> CalendarEventRecord:
        """Map row to CalendarEventRecord."""
        start_time = self._normalize_dt(row["start_time"])
        end_time = self._normalize_dt(row["end_time"])
        created_at = self._normalize_dt(row["created_at"]) if row["created_at"] else datetime.now(timezone.utc)

        return CalendarEventRecord(
            event_id=row["event_id"],
            user_id=row["user_id"],
            summary=row["summary"],
            start_time=start_time,
            end_time=end_time,
            location=row["location"] or "",
            description=row["description"] or "",
            external_calendar_id=row["external_calendar_id"],
            is_all_day=bool(row["is_all_day"]),
            created_at=created_at,
        )

    def create(
        self,
        user_id: str,
        summary: str,
        start_time: Union[str, datetime],
        end_time: Union[str, datetime],
        location: str = "",
        description: str = "",
        external_calendar_id: Optional[str] = None,
        is_all_day: bool = False,
        event_id: Optional[str] = None,
    ) -> CalendarEventRecord:
        """Create a new event in the repository."""
        s = self._normalize_dt(start_time)
        e = self._normalize_dt(end_time)

        if e <= s:
            raise ValueError("Event end time cannot be before or equal to start time.")

        eid = event_id or f"evt_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        conn = self._get_connection()
        should_close = self._injected_conn is None
        try:
            conn.execute(
                """
                INSERT INTO calendar_events (
                    event_id, user_id, external_calendar_id, summary,
                    description, location, start_time, end_time, is_all_day, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    eid,
                    user_id,
                    external_calendar_id,
                    summary.strip(),
                    description.strip() if description else "",
                    location.strip() if location else "",
                    s.isoformat(),
                    e.isoformat(),
                    1 if is_all_day else 0,
                    now.isoformat(),
                ),
            )
            conn.commit()
        finally:
            if should_close:
                conn.close()

        return CalendarEventRecord(
            event_id=eid,
            user_id=user_id,
            summary=summary.strip(),
            start_time=s,
            end_time=e,
            location=location.strip() if location else "",
            description=description.strip() if description else "",
            external_calendar_id=external_calendar_id,
            is_all_day=is_all_day,
            created_at=now,
        )

    def get_by_id(self, event_id: str, user_id: Optional[str] = None) -> Optional[CalendarEventRecord]:
        """Fetch event by ID."""
        conn = self._get_connection()
        should_close = self._injected_conn is None
        try:
            if user_id:
                cur = conn.execute(
                    "SELECT * FROM calendar_events WHERE event_id = ? AND user_id = ?;",
                    (event_id, user_id),
                )
            else:
                cur = conn.execute("SELECT * FROM calendar_events WHERE event_id = ?;", (event_id,))
            row = cur.fetchone()
            return self._row_to_record(row) if row else None
        finally:
            if should_close:
                conn.close()

    def list_events(
        self,
        user_id: str,
        start_time: Optional[Union[str, datetime]] = None,
        end_time: Optional[Union[str, datetime]] = None,
    ) -> List[CalendarEventRecord]:
        """List events in chronological order, optionally within a time window."""
        conn = self._get_connection()
        should_close = self._injected_conn is None
        try:
            cur = conn.execute(
                "SELECT * FROM calendar_events WHERE user_id = ? ORDER BY start_time ASC;",
                (user_id,),
            )
            rows = cur.fetchall()
            events = [self._row_to_record(r) for r in rows]
            events.sort(key=lambda x: x.start_time)

            t_min = self._normalize_dt(start_time) if start_time else None
            t_max = self._normalize_dt(end_time) if end_time else None

            if t_min or t_max:
                filtered = []
                for ev in events:
                    if t_min and ev.end_time <= t_min:
                        continue
                    if t_max and ev.start_time >= t_max:
                        continue
                    filtered.append(ev)
                return filtered

            return events
        finally:
            if should_close:
                conn.close()

    def find_conflicts(
        self,
        user_id: str,
        start_time: Union[str, datetime],
        end_time: Union[str, datetime],
        exclude_event_id: Optional[str] = None,
    ) -> List[CalendarEventRecord]:
        """Strict interval conflict check: max(start1, start2) < min(end1, end2)."""
        s = self._normalize_dt(start_time)
        e = self._normalize_dt(end_time)

        if e <= s:
            raise ValueError("Event end time cannot be before or equal to start time.")

        all_events = self.list_events(user_id=user_id)
        conflicts = []
        for ev in all_events:
            if exclude_event_id and ev.event_id == exclude_event_id:
                continue

            # Strict interval overlap rule
            if max(s, ev.start_time) < min(e, ev.end_time):
                conflicts.append(ev)

        return conflicts

    def delete(self, event_id: str, user_id: Optional[str] = None) -> bool:
        """Delete event by ID."""
        conn = self._get_connection()
        should_close = self._injected_conn is None
        try:
            if user_id:
                cur = conn.execute(
                    "DELETE FROM calendar_events WHERE event_id = ? AND user_id = ?;",
                    (event_id, user_id),
                )
            else:
                cur = conn.execute("DELETE FROM calendar_events WHERE event_id = ?;", (event_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            if should_close:
                conn.close()
