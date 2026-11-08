"""Task repository providing typed CRUD, status transitions, and reminder scheduling."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

PRIORITY_RANKS = {
    "urgent": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}

VALID_STATUSES = {"pending", "in_progress", "completed", "cancelled"}
VALID_PRIORITIES = {"urgent", "high", "medium", "low"}


@dataclass
class Task:
    """Typed domain entity for user to-do tasks and reminders."""

    task_id: str
    user_id: str
    title: str
    description: str = ""
    priority: str = "medium"
    due_date: Optional[datetime] = None
    status: str = "pending"
    category: str = "general"
    is_completed: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert task to dictionary representation."""
        return {
            "task_id": self.task_id,
            "id": self.task_id,  # convenience alias
            "user_id": self.user_id,
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "status": self.status,
            "category": self.category,
            "is_completed": self.is_completed,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else str(self.created_at),
            "completed_at": self.completed_at.isoformat() if isinstance(self.completed_at, datetime) else (str(self.completed_at) if self.completed_at else None),
        }


class TaskRepository:
    """Repository for managing task persistence and state in SQLite."""

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
            # Standalone fallback
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
        """Ensure tasks table and required columns exist."""
        conn = self._get_connection()
        should_close = self._injected_conn is None
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    telegram_chat_id TEXT UNIQUE,
                    full_name TEXT,
                    timezone TEXT DEFAULT 'UTC',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    priority TEXT NOT NULL DEFAULT 'medium',
                    due_date TIMESTAMP,
                    is_completed BOOLEAN NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    category TEXT NOT NULL DEFAULT 'general',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_user_status ON tasks(user_id, status, is_completed, due_date);"
            )

            # Check for existing table that might lack status or category columns
            cursor = conn.execute("PRAGMA table_info(tasks);")
            columns = {row["name"] for row in cursor.fetchall()}
            if "status" not in columns:
                try:
                    conn.execute("ALTER TABLE tasks ADD COLUMN status TEXT NOT NULL DEFAULT 'pending';")
                except sqlite3.OperationalError:
                    pass
            if "category" not in columns:
                try:
                    conn.execute("ALTER TABLE tasks ADD COLUMN category TEXT NOT NULL DEFAULT 'general';")
                except sqlite3.OperationalError:
                    pass
            conn.commit()
        finally:
            if should_close:
                conn.close()

    def _parse_datetime(self, val: Any) -> Optional[datetime]:
        """Safely parse datetime from timestamp or ISO string."""
        if val is None:
            return None
        if isinstance(val, datetime):
            return val if val.tzinfo is not None else val.replace(tzinfo=timezone.utc)
        if isinstance(val, (int, float)):
            return datetime.fromtimestamp(val, tz=timezone.utc)
        if isinstance(val, str):
            val_clean = val.strip()
            if not val_clean:
                return None
            try:
                dt = datetime.fromisoformat(val_clean.replace("Z", "+00:00"))
                return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
            except ValueError:
                # Try common formats
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                    try:
                        return datetime.strptime(val_clean, fmt).replace(tzinfo=timezone.utc)
                    except ValueError:
                        pass
        return None

    def _row_to_task(self, row: sqlite3.Row) -> Task:
        """Map database row to Task model."""
        created_at = self._parse_datetime(row["created_at"]) or datetime.now(timezone.utc)
        completed_at = self._parse_datetime(row["completed_at"])
        due_date = self._parse_datetime(row["due_date"])
        status = row["status"] if "status" in row.keys() and row["status"] else ("completed" if row["is_completed"] else "pending")
        category = row["category"] if "category" in row.keys() and row["category"] else "general"

        return Task(
            task_id=row["task_id"],
            user_id=row["user_id"],
            title=row["title"],
            description=row["description"] or "",
            priority=row["priority"] or "medium",
            due_date=due_date,
            status=status,
            category=category,
            is_completed=bool(row["is_completed"] or status == "completed"),
            created_at=created_at,
            completed_at=completed_at,
        )

    def create(
        self,
        user_id: str,
        title: str,
        due_date: Optional[Union[str, datetime]] = None,
        priority: str = "medium",
        description: str = "",
        category: str = "general",
        task_id: Optional[str] = None,
    ) -> Task:
        """Create a new task with input validation and title truncation."""
        if not title or not title.strip():
            raise ValueError("Task title cannot be empty.")

        title_clean = title.strip()
        # Truncate title cleanly to 255 characters with ellipsis if oversized (T2-R4-05)
        if len(title_clean) > 255:
            title_clean = title_clean[:252] + "..."

        p_norm = priority.lower().strip() if priority else "medium"
        if p_norm not in VALID_PRIORITIES:
            p_norm = "medium"

        dt = self._parse_datetime(due_date)
        tid = task_id or f"task_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        conn = self._get_connection()
        should_close = self._injected_conn is None
        try:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO users (user_id, full_name) VALUES (?, ?);",
                    (user_id, user_id),
                )
            except sqlite3.OperationalError:
                pass
            conn.execute(
                """
                INSERT INTO tasks (
                    task_id, user_id, title, description, priority,
                    due_date, is_completed, status, category, created_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, 'pending', ?, ?, NULL);
                """,
                (
                    tid,
                    user_id,
                    title_clean,
                    description.strip() if description else "",
                    p_norm,
                    dt.isoformat() if dt else None,
                    category.strip() if category else "general",
                    now.isoformat(),
                ),
            )
            conn.commit()
        finally:
            if should_close:
                conn.close()

        return Task(
            task_id=tid,
            user_id=user_id,
            title=title_clean,
            description=description.strip() if description else "",
            priority=p_norm,
            due_date=dt,
            status="pending",
            category=category.strip() if category else "general",
            is_completed=False,
            created_at=now,
            completed_at=None,
        )

    def get_by_id(self, task_id: str, user_id: Optional[str] = None) -> Optional[Task]:
        """Fetch task by ID, optionally scoped to a user."""
        conn = self._get_connection()
        should_close = self._injected_conn is None
        try:
            if user_id:
                cur = conn.execute(
                    "SELECT * FROM tasks WHERE task_id = ? AND user_id = ?;",
                    (task_id, user_id),
                )
            else:
                cur = conn.execute("SELECT * FROM tasks WHERE task_id = ?;", (task_id,))
            row = cur.fetchone()
            return self._row_to_task(row) if row else None
        finally:
            if should_close:
                conn.close()

    def list_tasks(
        self,
        user_id: str,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[Task]:
        """List tasks for a user, filtered by status/priority and sorted."""
        conn = self._get_connection()
        should_close = self._injected_conn is None
        try:
            query = "SELECT * FROM tasks WHERE user_id = ?"
            params: List[Any] = [user_id]

            if status:
                s_norm = status.lower().strip()
                if s_norm in {"completed", "done"}:
                    query += " AND (status = 'completed' OR is_completed = 1)"
                elif s_norm in {"pending", "open", "todo"}:
                    query += " AND (status = 'pending' AND is_completed = 0)"
                else:
                    query += " AND status = ?"
                    params.append(s_norm)

            if priority:
                query += " AND priority = ?"
                params.append(priority.lower().strip())

            if category:
                query += " AND category = ?"
                params.append(category.strip())

            cur = conn.execute(query, params)
            rows = cur.fetchall()
            tasks = [self._row_to_task(r) for r in rows]

            # Sort priority (urgent=0, high=1, medium=2, low=3), then due date
            def sort_key(t: Task):
                p_rank = PRIORITY_RANKS.get(t.priority.lower(), 2)
                due_ts = t.due_date.timestamp() if t.due_date else float("inf")
                return (p_rank, due_ts, t.created_at.timestamp())

            tasks.sort(key=sort_key)
            return tasks
        finally:
            if should_close:
                conn.close()

    def update_status(
        self,
        task_id: str,
        status: str,
        user_id: Optional[str] = None,
    ) -> Optional[Task]:
        """Transition task status (pending -> in_progress -> completed -> cancelled)."""
        s_norm = status.lower().strip()
        if s_norm not in VALID_STATUSES:
            raise ValueError(f"Invalid task status '{status}'. Must be one of {VALID_STATUSES}")

        is_completed = 1 if s_norm == "completed" else 0
        completed_at = datetime.now(timezone.utc).isoformat() if s_norm == "completed" else None

        conn = self._get_connection()
        should_close = self._injected_conn is None
        try:
            if user_id:
                cur = conn.execute(
                    """
                    UPDATE tasks
                    SET status = ?, is_completed = ?, completed_at = ?
                    WHERE task_id = ? AND user_id = ?;
                    """,
                    (s_norm, is_completed, completed_at, task_id, user_id),
                )
            else:
                cur = conn.execute(
                    """
                    UPDATE tasks
                    SET status = ?, is_completed = ?, completed_at = ?
                    WHERE task_id = ?;
                    """,
                    (s_norm, is_completed, completed_at, task_id),
                )
            conn.commit()
            if cur.rowcount == 0:
                return None
            return self.get_by_id(task_id, user_id=user_id)
        finally:
            if should_close:
                conn.close()

    def update(
        self,
        task_id: str,
        updates: Dict[str, Any],
        user_id: Optional[str] = None,
    ) -> Optional[Task]:
        """Update arbitrary task fields."""
        task = self.get_by_id(task_id, user_id=user_id)
        if not task:
            return None

        fields: List[str] = []
        values: List[Any] = []

        if "title" in updates:
            t = updates["title"]
            if not t or not str(t).strip():
                raise ValueError("Task title cannot be empty.")
            t_clean = str(t).strip()
            if len(t_clean) > 255:
                t_clean = t_clean[:252] + "..."
            fields.append("title = ?")
            values.append(t_clean)

        if "description" in updates:
            fields.append("description = ?")
            values.append(str(updates["description"]).strip())

        if "priority" in updates:
            p = str(updates["priority"]).lower().strip()
            if p in VALID_PRIORITIES:
                fields.append("priority = ?")
                values.append(p)

        if "due_date" in updates:
            dt = self._parse_datetime(updates["due_date"])
            fields.append("due_date = ?")
            values.append(dt.isoformat() if dt else None)

        if "status" in updates:
            st = str(updates["status"]).lower().strip()
            if st in VALID_STATUSES:
                fields.append("status = ?")
                values.append(st)
                fields.append("is_completed = ?")
                values.append(1 if st == "completed" else 0)
                if st == "completed":
                    fields.append("completed_at = ?")
                    values.append(datetime.now(timezone.utc).isoformat())
                else:
                    fields.append("completed_at = NULL")

        if not fields:
            return task

        conn = self._get_connection()
        should_close = self._injected_conn is None
        try:
            sql = f"UPDATE tasks SET {', '.join(fields)} WHERE task_id = ?"
            values.append(task_id)
            if user_id:
                sql += " AND user_id = ?"
                values.append(user_id)

            conn.execute(sql, values)
            conn.commit()
            return self.get_by_id(task_id, user_id=user_id)
        finally:
            if should_close:
                conn.close()

    def delete(self, task_id: str, user_id: Optional[str] = None) -> bool:
        """Delete task by ID."""
        conn = self._get_connection()
        should_close = self._injected_conn is None
        try:
            if user_id:
                cur = conn.execute(
                    "DELETE FROM tasks WHERE task_id = ? AND user_id = ?;",
                    (task_id, user_id),
                )
            else:
                cur = conn.execute("DELETE FROM tasks WHERE task_id = ?;", (task_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            if should_close:
                conn.close()

    def get_upcoming_reminders(
        self,
        user_id: str,
        window_minutes: int = 60,
        current_time: Optional[datetime] = None,
    ) -> List[Task]:
        """Fetch pending tasks due within the upcoming time window."""
        now = self._parse_datetime(current_time) or datetime.now(timezone.utc)
        window_end = datetime.fromtimestamp(now.timestamp() + (window_minutes * 60), tz=timezone.utc)

        all_pending = self.list_tasks(user_id=user_id, status="pending")
        upcoming = []
        for t in all_pending:
            if t.due_date and now <= t.due_date <= window_end:
                upcoming.append(t)
        return upcoming

    def get_overdue_tasks(
        self,
        user_id: str,
        current_time: Optional[datetime] = None,
    ) -> List[Task]:
        """Fetch pending tasks whose due date has passed."""
        now = self._parse_datetime(current_time) or datetime.now(timezone.utc)
        all_pending = self.list_tasks(user_id=user_id, status="pending")
        overdue = []
        for t in all_pending:
            if t.due_date and t.due_date < now:
                overdue.append(t)
        return overdue
