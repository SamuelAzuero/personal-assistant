"""Tier 2: Boundary & Corner Cases — R3: Email Monitoring & Intelligent Digest.

Tests T2-R3-01 to T2-R3-06 verifying empty inboxes, malformed MIME headers,
body truncation (>50KB), marketing urgency spoofing, rate limiting (429), and OAuth2 expiry (401).
"""

import base64
import pytest

from app.integrations.mocks import GmailAPIError, MockGmailClient
from app.services.email_service import EmailService


@pytest.fixture
def email_service() -> EmailService:
    client = MockGmailClient()
    return EmailService(client=client)


def test_t2_r3_01_zero_unread_emails_empty_inbox(email_service: EmailService):
    """T2-R3-01: Empty unread inbox produces clean zero summary without division by zero."""
    email_service.client.messages.clear()
    digest = email_service.generate_digest("usr_test_default")

    assert digest["total_unread"] == 0
    assert digest["urgent_count"] == 0
    assert "all caught up" in digest["summary_text"].lower() or "0 unread" in digest["summary_text"].lower()


def test_t2_r3_02_malformed_email_payload(email_service: EmailService):
    """T2-R3-02: Email missing Subject and From headers defaults safely without raising exceptions."""
    email_service.client.messages.clear()
    email_service.client.add_message(
        msg_id="msg_malformed_001",
        sender="",
        to="usr_test_default",
        subject="",
        date="2026-11-04",
        body="",
        labels=["UNREAD"],
    )

    items = email_service.poll_unread("usr_test_default")
    assert len(items) == 1
    item = items[0]
    assert item["subject"] in ["(No Subject)", ""]
    assert item["sender"] in ["Unknown", ""]


def test_t2_r3_03_massive_email_body_truncation(email_service: EmailService):
    """T2-R3-03: Massive email body (>50KB) is truncated safely to preserve free-tier memory."""
    huge_body = "Important system update details. " + ("X" * 60_000)
    encoded = base64.b64encode(huge_body.encode("utf-8")).decode("utf-8")

    decoded = email_service._decode_body({"body": {"data": encoded}})
    assert len(decoded) <= 51_000
    assert "...[Body truncated" in decoded or "truncated" in decoded.lower()


def test_t2_r3_04_spoofed_urgency_marketing_noise(email_service: EmailService):
    """T2-R3-04: Promotional subject with URGENT prefix is de-escalated by marketing heuristics."""
    headers = {
        "From": "deals@shoeoutlet.com",
        "Subject": "URGENT FLASH SALE: 90% OFF SHOES!",
        "List-Unsubscribe": "<mailto:unsub@shoeoutlet.com>",
    }
    body = "Click here to save 90% off your favorite shoes now!"

    score, is_urgent, category = email_service._compute_urgency_score_and_category(
        headers=headers,
        subject=headers["Subject"],
        body=body,
    )

    assert is_urgent is False
    assert category == "NEWSLETTER"
    assert score < 50


def test_t2_r3_05_gmail_api_rate_limiting_429(email_service: EmailService):
    """T2-R3-05: Gmail API 429 rate limit triggers handled exception with descriptive error message."""
    email_service.client.set_simulate_rate_limit(True)

    with pytest.raises(GmailAPIError) as excinfo:
        email_service.poll_unread("usr_test_default")

    assert "rate limit" in str(excinfo.value).lower() or "429" in str(excinfo.value)


def test_t2_r3_06_expired_oauth2_token_401(email_service: EmailService):
    """T2-R3-06: Expired OAuth2 token (401 Unauthorized) raises handled auth exception."""
    email_service.client.set_simulate_unauthorized(True)

    with pytest.raises(GmailAPIError) as excinfo:
        email_service.poll_unread("usr_test_default")

    assert "401" in str(excinfo.value) or "expired" in str(excinfo.value).lower()
