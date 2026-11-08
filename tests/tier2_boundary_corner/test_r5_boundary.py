"""Tier 2: Boundary & Corner Cases — R5: Dual User Interface & Free-Tier Cloud Deployment.

Tests T2-R5-01 to T2-R5-06 verifying webhook secret validation, corrupted voice audio,
missing Telegram payload keys, malformed REST parameters, cold-start empty DB queries, and empty task validation.
"""

from typing import Any, Dict
import pytest
from fastapi.testclient import TestClient


def test_t2_r5_01_missing_or_invalid_webhook_secret(test_client: TestClient, telegram_fixtures: Dict[str, Any]):
    """T2-R5-01: Webhook rejects request with invalid secret token with HTTP 403 Forbidden."""
    update = telegram_fixtures["text_update"]
    headers = {"X-Telegram-Bot-Api-Secret-Token": "wrong_secret_token"}

    response = test_client.post("/api/webhook/telegram", json=update, headers=headers)
    assert response.status_code == 403
    assert "forbidden" in response.text.lower() or "secret" in response.text.lower()


def test_t2_r5_02_corrupted_audio_file_bytes(test_client: TestClient, mock_services):
    """T2-R5-02: Corrupted audio payload handled gracefully without 500 error; notifies user."""
    mock_services["telegram"].clear()
    payload = {
        "update_id": 99912,
        "message": {
            "message_id": 912,
            "chat": {"id": 12345},
            "voice": {
                "file_id": "voice_file_corrupted",
                "duration": 5,
            },
        },
    }

    response = test_client.post("/api/webhook/telegram", json=payload)
    assert response.status_code == 200

    last_msg = mock_services["telegram"].get_last_message()
    assert last_msg is not None
    assert "could not transcribe" in last_msg["text"].lower() or "re-record" in last_msg["text"].lower()


def test_t2_r5_03_telegram_json_missing_keys(test_client: TestClient):
    """T2-R5-03: Webhook payload missing 'message' key returns 200 OK to Telegram without crashing."""
    payload = {"update_id": 88888}
    response = test_client.post("/api/webhook/telegram", json=payload)
    assert response.status_code == 200


def test_t2_r5_04_dashboard_malformed_query_params(test_client: TestClient):
    """T2-R5-04: Malformed query parameters return HTTP 422 Unprocessable Entity."""
    response = test_client.get("/api/finance/transactions?start_date=abc&end_date=xyz")
    assert response.status_code == 422


def test_t2_r5_05_empty_database_cold_start(test_client: TestClient, mock_db):
    """T2-R5-05: Dashboard endpoints queried on empty database return valid empty collections without 500s."""
    # Wipe tables to simulate absolute cold start
    mock_db.execute("DELETE FROM transactions")
    mock_db.execute("DELETE FROM tasks")
    mock_db.commit()

    r1 = test_client.get("/api/finance/summary")
    assert r1.status_code == 200
    assert r1.json()["total_income"] == 0.0
    assert r1.json()["total_expenses"] == 0.0
    assert r1.json()["net_balance"] == 0.0

    r2 = test_client.get("/api/finance/transactions")
    assert r2.status_code == 200
    assert r2.json() == []

    r3 = test_client.get("/api/tasks")
    assert r3.status_code == 200
    assert r3.json() == []


def test_t2_r5_06_dashboard_task_missing_title(test_client: TestClient):
    """T2-R5-06: Task creation with empty or whitespace title is rejected with HTTP 422."""
    resp1 = test_client.post("/api/tasks", json={"title": "", "priority": "medium"})
    assert resp1.status_code == 422

    resp2 = test_client.post("/api/tasks", json={"title": "   ", "priority": "high"})
    assert resp2.status_code == 422
