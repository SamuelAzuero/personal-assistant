"""Tier 1: Feature Coverage — R5: Dual User Interface & Free-Tier Cloud Deployment.

Tests T1-R5-01 to T1-R5-06 verifying Telegram text and voice webhook handling,
static SPA serving, dashboard REST summary, health/readiness probes, and deployment configuration.
"""

from pathlib import Path
from typing import Any, Dict
import pytest
from fastapi.testclient import TestClient


def test_t1_r5_01_telegram_webhook_text(test_client: TestClient, telegram_fixtures: Dict[str, Any], mock_services):
    """T1-R5-01: Ingest text message update via webhook returns 200 OK and queues response."""
    update = telegram_fixtures["text_update"]
    mock_services["telegram"].clear()

    response = test_client.post("/api/webhook/telegram", json=update)
    assert response.status_code == 200

    last_msg = mock_services["telegram"].get_last_message()
    assert last_msg is not None
    assert "18.50" in last_msg["text"] or "expense" in last_msg["text"].lower()


def test_t1_r5_02_telegram_webhook_voice(test_client: TestClient, telegram_fixtures: Dict[str, Any], mock_services):
    """T1-R5-02: Ingest voice note update via webhook transcribes and replies."""
    update = telegram_fixtures["voice_update"]
    mock_services["telegram"].clear()

    response = test_client.post("/api/webhook/telegram", json=update)
    assert response.status_code == 200

    last_msg = mock_services["telegram"].get_last_message()
    assert last_msg is not None
    assert "78.45" in last_msg["text"] or "groceries" in last_msg["text"].lower() or "recorded" in last_msg["text"].lower()


def test_t1_r5_03_web_dashboard_spa_host(test_client: TestClient):
    """T1-R5-03: Web dashboard root endpoint GET / serves HTML single-page application."""
    response = test_client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    content = response.text
    assert "<div id=\"app\"" in content or "dashboard" in content.lower()


def test_t1_r5_04_dashboard_rest_summary(test_client: TestClient):
    """T1-R5-04: Dashboard REST summary GET /api/finance/summary returns valid financial KPI payload."""
    response = test_client.get("/api/finance/summary")
    assert response.status_code == 200
    data = response.json()
    assert "total_income" in data
    assert "total_expenses" in data
    assert "net_balance" in data
    assert "categories" in data
    assert isinstance(data["categories"], dict)


def test_t1_r5_05_health_and_readiness_probes(test_client: TestClient):
    """T1-R5-05: Health and readiness endpoints return 200 OK for Cloud Run liveness monitoring."""
    resp_health = test_client.get("/health")
    assert resp_health.status_code == 200
    assert resp_health.json().get("status") == "healthy"

    resp_ready = test_client.get("/ready")
    assert resp_ready.status_code == 200
    assert resp_ready.json().get("status") == "ready"


def test_t1_r5_06_free_tier_deployment_validation():
    """T1-R5-06: Static audit of deployment manifests ensuring lightweight free-tier specifications."""
    project_root = Path(__file__).parent.parent.parent

    # Check for Dockerfile candidates
    dockerfile_candidates = [
        project_root / "deploy" / "Dockerfile",
        project_root / "Dockerfile",
    ]
    found_dockerfile = None
    for cand in dockerfile_candidates:
        if cand.exists():
            found_dockerfile = cand
            break

    if found_dockerfile:
        content = found_dockerfile.read_text(encoding="utf-8")
        assert "python:3.12-slim" in content or "slim" in content or "alpine" in content

    # Check env template or PROJECT.md
    env_cand = project_root / ".env.example"
    project_doc = project_root / "PROJECT.md"
    assert env_cand.exists() or project_doc.exists()
