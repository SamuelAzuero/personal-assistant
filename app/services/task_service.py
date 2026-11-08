"""Task and daily to-do management service with priority tagging and reminder scheduling."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from app.database.repositories.task_repo import Task, TaskRepository


class TaskService:
    """Service providing task lifecycle management and reminder scheduling."""

    def __init__(self, repository: Optional[TaskRepository] = None) -> None:
        self.repository = repository or TaskRepository()

    def create_task(
        self,
        user_id: str,
        title: str,
        due_date: Optional[Union[str, datetime]] = None,
        priority: str = "medium",
        description: str = "",
        category: str = "general",
    ) -> Dict[str, Any]:
        """Create a new daily task with priority and optional due date."""
        task = self.repository.create(
            user_id=user_id,
            title=title,
            due_date=due_date,
            priority=priority,
            description=description,
            category=category,
        )
        return task.to_dict()

    def list_tasks(
        self,
        user_id: str,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List tasks for a user, sorted by priority (urgent first) and due date."""
        tasks = self.repository.list_tasks(
            user_id=user_id,
            status=status,
            priority=priority,
            category=category,
        )
        return [t.to_dict() for t in tasks]

    def get_task(self, task_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Retrieve task by ID."""
        task = self.repository.get_by_id(task_id, user_id=user_id)
        return task.to_dict() if task else None

    def update_status(
        self,
        task_id: str,
        status: str,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update task status (pending -> in_progress -> completed -> cancelled)."""
        updated = self.repository.update_status(task_id=task_id, status=status, user_id=user_id)
        if not updated:
            raise KeyError(f"Task with id '{task_id}' not found.")
        return updated.to_dict()

    def update_task(
        self,
        task_id: str,
        updates: Dict[str, Any],
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update arbitrary task fields."""
        updated = self.repository.update(task_id=task_id, updates=updates, user_id=user_id)
        if not updated:
            raise KeyError(f"Task with id '{task_id}' not found.")
        return updated.to_dict()

    def delete_task(self, task_id: str, user_id: Optional[str] = None) -> bool:
        """Delete task by ID."""
        return self.repository.delete(task_id=task_id, user_id=user_id)

    def get_upcoming_reminders(
        self,
        user_id: str,
        window_minutes: int = 60,
        current_time: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Get pending tasks due within the upcoming time window."""
        tasks = self.repository.get_upcoming_reminders(
            user_id=user_id,
            window_minutes=window_minutes,
            current_time=current_time,
        )
        return [t.to_dict() for t in tasks]

    def get_overdue_tasks(
        self,
        user_id: str,
        current_time: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Get pending tasks that are overdue."""
        tasks = self.repository.get_overdue_tasks(
            user_id=user_id,
            current_time=current_time,
        )
        return [t.to_dict() for t in tasks]

    def complete_task_by_query(self, user_id: str, query: str) -> Optional[Dict[str, Any]]:
        """Find a task by ID, index, or title match and mark it completed."""
        clean_q = query.strip().lower()
        if not clean_q:
            return None

        # 1. Direct ID match
        direct = self.get_task(clean_q, user_id=user_id)
        if direct:
            return self.update_status(direct["task_id"], status="completed", user_id=user_id)

        tasks = self.list_tasks(user_id=user_id, status="pending")
        if not tasks:
            tasks = self.list_tasks(user_id=user_id)

        # 2. Number index match (e.g. "1", "#2")
        num_clean = clean_q.lstrip("#").strip()
        if num_clean.isdigit():
            idx = int(num_clean) - 1
            if 0 <= idx < len(tasks):
                target = tasks[idx]
                return self.update_status(target["task_id"], status="completed", user_id=user_id)

        # 3. Substring match on title
        for t in tasks:
            t_title = t.get("title", "").lower()
            if clean_q in t_title or t_title in clean_q:
                return self.update_status(t["task_id"], status="completed", user_id=user_id)

        return None

    def delete_task_by_query(self, user_id: str, query: str) -> Optional[Dict[str, Any]]:
        """Find a task by ID, index, or title match and delete it."""
        clean_q = query.strip().lower()
        if not clean_q:
            return None

        # 1. Direct ID match
        direct = self.get_task(clean_q, user_id=user_id)
        if direct:
            self.delete_task(direct["task_id"], user_id=user_id)
            return direct

        tasks = self.list_tasks(user_id=user_id, status="pending")
        if not tasks:
            tasks = self.list_tasks(user_id=user_id)

        # 2. Number index match
        num_clean = clean_q.lstrip("#").strip()
        if num_clean.isdigit():
            idx = int(num_clean) - 1
            if 0 <= idx < len(tasks):
                target = tasks[idx]
                self.delete_task(target["task_id"], user_id=user_id)
                return target

        # 3. Substring match on title
        for t in tasks:
            t_title = t.get("title", "").lower()
            if clean_q in t_title or t_title in clean_q:
                self.delete_task(t["task_id"], user_id=user_id)
                return t

        return None
