"""Unit tests for Milestone 4: Dual User Interface & Free-Tier Cloud Packaging (R5).

Verifies:
1. Pydantic Settings configuration loading and overrides.
2. FastAPI application assembly, lifespan lifecycle, and database initialization.
3. Health and readiness check probe endpoints (/health, /healthz, /ready).
4. Static file mounting and web dashboard SPA delivery (index.html, styles.css, app.js, charts.js).
5. REST API routing through the application gateway (finance, tasks, widgets, webhook).
6. Cloud packaging artifacts (Dockerfile multi-stage validation, deploy script,
   Knative manifest, .env.example, requirements).
"""

import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.api.finance_router import set_finance_service
from app.api.task_router import set_task_service
from app.config import Settings, get_settings
from app.database.connection import DatabaseManager, init_db
from app.database.repositories.task_repo import TaskRepository
from app.main import app
from app.services.finance_service import FinanceService
from app.services.task_service import TaskService


@pytest.fixture
def client(tmp_path):
    """Hermetic test client fixture for FastAPI app with isolated SQLite database."""
    test_db_path = str(tmp_path / "test_ui_assistant.db")
    init_db(test_db_path)

    from app.database.connection import set_default_manager
    manager = DatabaseManager(test_db_path)
    set_default_manager(manager)
    with manager.connection() as conn:
        conn.execute("INSERT OR IGNORE INTO users (user_id, full_name) VALUES ('default_user', 'Default User');")
        conn.execute("INSERT OR IGNORE INTO users (user_id, full_name) VALUES ('test_user_ui', 'Test UI User');")
        conn.commit()

    finance_service = FinanceService(db_manager=manager)
    task_repo = TaskRepository(db_path=test_db_path)
    task_service = TaskService(repository=task_repo)

    set_finance_service(finance_service)
    set_task_service(task_service)

    app.state.db = None
    app.state.tool_router = None
    app.dependency_overrides[get_settings] = lambda: Settings(database_path=test_db_path)

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    # Reset services to fresh default managers
    set_default_manager(None)
    set_finance_service(None)
    set_task_service(None)


# ==============================================================================
# 1. Configuration & Settings Loading Tests
# ==============================================================================

def test_config_defaults():
    """Verify default configuration values meet specification."""
    settings = Settings()
    assert settings.app_env == "development"
    assert settings.host == "0.0.0.0"
    assert settings.port == 8080
    assert settings.mock_services is True
    assert settings.database_path == "data/assistant.db"
    assert settings.calendar_id == "primary"
    assert settings.telegram_bot_token is None


def test_config_environment_override(monkeypatch):
    """Verify settings correctly load overrides from environment variables."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PORT", "9090")
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.setenv("DATABASE_PATH", ":memory:")
    monkeypatch.setenv("MOCK_SERVICES", "false")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_bot_token_xyz")
    monkeypatch.setenv("TELEGRAM_SECRET_TOKEN", "secret_123")

    settings = Settings()
    assert settings.app_env == "production"
    assert settings.port == 9090
    assert settings.host == "127.0.0.1"
    assert settings.database_path == ":memory:"
    assert settings.mock_services is False
    assert settings.telegram_bot_token == "test_bot_token_xyz"
    assert settings.effective_telegram_secret == "secret_123"


def test_config_effective_telegram_secret_alias(monkeypatch):
    """Verify fallback to TELEGRAM_WEBHOOK_SECRET when TELEGRAM_SECRET_TOKEN is unset."""
    monkeypatch.delenv("TELEGRAM_SECRET_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "alias_secret_456")

    settings = Settings()
    assert settings.effective_telegram_secret == "alias_secret_456"


# ==============================================================================
# 2. Health & Readiness Probe Endpoint Tests
# ==============================================================================

def test_health_endpoint(client):
    """Verify GET /health returns 200 with service information."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "personal-assistant"
    assert data["version"] == "1.0.0"


def test_healthz_endpoint_alias(client):
    """Verify GET /healthz provides identical liveness status."""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_ready_endpoint_healthy(client):
    """Verify GET /ready returns 200 when database connectivity is verified."""
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_ready_endpoint_failure(monkeypatch, client):
    """Verify GET /ready returns 503 if database check encounters an error."""
    from contextlib import contextmanager

    @contextmanager
    def broken_conn(path=None):
        raise RuntimeError("Simulated database failure")

    monkeypatch.setattr("app.main.get_db_connection", broken_conn)
    response = client.get("/ready")
    assert response.status_code == 503
    assert "Database not ready" in response.json()["detail"]


