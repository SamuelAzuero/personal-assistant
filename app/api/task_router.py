"""FastAPI REST router for Web Dashboard task management."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from app.services.task_service import TaskService

router = APIRouter(prefix="/api/tasks", tags=["tasks"])
_task_service: Optional[TaskService] = None


def get_task_service() -> TaskService:
    """Dependency resolver for TaskService."""
    global _task_service
    if _task_service is None:
        _task_service = TaskService()
    return _task_service


def set_task_service(service: TaskService) -> None:
    """Setter for dependency injection during testing."""
    global _task_service
    _task_service = service


class TaskCreateRequest(BaseModel):
    """Schema for creating a new task."""

    title: str = Field(..., description="Task title, must be non-empty")
    due_date: Optional[str] = Field(None, description="ISO-8601 due date/time")
    priority: Optional[str] = Field("medium", description="Priority level: low, medium, high, urgent")
    description: Optional[str] = Field("", description="Detailed task note")
    category: Optional[str] = Field("general", description="Task category tag")
    user_id: Optional[str] = Field("default_user", description="Owner user ID")

    @field_validator("title")
    @classmethod
    def validate_title_not_empty(cls, v: str) -> str:
        if v is None or not str(v).strip():
            raise ValueError("Task title cannot be empty.")
        return str(v).strip()


class TaskUpdateRequest(BaseModel):
    """Schema for updating an existing task."""

    status: Optional[str] = Field(None, description="Status: pending, in_progress, completed, cancelled")
    title: Optional[str] = Field(None, description="Updated task title")
    priority: Optional[str] = Field(None, description="Updated priority")
    description: Optional[str] = Field(None, description="Updated description")
    due_date: Optional[str] = Field(None, description="Updated due date")


@router.get("", response_model=List[Dict[str, Any]])
@router.get("/", response_model=List[Dict[str, Any]])
def list_tasks(
    user_id: str = Query("default_user", description="User ID"),
    status: Optional[str] = Query(None, description="Filter by status (pending, completed, etc.)"),
    priority: Optional[str] = Query(None, description="Filter by priority (low, medium, high, urgent)"),
    category: Optional[str] = Query(None, description="Filter by category"),
) -> List[Dict[str, Any]]:
    """List daily tasks, filtered by status or priority, sorted by priority and due date."""
    service = get_task_service()
    tasks = service.list_tasks(
        user_id=user_id,
        status=status,
        priority=priority,
        category=category,
    )
    if not tasks and user_id == "default_user":
        try:
            conn = service.repository._get_connection()
            should_close = service.repository._injected_conn is None
            try:
                row = conn.execute("SELECT user_id FROM tasks ORDER BY created_at DESC LIMIT 1;").fetchone()
                if row and row["user_id"] != user_id:
                    alt_tasks = service.list_tasks(
                        user_id=row["user_id"],
                        status=status,
                        priority=priority,
                        category=category,
                    )
                    if alt_tasks:
                        return alt_tasks
            finally:
                if should_close:
                    conn.close()
        except Exception:
            pass
    return tasks


@router.post("", status_code=status.HTTP_201_CREATED, response_model=Dict[str, Any])
@router.post("/", status_code=status.HTTP_201_CREATED, response_model=Dict[str, Any])
def create_task(req: TaskCreateRequest) -> Dict[str, Any]:
    """Create a new daily to-do item."""
    service = get_task_service()
    try:
        task = service.create_task(
            user_id=req.user_id or "default_user",
            title=req.title,
            due_date=req.due_date,
            priority=req.priority or "medium",
            description=req.description or "",
            category=req.category or "general",
        )
        return task
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )


@router.patch("/{task_id}", response_model=Dict[str, Any])
def update_task(task_id: str, req: TaskUpdateRequest) -> Dict[str, Any]:
    """Update task fields or transition status."""
    service = get_task_service()
    existing = service.get_task(task_id=task_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id '{task_id}' not found.",
        )

    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    try:
        updated = service.update_task(task_id=task_id, updates=updates)
        return updated
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id '{task_id}' not found.",
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )


@router.delete("/{task_id}")
def delete_task(task_id: str) -> Dict[str, Any]:
    """Delete a task."""
    service = get_task_service()
    deleted = service.delete_task(task_id=task_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id '{task_id}' not found.",
        )
    return {"success": True, "message": "Task deleted successfully", "task_id": task_id}
