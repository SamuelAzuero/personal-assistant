"""FastAPI application entry point for the Autonomous Personal Assistant.

Assembles lifespan context, database schema initialization, static dashboard
file mounting, API routers (webhook, finance, tasks), and health check probes.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api.finance_router import router as finance_router
from app.api.task_router import router as task_router
from app.api.webhook import webhook_router
from app.config import Settings, get_settings
from app.database.connection import get_db_connection, init_db
from app.integrations.telegram_client import TelegramClient
from app.services.calendar_service import CalendarService
from app.services.email_service import EmailService
from app.services.search_service import SearchService

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager: ensures data directory and initializes database schema."""
    settings = get_settings()
    db_path = settings.database_path

    # Ensure parent directory exists for file-based SQLite database
    if db_path != ":memory:" and not db_path.startswith("file:"):
        db_file = Path(db_path)
        if not db_file.parent.exists():
            db_file.parent.mkdir(parents=True, exist_ok=True)

    # Initialize SQLite database schema
    init_db(db_path=db_path)

    # Initialize live Telegram client on app.state for outbound message dispatch if not already provided
    if getattr(app.state, "telegram", None) is None:
        token = settings.telegram_bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
        secret = (
            settings.telegram_secret_token
            or os.environ.get("TELEGRAM_SECRET_TOKEN")
            or os.environ.get("TELEGRAM_WEBHOOK_SECRET")
            or ""
        )
        is_mock = getattr(settings, "mock_telegram", False)
        if not token:
            is_mock = True
        app.state.telegram = TelegramClient(
            bot_token=token,
            secret_token=secret,
            mock_mode=is_mock,
        )

    yield


app = FastAPI(
    title="Personal Assistant API",
    description="Autonomous cloud-based personal assistant with Telegram webhook and web dashboard.",
    version="1.0.0",
    lifespan=lifespan,
)

# Enable CORS for local development and web dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API Routers
app.include_router(webhook_router)
app.include_router(finance_router)
app.include_router(task_router)


# Health & Readiness Probes
@app.get("/health", tags=["Health"])
@app.get("/healthz", tags=["Health"])
def health_check() -> Dict[str, str]:
    """Liveness probe reporting service status and version."""
    return {
        "status": "healthy",
        "service": "personal-assistant",
        "version": "1.0.0",
    }


@app.get("/ready", tags=["Health"])
def readiness_check(settings: Settings = Depends(get_settings)) -> Dict[str, str]:
    """Readiness probe verifying database connectivity."""
    try:
        with get_db_connection(settings.database_path) as conn:
            cursor = conn.execute("SELECT 1;")
            cursor.fetchone()
        return {"status": "ready"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database not ready: {str(e)}",
        )


# Dashboard Widget Endpoints
@app.get("/api/email/digest", tags=["Dashboard Widgets"])
@app.get("/api/emails/digest", tags=["Dashboard Widgets"])
def get_email_digest(request: Request, user_id: str = "default_user") -> Dict[str, Any]:
    """Return executive email digest for the web dashboard."""
    app_gmail = getattr(request.app.state, "gmail", None)
    if app_gmail is not None and hasattr(app_gmail, "generate_digest"):
        return app_gmail.generate_digest(user_id=user_id)
    service = EmailService()
    return service.generate_digest(user_id=user_id)


@app.get("/api/research/outings", tags=["Dashboard Widgets"])
def get_outing_recommendations(
    request: Request,
    user_id: str = "default_user",
    query: str = "dinner and leisure",
    location: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return curated outing recommendations for the web dashboard."""
    app_search = getattr(request.app.state, "search", None)
    if app_search is not None and hasattr(app_search, "search_outings"):
        return app_search.search_outings(user_id=user_id, query=query, location=location)
    service = SearchService()
    return service.search_outings(user_id=user_id, query=query, location=location)


@app.get("/api/calendar/events", tags=["Dashboard Widgets"])
def get_calendar_events(
    request: Request,
    user_id: str = "default_user",
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return calendar events for the web dashboard."""
    start_dt = (
        datetime.fromisoformat(time_min.replace("Z", "+00:00"))
        if time_min
        else datetime(2026, 1, 1, tzinfo=timezone.utc)
    )
    end_dt = (
        datetime.fromisoformat(time_max.replace("Z", "+00:00"))
        if time_max
        else datetime(2026, 12, 31, tzinfo=timezone.utc)
    )
    app_cal = getattr(request.app.state, "calendar", None)
    if app_cal is not None and hasattr(app_cal, "list_events"):
        return app_cal.list_events(user_id, start_dt, end_dt)
    service = CalendarService()
    return service.list_events(user_id, start_dt, end_dt)


# Static Files Mount & Dashboard SPA Entrypoint
if not STATIC_DIR.exists():
    STATIC_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", tags=["Dashboard"])
def serve_dashboard():
    """Serve the single-page application dashboard index.html."""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file), media_type="text/html")
    return HTMLResponse("<h1>Personal Assistant</h1>", status_code=200)