# ==============================================================================
# 3. Static File Mounting & Web Dashboard Delivery Tests
# ==============================================================================

def test_root_serves_dashboard_index(client):
    """Verify GET / delivers index.html single page application."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    content = response.text
    # Verify core dashboard DOM anchors
    assert "Personal Assistant" in content
    assert "kpi-net-balance" in content
    assert "categoryChart" in content
    assert "trendChart" in content
    assert "transactions-table" in content
    assert "task-list" in content
    assert "transaction-dialog" in content
    assert "task-dialog" in content


def test_static_stylesheet_served(client):
    """Verify styles.css is served with 200 and CSS content."""
    response = client.get("/static/css/styles.css")
    assert response.status_code == 200
    assert "text/css" in response.headers.get("content-type", "")
    assert "--color-primary" in response.text
    assert "dialog:modal" in response.text


def test_static_charts_js_served(client):
    """Verify charts.js is served with 200 and chart rendering functions."""
    response = client.get("/static/js/charts.js")
    assert response.status_code == 200
    assert "renderCategoryChart" in response.text
    assert "renderTrendChart" in response.text


def test_static_app_js_served(client):
    """Verify app.js is served with 200 and application logic."""
    response = client.get("/static/js/app.js")
    assert response.status_code == 200
    assert "loadFinancialSummary" in response.text
    assert "renderTransactionsTable" in response.text


def test_static_404_on_missing_file(client):
    """Verify non-existent static file returns 404."""
    response = client.get("/static/does_not_exist_xyz.txt")
    assert response.status_code == 404


# ==============================================================================
# 4. REST API Gateway Routing Tests
# ==============================================================================

def test_api_finance_summary_routed(client):
    """Verify /api/finance/summary is accessible through application router."""
    response = client.get("/api/finance/summary?user_id=default_user")
    assert response.status_code == 200
    data = response.json()
    assert "net_balance" in data or "total_income" in data


def test_api_finance_transactions_crud(client):
    """Verify recording, listing, and voiding transactions via /api/finance."""
    # 1. Create transaction
    create_payload = {
        "amount": 75.50,
        "type": "expense",
        "category": "Dining",
        "description": "Lunch meeting with client",
        "user_id": "test_user_ui",
    }
    create_res = client.post("/api/finance/transactions", json=create_payload)
    assert create_res.status_code == 201
    tx_data = create_res.json()
    tx_id = tx_data["id"]

    # 2. List transactions
    list_res = client.get("/api/finance/transactions?user_id=test_user_ui")
    assert list_res.status_code == 200
    txs = list_res.json()
    assert any(tx["id"] == tx_id for tx in txs)

    # 3. Void transaction
    del_res = client.delete(f"/api/finance/transactions/{tx_id}?user_id=test_user_ui")
    assert del_res.status_code == 200
    assert del_res.json()["deleted"] is True


def test_api_finance_categories_routed(client):
    """Verify /api/finance/categories endpoint."""
    response = client.get("/api/finance/categories?user_id=default_user")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_api_tasks_crud(client):
    """Verify creating, listing, updating, and deleting tasks via /api/tasks."""
    # 1. Create task
    task_payload = {
        "title": "Cloud Run deployment verification",
        "priority": "high",
        "category": "devops",
        "user_id": "test_user_ui",
    }
    create_res = client.post("/api/tasks", json=task_payload)
    assert create_res.status_code == 201
    task_data = create_res.json()
    task_id = task_data["task_id"]
    assert task_data["priority"] == "high"

    # 2. List tasks
    list_res = client.get("/api/tasks?user_id=test_user_ui")
    assert list_res.status_code == 200
    tasks = list_res.json()
    assert any(t["task_id"] == task_id for t in tasks)

    # 3. Update task
    update_res = client.patch(f"/api/tasks/{task_id}", json={"status": "completed"})
    assert update_res.status_code == 200
    assert update_res.json()["status"] == "completed"

    # 4. Delete task
    del_res = client.delete(f"/api/tasks/{task_id}")
    assert del_res.status_code == 200
    assert del_res.json()["success"] is True


def test_api_dashboard_widgets_endpoints(client):
    """Verify auxiliary dashboard widgets: email digest and outing recommendations."""
    # Email digest
    email_res = client.get("/api/email/digest?user_id=default_user")
    assert email_res.status_code == 200
    digest = email_res.json()
    assert "urgent_count" in digest
    assert "items" in digest

    # Outing recommendations
    outing_res = client.get("/api/research/outings?location=downtown")
    assert outing_res.status_code == 200
    outings = outing_res.json()
    assert isinstance(outings, list)
    assert len(outings) > 0


def test_api_webhook_telegram_routed(client):
    """Verify Telegram webhook endpoint POST /api/webhook/telegram is mounted."""
    payload = {
        "update_id": 999901,
        "message": {
            "message_id": 101,
            "chat": {"id": 123456},
            "from": {"id": 123456, "first_name": "TestUser"},
            "text": "What is my balance?",
        },
    }
    res = client.post("/api/webhook/telegram", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "response" in data


# ==============================================================================
# 5. Cloud Packaging & Artifact Verification Tests
# ==============================================================================

def test_dockerfile_multi_stage_structure():
    """Verify Dockerfile uses multi-stage build, non-root user, and exposes port 8080."""
    dockerfile_path = Path("deploy/Dockerfile")
    assert dockerfile_path.exists(), "deploy/Dockerfile must exist"
    content = dockerfile_path.read_text(encoding="utf-8")

    # Multi-stage checks
    assert "FROM python:3.12-slim AS builder" in content
    assert "FROM python:3.12-slim AS runner" in content
    assert "COPY --from=builder" in content

    # Security: non-root user
    assert "useradd" in content
    assert "USER appuser" in content

    # Cloud Run specifications
    assert "EXPOSE 8080" in content
    assert "PORT=8080" in content
    assert "HEALTHCHECK" in content
    assert "uvicorn" in content


def test_deploy_cloud_run_script_attributes():
    """Verify deploy_cloud_run.sh exists, is executable, and contains free-tier parameters."""
    script_path = Path("deploy/deploy_cloud_run.sh")
    assert script_path.exists(), "deploy/deploy_cloud_run.sh must exist"
    assert os.access(script_path, os.X_OK), "deploy/deploy_cloud_run.sh must be executable (chmod +x)"

    content = script_path.read_text(encoding="utf-8")
    assert "gcloud run deploy" in content
    assert "--min-instances 0" in content  # Scale to zero for true free-tier zero cost
    assert "--memory 512Mi" in content or "--memory 256Mi" in content    # Lightweight footprint
    assert "--cpu 1" in content


def test_cloudrun_yaml_manifest_structure():
    """Verify cloudrun.yaml declarative Knative service manifest specifications."""
    manifest_path = Path("deploy/cloudrun.yaml")
    assert manifest_path.exists(), "deploy/cloudrun.yaml must exist"
    content = manifest_path.read_text(encoding="utf-8")

    assert "apiVersion: serving.knative.dev/v1" in content
    assert "kind: Service" in content
    assert "autoscaling.knative.dev/minScale: \"0\"" in content
    assert "containerPort: 8080" in content
    assert "startupProbe" in content
    assert "livenessProbe" in content
    assert "readinessProbe" in content


def test_env_example_completeness():
    """Verify .env.example contains essential environment variable keys."""
    env_path = Path(".env.example")
    assert env_path.exists(), ".env.example must exist"
    content = env_path.read_text(encoding="utf-8")

    essential_keys = [
        "APP_ENV",
        "PORT",
        "DATABASE_PATH",
        "MOCK_SERVICES",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_SECRET_TOKEN",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
    ]
    for key in essential_keys:
        assert key in content, f"Key {key} missing from .env.example"


def test_requirements_files_completeness():
    """Verify requirements.txt and requirements-dev.txt include all core packages."""
    req_path = Path("requirements.txt")
    assert req_path.exists()
    req_content = req_path.read_text(encoding="utf-8")
    assert "fastapi" in req_content
    assert "uvicorn" in req_content
    assert "pydantic" in req_content
    assert "pydantic-settings" in req_content
    assert "httpx" in req_content

    dev_path = Path("requirements-dev.txt")
    assert dev_path.exists()
    dev_content = dev_path.read_text(encoding="utf-8")
    assert "pytest" in dev_content
    assert "flake8" in dev_content


def test_readme_documentation_completeness():
    """Verify README.md covers architecture, quickstart, and deployment."""
    readme_path = Path("README.md")
    assert readme_path.exists()
    content = readme_path.read_text(encoding="utf-8")
    assert "Autonomous Cloud-Based Personal Assistant" in content
    assert "Google Cloud Run" in content
    assert "Telegram Bot" in content
    assert "Web Dashboard" in content
    assert "Quickstart" in content
